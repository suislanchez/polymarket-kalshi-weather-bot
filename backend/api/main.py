"""FastAPI backend for BTC 5-min trading bot dashboard."""
from fastapi import FastAPI, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import asyncio
import json
import math
import os
import stat
import tempfile
from urllib.parse import urlparse

from backend.config import settings
from backend.models.database import (
    get_db, init_db, SessionLocal,
    Signal, Trade, BotState, AILog, ScanLog
)
from backend.core.signals import scan_for_signals, TradingSignal
from backend.data.btc_markets import fetch_active_btc_markets, BtcMarket
from backend.data.crypto import fetch_crypto_price, compute_btc_microstructure

from pydantic import BaseModel

app = FastAPI(
    title="Weather Edge",
    description="Kalshi weather market signal engine — GFS 31-member ensemble + METAR real-time",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


DEFAULT_LIVE_DATA = {
    "kalshi": {
        "balance": 0.0,
        "portfolio_value": 0.0,
        "total": 0.0,
        "positions": [],
        "resting_orders": [],
        "last_live_trade_ts": "",
        "error": None,
    },
    "polymarket": {
        "balance": 0.0,
        "position_value": 0.0,
        "total": 0.0,
        "positions": [],
        "last_live_trade_ts": "",
        "dry_run_warning": False,
        "error": None,
    },
    "lifetime": {
        "lifetime_pnl": 0.0,
        "kalshi_lifetime_pnl": 0.0,
        "poly_lifetime_pnl": 0.0,
        "total_deposited": 0.0,
        "kalshi_deposited": 0.0,
        "poly_deposited": 0.0,
        "current_total": 0.0,
        "today_spent": 0.0,
        "error": None,
    },
}


def _get_or_create_bot_state(db: Session) -> BotState:
    state = db.query(BotState).first()
    if not state:
        state = BotState(
            bankroll=settings.INITIAL_BANKROLL,
            total_trades=0,
            winning_trades=0,
            total_pnl=0.0,
            is_running=False,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _log_event(event_type: str, message: str, data: Optional[dict] = None) -> None:
    try:
        from backend.core.scheduler import log_event
        log_event(event_type, message, data or {})
    except ModuleNotFoundError:
        return


# Pydantic response models
def _safe_float(value, default: Optional[float] = 0.0) -> Optional[float]:
    """Return finite JSON-safe floats only; sanitize DB/provider NaN/Infinity/None."""
    if value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


class BtcPriceResponse(BaseModel):
    price: float
    change_24h: float
    change_7d: float
    market_cap: float
    volume_24h: float
    last_updated: datetime


class BtcWindowResponse(BaseModel):
    slug: str
    market_id: str
    up_price: float
    down_price: float
    window_start: datetime
    window_end: datetime
    volume: float
    is_active: bool
    is_upcoming: bool
    time_until_end: float
    spread: float


class MicrostructureResponse(BaseModel):
    rsi: float = 50.0
    momentum_1m: float = 0.0
    momentum_5m: float = 0.0
    momentum_15m: float = 0.0
    vwap_deviation: float = 0.0
    sma_crossover: float = 0.0
    volatility: float = 0.0
    price: float = 0.0
    source: str = "unknown"


class SignalResponse(BaseModel):
    market_ticker: str
    market_title: str
    platform: str
    direction: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    suggested_size: float
    reasoning: str
    timestamp: datetime
    category: str = "crypto"
    event_slug: Optional[str] = None
    btc_price: float = 0.0
    btc_change_24h: float = 0.0
    window_end: Optional[datetime] = None
    actionable: bool = False


class TradeResponse(BaseModel):
    id: int
    market_ticker: str
    platform: str
    event_slug: Optional[str] = None
    direction: str
    entry_price: float
    size: float
    timestamp: datetime
    settled: bool
    result: str
    pnl: Optional[float]


class BotStats(BaseModel):
    bankroll: float
    total_trades: int
    winning_trades: int
    win_rate: float
    total_pnl: float
    is_running: bool
    last_run: Optional[datetime]


class CalibrationBucket(BaseModel):
    bucket: str
    predicted_avg: float
    actual_rate: float
    count: int


class CalibrationSummary(BaseModel):
    total_signals: int
    total_with_outcome: int
    accuracy: float
    avg_predicted_edge: float
    avg_actual_edge: float
    brier_score: float


class WeatherForecastResponse(BaseModel):
    city_key: str
    city_name: str
    target_date: str
    mean_high: float
    std_high: float
    mean_low: float
    std_low: float
    num_members: int
    ensemble_agreement: float


class WeatherMarketResponse(BaseModel):
    slug: str
    market_id: str
    platform: str = "polymarket"
    title: str
    city_key: str
    city_name: str
    target_date: str
    threshold_f: float
    metric: str
    direction: str
    yes_price: float
    no_price: float
    volume: float


class WeatherSignalResponse(BaseModel):
    market_id: str
    city_key: str
    city_name: str
    target_date: str
    threshold_f: float
    metric: str
    direction: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    suggested_size: float
    reasoning: str
    ensemble_mean: float
    ensemble_std: float
    ensemble_members: int
    signal_source: Optional[str] = None
    metar_note: Optional[str] = None
    observation_source: Optional[str] = None
    station_id: Optional[str] = None
    observed_at: Optional[str] = None
    fetched_at: Optional[str] = None
    signal_at: Optional[str] = None
    observation_latency_seconds: Optional[float] = None
    signal_latency_seconds: Optional[float] = None
    threshold_state: Optional[str] = None
    fusion_lock_state: Optional[str] = None
    fusion_trade_allowed: Optional[bool] = None
    fusion_authority_source: Optional[str] = None
    fusion_watch_sources: List[str] = []
    fusion_rejected_sources: List[str] = []
    fusion_conflicts: List[str] = []
    fusion_skip_reason: Optional[str] = None
    raw_hash: Optional[str] = None
    source_url: Optional[str] = None
    actionable: bool = False


class DashboardData(BaseModel):
    stats: BotStats
    btc_price: Optional[BtcPriceResponse]
    microstructure: Optional[MicrostructureResponse] = None
    windows: List[BtcWindowResponse]
    active_signals: List[SignalResponse]
    recent_trades: List[TradeResponse]
    equity_curve: List[dict]
    calibration: Optional[CalibrationSummary] = None
    weather_signals: List[WeatherSignalResponse] = []
    weather_forecasts: List[WeatherForecastResponse] = []


class EventResponse(BaseModel):
    timestamp: str
    type: str
    message: str
    data: dict = {}


class WeatherStatusResponse(BaseModel):
    enabled: bool
    fast_loop_interval_seconds: int
    next_fast_scan_in_seconds: Optional[float] = None
    cache_age_seconds: Optional[float] = None
    last_observation_age_seconds: Optional[float] = None
    last_observation: Optional[dict] = None
    last_change: Optional[dict] = None


# Startup / Shutdown
@app.on_event("startup")
async def startup():
    print("=" * 60)
    print("WEATHER EDGE v2.0")
    print("GFS Ensemble + METAR Real-Time Kalshi Signal Engine")
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
            print(f"Initialized fresh state")
        else:
            state.is_running = True
            db.commit()
    finally:
        db.close()

    print("")
    print("Configuration:")
    print(f"  - Simulation mode: {settings.SIMULATION_MODE}")
    print(f"  - Weather edge threshold: {settings.WEATHER_MIN_EDGE_THRESHOLD:.0%}")
    print(f"  - Kelly fraction: {settings.KELLY_FRACTION:.0%}")
    print(f"  - Weather scan: every {settings.WEATHER_SCAN_INTERVAL_SECONDS}s")
    print("")

    from backend.core.scheduler import start_scheduler, log_event
    start_scheduler()
    log_event("success", "Weather Edge initialized")

    print("Weather Edge is now running!")
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
@app.get("/api/status")
async def root():
    return {"status": "ok", "message": "Weather Edge API v2.0 — GFS Ensemble + METAR", "simulation_mode": settings.SIMULATION_MODE}


@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/data")
async def get_live_data(db: Session = Depends(get_db)):
    state = _get_or_create_bot_state(db)
    return {
        "ts": datetime.utcnow().isoformat(),
        **DEFAULT_LIVE_DATA,
        "metar_lines": [],
        "metar_poly_lines": [],
        "metar_v2_signals": [],
        "system": {
            "services": [{"label": "Weather Edge", "running": bool(state.is_running)}],
            "socks_up": False,
        },
    }


@app.get("/api/stats", response_model=BotStats)
async def get_stats(db: Session = Depends(get_db)):
    state = db.query(BotState).first()
    if not state:
        raise HTTPException(status_code=404, detail="Bot state not initialized")

    bankroll = _safe_float(state.bankroll, 0.0) or 0.0
    total_pnl = _safe_float(state.total_pnl, 0.0) or 0.0
    win_rate = state.winning_trades / state.total_trades if state.total_trades > 0 else 0
    win_rate = _safe_float(win_rate, 0.0) or 0.0

    return BotStats(
        bankroll=bankroll,
        total_trades=state.total_trades,
        winning_trades=state.winning_trades,
        win_rate=win_rate,
        total_pnl=total_pnl,
        is_running=state.is_running,
        last_run=state.last_run
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
                volume=m.volume,
                is_active=m.is_active,
                is_upcoming=m.is_upcoming,
                time_until_end=m.time_until_end,
                spread=m.spread,
            )
            for m in markets
        ]
    except Exception:
        return []


@app.get("/api/signals", response_model=List[SignalResponse])
async def get_signals():
    """Get current BTC trading signals (returns empty if BTC disabled)."""
    if not settings.BTC_ENABLED:
        return []
    try:
        signals = await scan_for_signals()
        return [_signal_to_response(s) for s in signals]
    except Exception:
        return []


@app.get("/api/signals/actionable", response_model=List[SignalResponse])
async def get_actionable_signals():
    """Get only signals that pass the edge threshold (returns empty if BTC disabled)."""
    if not settings.BTC_ENABLED:
        return []
    try:
        signals = await scan_for_signals()
        actionable = [s for s in signals if s.passes_threshold]
        return [_signal_to_response(s) for s in actionable]
    except Exception:
        return []


def _signal_to_response(s: TradingSignal, actionable: bool = False) -> SignalResponse:
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
        actionable=actionable,
    )


