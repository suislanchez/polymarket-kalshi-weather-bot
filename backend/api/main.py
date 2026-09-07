"""FastAPI backend for the unified paper-trading dashboard (weather, stocks, spot crypto)."""
from fastapi import FastAPI, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import asyncio
import time
import json
import os

from backend.config import settings
from pathlib import Path

from backend.trading.execution_mode import (
    KILL_SWITCH_SOURCE as _execution_kill_switch_source,
    archives_required_directories,
    archives_runtime_paths,
    kill_switch_engaged as _execution_kill_switch_engaged,
    require_archives_runtime,
    require_paper_mode,
    sqlite_path as _sqlite_path,
)
from backend.models.database import (
    get_db, init_db, SessionLocal,
    Signal, Trade, BotState, AILog, ScanLog, RottenTomatoesSourceState
)
from backend.core.signals import scan_for_signals, TradingSignal
from backend.core.btc_methodology import validate_btc_signal_for_simulation
from backend.core.btc_paper_account import (
    load_latest_btc_calibration_rows_from_sqlite,
    load_latest_btc_calibration_summary_from_sqlite,
    summarize_btc_paper_account,
)
from backend.core.entertainment_paper_account import (
    load_latest_entertainment_calibration_summary_from_sqlite,
    summarize_entertainment_paper_account,
)
from backend.core.entertainment_signals import (
    build_rotten_tomatoes_review_rows,
    load_latest_rotten_tomatoes_market_rows,
    summarize_latest_rotten_tomatoes_source_states,
)
from backend.core.signal_review import summarize_signal_review_queue
from backend.core.weather_paper_account import (
    load_bot_weather_signal_calibration_rows_from_sqlite,
    load_latest_polymarket_weather_source_state_rows_from_sqlite,
    load_latest_polymarket_weather_source_state_summary_from_sqlite,
    load_latest_weather_bot_signal_calibration_rows_from_sqlite,
    load_latest_weather_bot_signal_calibration_summary_from_sqlite,
    load_latest_weather_calibration_rows_from_sqlite,
    load_latest_weather_calibration_summary_from_sqlite,
    load_latest_weather_signal_review_candidate_rows_from_sqlite,
    summarize_weather_paper_account,
)
from backend.data.btc_markets import fetch_active_btc_markets, BtcMarket
from backend.data.crypto import fetch_crypto_price, compute_btc_microstructure
from backend.api.schemas import (
    BtcCalibrationRowResponse,
    BtcCalibrationSummaryResponse,
    BtcPriceResponse,
    BtcWindowResponse,
    BotStats,
    CalibrationBucket,
    CalibrationSummary,
    DashboardData,
    EntertainmentCalibrationSummaryResponse,
    EventResponse,
    MicrostructureResponse,
    OpenPositionRiskRowResponse,
    OpenPositionRiskSummaryResponse,
    PaperRunResponse,
    PaperRunResultResponse,
    PolymarketWeatherSourceStateResponse,
    PolymarketWeatherSourceStateSummaryResponse,
    RottenTomatoesSourceStateResponse,
    SignalResponse,
    SignalReviewQueueResponse,
    TradeResponse,
    TradingArchivesResponse,
    TradingEventResponse,
    TradingKillSwitchResponse,
    TradingPortfolioResponse,
    TradingPositionResponse,
    MirrorSnapshotResponse,
    TradingStatusResponse,
    TradingVenueStateResponse,
    UnifiedOrderResponse,
    WeatherBotCalibrationRowResponse,
    WeatherCalibrationRowResponse,
    WeatherCalibrationSummaryResponse,
    WeatherDivergenceResponse,
    WeatherForecastResponse,
    WeatherMarketResponse,
    WeatherSignalResponse,
    WeatherSignalReviewCandidateResponse,
)

