"""FastAPI backend for Weather Edge — Kalshi weather signal dashboard."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import os
import stat
import tempfile

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import BotState, Signal, Trade, get_db, init_db, SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 60)
    print("WEATHER EDGE")
    print("GFS Ensemble + METAR Real-Time Kalshi Signal Engine")
    print("=" * 60)
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
                is_running=False,
            )
            db.add(state)
        else:
            state.is_running = False
        db.commit()
    finally:
        db.close()

    try:
        from backend.core.scheduler import log_event
        log_event("success", "Weather Edge initialized in paused mode")
    except (ImportError, ModuleNotFoundError):
        pass
    print("Weather Edge initialized in paused mode. Press Start to scan.")
    print(f"Weather scan interval: {settings.WEATHER_SCAN_INTERVAL_SECONDS}s")
    print(f"Weather cities: {settings.WEATHER_CITIES}")
    print("=" * 60)
    try:
        yield
    finally:
        from backend.core.scheduler import stop_scheduler
        stop_scheduler()


app = FastAPI(
    title="Weather Edge",
    description="Kalshi weather market signal engine — GFS ensemble + METAR real-time lock detection",
    version="2.3.0",
    lifespan=lifespan,
)

ALLOWED_LOCAL_ORIGINS = {
    "http://localhost:8765",
    "http://127.0.0.1:8765",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ALLOWED_LOCAL_ORIGINS),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)


ws_manager = ConnectionManager()


class WeatherForecastResponse(BaseModel):
    city_key: str
    city_name: str
    target_date: str
    mean_high: float
    std_high: float
    mean_low: float = 0.0
    std_low: float = 0.0
    num_members: int
    ensemble_agreement: float


class WeatherMarketResponse(BaseModel):
    slug: str
    market_id: str
    platform: str = "kalshi"
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
    actionable: bool = False
    platform: str = "kalshi"
    signal_source: str = "GFS-ensemble"
    metar_note: str = ""
    gfs_probability: float = 0.0


class EventResponse(BaseModel):
    timestamp: str
    type: str
    message: str
    data: dict = {}


def _is_loopback_client(request: Request) -> bool:
    if request.client is None:
        return False
    return request.client.host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _require_loopback_mutation(request: Request, action: str = "Mutation") -> None:
    if not _is_loopback_client(request):
        raise HTTPException(status_code=403, detail=f"{action} is allowed only from localhost")
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_LOCAL_ORIGINS:
        raise HTTPException(status_code=403, detail=f"{action} rejected: invalid Origin")
    referer = request.headers.get("referer")
    if referer:
        try:
            from urllib.parse import urlsplit
            parsed = urlsplit(referer)
            referer_origin = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            referer_origin = ""
        if referer_origin and referer_origin not in ALLOWED_LOCAL_ORIGINS:
            raise HTTPException(status_code=403, detail=f"{action} rejected: invalid Referer")


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
    except (ImportError, ModuleNotFoundError):
        return


def _weather_signal_to_response(s) -> WeatherSignalResponse:
    net_edge = getattr(s, "net_edge", s.edge)
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
        actionable=s.passes_threshold,
        platform="kalshi",
        signal_source=getattr(s, "signal_source", "GFS-ensemble"),
        metar_note=getattr(s, "metar_note", ""),
        gfs_probability=getattr(s, "gfs_prob", 0.0),
    )


def _signal_to_market_response(s) -> WeatherMarketResponse:
    m = s.market
    return WeatherMarketResponse(
        slug=m.slug,
        market_id=m.market_id,
        platform="kalshi",
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


def _weather_forecasts_from_signals(signals: list) -> list[WeatherForecastResponse]:
    by_key: dict[str, object] = {}
    for s in signals:
        key = f"{s.market.city_key}:{s.market.target_date.isoformat()}"
        if key not in by_key:
            by_key[key] = s
    return [
        WeatherForecastResponse(
            city_key=s.market.city_key,
            city_name=s.market.city_name,
            target_date=s.market.target_date.isoformat(),
            mean_high=s.ensemble_mean,
            std_high=s.ensemble_std,
            num_members=s.ensemble_members,
            ensemble_agreement=max(s.gfs_prob, 1 - s.gfs_prob),
        )
        for s in by_key.values()
    ]


def _market_to_frontend_from_signal(s) -> dict:
    m = s.market
    status = "watching_hot" if s.passes_threshold else "watching" if s.signal_source != "GFS-veto" else "flagged"
    return {
        "condition_id": m.market_id,
        "city": m.city_name,
        "question": m.title,
        "side": s.direction,
        "price": m.yes_price if s.direction == "yes" else m.no_price,
        "bet_usd": s.suggested_size if s.passes_threshold else None,
        "metar_temp_f": None,
        "threshold": str(m.threshold_f),
        "score": None,
        "score_desc": None,
        "dry_run": settings.SIMULATION_MODE,
        "order_success": False,
        "order_id": "",
        "ts": s.timestamp.isoformat(),
        "status": status,
        "roi_pct": (s.edge * 100) if s.edge is not None else None,
        "current_price": m.yes_price,
        "current_pnl": None,
        "position_size": None,
        "trigger": s.signal_source,
        "threshold_raw": str(m.threshold_f),
        "current_temp_f": None,
        "peak_temp_f": None,
        "confidence": s.confidence,
        "raw_price": s.market_probability,
        "filtered_prob": s.model_probability,
        "ev_net": s.net_edge,
        "ev_gross": s.edge,
        "uncertainty": max(0.0, 1.0 - s.confidence),
        "recommend": s.passes_threshold,
        "flagged_informed": s.signal_source == "GFS-veto",
        "is_traded": False,
        "v1": None,
        "v2": None,
    }


@app.get("/api/status")
async def root():
    return {
        "status": "ok",
        "message": "Weather Edge API — GFS Ensemble + METAR",
        "simulation_mode": settings.SIMULATION_MODE,
    }


@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/data")
async def get_live_data(db: Session = Depends(get_db)):
    from backend.core.weather_signals import get_cached_signals, get_signal_cache_age_seconds

    state = _get_or_create_bot_state(db)
    signals = get_cached_signals()
    cache_age = get_signal_cache_age_seconds()
    if cache_age == float("inf"):
        cache_age = None
    weather_signals = [_weather_signal_to_response(s) for s in signals]
    forecasts = _weather_forecasts_from_signals(signals)
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kalshi": {
            "balance": 0.0,
            "portfolio_value": 0.0,
            "total": 0.0,
            "positions": [],
            "resting_orders": [],
            "last_live_trade_ts": "",
            "error": None,
        },
        "lifetime": {
            "lifetime_pnl": state.total_pnl,
            "kalshi_lifetime_pnl": state.total_pnl,
            "total_deposited": 0.0,
            "kalshi_deposited": 0.0,
            "current_total": state.bankroll,
            "today_spent": 0.0,
            "error": None,
        },
        "weather_signals": [w.model_dump() for w in weather_signals],
        "weather_forecasts": [f.model_dump() for f in forecasts],
        "system": {
            "services": [{"label": "Weather Edge", "running": bool(state.is_running)}],
            "weather_enabled": settings.WEATHER_ENABLED,
            "kalshi_configured": bool(settings.KALSHI_API_KEY_ID and settings.KALSHI_PRIVATE_KEY_PATH),
            "signal_cache_age_seconds": cache_age,
        },
    }


@app.post("/api/run-scan")
async def run_scan(request: Request, db: Session = Depends(get_db)):
    _require_loopback_mutation(request, "Manual scan")
    from backend.core.weather_signals import scan_for_weather_signals
    from backend.core.scheduler import log_event

    state = _get_or_create_bot_state(db)
    state.last_run = datetime.now(timezone.utc)
    db.commit()

    log_event("info", "Manual weather scan triggered")
    signals = await scan_for_weather_signals()
    actionable = [s for s in signals if s.passes_threshold]
    return {
        "status": "ok",
        "weather_signals": len(signals),
        "weather_actionable": len(actionable),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/settle-trades")
async def settle_trades_endpoint(request: Request, db: Session = Depends(get_db)):
    _require_loopback_mutation(request, "Manual settlement")
    from backend.core.settlement import settle_pending_trades, update_bot_state_with_settlements
    from backend.core.scheduler import log_event

    log_event("info", "Manual weather settlement triggered")
    settled = await settle_pending_trades(db)
    await update_bot_state_with_settlements(db, settled)
    return {
        "status": "ok",
        "settled_count": len(settled),
        "trades": [{"id": t.id, "result": t.result, "pnl": t.pnl} for t in settled],
    }


@app.get("/api/settings")
async def get_settings():
    from backend.data.kalshi_client import kalshi_credentials_present
    return {
        "simulation_mode": settings.SIMULATION_MODE,
        "kalshi_configured": kalshi_credentials_present(),
        "initial_bankroll": settings.INITIAL_BANKROLL,
        "weather_min_edge_threshold": settings.WEATHER_MIN_EDGE_THRESHOLD,
        "weather_max_trade_size": settings.WEATHER_MAX_TRADE_SIZE,
        "weather_max_entry_price": settings.WEATHER_MAX_ENTRY_PRICE,
        "live_trading_supported": False,
    }


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
    _require_loopback_mutation(request, "Settings updates")
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    env_lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            env_lines = f.readlines()

    key_id = payload.get("key_id")
    private_key_pem = payload.get("private_key_pem")

    if payload.get("simulation_mode") is False:
        raise HTTPException(
            status_code=422,
            detail="Weather Edge is paper-only: live Kalshi order execution is not implemented",
        )

    numeric_updates = []
    for payload_key, setting_name, env_key, min_value, max_value in [
        ("initial_bankroll", "INITIAL_BANKROLL", "INITIAL_BANKROLL", 0.0, None),
        ("min_edge", "WEATHER_MIN_EDGE_THRESHOLD", "WEATHER_MIN_EDGE_THRESHOLD", 0.0, 1.0),
        ("max_trade_size", "WEATHER_MAX_TRADE_SIZE", "WEATHER_MAX_TRADE_SIZE", 1.0, None),
    ]:
        if payload_key in payload:
            try:
                val = float(payload[payload_key])
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail=f"{payload_key} must be numeric")
            if val < min_value or (max_value is not None and val > max_value):
                range_desc = f">= {min_value}" if max_value is None else f"between {min_value} and {max_value}"
                raise HTTPException(status_code=422, detail=f"{payload_key} must be {range_desc}")
            numeric_updates.append((setting_name, env_key, val))

    if key_id is not None:
        object.__setattr__(settings, "KALSHI_API_KEY_ID", key_id or None)
        os.environ["KALSHI_API_KEY_ID"] = key_id
        env_lines = _upsert_env_value_preserving_lines(env_lines, "KALSHI_API_KEY_ID", key_id)

    if private_key_pem:
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

    for setting_name, env_key, val in numeric_updates:
        object.__setattr__(settings, setting_name, val)
        os.environ[env_key] = str(val)
        env_lines = _upsert_env_value_preserving_lines(env_lines, env_key, str(val))

    _write_text_atomic(env_path, env_lines)
    from backend.data.kalshi_client import kalshi_credentials_present
    return {"ok": True, "kalshi_configured": kalshi_credentials_present(), "simulation_mode": settings.SIMULATION_MODE}


@app.post("/api/settings/test-connection")
async def test_kalshi_connection(request: Request):
    _require_loopback_mutation(request, "Kalshi connection test")
    from backend.data.kalshi_client import KalshiClient, kalshi_credentials_present
    if not kalshi_credentials_present():
        return {"ok": False, "error": "Kalshi credentials not configured. Set Key ID and Private Key above."}
    try:
        client = KalshiClient()
        balance_data = await client.get_balance()
        return {"ok": True, "balance": balance_data}
    except Exception:
        return {"ok": False, "error": "Kalshi connection failed"}


@app.get("/api/kalshi/status")
async def get_kalshi_status(request: Request):
    _require_loopback_mutation(request, "Kalshi status")
    from backend.data.kalshi_client import KalshiClient, kalshi_credentials_present
    if not kalshi_credentials_present():
        return {"connected": False, "error": "Kalshi credentials not configured"}
    try:
        client = KalshiClient()
        balance_data = await client.get_balance()
        return {"connected": True, "balance": balance_data}
    except Exception:
        return {"connected": False, "error": "Kalshi connection failed"}


@app.get("/api/weather/forecasts", response_model=List[WeatherForecastResponse])
async def get_weather_forecasts():
    from backend.core.weather_signals import get_cached_signals
    return _weather_forecasts_from_signals(get_cached_signals())


@app.get("/api/weather/signals", response_model=List[WeatherSignalResponse])
async def get_weather_signals():
    from backend.core.weather_signals import get_cached_signals
    return [_weather_signal_to_response(s) for s in get_cached_signals()]


@app.get("/api/weather/markets", response_model=List[WeatherMarketResponse])
async def get_weather_markets():
    from backend.core.weather_signals import get_cached_signals
    seen = {}
    for s in get_cached_signals():
        seen.setdefault(s.market.market_id, _signal_to_market_response(s))
    return list(seen.values())


@app.get("/api/kalshi/markets")
async def get_kalshi_markets():
    from backend.core.weather_signals import get_cached_signals
    signals = get_cached_signals()
    return {
        "markets": [_market_to_frontend_from_signal(s) for s in signals],
        "count": len(signals),
        "traded_today_count": 0,
    }


@app.get("/api/events", response_model=List[EventResponse])
async def get_events(limit: int = 50):
    from backend.core.scheduler import get_recent_events
    return [EventResponse(timestamp=e["timestamp"], type=e["type"], message=e["message"], data=e.get("data", {})) for e in get_recent_events(limit)]


@app.post("/api/bot/start")
async def start_bot(request: Request, db: Session = Depends(get_db)):
    _require_loopback_mutation(request, "Bot start")
    state = _get_or_create_bot_state(db)
    state.is_running = True
    db.commit()
    try:
        from backend.core.scheduler import start_scheduler, is_scheduler_running
        if not is_scheduler_running():
            start_scheduler()
    except (ImportError, ModuleNotFoundError):
        pass
    _log_event("success", "Weather scanner started")
    return {"status": "started", "is_running": True}


@app.post("/api/bot/stop")
async def stop_bot(request: Request, db: Session = Depends(get_db)):
    _require_loopback_mutation(request, "Bot stop")
    state = _get_or_create_bot_state(db)
    state.is_running = False
    db.commit()
    try:
        from backend.core.scheduler import stop_scheduler
        stop_scheduler()
    except (ImportError, ModuleNotFoundError):
        pass
    _log_event("info", "Weather scanner paused")
    return {"status": "stopped", "is_running": False}


@app.post("/api/bot/reset")
async def reset_bot(request: Request, db: Session = Depends(get_db)):
    _require_loopback_mutation(request, "Bot reset")
    try:
        trades_deleted = db.query(Trade).filter(Trade.market_type == "weather").delete()
        state = _get_or_create_bot_state(db)
        state.bankroll = settings.INITIAL_BANKROLL
        state.total_trades = 0
        state.winning_trades = 0
        state.total_pnl = 0.0
        state.is_running = False
        db.commit()
        _log_event("success", f"Weather bot reset: {trades_deleted} trades deleted")
        return {"status": "reset", "trades_deleted": trades_deleted, "new_bankroll": settings.INITIAL_BANKROLL}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Reset failed: {e}")


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        await websocket.send_json({"timestamp": datetime.now(timezone.utc).isoformat(), "type": "success", "message": "Connected to Weather Edge"})
        from backend.core.scheduler import get_recent_events
        last_event_count = 0
        while True:
            import asyncio
            await asyncio.sleep(2)
            current_events = get_recent_events(200)
            if len(current_events) > last_event_count:
                for event in current_events[last_event_count:]:
                    await websocket.send_json(event)
                last_event_count = len(current_events)
            await websocket.send_json({"type": "heartbeat", "timestamp": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


_FRONTEND_DIST = (Path(__file__).parent / ".." / ".." / "frontend" / "dist").resolve()
if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(str(_FRONTEND_DIST / "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("ws"):
            raise HTTPException(status_code=404)
        index = _FRONTEND_DIST / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="Frontend not built")
        return FileResponse(str(index))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8765")))