@app.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(
    limit: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    from backend.data.kalshi_client import kalshi_credentials_present

    # If Kalshi is configured and not in simulation mode, return real fills
    if kalshi_credentials_present() and not settings.SIMULATION_MODE:
        try:
            from backend.data.kalshi_client import KalshiClient
            client = KalshiClient()
            fills_data = await client.get("/portfolio/fills", params={"limit": limit})
            fills = fills_data.get("fills", [])
            result = []
            for i, fill in enumerate(fills):
                action = fill.get("action", "buy")
                direction = "YES" if action == "buy" else "NO"
                side = fill.get("side", "yes")
                price_cents = fill.get("yes_price", fill.get("no_price", 50))
                entry_price = price_cents / 100.0
                created_time = fill.get("created_time", datetime.utcnow().isoformat())
                if isinstance(created_time, str):
                    try:
                        ts = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
                    except Exception:
                        ts = datetime.utcnow()
                else:
                    ts = datetime.utcnow()
                result.append(TradeResponse(
                    id=i + 1,
                    market_ticker=fill.get("ticker", ""),
                    platform="kalshi",
                    event_slug=fill.get("ticker", ""),
                    direction=side.upper(),
                    entry_price=entry_price,
                    size=fill.get("count", 0) * entry_price,
                    timestamp=ts,
                    settled=False,
                    result="pending",
                    pnl=None,
                ))
            return result
        except Exception:
            pass  # Fall through to DB trades on error

    # Default: DB trades (simulation)
    query = db.query(Trade)
    if status:
        query = query.filter(Trade.result == status)
    trades = query.order_by(Trade.timestamp.desc()).limit(limit).all()

    return [
        TradeResponse(
            id=t.id,
            market_ticker=t.market_ticker,
            platform=t.platform,
            event_slug=t.event_slug,
            direction=t.direction,
            entry_price=_safe_float(t.entry_price, 0.0) or 0.0,
            size=_safe_float(t.size, 0.0) or 0.0,
            timestamp=t.timestamp,
            settled=t.settled,
            result=t.result,
            pnl=_safe_float(t.pnl, None)
        )
        for t in trades
    ]


@app.get("/api/equity-curve")
async def get_equity_curve(db: Session = Depends(get_db)):
    from backend.data.kalshi_client import kalshi_credentials_present

    # If Kalshi configured and live mode, build equity curve from balance snapshots or fills
    if kalshi_credentials_present() and not settings.SIMULATION_MODE:
        try:
            from backend.data.kalshi_client import KalshiClient
            client = KalshiClient()
            balance_data = await client.get_balance()
            balance_cents = balance_data.get("balance", 0)
            balance_usd = balance_cents / 100.0
            return [{
                "timestamp": datetime.utcnow().isoformat(),
                "pnl": balance_usd - settings.INITIAL_BANKROLL,
                "bankroll": balance_usd,
            }]
        except Exception:
            pass  # Fall through to DB curve

    # Default: build from settled DB trades
    trades = db.query(Trade).filter(Trade.settled == True).order_by(Trade.timestamp).all()

    curve = []
    cumulative_pnl = 0
    bankroll = settings.INITIAL_BANKROLL

    for trade in trades:
        pnl = _safe_float(trade.pnl, None)
        if pnl is not None:
            cumulative_pnl += pnl
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


# Settings endpoints
@app.get("/api/settings")
async def get_settings():
    """Return current runtime configuration (no secrets in response)."""
    from backend.data.kalshi_client import kalshi_credentials_present
    return {
        "simulation_mode": settings.SIMULATION_MODE,
        "kalshi_configured": kalshi_credentials_present(),
        "kalshi_key_id": settings.KALSHI_API_KEY_ID or "",
        "initial_bankroll": settings.INITIAL_BANKROLL,
        "weather_min_edge_threshold": settings.WEATHER_MIN_EDGE_THRESHOLD,
        "weather_max_trade_size": settings.WEATHER_MAX_TRADE_SIZE,
    }


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _is_loopback_origin(origin: str) -> bool:
    try:
        parsed = urlparse(origin)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in _LOOPBACK_HOSTS


def _is_loopback_client(request: Request) -> bool:
    if request.client is None:
        return False
    return request.client.host in _LOOPBACK_HOSTS


def _require_loopback_mutation(request: Request) -> None:
    """Raise 403 unless the request originates from loopback.

    Two checks:
    1. TCP peer address must be a loopback host.
    2. If an Origin header is present it must be a loopback origin —
       this blocks CSRF from malicious web pages that can POST to localhost.
    """
    if not _is_loopback_client(request):
        raise HTTPException(status_code=403, detail="Credential updates are allowed only from localhost")

    origin = request.headers.get("origin")
    if origin is not None and not _is_loopback_origin(origin):
        raise HTTPException(status_code=403, detail="Cross-origin settings updates are not allowed")


def _upsert_env_value_preserving_lines(lines: list[str], key: str, value: str) -> list[str]:
    updated = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("#") and "=" in stripped:
            existing_key = stripped.partition("=")[0].strip()
            if existing_key == key:
                newline = "\n" if line.endswith("\n") else ""
                new_lines.append(f"{key}={value}{newline}")
                updated = True
                continue
        new_lines.append(line)
    if not updated:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] = new_lines[-1] + "\n"
        new_lines.append(f"{key}={value}\n")
    return new_lines