app = FastAPI(
    title="Unified Paper Trading Dashboard",
    description=(
        "Paper-only unified trading dashboard. Stocks, spot crypto and "
        "prediction-market weather share one proposal, risk, order and ledger "
        "path. Simulation only: there is no live-order endpoint."
    ),
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _redact_address(address: Optional[str]) -> Optional[str]:
    """Shorten an account/wallet address for status display.

    Never returns the full value. Short inputs collapse to a single ellipsis so
    we don't accidentally reveal a whole short identifier.
    """
    if not address:
        return None
    text = str(address)
    if len(text) <= 12:
        return "…"
    return f"{text[:6]}…{text[-4:]}"


def _summarize_account_balance(balance_data: object) -> bool:
    """Reduce a raw private balance payload to a non-sensitive presence flag.

    Returns True when the payload looks like it carries balance information, so
    the dashboard can show "funded/connected" without ever exposing the value.
    """
    if isinstance(balance_data, dict):
        return any(
            key in balance_data
            for key in ("balance", "available_balance", "portfolio_value", "cash")
        )
    return bool(balance_data)


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


ws_manager = ConnectionManager()


# Pydantic response models are imported from backend.api.schemas so dashboard
# serialization stays dependency-light and covered without importing FastAPI or
# SQLAlchemy route modules.


WEATHER_ONLY_LEGACY_NOTE = "Legacy BTC and RT/entertainment dashboard sections paused in weather-only scope"
WEATHER_MARKET_TYPES = ("weather", "kalshi_weather", "polymarket_weather", "temperature", "rain")
ENTERTAINMENT_MARKET_TYPES = ("entertainment", "rt", "rotten_tomatoes", "box_office")


# Scopes that explicitly ask for the legacy BTC / RT-entertainment sections.
# "all" is pinned by an existing test as legacy-on.
LEGACY_DASHBOARD_SCOPES = frozenset({"all", "legacy", "btc"})


def _legacy_dashboard_sections_enabled() -> bool:
    """Return whether /api/dashboard should include legacy BTC/RT sections.

    Direct BTC and RT endpoints remain available for historical/debug access, but
    Kayvon's active dashboard scope is weather-only unless explicitly overridden.
    """
    scope = (getattr(settings, "ACTIVE_PRODUCT_SCOPE", "weather") or "weather").strip().lower()
    explicit_legacy = bool(getattr(settings, "DASHBOARD_LEGACY_SECTIONS_ENABLED", False))
    # Legacy is on when explicitly enabled, or when the scope names the legacy
    # product. It used to be "on for any scope that isn't weather", and the
    # rename to unified_paper silently switched every BTC/RT section -- and
    # ~17s of fetching per cold load -- back on while both off-switches in
    # config said otherwise. An allowlist cannot be flipped by a rename.
    return explicit_legacy or scope in LEGACY_DASHBOARD_SCOPES


def _dashboard_legacy_note() -> Optional[str]:
    if _legacy_dashboard_sections_enabled():
        return None
    return WEATHER_ONLY_LEGACY_NOTE


def _active_product_scope() -> str:
    return (getattr(settings, "ACTIVE_PRODUCT_SCOPE", "weather") or "weather").strip().lower() or "weather"


def _query_dashboard_recent_trades(
    db: Session,
    *,
    legacy_sections_enabled: bool,
    limit: int = 50,
) -> List[Trade]:
    """Return trade rows for the active dashboard scope.

    In Kayvon's default weather-only scope, legacy BTC/RT trade rows can still
    remain in the app DB for historical debugging. Keep the active dashboard's
    recent-trades panel weather-scoped unless legacy sections are explicitly
    re-enabled.
    """
    query = db.query(Trade)
    if not legacy_sections_enabled:
        query = query.filter(Trade.market_type.in_(WEATHER_MARKET_TYPES))
    return query.order_by(Trade.timestamp.desc()).limit(limit).all()


def _query_dashboard_equity_trades(
    db: Session,
    *,
    legacy_sections_enabled: bool,
) -> List[Trade]:
    """Return settled trade rows used by the active dashboard equity curve."""
    query = db.query(Trade).filter(Trade.settled == True)
    if not legacy_sections_enabled:
        query = query.filter(Trade.market_type.in_(WEATHER_MARKET_TYPES))
    return query.order_by(Trade.timestamp).all()


def _query_open_position_risk_trades(
    db: Session,
    *,
    legacy_sections_enabled: bool,
    limit: int = 50,
) -> List[Trade]:
    """Return open trades for the active Cash-out Risk scope.

    The active product scope is weather-only, so the dashboard and default API
    readback should not surface legacy BTC/RT open rows unless legacy sections
    are explicitly re-enabled for debugging.
    """
    query = (
        db.query(Trade)
        .filter(Trade.settled == False)  # noqa: E712 - SQLAlchemy comparison
        .filter(Trade.closed_early == False)  # noqa: E712 - SQLAlchemy comparison
    )
    if not legacy_sections_enabled:
        query = query.filter(Trade.market_type.in_(WEATHER_MARKET_TYPES))
    return query.order_by(Trade.last_mark_time.desc().nullslast(), Trade.timestamp.desc()).limit(limit).all()


def _aggregate_bot_stats_for_scope(
    state: BotState,
    *,
    weather_account: dict,
    legacy_sections_enabled: bool,
) -> dict:
    """Choose top-level stats for the active product scope.

    `BotState` historically tracks the original all-lane bankroll. In the
    default weather-only product scope, top-level `/api/stats` and the dashboard
    header should mirror the active weather paper ledger instead of legacy BTC
    or RT state that may remain in the database.
    """
    if not legacy_sections_enabled:
        total_trades = int(weather_account.get("total_trades") or 0)
        winning_trades = int(weather_account.get("winning_trades") or 0)
        return {
            "bankroll": float(weather_account.get("current_equity") or 0.0),
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "win_rate": winning_trades / total_trades if total_trades > 0 else 0,
            "total_pnl": float(weather_account.get("realized_pnl") or 0.0),
            "is_running": bool(getattr(state, "is_running", False)),
            "last_run": getattr(state, "last_run", None),
        }

    total_trades = int(getattr(state, "total_trades", 0) or 0)
    winning_trades = int(getattr(state, "winning_trades", 0) or 0)
    return {
        "bankroll": float(getattr(state, "bankroll", 0.0) or 0.0),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "win_rate": winning_trades / total_trades if total_trades > 0 else 0,
        "total_pnl": float(getattr(state, "total_pnl", 0.0) or 0.0),
        "is_running": bool(getattr(state, "is_running", False)),
        "last_run": getattr(state, "last_run", None),
    }


def _trade_to_response(t: Trade) -> TradeResponse:
    return TradeResponse(
        id=t.id,
        market_ticker=t.market_ticker,
        platform=t.platform,
        event_slug=t.event_slug,
        direction=t.direction,
        entry_price=t.entry_price,
        size=t.size,
        timestamp=t.timestamp,
        settled=t.settled,
        result=t.result,
        pnl=t.pnl,
        closed_early=bool(getattr(t, "closed_early", False)),
        exit_time=getattr(t, "exit_time", None),
        exit_price=getattr(t, "exit_price", None),
        exit_reason=getattr(t, "exit_reason", None),
        unrealized_pnl=getattr(t, "unrealized_pnl", None),
        last_mark_price=getattr(t, "last_mark_price", None),
        last_mark_time=getattr(t, "last_mark_time", None),
        last_risk_action=getattr(t, "last_risk_action", None),
        last_risk_reasons=getattr(t, "last_risk_reasons", None) or [],
        last_risk_source_status=getattr(t, "last_risk_source_status", None),
        last_risk_evidence=getattr(t, "last_risk_evidence", None) or {},
    )


def _open_position_risk_row_from_trade(t: Trade) -> OpenPositionRiskRowResponse:
    last_mark_time = getattr(t, "last_mark_time", None)
    risk_scan_stale = last_mark_time is None
    checked_at = last_mark_time or datetime.utcnow()
    risk_evidence = getattr(t, "last_risk_evidence", None) or {}
    return OpenPositionRiskRowResponse(
        trade_id=t.id,
        market_type=getattr(t, "market_type", None) or "btc",
        market_ticker=t.market_ticker,
        event_slug=t.event_slug,
        direction=t.direction,
        entry_price=t.entry_price,
        size=t.size,
        current_exit_price=getattr(t, "last_mark_price", None),
        unrealized_pnl=getattr(t, "unrealized_pnl", None),
        model_probability_for_held_side=getattr(t, "model_probability", None),
        market_probability_for_held_side=getattr(t, "last_mark_price", None),
        action=getattr(t, "last_risk_action", None) or "watch",
        reasons=getattr(t, "last_risk_reasons", None) or ["risk scan has not refreshed this position yet"],
        source_status=getattr(t, "last_risk_source_status", None),
        risk_evidence=risk_evidence,
        live_exit_quote_bid=risk_evidence.get("live_exit_quote_bid"),
        live_exit_quote_ask=risk_evidence.get("live_exit_quote_ask"),
        live_exit_quote_top_bid_size=risk_evidence.get("live_exit_quote_top_bid_size"),
        live_exit_quote_top_ask_size=risk_evidence.get("live_exit_quote_top_ask_size"),
        live_exit_quote_source=risk_evidence.get("quote_source"),
        live_exit_quote_error=risk_evidence.get("quote_error"),
        settlement_source_known=risk_evidence.get("settlement_source_known"),
        station_known=risk_evidence.get("station_known"),
        settlement_url=risk_evidence.get("settlement_url"),
        settlement_tags=risk_evidence.get("settlement_tags") or [],
        latest_signal_id=risk_evidence.get("latest_signal_id"),
        latest_signal_timestamp=risk_evidence.get("latest_signal_timestamp"),
        latest_signal_market_price=risk_evidence.get("latest_signal_market_price"),
        latest_signal_edge=risk_evidence.get("latest_signal_edge"),
        latest_signal_suggested_size=risk_evidence.get("latest_signal_suggested_size"),
        latest_signal_model_probability_for_held_side=risk_evidence.get("latest_signal_model_probability_for_held_side"),
        checked_at=checked_at,
        risk_scan_stale=risk_scan_stale,
    )


# Startup / Shutdown
def _maybe_start_scheduler() -> bool:
    """Launch background scheduler jobs unless autostart is disabled.

    Returns True if the scheduler was started. Read-only API smokes and the
    FastAPI TestClient can set ``SCHEDULER_AUTOSTART=false`` so constructing the
    app never starts market scans, settlement, or paper trades.
    """
    from backend.core.scheduler import start_scheduler, log_event

    if not settings.SCHEDULER_AUTOSTART:
        log_event(
            "info",
            "Scheduler autostart disabled (SCHEDULER_AUTOSTART=false); no background jobs started",
        )
        return False

    start_scheduler()
    log_event("success", "Trading bot scheduler initialized")
    return True


@app.on_event("startup")
async def startup():
    require_paper_mode(settings.EXECUTION_MODE, settings.LIVE_TRADING_ENABLED)
    require_archives_runtime(
        settings.TRADING_ARCHIVES_ROOT,
        archives_runtime_paths(settings),
        required_directories=archives_required_directories(settings),
    )

    print("=" * 60)
    print("BTC 5-MIN TRADING BOT v3.0")
    print("=" * 60)
    print("Initializing database...")

    init_db()

    db = SessionLocal()
    try:
        state = db.query(BotState).first()
        if not state:
            state = BotState(
                bankroll=settings.INITIAL_BANKROLL,
                total_trades=0,
                winning_trades=0,
                total_pnl=0.0,
                is_running=True
            )
            db.add(state)
            db.commit()
            print(f"Created new bot state with ${settings.INITIAL_BANKROLL:,.2f} bankroll")
        else:
            state.is_running = True
            db.commit()
            print(f"Loaded bot state: Bankroll ${state.bankroll:,.2f}, P&L ${state.total_pnl:+,.2f}, {state.total_trades} trades")
    finally:
        db.close()

    print("")
    print("Configuration:")
    print(f"  - Simulation mode: {settings.SIMULATION_MODE}")
    print(f"  - Min edge threshold: {settings.MIN_EDGE_THRESHOLD:.0%}")
    print(f"  - Kelly fraction: {settings.KELLY_FRACTION:.0%}")
    print(f"  - Scan interval: {settings.SCAN_INTERVAL_SECONDS}s")
    print(f"  - Settlement interval: {settings.SETTLEMENT_INTERVAL_SECONDS}s")
    print("")

    started = _maybe_start_scheduler()

    if not started:
        print("Scheduler autostart disabled (SCHEDULER_AUTOSTART=false).")
        print("  - No background scans/settlement/paper jobs started.")
        print("=" * 60)
        return

    print("Bot is now running!")
    if settings.BTC_LANE_ENABLED:
        print(f"  - BTC scan: every {settings.SCAN_INTERVAL_SECONDS}s (edge >= {settings.MIN_EDGE_THRESHOLD:.0%})")
    else:
        print("  - BTC lane: DISABLED (BTC_LANE_ENABLED=false)")
    print(f"  - Settlement check: every {settings.SETTLEMENT_INTERVAL_SECONDS}s")
    if settings.WEATHER_ENABLED:
        print(f"  - Weather scan: every {settings.WEATHER_SCAN_INTERVAL_SECONDS}s (edge >= {settings.WEATHER_MIN_EDGE_THRESHOLD:.0%})")
        print(f"  - Weather cities: {settings.WEATHER_CITIES}")
    else:
        print("  - Weather trading: DISABLED")
    print("=" * 60)


@app.on_event("shutdown")
async def shutdown():
    from backend.core.scheduler import stop_scheduler
    stop_scheduler()


# Core endpoints
@app.get("/")
async def root():
    return {"status": "ok", "message": "Unified Paper Trading Dashboard API v3.0", "simulation_mode": settings.SIMULATION_MODE}


def _sqlite_path_from_database_url(database_url: str) -> str:
    if database_url.startswith("sqlite:///"):
        return database_url.removeprefix("sqlite:///")
    if database_url.startswith("sqlite://"):
        return database_url.removeprefix("sqlite://")
    return database_url


def _load_bot_weather_signal_calibration_rows(limit: int = 500) -> list[dict]:
    """Load bot-model weather signal scores for the paper-account summary.

    Read-only observability: this joins app DB signal rows to research final NWS
    outcomes and never writes trades or upgrades actionability.
    """
    app_db_path = _sqlite_path_from_database_url(settings.DATABASE_URL)
    research_db_path = settings.RESEARCH_DATABASE_PATH
    scored_at = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return load_bot_weather_signal_calibration_rows_from_sqlite(
        app_db_path,
        research_db_path,
        scored_at=scored_at,
        limit=limit,
    )


@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/stats", response_model=BotStats)
async def get_stats(db: Session = Depends(get_db)):
    state = db.query(BotState).first()
    if not state:
        raise HTTPException(status_code=404, detail="Bot state not initialized")

    btc_trades = db.query(Trade).filter(Trade.market_type == "btc").all()
    weather_trades = db.query(Trade).filter(Trade.market_type.in_(WEATHER_MARKET_TYPES)).all()
    entertainment_trades = db.query(Trade).filter(
        Trade.market_type.in_(ENTERTAINMENT_MARKET_TYPES)
    ).all()
    weather_account = summarize_weather_paper_account(
        weather_trades,
        settled_forecasts=_load_bot_weather_signal_calibration_rows(),
    )
    btc_account = summarize_btc_paper_account(btc_trades)
    entertainment_account = summarize_entertainment_paper_account(entertainment_trades)
    aggregate_stats = _aggregate_bot_stats_for_scope(
        state,
        weather_account=weather_account,
        legacy_sections_enabled=_legacy_dashboard_sections_enabled(),
    )

    return BotStats(
        **aggregate_stats,
        weather_paper_account=weather_account,
        btc_paper_account=btc_account,
        entertainment_paper_account=entertainment_account,
    )


# BTC-specific endpoints
@app.get("/api/btc/price", response_model=Optional[BtcPriceResponse])
async def get_btc_price():
    """Get current BTC price and momentum data."""
    try:
        btc = await fetch_crypto_price("BTC")
        if not btc:
            return None

        return BtcPriceResponse(
            price=btc.current_price,
            change_24h=btc.change_24h,
            change_7d=btc.change_7d,
            market_cap=btc.market_cap,
            volume_24h=btc.volume_24h,
            last_updated=btc.last_updated
        )
    except Exception:
        return None


@app.get("/api/btc/windows", response_model=List[BtcWindowResponse])
async def get_btc_windows():
    """Get upcoming BTC 5-min windows with prices."""
    try:
        markets = await fetch_active_btc_markets()
        return [
            BtcWindowResponse(
                slug=m.slug,
                market_id=m.market_id,
                up_price=m.up_price,
                down_price=m.down_price,
                window_start=m.window_start,
                window_end=m.window_end,
                window_start_ts=int(m.window_start.timestamp()) if m.window_start else None,
                window_end_ts=int(m.window_end.timestamp()) if m.window_end else None,
                volume=m.volume,
                is_active=m.is_active,
                is_upcoming=m.is_upcoming,
                time_until_end=m.time_until_end,
                spread=m.spread,
                up_bid=m.up_bid,
                up_ask=m.up_ask,
                up_ask_size=m.up_ask_size,
                down_bid=m.down_bid,
                down_ask=m.down_ask,
                down_ask_size=m.down_ask_size,
                up_midpoint=m.up_midpoint,
                down_midpoint=m.down_midpoint,
                up_last_price=m.up_last_price,
                down_last_price=m.down_last_price,
                recent_trades_count=m.recent_trades_count,
                settlement_source=m.settlement_source,
                settlement_url=m.settlement_url,
            )
            for m in markets
        ]
    except Exception:
        return []


@app.get("/api/signals", response_model=List[SignalResponse])
async def get_signals():
    """Get current BTC trading signals."""
    try:
        signals = await scan_for_signals()
        return [_signal_to_response(s) for s in signals]
    except Exception:
        return []


@app.get("/api/signals/actionable", response_model=List[SignalResponse])
async def get_actionable_signals():
    """Get only signals that pass the edge threshold."""
    try:
        signals = await scan_for_signals()
        actionable = [s for s in signals if s.passes_threshold]
        return [_signal_to_response(s) for s in actionable]
    except Exception:
        return []


def _signal_to_response(s: TradingSignal, actionable: Optional[bool] = None) -> SignalResponse:
    is_actionable = s.actionable if actionable is None else actionable
    return SignalResponse(
        market_ticker=s.market.market_id,
        market_title=f"BTC 5m - {s.market.slug}",
        platform="polymarket",
        direction=s.direction,
        model_probability=s.model_probability,
        market_probability=s.market_probability,
        edge=s.edge,
        confidence=s.confidence,
        suggested_size=s.suggested_size,
        reasoning=s.reasoning,
        timestamp=s.timestamp,
        category="crypto",
        event_slug=s.market.slug,
        btc_price=s.btc_price,
        btc_change_24h=s.btc_change_24h,
        window_end=s.market.window_end,
        actionable=is_actionable,
        no_trade_reasons=s.no_trade_reasons,
        execution_spread=s.execution_spread,
        top_ask_size=s.top_ask_size,
        settlement_source=s.settlement_source,
        settlement_url=s.settlement_url,
        model_price_source=s.model_price_source,
        chainlink_feed_id=s.chainlink_feed_id,
        chainlink_capture_method=s.chainlink_capture_method,
        chainlink_source_url=s.chainlink_source_url,
        chainlink_start_price=s.chainlink_start_price,
        chainlink_end_price=s.chainlink_end_price,
        chainlink_start_observed_at=s.chainlink_start_observed_at,
        chainlink_end_observed_at=s.chainlink_end_observed_at,
        chainlink_start_source_snapshot_path=s.chainlink_start_source_snapshot_path,
        chainlink_end_source_snapshot_path=s.chainlink_end_source_snapshot_path,
    )


@app.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(
    limit: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Trade)
    if status:
        query = query.filter(Trade.result == status)
    trades = query.order_by(Trade.timestamp.desc()).limit(limit).all()

    return [_trade_to_response(t) for t in trades]


@app.get("/api/open-position-risk", response_model=List[OpenPositionRiskRowResponse])
async def get_open_position_risk(db: Session = Depends(get_db)):
    """Read current open-position mark-to-market / exit recommendations.

    This endpoint is paper/simulation observability only. It does not execute
    exits; the scheduler/explicit scan path owns recommendation refreshes.
    """
    trades = _query_open_position_risk_trades(
        db,
        legacy_sections_enabled=_legacy_dashboard_sections_enabled(),
        limit=50,
    )
    return [_open_position_risk_row_from_trade(t) for t in trades]


@app.get("/api/entertainment/source-states", response_model=List[RottenTomatoesSourceStateResponse])
async def get_rotten_tomatoes_source_states(limit: int = 10, db: Session = Depends(get_db)):
    """Latest direct Rotten Tomatoes source-state snapshots.

    These rows are research/audit context only. They deliberately remain
    non-actionable until joined with current market quotes, CLOB depth, and
    no-trade gate evaluation.
    """
    rows = db.query(RottenTomatoesSourceState).order_by(
        RottenTomatoesSourceState.captured_at.desc()
    ).limit(max(limit * 3, limit)).all()
    return summarize_latest_rotten_tomatoes_source_states(rows, limit=limit)


@app.get("/api/equity-curve")
async def get_equity_curve(db: Session = Depends(get_db)):
    trades = db.query(Trade).filter(Trade.settled == True).order_by(Trade.timestamp).all()

    curve = []
    cumulative_pnl = 0
    bankroll = settings.INITIAL_BANKROLL

    for trade in trades:
        if trade.pnl is not None:
            cumulative_pnl += trade.pnl
            curve.append({
                "timestamp": trade.timestamp.isoformat(),
                "pnl": cumulative_pnl,
                "bankroll": bankroll + cumulative_pnl,
                "trade_id": trade.id
            })

    return curve


@app.post("/api/simulate-trade")
async def simulate_trade(signal_ticker: str, db: Session = Depends(get_db)):
    from backend.core.scheduler import log_event

    signals = await scan_for_signals()
    signal = next((s for s in signals if s.market.market_id == signal_ticker), None)

    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    allowed, guard_reason = validate_btc_signal_for_simulation(signal)
    if not allowed:
        raise HTTPException(status_code=400, detail=guard_reason)

    state = db.query(BotState).first()
    if not state:
        raise HTTPException(status_code=500, detail="Bot state not initialized")

    entry_price = signal.market.up_price if signal.direction == "up" else signal.market.down_price

    trade = Trade(
        market_ticker=signal.market.market_id,
        platform="polymarket",
        event_slug=signal.market.slug,
        direction=signal.direction,
        entry_price=entry_price,
        size=min(signal.suggested_size, state.bankroll * 0.05),
        model_probability=signal.model_probability,
        market_price_at_entry=signal.market_probability,
        edge_at_entry=signal.edge
    )

    db.add(trade)
    state.total_trades += 1
    db.commit()

    log_event("trade", f"Manual BTC trade: {signal.direction.upper()} {signal.market.slug}")
    return {"status": "ok", "trade_id": trade.id, "size": trade.size}


@app.post("/api/run-scan")
async def run_scan(db: Session = Depends(get_db)):
    from backend.core.scheduler import run_manual_scan, log_event

    state = db.query(BotState).first()
    if state:
        state.last_run = datetime.utcnow()
        db.commit()

    log_event("info", "Manual scan triggered (BTC + Weather)")
    await run_manual_scan()

    signals = await scan_for_signals()
    actionable = [s for s in signals if s.passes_threshold]

    result = {
        "status": "ok",
        "total_signals": len(signals),
        "actionable_signals": len(actionable),
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Also run weather scan if enabled
    if settings.WEATHER_ENABLED:
        try:
            from backend.core.weather_signals import scan_for_weather_signals
            wx_signals = await scan_for_weather_signals()
            wx_actionable = [s for s in wx_signals if s.passes_threshold]
            result["weather_signals"] = len(wx_signals)
            result["weather_actionable"] = len(wx_actionable)
        except Exception:
            result["weather_signals"] = 0
            result["weather_actionable"] = 0

    return result


@app.post("/api/settle-trades")
async def settle_trades_endpoint(db: Session = Depends(get_db)):
    from backend.core.settlement import settle_pending_trades, update_bot_state_with_settlements
    from backend.core.scheduler import log_event

    log_event("info", "Manual settlement triggered")

    settled = await settle_pending_trades(db)
    await update_bot_state_with_settlements(db, settled)

    return {
        "status": "ok",
        "settled_count": len(settled),
        "trades": [{"id": t.id, "result": t.result, "pnl": t.pnl} for t in settled]
    }


def _compute_calibration_summary(db: Session) -> Optional[CalibrationSummary]:
    """Compute calibration summary from settled signals."""
    total_signals = db.query(Signal).count()
    settled_signals = db.query(Signal).filter(Signal.outcome_correct.isnot(None)).all()

    if not settled_signals:
        if total_signals == 0:
            return None
        return CalibrationSummary(
            total_signals=total_signals,
            total_with_outcome=0,
            accuracy=0.0,
            avg_predicted_edge=0.0,
            avg_actual_edge=0.0,
            brier_score=0.0,
        )

    total_with_outcome = len(settled_signals)
    correct = sum(1 for s in settled_signals if s.outcome_correct)
    accuracy = correct / total_with_outcome if total_with_outcome > 0 else 0.0

    avg_predicted_edge = sum(abs(s.edge) for s in settled_signals) / total_with_outcome
    # Actual edge: for correct predictions, edge was real; for incorrect, edge was negative
    avg_actual_edge = sum(
        abs(s.edge) if s.outcome_correct else -abs(s.edge)
        for s in settled_signals
    ) / total_with_outcome

    # Brier score: mean squared error of probability forecasts
    # For each signal: (predicted_prob - actual_outcome)^2
    brier_sum = 0.0
    for s in settled_signals:
        # Model probability is for UP; actual is 1.0 if UP won, 0.0 if DOWN won
        actual = s.settlement_value if s.settlement_value is not None else 0.5
        brier_sum += (s.model_probability - actual) ** 2
    brier_score = brier_sum / total_with_outcome

    return CalibrationSummary(
        total_signals=total_signals,
        total_with_outcome=total_with_outcome,
        accuracy=accuracy,
        avg_predicted_edge=avg_predicted_edge,
        avg_actual_edge=avg_actual_edge,
        brier_score=brier_score,
    )


def _load_latest_weather_calibration_summary() -> Optional[WeatherCalibrationSummaryResponse]:
    """Load latest market-implied weather calibration batch from research SQLite.

    This is read-only observability. Missing DB/table should not break the live
    dashboard and never creates paper trades/actionability.
    """
    db_path = settings.RESEARCH_DATABASE_PATH
    summary = load_latest_weather_calibration_summary_from_sqlite(db_path)
    if summary is None:
        return None
    if hasattr(WeatherCalibrationSummaryResponse, "model_validate"):
        return WeatherCalibrationSummaryResponse.model_validate(summary)
    return WeatherCalibrationSummaryResponse.parse_obj(summary)


def _load_latest_weather_calibration_rows(limit: int = 5) -> List[WeatherCalibrationRowResponse]:
    """Load latest weather calibration audit rows from research SQLite.

    Rows are highest-error market-implied quote scores from the newest batch
    only. They are diagnostics for review, not paper entries or actionability.
    """
    db_path = settings.RESEARCH_DATABASE_PATH
    rows = load_latest_weather_calibration_rows_from_sqlite(db_path, limit=limit)
    if hasattr(WeatherCalibrationRowResponse, "model_validate"):
        return [WeatherCalibrationRowResponse.model_validate(row) for row in rows]
    return [WeatherCalibrationRowResponse.parse_obj(row) for row in rows]


def _load_latest_weather_bot_calibration_summary() -> Optional[WeatherCalibrationSummaryResponse]:
    """Load latest bot-model weather calibration batch from research SQLite.

    This is read-only model QA telemetry, separate from market-implied quote
    calibration and paper ledger PnL/actionability.
    """
    db_path = settings.RESEARCH_DATABASE_PATH
    summary = load_latest_weather_bot_signal_calibration_summary_from_sqlite(db_path)
    if summary is None:
        return None
    if hasattr(WeatherCalibrationSummaryResponse, "model_validate"):
        return WeatherCalibrationSummaryResponse.model_validate(summary)
    return WeatherCalibrationSummaryResponse.parse_obj(summary)


def _load_latest_weather_bot_calibration_rows(limit: int = 5) -> List[WeatherBotCalibrationRowResponse]:
    """Load highest-error bot-model weather calibration rows from SQLite.

    Rows are newest-batch model QA diagnostics only and remain non-actionable /
    non-executed. They are separate from market-implied weather calibration rows.
    """
    db_path = settings.RESEARCH_DATABASE_PATH
    rows = load_latest_weather_bot_signal_calibration_rows_from_sqlite(db_path, limit=limit)
    if hasattr(WeatherBotCalibrationRowResponse, "model_validate"):
        return [WeatherBotCalibrationRowResponse.model_validate(row) for row in rows]
    return [WeatherBotCalibrationRowResponse.parse_obj(row) for row in rows]


def _load_latest_weather_signal_review_candidates(limit: int = 5) -> List[WeatherSignalReviewCandidateResponse]:
    """Load newest weather threshold review candidates from SQLite.

    These are review-only diagnostics exported from live weather scans. The
    loader normalizes rows as non-actionable, non-executed, and zero-size.
    """
    db_path = settings.RESEARCH_DATABASE_PATH
    rows = load_latest_weather_signal_review_candidate_rows_from_sqlite(db_path, limit=limit)
    if hasattr(WeatherSignalReviewCandidateResponse, "model_validate"):
        return [WeatherSignalReviewCandidateResponse.model_validate(row) for row in rows]
    return [WeatherSignalReviewCandidateResponse.parse_obj(row) for row in rows]


def _load_latest_polymarket_weather_source_states(
    limit: int = 5,
    category: Optional[str] = None,
    market_state: Optional[str] = None,
) -> List[PolymarketWeatherSourceStateResponse]:
    """Load newest Polymarket weather source-state rows from SQLite.

    Rows preserve source/station/rule and token-level book context only; they
    remain non-actionable until final source, model, liquidity, and sizing gates
    are independently satisfied.
    """
    db_path = settings.RESEARCH_DATABASE_PATH
    rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(
        db_path,
        limit=limit,
        category=category,
        market_state=market_state,
    )
    if hasattr(PolymarketWeatherSourceStateResponse, "model_validate"):
        return [PolymarketWeatherSourceStateResponse.model_validate(row) for row in rows]
    return [PolymarketWeatherSourceStateResponse.parse_obj(row) for row in rows]


@app.get("/api/weather/polymarket-source-states", response_model=List[PolymarketWeatherSourceStateResponse])
async def get_polymarket_weather_source_states(
    category: Optional[str] = Query(
        default=None,
        description="Optional source-state sample category: warn, part, hko, obs, src, or all.",
    ),
    market_state: Optional[str] = Query(
        default=None,
        description="Optional market state filter: open, closed, or all.",
    ),
    limit: int = Query(default=25, ge=0, le=100),
) -> List[PolymarketWeatherSourceStateResponse]:
    """Return newest Polymarket weather source-state rows, optionally category-filtered.

    This is read-only operator drilldown for the weather dashboard. Rows remain
    source-state-only/non-actionable regardless of category or sample size.
    """
    return _load_latest_polymarket_weather_source_states(
        limit=limit,
        category=category,
        market_state=market_state,
    )


def _load_latest_polymarket_weather_source_state_summary() -> Optional[PolymarketWeatherSourceStateSummaryResponse]:
    """Load newest Polymarket weather source-state coverage summary read-only."""
    db_path = settings.RESEARCH_DATABASE_PATH
    summary = load_latest_polymarket_weather_source_state_summary_from_sqlite(db_path)
    if summary is None:
        return None
    if hasattr(PolymarketWeatherSourceStateSummaryResponse, "model_validate"):
        return PolymarketWeatherSourceStateSummaryResponse.model_validate(summary)
    return PolymarketWeatherSourceStateSummaryResponse.parse_obj(summary)


def _load_latest_btc_calibration_summary() -> Optional[BtcCalibrationSummaryResponse]:
    """Load latest BTC scoring/boundary calibration batch from research SQLite.

    This is read-only observability for Chainlink-boundary/outcome join quality;
    it never creates paper trades or actionability.
    """
    db_path = settings.RESEARCH_DATABASE_PATH
    summary = load_latest_btc_calibration_summary_from_sqlite(db_path)
    if summary is None:
        return None
    if hasattr(BtcCalibrationSummaryResponse, "model_validate"):
        return BtcCalibrationSummaryResponse.model_validate(summary)
    return BtcCalibrationSummaryResponse.parse_obj(summary)


def _load_latest_btc_calibration_rows(limit: int = 16) -> List[BtcCalibrationRowResponse]:
    """Load latest BTC scoring audit rows from research SQLite.

    Rows are Chainlink-boundary/outcome join diagnostics from the newest batch
    only. Default to 16 rows so the dashboard can show the complete 8-window
    Up/Down BTC batch before any UI display limiting.
    """
    db_path = settings.RESEARCH_DATABASE_PATH
    rows = load_latest_btc_calibration_rows_from_sqlite(db_path, limit=limit)
    if hasattr(BtcCalibrationRowResponse, "model_validate"):
        return [BtcCalibrationRowResponse.model_validate(row) for row in rows]
    return [BtcCalibrationRowResponse.parse_obj(row) for row in rows]


def _load_latest_entertainment_calibration_summary() -> Optional[EntertainmentCalibrationSummaryResponse]:
    """Load latest RT/entertainment calibration batch from research SQLite.

    This is read-only source-resolution/outcome-score observability; missing
    calibration rows are expected until final-source watchers are built.
    """
    db_path = settings.RESEARCH_DATABASE_PATH
    summary = load_latest_entertainment_calibration_summary_from_sqlite(db_path)
    if summary is None:
        return None
    if hasattr(EntertainmentCalibrationSummaryResponse, "model_validate"):
        return EntertainmentCalibrationSummaryResponse.model_validate(summary)
    return EntertainmentCalibrationSummaryResponse.parse_obj(summary)


@app.get("/api/calibration")
async def get_calibration(db: Session = Depends(get_db)):
    """Return calibration data: predicted probability vs actual win rate."""
    signals = db.query(Signal).filter(Signal.outcome_correct.isnot(None)).all()

    if not signals:
        return {"buckets": [], "summary": None}

    # Bucket signals by model_probability into 5% bins
    from collections import defaultdict
    buckets_data = defaultdict(lambda: {"predicted_sum": 0.0, "correct": 0, "total": 0})

    for s in signals:
        # Bin by 5% increments
        bin_start = int(s.model_probability * 100 // 5) * 5
        bin_end = bin_start + 5
        bucket_key = f"{bin_start}-{bin_end}%"

        buckets_data[bucket_key]["predicted_sum"] += s.model_probability
        buckets_data[bucket_key]["total"] += 1
        if s.outcome_correct:
            buckets_data[bucket_key]["correct"] += 1

    buckets = []
    for bucket_key in sorted(buckets_data.keys()):
        d = buckets_data[bucket_key]
        buckets.append(CalibrationBucket(
            bucket=bucket_key,
            predicted_avg=d["predicted_sum"] / d["total"],
            actual_rate=d["correct"] / d["total"],
            count=d["total"],
        ))

    summary = _compute_calibration_summary(db)

    return {"buckets": buckets, "summary": summary}


@app.get("/api/polymarket/relayer/status")
async def get_polymarket_relayer_status():
    """Check whether Polymarket relayer credentials are configured and reachable."""
    from backend.data.polymarket_relayer import (
        PolymarketRelayerClient,
        relayer_credentials_present,
    )

    if not relayer_credentials_present():
        return {
            "configured": False,
            "connected": False,
            "error": "Relayer credentials not configured (RELAYER_API_KEY / RELAYER_API_KEY_ADDRESS)",
        }

    address_present = bool(settings.RELAYER_API_KEY_ADDRESS)
    address_preview = _redact_address(settings.RELAYER_API_KEY_ADDRESS)
    try:
        async with PolymarketRelayerClient() as client:
            connected = await client.validate_credentials()
        return {
            "configured": True,
            "connected": connected,
            "address_present": address_present,
            "address_preview": address_preview,
        }
    except Exception as e:
        return {
            "configured": True,
            "connected": False,
            "address_present": address_present,
            "address_preview": address_preview,
            "error": str(e),
        }


# Kalshi endpoints
@app.get("/api/kalshi/status")
async def get_kalshi_status():
    """Test Kalshi API authentication and return connection status."""
    from backend.data.kalshi_client import KalshiClient, kalshi_credentials_present

    if not kalshi_credentials_present():
        return {
            "connected": False,
            "error": "Kalshi credentials not configured (KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH)",
        }

    try:
        client = KalshiClient()
        balance_data = await client.get_balance()
        # Redact: expose only that the account responded with balance info, not
        # the raw value. Detailed private payloads require an explicit operator
        # view, never the default dashboard status route.
        return {
            "connected": True,
            "balance_available": _summarize_account_balance(balance_data),
        }
    except Exception as error:
        # Never str(error). A missing or unreadable key raises with the private
        # key's absolute path in its message, and this route is unauthenticated,
        # so echoing it published the path to anyone who asked. The exception
        # type is enough to tell an operator what to look at.
        return {
            "connected": False,
            "error_type": type(error).__name__,
        }


# Weather endpoints
@app.get("/api/weather/forecasts", response_model=List[WeatherForecastResponse])
async def get_weather_forecasts():
    """Get ensemble forecasts for configured cities."""
    if not (settings.WEATHER_ENABLED or settings.WEATHER_RESEARCH_ENABLED):
        return []

    try:
        from backend.data.weather import fetch_ensemble_forecast, CITY_CONFIG
        from datetime import date

        city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
        forecasts = []

        # One ensemble fetch per city, and 17 cities is the normal
        # configuration. They are independent, so awaiting them in sequence was
        # 17 round trips deep for no reason. gather preserves order, so the
        # response is identical to the serial version's.
        known_cities = [c for c in city_keys if c in CITY_CONFIG]
        settled = await asyncio.gather(
            *(fetch_ensemble_forecast(city_key) for city_key in known_cities),
            return_exceptions=True,
        )

        for forecast in settled:
            if isinstance(forecast, BaseException):
                # One city's upstream failing must not empty the panel.
                logger.debug(f"Ensemble forecast failed: {forecast}")
                continue
            if forecast:
                forecasts.append(WeatherForecastResponse(
                    city_key=forecast.city_key,
                    city_name=forecast.city_name,
                    target_date=forecast.target_date.isoformat(),
                    mean_high=forecast.mean_high,
                    std_high=forecast.std_high,
                    mean_low=forecast.mean_low,
                    std_low=forecast.std_low,
                    num_members=forecast.num_members,
                    ensemble_agreement=forecast.ensemble_agreement,
                ))

        return forecasts
    except Exception:
        return []


@app.get("/api/weather/markets", response_model=List[WeatherMarketResponse])
async def get_weather_markets():
    """Get active weather temperature markets."""
    if not (settings.WEATHER_ENABLED or settings.WEATHER_RESEARCH_ENABLED):
        return []

    try:
        from backend.data.weather_markets import fetch_polymarket_weather_markets

        city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
        markets = await fetch_polymarket_weather_markets(city_keys)

        # Also fetch Kalshi markets if enabled for live use or read-only
        # research/dashboard mode. Public market-data endpoints do not require
        # private credentials, and no trade/account endpoints are touched here.
        if settings.KALSHI_ENABLED or settings.WEATHER_RESEARCH_ENABLED:
            try:
                from backend.data.kalshi_markets import fetch_kalshi_weather_markets
                kalshi_markets = await fetch_kalshi_weather_markets(city_keys)
                markets.extend(kalshi_markets)
            except Exception:
                pass

        return [
            WeatherMarketResponse(
                slug=m.slug,
                market_id=m.market_id,
                platform=m.platform,
                title=m.title,
                city_key=m.city_key,
                city_name=m.city_name,
                target_date=m.target_date.isoformat(),
                threshold_f=m.threshold_f,
                metric=m.metric,
                direction=m.direction,
                yes_price=m.yes_price,
                no_price=m.no_price,
                volume=m.volume,
                yes_midpoint=getattr(m, "yes_midpoint", None),
                yes_last_price=getattr(m, "yes_last_price", None),
                recent_trades_count=getattr(m, "recent_trades_count", 0),
            )
            for m in markets
        ]
    except Exception:
        return []


@app.get("/api/weather/divergences", response_model=List[WeatherDivergenceResponse])
async def get_weather_divergences(
    min_probability_gap: float = 0.05,
    threshold_tolerance_f: float = 0.5,
):
    """Compare Polymarket vs Kalshi weather lines and return largest probability gaps."""
    if not (settings.WEATHER_ENABLED or settings.WEATHER_RESEARCH_ENABLED):
        return []

    try:
        from backend.core.weather_divergence import find_cross_venue_weather_divergences
        from backend.data.weather_markets import fetch_polymarket_weather_markets
        from backend.data.kalshi_markets import fetch_kalshi_weather_markets

        city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
        markets = await fetch_polymarket_weather_markets(city_keys)
        if settings.KALSHI_ENABLED or settings.WEATHER_RESEARCH_ENABLED:
            markets.extend(await fetch_kalshi_weather_markets(city_keys))

        divergences = find_cross_venue_weather_divergences(
            markets,
            min_probability_gap=min_probability_gap,
            threshold_tolerance_f=threshold_tolerance_f,
        )

        return [
            WeatherDivergenceResponse(
                city_key=row.city_key,
                target_date=row.target_date.isoformat(),
                metric=row.metric,
                direction=row.direction,
                threshold_f=row.threshold_f,
                polymarket_market_id=row.polymarket_market_id,
                kalshi_market_id=row.kalshi_market_id,
                polymarket_yes_price=row.polymarket_yes_price,
                kalshi_yes_price=row.kalshi_yes_price,
                probability_gap=row.probability_gap,
                buy_yes_venue=row.buy_yes_venue,
                sell_yes_venue=row.sell_yes_venue,
                min_volume=row.min_volume,
            )
            for row in divergences
        ]
    except Exception:
        return []


@app.get("/api/weather/signals", response_model=List[WeatherSignalResponse])
async def get_weather_signals():
    """Get current weather trading signals."""
    if not (settings.WEATHER_ENABLED or settings.WEATHER_RESEARCH_ENABLED):
        return []

    try:
        from backend.core.weather_signals import scan_for_weather_signals

        signals = await scan_for_weather_signals()
        return [_weather_signal_to_response(s) for s in signals]
    except Exception:
        return []


def _weather_signal_to_response(s) -> WeatherSignalResponse:
    return WeatherSignalResponse(
        market_id=s.market.market_id,
        city_key=s.market.city_key,
        city_name=s.market.city_name,
        target_date=s.market.target_date.isoformat(),
        threshold_f=s.market.threshold_f,
        metric=s.market.metric,
        direction=s.direction,
        model_probability=s.model_probability,
        market_probability=s.market_probability,
        edge=s.edge,
        confidence=s.confidence,
        suggested_size=s.suggested_size,
        reasoning=s.reasoning,
        ensemble_mean=s.ensemble_mean,
        ensemble_std=s.ensemble_std,
        ensemble_members=s.ensemble_members,
        actionable=s.passes_threshold,
        no_trade_reasons=s.no_trade_reasons,
        execution_spread=s.execution_spread,
        top_ask_size=s.top_ask_size,
        bucket_set_probability_mass=s.bucket_set_probability_mass,
        bucket_set_sanity_passed=s.bucket_set_sanity_passed,
        bucket_set_size=s.bucket_set_size,
    )


@app.get("/api/events", response_model=List[EventResponse])
async def get_events(limit: int = 50):
    from backend.core.scheduler import get_recent_events
    events = get_recent_events(limit)
    return [
        EventResponse(
            timestamp=e["timestamp"],
            type=e["type"],
            message=e["message"],
            data=e.get("data", {})
        )
        for e in events
    ]


# Bot control
@app.post("/api/bot/start")
async def start_bot(db: Session = Depends(get_db)):
    from backend.core.scheduler import start_scheduler, log_event, is_scheduler_running

    state = db.query(BotState).first()
    if state:
        state.is_running = True
        db.commit()

    if not is_scheduler_running():
        start_scheduler()

    log_event("success", "Trading bot started")
    return {"status": "started", "is_running": True}


@app.post("/api/bot/stop")
async def stop_bot(db: Session = Depends(get_db)):
    from backend.core.scheduler import log_event

    state = db.query(BotState).first()
    if state:
        state.is_running = False
        db.commit()

    log_event("info", "Trading bot paused")
    return {"status": "stopped", "is_running": False}


@app.post("/api/bot/reset")
async def reset_bot(db: Session = Depends(get_db)):
    from backend.core.scheduler import log_event

    try:
        trades_deleted = db.query(Trade).delete()
        state = db.query(BotState).first()
        if state:
            state.bankroll = settings.INITIAL_BANKROLL
            state.total_trades = 0
            state.winning_trades = 0
            state.total_pnl = 0.0
            state.is_running = True

        ai_logs_deleted = db.query(AILog).delete()
        db.commit()

        log_event("success", f"Bot reset: {trades_deleted} trades deleted. Fresh start with ${settings.INITIAL_BANKROLL:,.2f}")

        return {
            "status": "reset",
            "trades_deleted": trades_deleted,
            "ai_logs_deleted": ai_logs_deleted,
            "new_bankroll": settings.INITIAL_BANKROLL
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Reset failed: {e}")


# The dashboard aggregate fans out to Polymarket, Kalshi and one ensemble
# forecast per configured city. Even fully parallelised that is tens of seconds
# of upstream work, and the frontend polls this endpoint every 10 seconds -- so
# uncached, every poll, reload and open tab starts its own crawl and they queue
# behind one another. Set to 0 to disable.
DASHBOARD_CACHE_TTL_SECONDS = float(
    getattr(settings, "DASHBOARD_CACHE_TTL_SECONDS", 45.0)
)

# (built_at, payload)
_dashboard_cache: Optional[tuple] = None
_dashboard_cache_lock = asyncio.Lock()


async def _cached_dashboard(build):
    """Return the cached aggregate, or build it once and share the result.

    The lock is the point. A plain TTL cache still lets simultaneous misses
    each run the full crawl, which is exactly the reload-storm this endpoint
    suffers from; single-flight collapses them into one.
    """
    global _dashboard_cache

    ttl = DASHBOARD_CACHE_TTL_SECONDS
    if ttl <= 0:
        return await build()

    cached = _dashboard_cache
    if cached is not None and (time.time() - cached[0]) < ttl:
        return cached[1]

    async with _dashboard_cache_lock:
        # Re-check: whoever held the lock may have just built it.
        cached = _dashboard_cache
        if cached is not None and (time.time() - cached[0]) < ttl:
            return cached[1]

        payload = await build()
        # Only a successful build is cached; caching a failure would pin the
        # dashboard broken for the whole TTL.
        _dashboard_cache = (time.time(), payload)
        return payload


@app.get("/api/dashboard", response_model=DashboardData)
async def get_dashboard(db: Session = Depends(get_db)):
    """Get all dashboard data in one call, cached briefly."""
    return await _cached_dashboard(lambda: _build_dashboard(db))


from backend.core.weather_divergence import find_cross_venue_weather_divergences
from backend.core.weather_signals import scan_for_weather_signals
from backend.data.weather import CITY_CONFIG, fetch_ensemble_forecast
from backend.data.weather_markets import fetch_polymarket_weather_markets
from backend.data.kalshi_markets import fetch_kalshi_weather_markets


async def _fetch_weather_slate(city_keys):
    """Both venues, once each, at the same time.

    A venue that fails contributes nothing rather than taking the other venue
    down with it -- the same posture the scan takes.
    """

    async def polymarket():
        return await fetch_polymarket_weather_markets(city_keys)

    async def kalshi():
        if not (settings.KALSHI_ENABLED or settings.WEATHER_RESEARCH_ENABLED):
            return []
        return await fetch_kalshi_weather_markets(city_keys)

    settled = await asyncio.gather(polymarket(), kalshi(), return_exceptions=True)
    markets = []
    for venue, result in zip(("polymarket", "kalshi"), settled):
        if isinstance(result, BaseException):
            logger.warning(f"Weather slate: {venue} fetch failed: {result}")
            continue
        markets.extend(result)
    return markets


async def _fetch_forecast_panel(city_keys):
    """One ensemble forecast per configured city, fetched together."""
    known = [c for c in city_keys if c in CITY_CONFIG]
    settled = await asyncio.gather(
        *(fetch_ensemble_forecast(c) for c in known), return_exceptions=True
    )
    panel = []
    for forecast in settled:
        if isinstance(forecast, BaseException):
            logger.debug(f"Ensemble forecast failed: {forecast}")
            continue
        if not forecast:
            continue
        panel.append(WeatherForecastResponse(
            city_key=forecast.city_key,
            city_name=forecast.city_name,
            target_date=forecast.target_date.isoformat(),
            mean_high=forecast.mean_high,
            std_high=forecast.std_high,
            mean_low=forecast.mean_low,
            std_low=forecast.std_low,
            num_members=forecast.num_members,
            ensemble_agreement=forecast.ensemble_agreement,
        ))
    return panel


async def _build_weather_section(city_keys):
    """Signals, divergences and forecasts, fetching each venue exactly once.

    Previously scan_for_weather_signals() fetched both venues, then this code
    fetched both again for the divergence panel, then fetched 17 forecasts one
    at a time, all in sequence. The slate is now fetched once and handed to the
    scan; the scan and the forecast panel are independent and run together.
    """
    markets = await _fetch_weather_slate(city_keys)

    scanned, forecasts = await asyncio.gather(
        scan_for_weather_signals(markets=markets),
        _fetch_forecast_panel(city_keys),
        return_exceptions=True,
    )
    if isinstance(scanned, BaseException):
        logger.warning(f"Weather signal scan failed: {scanned}")
        scanned = []
    if isinstance(forecasts, BaseException):
        logger.warning(f"Forecast panel failed: {forecasts}")
        forecasts = []

    signals_data = [_weather_signal_to_response(s) for s in scanned]
    divergences_data = [
        WeatherDivergenceResponse(
            city_key=row.city_key,
            target_date=row.target_date.isoformat(),
            metric=row.metric,
            direction=row.direction,
            threshold_f=row.threshold_f,
            polymarket_market_id=row.polymarket_market_id,
            kalshi_market_id=row.kalshi_market_id,
            polymarket_yes_price=row.polymarket_yes_price,
            kalshi_yes_price=row.kalshi_yes_price,
            probability_gap=row.probability_gap,
            buy_yes_venue=row.buy_yes_venue,
            sell_yes_venue=row.sell_yes_venue,
            min_volume=row.min_volume,
        )
        for row in find_cross_venue_weather_divergences(markets)[:20]
    ]
    return signals_data, divergences_data, forecasts


async def _build_dashboard(db: Session):
    """Assemble the dashboard aggregate. Expensive; see _cached_dashboard."""
    stats = await get_stats(db)
    legacy_sections_enabled = _legacy_dashboard_sections_enabled()

    # Legacy BTC/RT dashboard work is intentionally skipped in the active
    # weather-only scope. Direct legacy endpoints still exist for historical
    # debugging, but /api/dashboard should avoid refreshing stale/off-scope data.
    btc_price_data = None
    micro_data = None
    windows = []
    signals = []
    if legacy_sections_enabled:
        # Fetch BTC price from microstructure first, fallback to CoinGecko
        try:
            micro = await compute_btc_microstructure()
            if micro:
                micro_data = MicrostructureResponse(
                    rsi=micro.rsi,
                    momentum_1m=micro.momentum_1m,
                    momentum_5m=micro.momentum_5m,
                    momentum_15m=micro.momentum_15m,
                    vwap_deviation=micro.vwap_deviation,
                    sma_crossover=micro.sma_crossover,
                    volatility=micro.volatility,
                    price=micro.price,
                    source=micro.source,
                )
                btc_price_data = BtcPriceResponse(
                    price=micro.price,
                    change_24h=micro.momentum_15m * 96,  # rough extrapolation
                    change_7d=0,
                    market_cap=0,
                    volume_24h=0,
                    last_updated=datetime.utcnow(),
                )
        except Exception:
            pass
        if not btc_price_data:
            try:
                btc = await fetch_crypto_price("BTC")
                if btc:
                    btc_price_data = BtcPriceResponse(
                        price=btc.current_price,
                        change_24h=btc.change_24h,
                        change_7d=btc.change_7d,
                        market_cap=btc.market_cap,
                        volume_24h=btc.volume_24h,
                        last_updated=btc.last_updated
                    )
            except Exception:
                pass

        # Fetch windows
        try:
            markets = await fetch_active_btc_markets()
            windows = [
                BtcWindowResponse(
                    slug=m.slug,
                    market_id=m.market_id,
                    up_price=m.up_price,
                    down_price=m.down_price,
                    window_start=m.window_start,
                    window_end=m.window_end,
                    window_start_ts=int(m.window_start.timestamp()) if m.window_start else None,
                    window_end_ts=int(m.window_end.timestamp()) if m.window_end else None,
                    volume=m.volume,
                    is_active=m.is_active,
                    is_upcoming=m.is_upcoming,
                    time_until_end=m.time_until_end,
                    spread=m.spread,
                    up_bid=m.up_bid,
                    up_ask=m.up_ask,
                    up_ask_size=m.up_ask_size,
                    down_bid=m.down_bid,
                    down_ask=m.down_ask,
                    down_ask_size=m.down_ask_size,
                    up_midpoint=m.up_midpoint,
                    down_midpoint=m.down_midpoint,
                    up_last_price=m.up_last_price,
                    down_last_price=m.down_last_price,
                    recent_trades_count=m.recent_trades_count,
                    settlement_source=m.settlement_source,
                    settlement_url=m.settlement_url,
                )
                for m in markets
            ]
        except Exception:
            pass

        # Signals — return ALL legacy BTC signals when legacy dashboard is enabled.
        try:
            raw_signals = await scan_for_signals()
            signals = [_signal_to_response(s, actionable=s.passes_threshold) for s in raw_signals]
        except Exception:
            pass

    # Recent trades
    trades = _query_dashboard_recent_trades(db, legacy_sections_enabled=legacy_sections_enabled, limit=50)
    recent_trades = [_trade_to_response(t) for t in trades]

    # Equity curve
    equity_trades = _query_dashboard_equity_trades(db, legacy_sections_enabled=legacy_sections_enabled)
    equity_curve = []
    cumulative_pnl = 0
    for trade in equity_trades:
        if trade.pnl is not None:
            cumulative_pnl += trade.pnl
            equity_curve.append({
                "timestamp": trade.timestamp.isoformat(),
                "pnl": cumulative_pnl,
                "bankroll": settings.INITIAL_BANKROLL + cumulative_pnl
            })

    # Calibration summary. Weather remains active; legacy BTC/RT calibration
    # loaders are skipped unless legacy dashboard sections are explicitly enabled.
    calibration = _compute_calibration_summary(db) if legacy_sections_enabled else None
    weather_calibration = _load_latest_weather_calibration_summary()
    weather_bot_calibration = _load_latest_weather_bot_calibration_summary()
    weather_calibration_rows = _load_latest_weather_calibration_rows(limit=5)
    weather_bot_calibration_rows = _load_latest_weather_bot_calibration_rows(limit=5)
    weather_signal_review_candidates = _load_latest_weather_signal_review_candidates(limit=5)
    polymarket_weather_source_states = _load_latest_polymarket_weather_source_states(limit=5)
    polymarket_weather_source_state_summary = _load_latest_polymarket_weather_source_state_summary()
    btc_calibration = _load_latest_btc_calibration_summary() if legacy_sections_enabled else None
    btc_calibration_rows = _load_latest_btc_calibration_rows(limit=16) if legacy_sections_enabled else []
    entertainment_calibration = _load_latest_entertainment_calibration_summary() if legacy_sections_enabled else None

    # Entertainment / Rotten Tomatoes direct source-state snapshots and latest
    # public market rows. Legacy RT work is paused in the weather-only dashboard
    # unless explicitly re-enabled via DASHBOARD_LEGACY_SECTIONS_ENABLED.
    rotten_tomatoes_source_states: List[RottenTomatoesSourceStateResponse] = []
    rt_review_rows = []
    if legacy_sections_enabled:
        try:
            rt_rows = db.query(RottenTomatoesSourceState).order_by(
                RottenTomatoesSourceState.captured_at.desc()
            ).limit(30).all()
            rotten_tomatoes_source_states = [
                RottenTomatoesSourceStateResponse(**summary)
                for summary in summarize_latest_rotten_tomatoes_source_states(rt_rows, limit=10)
            ]
            source_summaries = [
                state.model_dump() if hasattr(state, "model_dump") else state.dict()
                for state in rotten_tomatoes_source_states
            ]
            latest_market_rows, _, _ = load_latest_rotten_tomatoes_market_rows()
            rt_review_rows = build_rotten_tomatoes_review_rows(
                latest_market_rows,
                source_summaries=source_summaries,
            )
        except Exception:
            rt_review_rows = rotten_tomatoes_source_states

    # Weather data (if enabled)
    weather_signals_data = []
    weather_divergences_data = []
    weather_forecasts_data = []
    if settings.WEATHER_ENABLED:
        try:
            city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
            (
                weather_signals_data,
                weather_divergences_data,
                weather_forecasts_data,
            ) = await _build_weather_section(city_keys)
        except Exception as error:
            # The dashboard must not 500 because weather did; but an empty
            # panel with no trace of why is how the 108s load hid for so long.
            logger.warning(f"Dashboard weather section failed: {error}")

    signal_review_queue = SignalReviewQueueResponse(
        **summarize_signal_review_queue(
            btc_signals=signals if legacy_sections_enabled else [],
            weather_signals=weather_signals_data,
            weather_review_candidates=weather_signal_review_candidates,
            weather_source_states=polymarket_weather_source_states,
            rt_source_states=rt_review_rows if legacy_sections_enabled else [],
            limit=12,
        )
    )

    open_position_risk_rows = await get_open_position_risk(db)
    open_position_risk_summary = OpenPositionRiskSummaryResponse(
        total_open_positions=len(open_position_risk_rows),
        action_counts={},
        auto_exit_enabled=settings.PAPER_AUTO_EXIT_ENABLED,
        recommendations_only=not settings.PAPER_AUTO_EXIT_ENABLED,
        stale_mark_count=sum(1 for row in open_position_risk_rows if row.risk_scan_stale),
        latest_checked_at=max(
            (row.checked_at for row in open_position_risk_rows if not row.risk_scan_stale),
            default=None,
        ),
        exited_count=0,
        live_exit_quote_error_count=sum(1 for row in open_position_risk_rows if row.live_exit_quote_error),
        closed_market_or_stale_token_count=sum(
            1 for row in open_position_risk_rows if row.source_status == "closed_market_or_stale_token"
        ),
        source_status_counts={},
    )
    for row in open_position_risk_rows:
        open_position_risk_summary.action_counts[row.action] = open_position_risk_summary.action_counts.get(row.action, 0) + 1
        if row.source_status:
            open_position_risk_summary.source_status_counts[row.source_status] = (
                open_position_risk_summary.source_status_counts.get(row.source_status, 0) + 1
            )

    return DashboardData(
        active_product_scope=_active_product_scope(),
        legacy_dashboard_sections_enabled=legacy_sections_enabled,
        legacy_dashboard_note=_dashboard_legacy_note(),
        stats=stats,
        btc_price=btc_price_data,
        microstructure=micro_data,
        windows=windows,
        active_signals=signals,
        recent_trades=recent_trades,
        equity_curve=equity_curve,
        calibration=calibration,
        weather_calibration=weather_calibration,
        weather_bot_calibration=weather_bot_calibration,
        weather_calibration_rows=weather_calibration_rows,
        weather_bot_calibration_rows=weather_bot_calibration_rows,
        weather_signal_review_candidates=weather_signal_review_candidates,
        polymarket_weather_source_states=polymarket_weather_source_states,
        polymarket_weather_source_state_summary=polymarket_weather_source_state_summary,
        btc_calibration=btc_calibration,
        btc_calibration_rows=btc_calibration_rows,
        entertainment_calibration=entertainment_calibration,
        weather_signals=weather_signals_data,
        weather_divergences=weather_divergences_data,
        weather_forecasts=weather_forecasts_data,
        rotten_tomatoes_source_states=rotten_tomatoes_source_states,
        signal_review_queue=signal_review_queue,
        open_position_risk_rows=open_position_risk_rows,
        open_position_risk_summary=open_position_risk_summary,
    )


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await ws_manager.connect(websocket)

    try:
        await websocket.send_json({
            "timestamp": datetime.utcnow().isoformat(),
            "type": "success",
            "message": "Connected to weather paper trading dashboard"
        })

        from backend.core.scheduler import get_recent_events
        for event in get_recent_events(20):
            await websocket.send_json(event)

        last_event_count = len(get_recent_events(200))
        while True:
            await asyncio.sleep(2)

            current_events = get_recent_events(200)
            if len(current_events) > last_event_count:
                new_events = current_events[last_event_count - len(current_events):]
                for event in new_events:
                    await websocket.send_json(event)
                last_event_count = len(current_events)

            await websocket.send_json({
                "type": "heartbeat",
                "timestamp": datetime.utcnow().isoformat()
            })

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Unified paper trading endpoints (Task 13)
#
# Four reads and one write. Handlers stay thin: each delegates to a module-level
# helper that is testable without FastAPI, following the /api/open-position-risk
# shape rather than the inline /api/dashboard one.
#
# Two rules hold across all five. Money crosses the boundary as strings, because
# a bare Decimal in a plain dict serializes to a float and silently drops the
# precision the ledger preserved. And no handler ever returns an exception
# string: refusals carry fixed reason codes, the way the trading layer already
# logs type(error).__name__ rather than the message.
# ---------------------------------------------------------------------------

_TRADING_CREDENTIAL_FIELDS = {
    "polymarket_api": ("POLYMARKET_API_KEY", "POLYMARKET_API_KEY_ID", "POLYMARKET_API_SECRET"),
    "polymarket_relayer": ("RELAYER_API_KEY", "RELAYER_API_KEY_ADDRESS"),
    "kalshi": ("KALSHI_API_KEY_ID", "KALSHI_PRIVATE_KEY_PATH"),
    "alpaca_paper": ("ALPACA_API_KEY", "ALPACA_API_SECRET"),
    "groq": ("GROQ_API_KEY",),
}

# Every flag that actually halts trading, reported by name. GLOBAL_TRADING_KILL_SWITCH
# used to be declared in config and read by no production code path, so this
# reported LIVE_TRADING_ENABLED alone to stop an operator flipping a dead flag.
# Both are now gates (backend/trading/execution_mode.KILL_SWITCH_FLAGS), so both
# are named.
_KILL_SWITCH_SOURCE = _execution_kill_switch_source

_paper_run_lock = asyncio.Lock()


def _credential_presence() -> dict:
    """Presence as booleans, never values, never lengths, never prefixes."""
    presence = {}
    for label, fields in _TRADING_CREDENTIAL_FIELDS.items():
        presence[label] = all(
            bool(str(getattr(settings, field, "") or "").strip()) for field in fields
        )
    return presence


def _archives_binding() -> dict:
    """The shape of the Archives binding, never the paths themselves."""
    from backend.trading.execution_mode import (
        ArchivesRuntimeError,
        archives_required_directories,
        archives_runtime_paths,
        require_archives_runtime,
    )

    root = str(getattr(settings, "TRADING_ARCHIVES_ROOT", "") or "").strip()
    binding = {
        "root_configured": bool(root),
        "root_available": False,
        "runtime_paths_contained": False,
        "required_directories_present": False,
    }
    if not binding["root_configured"]:
        return binding
    try:
        require_archives_runtime(
            settings.TRADING_ARCHIVES_ROOT,
            archives_runtime_paths(settings),
            required_directories=archives_required_directories(settings),
        )
    except ArchivesRuntimeError:
        return binding
    except Exception:
        return binding
    binding.update(
        root_available=True,
        runtime_paths_contained=True,
        required_directories_present=True,
    )
    return binding


def _venue_states() -> list:
    """Every venue the runtime knows about, so each of its states is reachable.

    Alpaca was omitted, which made the dashboard's "connected" state
    unreachable: it requires this list to carry alpaca_paper with
    execution_enabled. The prediction venues remain internal simulations
    always; Alpaca is a real paper broker, hence simulation=False.
    """
    kalshi_enabled = bool(getattr(settings, "WEATHER_KALSHI_PAPER_EXECUTION_ENABLED", False))
    stock_lane = bool(getattr(settings, "STOCK_CRYPTO_LANE_ENABLED", False))
    return [
        TradingVenueStateResponse(
            venue="alpaca_paper",
            simulation=False,
            execution_enabled=stock_lane,
            monitor_only=not stock_lane,
        ),
        TradingVenueStateResponse(
            venue="polymarket_paper",
            simulation=True,
            execution_enabled=True,
            monitor_only=False,
        ),
        TradingVenueStateResponse(
            venue="kalshi_paper",
            simulation=True,
            execution_enabled=kalshi_enabled,
            monitor_only=not kalshi_enabled,
        ),
    ]


def _kill_switch_engaged() -> bool:
    return _execution_kill_switch_engaged(settings)


def _is_paper_mode() -> bool:
    mode = getattr(settings, "EXECUTION_MODE", "")
    return isinstance(mode, str) and mode.strip().lower() == "paper"


def _unified_order_response(row) -> UnifiedOrderResponse:
    """Explicit projection. order_metadata is deliberately not carried."""
    return UnifiedOrderResponse(
        client_order_id=str(row.client_order_id),
        proposal_id=(str(row.proposal_id) if row.proposal_id else None),
        venue=str(row.venue),
        asset_class=(str(row.asset_class) if row.asset_class else None),
        symbol=(str(row.symbol) if row.symbol else None),
        side=(str(row.side) if row.side else None),
        status=str(row.status),
        broker_order_id=(str(row.broker_order_id) if row.broker_order_id else None),
        rejection_reason=(str(row.rejection_reason) if row.rejection_reason else None),
        filled_quantity=str(row.filled_quantity),
        filled_notional=str(row.filled_notional),
        average_fill_price=(
            str(row.average_fill_price) if row.average_fill_price is not None else None
        ),
        occurred_at=row.occurred_at,
    )


# Payload keys the ledger writes that are safe to return. Anything else -- a
# rationale, a caller metadata dict, an adapter-controlled identifier -- is
# dropped rather than trusted, because the projection and the event payload copy
# some fields through without filtering.
_TRADING_EVENT_PAYLOAD_KEYS = frozenset(
    {
        "proposal_id",
        "strategy_id",
        "venue",
        "asset_class",
        "symbol",
        "side",
        "order_type",
        "quantity",
        "notional",
        "reference_price",
        "limit_price",
        "status",
        "approved",
        "reason_codes",
        "filled_quantity",
        "filled_notional",
        "average_fill_price",
        "rejection_reason",
        "occurred_at",
        "created_at",
    }
)


def _trading_event_response(row) -> TradingEventResponse:
    payload = row.payload if isinstance(row.payload, dict) else {}
    return TradingEventResponse(
        aggregate_id=str(row.aggregate_id),
        sequence=int(row.sequence),
        event_type=str(row.event_type),
        occurred_at=row.occurred_at,
        payload={
            key: value
            for key, value in payload.items()
            if key in _TRADING_EVENT_PAYLOAD_KEYS
        },
    )


@app.get("/api/trading/status", response_model=TradingStatusResponse)
async def get_trading_status():
    """Paper-only runtime posture. Credential presence only, never values."""
    return TradingStatusResponse(
        execution_mode=str(getattr(settings, "EXECUTION_MODE", "")),
        paper_only=_is_paper_mode() and not _kill_switch_engaged(),
        kill_switch=TradingKillSwitchResponse(
            engaged=_kill_switch_engaged(), source=_KILL_SWITCH_SOURCE
        ),
        lanes={
            "stock_crypto": bool(getattr(settings, "STOCK_CRYPTO_LANE_ENABLED", False)),
            "weather_unified_ledger": bool(
                getattr(settings, "WEATHER_UNIFIED_LEDGER_ENABLED", False)
            ),
            "scheduler_autostart": bool(getattr(settings, "SCHEDULER_AUTOSTART", False)),
        },
        venues=_venue_states(),
        credentials=_credential_presence(),
        archives=TradingArchivesResponse(**_archives_binding()),
    )


@app.get("/api/trading/orders", response_model=List[UnifiedOrderResponse])
async def get_trading_orders(
    limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)
):
    """Normalized order projections, newest first."""
    from backend.models.database import UnifiedOrder

    rows = (
        db.query(UnifiedOrder)
        .order_by(UnifiedOrder.occurred_at.desc(), UnifiedOrder.id.desc())
        .limit(limit)
        .all()
    )
    return [_unified_order_response(row) for row in rows]


@app.get("/api/trading/events", response_model=List[TradingEventResponse])
async def get_trading_events(
    limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)
):
    """Sanitized audit events in ledger order."""
    from backend.models.database import TradingEvent

    rows = (
        db.query(TradingEvent)
        .order_by(TradingEvent.id.asc())
        .limit(limit)
        .all()
    )
    return [_trading_event_response(row) for row in rows]


@app.get("/api/trading/portfolio", response_model=TradingPortfolioResponse)
async def get_trading_portfolio(db: Session = Depends(get_db)):
    """Real account state, or an explicit absence.

    Never an adapter snapshot: both production adapters return a hard-coded
    balance that looks like an account read and is not one. Never cash aliased
    to equity.
    """
    from backend.core.scheduler import weather_portfolio_state

    state = weather_portfolio_state(db)
    if state is None:
        return TradingPortfolioResponse(
            available=False, reason="portfolio_state_unavailable"
        )
    return TradingPortfolioResponse(
        available=True,
        equity=str(state.equity),
        cash=None,
        positions=[],
    )


def _paper_run_response(outcome) -> PaperRunResponse:
    results = []
    for item in outcome.results:
        proposal = item.proposal
        results.append(
            PaperRunResultResponse(
                proposal_id=str(getattr(proposal, "proposal_id", "")),
                strategy_id=str(getattr(proposal, "strategy_id", "")),
                venue=str(getattr(getattr(proposal, "venue", ""), "value", "")),
                asset_class=str(getattr(getattr(proposal, "asset_class", ""), "value", "")),
                symbol=str(getattr(proposal, "symbol", "")),
                side=str(getattr(getattr(proposal, "side", ""), "value", "")),
                outcome=str(item.outcome),
                status=item.status,
                reason_codes=[str(code) for code in item.reason_codes],
                rejection_reason=item.rejection_reason,
                notional=(
                    str(proposal.notional)
                    if getattr(proposal, "notional", None) is not None
                    else None
                ),
            )
        )
    return PaperRunResponse(ran=True, proposals=outcome.proposals, results=results)


@app.get("/api/trading/mirror/{venue}", response_model=MirrorSnapshotResponse)
async def get_trading_mirror(venue: str, db: Session = Depends(get_db)):
    """The latest read-only snapshot an agent pushed for a mirrored venue.

    Served from its own table, never from the risk gate's portfolio state, and
    every account identifier in it was masked before it was stored.
    """
    from backend.trading.mirror import MIRROR_VENUES, latest_snapshot

    if venue not in MIRROR_VENUES:
        raise HTTPException(status_code=404, detail="not a mirror venue")
    row = latest_snapshot(db, venue)
    if row is None:
        return MirrorSnapshotResponse(available=False, venue=venue)
    payload = row.payload if isinstance(row.payload, dict) else {}
    return MirrorSnapshotResponse(
        available=True,
        venue=venue,
        captured_at=row.captured_at,
        source_agent=str(row.source_agent),
        total_value=str(row.total_value),
        accounts=payload.get("accounts", []),
    )


@app.post("/api/trading/paper/run")
async def run_paper_lane(db: Session = Depends(get_db)):
    """Run the stock/crypto paper lane once, on demand.

    Refuses rather than resizes, like everything else here. The startup
    paper-mode guard is a snapshot taken once against mutable settings and does
    not protect this handler, so the check is repeated here on every request.

    A run that proposes nothing is a success with zero results.
    """
    from fastapi.responses import JSONResponse
    from backend.core import scheduler as scheduler_module

    if not _is_paper_mode():
        return JSONResponse(status_code=409, content={"refused": "not_paper_mode"})
    if _kill_switch_engaged():
        return JSONResponse(status_code=409, content={"refused": "kill_switch_engaged"})
    archives = _archives_binding()
    if not archives["root_available"]:
        return JSONResponse(status_code=409, content={"refused": "archives_unavailable"})

    if _paper_run_lock.locked():
        return JSONResponse(status_code=409, content={"refused": "run_in_progress"})

    async with _paper_run_lock:
        try:
            outcome = await _run_manual_paper_lane_async(db)
            # This handler owns the transaction boundary: get_db neither commits
            # nor rolls back, and the execution service is forbidden from doing
            # either.
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            # No partial results. Reporting outcomes accumulated before the
            # failure would name orders that do not exist.
            return JSONResponse(status_code=503, content={"refused": "run_failed"})

    return _paper_run_response(outcome)


async def _run_manual_paper_lane_async(db):
    """Seam for the lane call, so a test can force a real overlap.

    The lane body is fully synchronous today, which means two handlers cannot
    interleave by accident -- and a concurrency test that relies on that passes
    for a reason that disappears the day a real market-data client is wired.
    """
    from backend.core.scheduler import run_manual_paper_lane

    return run_manual_paper_lane(db)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