def _write_text_atomic(path: str, lines: list[str]) -> None:
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w") as f:
            f.writelines(lines)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/api/settings")
async def update_settings(payload: dict, request: Request):
    """Update runtime settings and persist to .env file."""

    _require_loopback_mutation(request)

    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    env_path = os.path.abspath(env_path)

    # --- Phase 1: validate all numeric fields BEFORE touching any file or state ---
    validated: dict = {}

    if "initial_bankroll" in payload:
        try:
            validated["initial_bankroll"] = float(payload["initial_bankroll"])
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="initial_bankroll must be a number")

    if "min_edge" in payload:
        try:
            val = float(payload["min_edge"])
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="min_edge must be a number")
        if val <= 0:
            raise HTTPException(status_code=422, detail="WEATHER_MIN_EDGE_THRESHOLD must be > 0")
        validated["min_edge"] = val

    if "max_trade_size" in payload:
        try:
            val = float(payload["max_trade_size"])
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="max_trade_size must be a number")
        if val <= 0:
            raise HTTPException(status_code=422, detail="WEATHER_MAX_TRADE_SIZE must be > 0")
        validated["max_trade_size"] = val

    # --- Phase 2: load existing .env (preserve comments, ordering, untouched keys) ---
    env_lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            env_lines = f.readlines()

    # --- Phase 3: apply all changes atomically ---
    key_id = payload.get("key_id")
    private_key_pem = payload.get("private_key_pem")

    if key_id is not None:
        object.__setattr__(settings, "KALSHI_API_KEY_ID", key_id or None)
        os.environ["KALSHI_API_KEY_ID"] = key_id
        env_lines = _upsert_env_value_preserving_lines(env_lines, "KALSHI_API_KEY_ID", key_id)

    if private_key_pem:
        # Normalize newlines: handle \n literals in JSON
        pem_text = private_key_pem.replace("\\n", "\n").strip()
        pem_path = os.path.join(os.path.dirname(env_path), "kalshi_private_key.pem")
        fd = os.open(pem_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(pem_text + "\n")
        os.chmod(pem_path, stat.S_IRUSR | stat.S_IWUSR)
        object.__setattr__(settings, "KALSHI_PRIVATE_KEY_PATH", pem_path)
        os.environ["KALSHI_PRIVATE_KEY_PATH"] = pem_path
        env_lines = _upsert_env_value_preserving_lines(env_lines, "KALSHI_PRIVATE_KEY_PATH", pem_path)

    if "simulation_mode" in payload:
        val = bool(payload["simulation_mode"])
        object.__setattr__(settings, "SIMULATION_MODE", val)
        os.environ["SIMULATION_MODE"] = str(val)
        env_lines = _upsert_env_value_preserving_lines(env_lines, "SIMULATION_MODE", str(val))

    if "initial_bankroll" in validated:
        val = validated["initial_bankroll"]
        object.__setattr__(settings, "INITIAL_BANKROLL", val)
        os.environ["INITIAL_BANKROLL"] = str(val)
        env_lines = _upsert_env_value_preserving_lines(env_lines, "INITIAL_BANKROLL", str(val))

    if "min_edge" in validated:
        val = validated["min_edge"]
        object.__setattr__(settings, "WEATHER_MIN_EDGE_THRESHOLD", val)
        os.environ["WEATHER_MIN_EDGE_THRESHOLD"] = str(val)
        env_lines = _upsert_env_value_preserving_lines(env_lines, "WEATHER_MIN_EDGE_THRESHOLD", str(val))

    if "max_trade_size" in validated:
        val = validated["max_trade_size"]
        object.__setattr__(settings, "WEATHER_MAX_TRADE_SIZE", val)
        os.environ["WEATHER_MAX_TRADE_SIZE"] = str(val)
        env_lines = _upsert_env_value_preserving_lines(env_lines, "WEATHER_MAX_TRADE_SIZE", str(val))

    _write_text_atomic(env_path, env_lines)

    from backend.data.kalshi_client import kalshi_credentials_present
    return {
        "ok": True,
        "kalshi_configured": kalshi_credentials_present(),
        "simulation_mode": settings.SIMULATION_MODE,
    }


@app.post("/api/settings/test-connection")
async def test_kalshi_connection():
    """Test Kalshi API connection using current credentials."""
    from backend.data.kalshi_client import KalshiClient, kalshi_credentials_present

    if not kalshi_credentials_present():
        return {"ok": False, "error": "Kalshi credentials not configured. Set Key ID and Private Key above."}

    try:
        client = KalshiClient()
        balance_data = await client.get_balance()
        return {"ok": True, "balance": balance_data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
        return {
            "connected": True,
            "balance": balance_data,
        }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
        }


# Weather endpoints
@app.get("/api/weather/forecasts", response_model=List[WeatherForecastResponse])
async def get_weather_forecasts():
    """Get ensemble forecasts for configured cities."""
    if not settings.WEATHER_ENABLED:
        return []

    try:
        from backend.data.weather import fetch_ensemble_forecast, CITY_CONFIG
        from datetime import date

        city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
        forecasts = []

        for city_key in city_keys:
            if city_key not in CITY_CONFIG:
                continue
            forecast = await fetch_ensemble_forecast(city_key)
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


@app.get("/api/kalshi/markets")
async def get_kalshi_markets():
    if not settings.WEATHER_ENABLED:
        return {"markets": [], "count": 0, "traded_today_count": 0}
    try:
        from backend.data.kalshi_markets import fetch_kalshi_weather_markets
        city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
        markets = await fetch_kalshi_weather_markets(city_keys)
    except Exception:
        markets = []
    return {"markets": [_market_to_frontend(m) for m in markets], "count": len(markets), "traded_today_count": 0}


@app.get("/api/polymarket/markets")
async def get_polymarket_markets():
    if not settings.WEATHER_ENABLED:
        return {"markets": [], "count": 0}
    try:
        from backend.data.weather_markets import fetch_polymarket_weather_markets
        city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
        markets = await fetch_polymarket_weather_markets(city_keys)
    except Exception:
        markets = []
    return {"markets": [_market_to_frontend(m) for m in markets], "count": len(markets)}


def _market_to_frontend(m) -> dict:
    return {
        "condition_id": getattr(m, "market_id", ""),
        "city": getattr(m, "city_name", ""),
        "question": getattr(m, "title", ""),
        "side": getattr(m, "direction", ""),
        "price": getattr(m, "yes_price", None),
        "bet_usd": None,
        "metar_temp_f": None,
        "threshold": str(getattr(m, "threshold_f", "")),
        "score": None,
        "score_desc": None,
        "dry_run": settings.SIMULATION_MODE,
        "order_success": False,
        "order_id": "",
        "ts": datetime.utcnow().isoformat(),
        "status": "scanned",
        "roi_pct": None,
        "current_price": getattr(m, "yes_price", None),
        "current_pnl": None,
        "position_size": None,
        "trigger": getattr(m, "metric", ""),
        "threshold_raw": str(getattr(m, "threshold_f", "")),
        "current_temp_f": None,
        "peak_temp_f": None,
        "confidence": None,
        "raw_price": getattr(m, "yes_price", None),
        "filtered_prob": None,
        "ev_net": None,
        "ev_gross": None,
        "uncertainty": None,
        "recommend": False,
        "flagged_informed": False,
        "is_traded": False,
        "v1": None,
        "v2": None,
    }


@app.get("/api/weather/markets", response_model=List[WeatherMarketResponse])
async def get_weather_markets():
    """Get active weather temperature markets. Falls back to signal-derived markets if Polymarket fetch is empty."""
    if not settings.WEATHER_ENABLED:
        return []

    markets = []

    try:
        from backend.data.weather_markets import fetch_polymarket_weather_markets
        city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
        markets = await fetch_polymarket_weather_markets(city_keys)
    except Exception:
        pass

    # If Polymarket returned nothing, derive markets from signal engine (Kalshi markets)
    if not markets:
        try:
            from backend.core.weather_signals import scan_for_weather_signals
            wx_signals = await scan_for_weather_signals()
            for s in wx_signals:
                m = s.market
                markets.append(WeatherMarketResponse(
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
                ))
            return markets
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
        )
        for m in markets
    ]


class WeatherSourceBenchmarkRunRequest(BaseModel):
    station_id: str
    lat: Optional[float] = None
    lon: Optional[float] = None


class WeatherSourceBenchmarkBatchRequest(BaseModel):
    targets: List[WeatherSourceBenchmarkRunRequest]


MAX_WEATHER_SOURCE_BENCHMARK_BATCH_TARGETS = 10


def _as_utc(value: datetime) -> datetime:
    """Normalize datetimes before age arithmetic; tolerate legacy naive UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@app.get("/api/weather/source-benchmark")
async def get_weather_source_benchmark():
    """Return benchmark-backed source-fusion evidence and conservative policy."""
    from backend.core.weather_source_benchmark import (
        build_source_promotion_policy,
        summarize_source_benchmark_history,
    )

    history_path = settings.WEATHER_SOURCE_BENCHMARK_HISTORY_PATH or "data/weather_source_benchmark_history.jsonl"
    summary = summarize_source_benchmark_history(history_path)
    policy = build_source_promotion_policy(summary)
    return {
        "history_path": history_path,
        "summary": summary,
        "policy": policy,
    }


@app.post("/api/weather/source-benchmark/run")
async def run_weather_source_benchmark(request: WeatherSourceBenchmarkRunRequest):
    """Run and persist a bounded weather-source benchmark for one station."""
    from dataclasses import asdict
    from backend.core.weather_source_benchmark import (
        append_source_benchmark_result,
        benchmark_observation_sources,
        build_source_promotion_policy,
        default_benchmark_providers,
        summarize_source_benchmark,
    )

    result = benchmark_observation_sources(
        station_id=request.station_id.upper(),
        lat=request.lat,
        lon=request.lon,
        providers=default_benchmark_providers(),
    )
    run_id = datetime.utcnow().isoformat()
    history_path = settings.WEATHER_SOURCE_BENCHMARK_HISTORY_PATH or "data/weather_source_benchmark_history.jsonl"
    append_source_benchmark_result(history_path, result, run_id=run_id)
    summary = summarize_source_benchmark(result.rows, failures=result.failures)
    policy = build_source_promotion_policy(summary)
    return {
        "run_id": run_id,
        "station_id": result.station_id,
        "history_path": history_path,
        "rows": [asdict(row) for row in result.rows],
        "failures": result.failures,
        "summary": summary,
        "policy": policy,
    }


@app.get("/api/weather/status", response_model=WeatherStatusResponse)
async def get_weather_status():
    """Expose Weather Edge nowcast freshness and threshold-state SLO fields."""
    from backend.core import scheduler as scheduler_mod
    from backend.core.weather_signals import get_cached_signals, get_signal_cache_age_seconds

    signals = get_cached_signals() if settings.WEATHER_ENABLED else []
    observations = [getattr(signal, "weather_observation", None) for signal in signals]
    observations = [observation for observation in observations if observation is not None]
    latest_observation = max(observations, key=lambda obs: _as_utc(obs.fetched_at), default=None)
    now = _as_utc(datetime.utcnow())
    cache_age = get_signal_cache_age_seconds() if settings.WEATHER_ENABLED else None
    if cache_age == float("inf"):
        cache_age = None

    last_change = None
    for event in reversed(scheduler_mod.get_recent_events(200)):
        if event.get("type") == "weather_state_change":
            last_change = event.get("data") or {}
            break

    return WeatherStatusResponse(
        enabled=settings.WEATHER_ENABLED,
        fast_loop_interval_seconds=settings.WEATHER_NOWCAST_INTERVAL_SECONDS,
        next_fast_scan_in_seconds=(
            max(0.0, settings.WEATHER_NOWCAST_INTERVAL_SECONDS - float(cache_age))
            if cache_age is not None else None
        ),
        cache_age_seconds=cache_age,
        last_observation_age_seconds=(
            max(0.0, (now - _as_utc(latest_observation.observed_at)).total_seconds())
            if latest_observation is not None else None
        ),
        last_observation=(
            {
                "source": latest_observation.source,
                "station_id": latest_observation.station_id,
                "observed_at": latest_observation.observed_at.isoformat(),
                "fetched_at": latest_observation.fetched_at.isoformat(),
                "temp_f": latest_observation.temp_f,
                "raw_hash": latest_observation.raw_hash,
            }
            if latest_observation is not None else None
        ),
        last_change=last_change,
    )


@app.post("/api/weather/source-benchmark/batch")
async def run_weather_source_benchmark_batch(request: WeatherSourceBenchmarkBatchRequest):
    """Run and persist bounded weather-source benchmarks for multiple stations."""
    from dataclasses import asdict
    from backend.core.weather_source_benchmark import (
        StationBenchmarkTarget,
        build_source_promotion_policy,
        default_benchmark_providers,
        run_station_benchmark_batch,
        summarize_source_benchmark_history,
    )

    if not 1 <= len(request.targets) <= MAX_WEATHER_SOURCE_BENCHMARK_BATCH_TARGETS:
        raise HTTPException(
            status_code=422,
            detail=f"targets must contain 1-{MAX_WEATHER_SOURCE_BENCHMARK_BATCH_TARGETS} stations",
        )

    run_id = datetime.utcnow().isoformat()
    history_path = settings.WEATHER_SOURCE_BENCHMARK_HISTORY_PATH or "data/weather_source_benchmark_history.jsonl"
    targets = [
        StationBenchmarkTarget(station_id=target.station_id.upper(), lat=target.lat, lon=target.lon)
        for target in request.targets
    ]
    results = run_station_benchmark_batch(
        targets,
        providers=default_benchmark_providers(),
        history_path=history_path,
        run_id=run_id,
    )
    summary = summarize_source_benchmark_history(history_path)
    policy = build_source_promotion_policy(summary)
    return {
        "run_id": run_id,
        "history_path": history_path,
        "results": [
            {
                "station_id": result.station_id,
                "rows": [asdict(row) for row in result.rows],
                "failures": result.failures,
            }
            for result in results
        ],
        "summary": summary,
        "policy": policy,
    }


@app.get("/api/weather/signals", response_model=List[WeatherSignalResponse])
async def get_weather_signals():
    """Get current weather trading signals from cache (populated by background scanner)."""
    if not settings.WEATHER_ENABLED:
        return []

    import logging
    _logger = logging.getLogger("trading_bot")
    try:
        from backend.core.weather_signals import get_cached_signals, get_signal_cache_age_seconds

        signals = get_cached_signals()
        age = get_signal_cache_age_seconds()
        _logger.info(f"Weather signals endpoint: {len(signals)} signals from cache (age: {age:.0f}s)")
        return [_weather_signal_to_response(s) for s in signals]
    except Exception as e:
        _logger.error(f"Weather signals endpoint error: {e}", exc_info=True)
        return []


def _weather_signal_to_response(s) -> WeatherSignalResponse:
    # Support both old WeatherTradingSignal (from weather_signals.py) formats
    net_edge = getattr(s, "net_edge", s.edge)
    observation = getattr(s, "weather_observation", None)
    signal_at = getattr(s, "signal_at", None)
    observation_latency = None
    signal_latency = None
    if observation is not None:
        observation_latency = observation.freshness_seconds
        if signal_at is not None:
            signal_latency = max(0.0, (signal_at - observation.fetched_at).total_seconds())
    fused = None
    source_observations = getattr(s, "source_observations", None)
    source_fusion_policy = getattr(s, "source_fusion_policy", None)
    if source_observations and source_fusion_policy:
        from backend.core.weather_source_fusion import fuse_weather_observations
        fused = fuse_weather_observations(
            observations=source_observations,
            policy=source_fusion_policy,
            threshold_f=s.market.threshold_f,
            metric=s.market.metric,
        )
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
        edge=net_edge,
        confidence=s.confidence,
        suggested_size=s.suggested_size,
        reasoning=s.reasoning,
        ensemble_mean=s.ensemble_mean,
        ensemble_std=s.ensemble_std,
        ensemble_members=s.ensemble_members,
        signal_source=getattr(s, "signal_source", None),
        metar_note=getattr(s, "metar_note", None),
        observation_source=getattr(observation, "source", None),
        station_id=getattr(observation, "station_id", None),
        observed_at=observation.observed_at.isoformat() if observation else None,
        fetched_at=observation.fetched_at.isoformat() if observation else None,
        signal_at=signal_at.isoformat() if signal_at else None,
        observation_latency_seconds=observation_latency,
        signal_latency_seconds=signal_latency,
        threshold_state=getattr(s, "threshold_state", None),
        fusion_lock_state=getattr(fused, "lock_state", None),
        fusion_trade_allowed=getattr(fused, "trade_allowed", None),
        fusion_authority_source=getattr(fused, "authority_source", None),
        fusion_watch_sources=getattr(fused, "watch_sources", []),
        fusion_rejected_sources=getattr(fused, "rejected_sources", []),
        fusion_conflicts=getattr(fused, "conflicts", []),
        fusion_skip_reason=getattr(fused, "skip_reason", None),
        raw_hash=getattr(observation, "raw_hash", None),
        source_url=getattr(observation, "source_url", None),
        actionable=s.passes_threshold,
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
    state = _get_or_create_bot_state(db)
    state.is_running = True
    db.commit()

    try:
        from backend.core.scheduler import start_scheduler, is_scheduler_running
        if not is_scheduler_running():
            start_scheduler()
    except ModuleNotFoundError:
        pass

    _log_event("success", "Trading bot started")
    return {"status": "started", "is_running": True}


@app.post("/api/bot/stop")
async def stop_bot(db: Session = Depends(get_db)):
    state = _get_or_create_bot_state(db)
    state.is_running = False
    db.commit()

    _log_event("info", "Trading bot paused")
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


@app.get("/api/dashboard", response_model=DashboardData)
async def get_dashboard(db: Session = Depends(get_db)):
    """Get all dashboard data in one call."""
    stats = await get_stats(db)

    # Fetch BTC price from microstructure first, fallback to CoinGecko
    # Skip if BTC is disabled to avoid hanging on dead network calls
    btc_price_data = None
    micro_data = None
    if settings.BTC_ENABLED:
        try:
            micro = await asyncio.wait_for(compute_btc_microstructure(), timeout=3.0)
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
    if not btc_price_data and settings.BTC_ENABLED:
        try:
            btc = await asyncio.wait_for(fetch_crypto_price("BTC"), timeout=3.0)
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

    # Fetch windows (only when BTC enabled)
    windows = []
    if settings.BTC_ENABLED:
        try:
            markets = await asyncio.wait_for(fetch_active_btc_markets(), timeout=3.0)
            windows = [
                BtcWindowResponse(
                    slug=m.slug,
                    market_id=m.market_id,
                    up_price=m.up_price,
                    down_price=m.down_price,
                    window_start=m.window_start,
                    window_end=m.window_end,
                    volume=m.volume,
                    is_active=m.is_active,
                    is_upcoming=m.is_upcoming,
                    time_until_end=m.time_until_end,
                    spread=m.spread,
                )
                for m in markets
            ]
        except Exception:
            pass

    # Signals — return BTC signals only if BTC is enabled
    signals = []
    if settings.BTC_ENABLED:
        try:
            raw_signals = await scan_for_signals()
            signals = [_signal_to_response(s, actionable=s.passes_threshold) for s in raw_signals]
        except Exception:
            pass

    # Recent trades
    trades = db.query(Trade).order_by(Trade.timestamp.desc()).limit(50).all()
    recent_trades = [
        TradeResponse(
            id=t.id,
            market_ticker=t.market_ticker,
            platform=t.platform,
            event_slug=t.event_slug,
            direction=t.direction,
            entry_price=_safe_float(t.entry_price, 0.0) or 0.0,
            size=_safe_float(t.size, 0.0) or 0.0,
            timestamp=t.timestamp,
            settled=t.settled,
            result=t.result,
            pnl=_safe_float(t.pnl, None)
        )
        for t in trades
    ]

    # Equity curve
    equity_trades = db.query(Trade).filter(Trade.settled == True).order_by(Trade.timestamp).all()
    equity_curve = []
    cumulative_pnl = 0
    for trade in equity_trades:
        pnl = _safe_float(trade.pnl, None)
        if pnl is not None:
            cumulative_pnl += pnl
            equity_curve.append({
                "timestamp": trade.timestamp.isoformat(),
                "pnl": cumulative_pnl,
                "bankroll": settings.INITIAL_BANKROLL + cumulative_pnl
            })

    # Calibration summary
    calibration = _compute_calibration_summary(db)

    # Weather data (if enabled)
    weather_signals_data = []
    weather_forecasts_data = []
    if settings.WEATHER_ENABLED:
        try:
            from backend.core.weather_signals import get_cached_signals, get_signal_cache_age_seconds

            # Serve from cache — fresh scan runs in background scheduler every 5min
            wx_signals = get_cached_signals()
            weather_signals_data = [_weather_signal_to_response(s) for s in wx_signals]
        except Exception:
            pass

    return DashboardData(
        stats=stats,
        btc_price=btc_price_data,
        microstructure=micro_data,
        windows=windows,
        active_signals=signals,
        recent_trades=recent_trades,
        equity_curve=equity_curve,
        calibration=calibration,
        weather_signals=weather_signals_data,
        weather_forecasts=weather_forecasts_data,
    )


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await ws_manager.connect(websocket)

    try:
        await websocket.send_json({
            "timestamp": datetime.utcnow().isoformat(),
            "type": "success",
            "message": "Connected to Weather Edge"
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


# Serve pre-built frontend from frontend/dist
from pathlib import Path
_FRONTEND_DIST = (Path(__file__).parent / ".." / ".." / "frontend" / "dist").resolve()
if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(str(_FRONTEND_DIST / "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Don't intercept /api or /ws routes
        if full_path.startswith("api/") or full_path.startswith("ws"):
            raise HTTPException(status_code=404)
        index = _FRONTEND_DIST / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="Frontend not built")
        return FileResponse(str(index))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8765")))
