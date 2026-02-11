"""FastAPI backend for the trading bot dashboard."""
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import asyncio
import json

from backend.config import settings
from backend.models.database import (
    get_db, init_db, SessionLocal,
    Market, Signal, Trade, WeatherForecast, BotState, AILog, ScanLog
)
from backend.core.signals import scan_for_signals, TradingSignal
from backend.data.weather import fetch_all_cities, WeatherPrediction
from backend.data.markets import fetch_all_weather_markets, fetch_all_markets
from backend.core.classifier import MarketCategory as MCEnum

from pydantic import BaseModel

app = FastAPI(
    title="Prediction Market Trading Bot",
    description="Weather-based prediction market trading bot with simulation mode",
    version="2.0.0"
)

# CORS for React frontend
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
        import logging
        logger = logging.getLogger("trading_bot")
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to broadcast to connection: {e}")


ws_manager = ConnectionManager()


# Pydantic models for API responses
class CityWeather(BaseModel):
    city: str
    lat: float
    lon: float
    high_temp: float
    low_temp: float
    ensemble_count: int
    confidence: float
    prob_above_40: float
    prob_above_50: float
    prob_above_60: float


class MarketResponse(BaseModel):
    platform: str
    ticker: str
    title: str
    category: str
    subcategory: Optional[str]
    yes_price: float
    volume: float
    threshold: Optional[float]
    model_probability: Optional[float]
    edge: Optional[float]


class SignalResponse(BaseModel):
    market_ticker: str
    market_title: str
    platform: str
    city: Optional[str]
    direction: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    suggested_size: float
    reasoning: str
    timestamp: datetime
    # New fields
    category: str = "weather"
    subcategory: Optional[str] = None
    event_slug: Optional[str] = None
    ai_reasoning: Optional[str] = None
    ai_confidence: Optional[float] = None


class TradeResponse(BaseModel):
    id: int
    market_ticker: str
    platform: str
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


class DashboardData(BaseModel):
    stats: BotStats
    cities: List[CityWeather]
    active_signals: List[SignalResponse]
    recent_trades: List[TradeResponse]
    equity_curve: List[dict]


class EventResponse(BaseModel):
    timestamp: str
    type: str
    message: str
    data: dict = {}


# Initialize database and scheduler on startup
@app.on_event("startup")
async def startup():
    import logging
    logger = logging.getLogger("trading_bot")

    print("=" * 60)
    print("PREDICTION MARKET TRADING BOT v2.0")
    print("=" * 60)
    print("Initializing database...")

    init_db()

    # Initialize bot state if not exists
    db = SessionLocal()
    try:
        state = db.query(BotState).first()
        if not state:
            state = BotState(
                bankroll=settings.INITIAL_BANKROLL,
                total_trades=0,
                winning_trades=0,
                total_pnl=0.0,
                is_running=True  # Start running by default
            )
            db.add(state)
            db.commit()
            print(f"Created new bot state with ${settings.INITIAL_BANKROLL:,.2f} bankroll")
        else:
            # Set running on startup
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
    print(f"  - Enabled categories: {settings.ENABLED_CATEGORIES}")
    print("")

    # Start the autonomous trading scheduler
    from backend.core.scheduler import start_scheduler, log_event
    start_scheduler()
    log_event("success", "Trading bot initialized and running")

    print("Bot is now running autonomously!")
    print("  - Market scan: every 5 minutes")
    print("  - Settlement check: every 30 minutes")
    print("  - Heartbeat: every 1 minute")
    print("=" * 60)


@app.on_event("shutdown")
async def shutdown():
    from backend.core.scheduler import stop_scheduler
    stop_scheduler()


@app.get("/")
async def root():
    return {"status": "ok", "message": "Trading Bot API v2.0", "simulation_mode": settings.SIMULATION_MODE}


@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/stats", response_model=BotStats)
async def get_stats(db: Session = Depends(get_db)):
    """Get current bot statistics."""
    state = db.query(BotState).first()
    if not state:
        raise HTTPException(status_code=404, detail="Bot state not initialized")

    win_rate = state.winning_trades / state.total_trades if state.total_trades > 0 else 0

    return BotStats(
        bankroll=state.bankroll,
        total_trades=state.total_trades,
        winning_trades=state.winning_trades,
        win_rate=win_rate,
        total_pnl=state.total_pnl,
        is_running=state.is_running,
        last_run=state.last_run
    )


@app.get("/api/weather", response_model=List[CityWeather])
async def get_weather():
    """Get current weather predictions for all cities."""
    import logging
    logger = logging.getLogger("trading_bot")

    try:
        weather_data = await fetch_all_cities()

        cities = []
        for city, pred in weather_data.items():
            coords = settings.CITY_COORDS.get(city, (0, 0))
            cities.append(CityWeather(
                city=city,
                lat=coords[0],
                lon=coords[1],
                high_temp=pred.high_temp,
                low_temp=pred.low_temp,
                ensemble_count=len(pred.ensemble_highs),
                confidence=pred.confidence(),
                prob_above_40=pred.prob_above(40),
                prob_above_50=pred.prob_above(50),
                prob_above_60=pred.prob_above(60)
            ))

        return cities
    except Exception as e:
        logger.error(f"Error fetching weather data: {e}")
        return []


@app.get("/api/markets", response_model=List[MarketResponse])
async def get_markets():
    """Get all active weather markets."""
    import logging
    logger = logging.getLogger("trading_bot")

    try:
        markets = await fetch_all_weather_markets()

        return [
            MarketResponse(
                platform=m.platform,
                ticker=m.ticker,
                title=m.title,
                category=m.category,
                subcategory=m.subcategory,
                yes_price=m.yes_price,
                volume=m.volume,
                threshold=m.threshold,
                model_probability=None,
                edge=None
            )
            for m in markets
        ]
    except Exception as e:
        logger.error(f"Error fetching markets: {e}")
        return []


@app.get("/api/signals", response_model=List[SignalResponse])
async def get_signals():
    """Get current trading signals."""
    import logging
    logger = logging.getLogger("trading_bot")

    try:
        signals = await scan_for_signals()

        return [
            SignalResponse(
                market_ticker=s.market.ticker,
                market_title=s.market.title,
                platform=s.market.platform,
                city=s.market.subcategory,
                direction=s.direction,
                model_probability=s.model_probability,
                market_probability=s.market_probability,
                edge=s.edge,
                confidence=s.confidence,
                suggested_size=s.suggested_size,
                reasoning=s.reasoning,
                timestamp=s.timestamp,
                category=getattr(s.market, 'category', 'weather'),
                subcategory=s.market.subcategory,
                event_slug=getattr(s.market, 'event_slug', None)
            )
            for s in signals
        ]
    except Exception as e:
        logger.error(f"Error fetching signals: {e}")
        return []


@app.get("/api/signals/actionable", response_model=List[SignalResponse])
async def get_actionable_signals():
    """Get only signals that pass the edge threshold."""
    import logging
    logger = logging.getLogger("trading_bot")

    try:
        signals = await scan_for_signals()
        actionable = [s for s in signals if s.passes_threshold]

        return [
            SignalResponse(
                market_ticker=s.market.ticker,
                market_title=s.market.title,
                platform=s.market.platform,
                city=s.market.subcategory,
                direction=s.direction,
                model_probability=s.model_probability,
                market_probability=s.market_probability,
                edge=s.edge,
                confidence=s.confidence,
                suggested_size=s.suggested_size,
                reasoning=s.reasoning,
                timestamp=s.timestamp,
                category=getattr(s.market, 'category', 'weather'),
                subcategory=s.market.subcategory,
                event_slug=getattr(s.market, 'event_slug', None)
            )
            for s in actionable
        ]
    except Exception as e:
        logger.error(f"Error fetching actionable signals: {e}")
        return []


@app.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(
    limit: int = 50,
    status: Optional[str] = None,
    platform: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get recent trades with optional filtering."""
    query = db.query(Trade)

    if status:
        query = query.filter(Trade.result == status)
    if platform:
        query = query.filter(Trade.platform == platform)

    trades = query.order_by(Trade.timestamp.desc()).limit(limit).all()

    return [
        TradeResponse(
            id=t.id,
            market_ticker=t.market_ticker,
            platform=t.platform,
            direction=t.direction,
            entry_price=t.entry_price,
            size=t.size,
            timestamp=t.timestamp,
            settled=t.settled,
            result=t.result,
            pnl=t.pnl
        )
        for t in trades
    ]


@app.get("/api/equity-curve")
async def get_equity_curve(db: Session = Depends(get_db)):
    """Get equity curve data for charting."""
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
async def simulate_trade(
    signal_ticker: str,
    db: Session = Depends(get_db)
):
    """
    Simulate executing a trade based on a signal.
    Records the trade for tracking.
    """
    from backend.core.scheduler import log_event

    signals = await scan_for_signals()
    signal = next((s for s in signals if s.market.ticker == signal_ticker), None)

    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    # Get bot state
    state = db.query(BotState).first()
    if not state:
        raise HTTPException(status_code=500, detail="Bot state not initialized")

    # Create trade
    trade = Trade(
        market_ticker=signal.market.ticker,
        platform=signal.market.platform,
        direction=signal.direction,
        entry_price=signal.market.yes_price if signal.direction == "yes" else signal.market.no_price,
        size=min(signal.suggested_size, state.bankroll * 0.05),
        model_probability=signal.model_probability,
        market_price_at_entry=signal.market_probability,
        edge_at_entry=signal.edge
    )

    db.add(trade)
    state.total_trades += 1
    db.commit()

    log_event("trade", f"Manual trade: {signal.direction.upper()} {signal.market.ticker}", {
        "ticker": signal.market.ticker,
        "size": trade.size
    })

    return {"status": "ok", "trade_id": trade.id, "size": trade.size}


@app.post("/api/run-scan")
async def run_scan(db: Session = Depends(get_db)):
    """Manually trigger a market scan."""
    from backend.core.scheduler import run_manual_scan, log_event

    state = db.query(BotState).first()
    if state:
        state.last_run = datetime.utcnow()
        db.commit()

    log_event("info", "Manual scan triggered")
    await run_manual_scan()

    signals = await scan_for_signals()
    actionable = [s for s in signals if s.passes_threshold]

    return {
        "status": "ok",
        "total_signals": len(signals),
        "actionable_signals": len(actionable),
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/api/settle-trades")
async def settle_trades_endpoint(db: Session = Depends(get_db)):
    """Manually trigger trade settlement check."""
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


@app.get("/api/events", response_model=List[EventResponse])
async def get_events(limit: int = 50):
    """Get recent bot events for terminal display."""
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


@app.post("/api/bot/start")
async def start_bot(db: Session = Depends(get_db)):
    """Start autonomous trading."""
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
    """Stop autonomous trading (pauses new trades, doesn't stop settlement)."""
    from backend.core.scheduler import log_event

    state = db.query(BotState).first()
    if state:
        state.is_running = False
        db.commit()

    log_event("info", "Trading bot paused")
    return {"status": "stopped", "is_running": False}


# ============ Category & AI Endpoints ============

@app.get("/api/categories")
async def get_categories():
    """Get list of supported market categories."""
    return {
        "categories": [
            {"id": "weather", "name": "Weather", "icon": "thermometer", "enabled": True},
            {"id": "crypto", "name": "Crypto", "icon": "bitcoin", "enabled": True},
            {"id": "politics", "name": "Politics", "icon": "vote", "enabled": True},
            {"id": "economics", "name": "Economics", "icon": "chart", "enabled": True},
            {"id": "sports", "name": "Sports", "icon": "trophy", "enabled": False},  # Always disabled
            {"id": "other", "name": "Other", "icon": "question", "enabled": True},
        ],
        "excluded": ["sports"]
    }


@app.get("/api/markets/all")
async def get_all_markets(
    categories: Optional[str] = None,
    exclude_sports: bool = True
):
    """
    Get markets from all platforms across categories.

    Args:
        categories: Comma-separated list of categories (e.g., "weather,crypto")
        exclude_sports: Whether to exclude sports markets (default True)
    """
    import logging
    logger = logging.getLogger("trading_bot")

    try:
        cat_set = None
        if categories:
            cat_set = set(categories.split(","))

        markets = await fetch_all_markets(cat_set, exclude_sports)

        return [
            {
                "platform": m.platform,
                "ticker": m.ticker,
                "title": m.title,
                "category": m.category,
                "subcategory": m.subcategory,
                "yes_price": m.yes_price,
                "volume": m.volume,
                "threshold": m.threshold,
                "event_slug": m.event_slug
            }
            for m in markets
        ]
    except Exception as e:
        logger.error(f"Error fetching all markets: {e}")
        return []


class AILogResponse(BaseModel):
    id: int
    timestamp: datetime
    provider: str
    model: str
    call_type: str
    latency_ms: float
    tokens_used: int
    cost_usd: float
    success: bool
    related_market: Optional[str]


@app.get("/api/ai/logs", response_model=List[AILogResponse])
async def get_ai_logs(
    limit: int = 50,
    provider: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get recent AI API call logs."""
    query = db.query(AILog)

    if provider:
        query = query.filter(AILog.provider == provider)

    logs = query.order_by(AILog.timestamp.desc()).limit(limit).all()

    return [
        AILogResponse(
            id=log.id,
            timestamp=log.timestamp,
            provider=log.provider,
            model=log.model,
            call_type=log.call_type,
            latency_ms=log.latency_ms,
            tokens_used=log.tokens_used,
            cost_usd=log.cost_usd,
            success=log.success,
            related_market=log.related_market
        )
        for log in logs
    ]


@app.get("/api/ai/stats")
async def get_ai_stats(db: Session = Depends(get_db)):
    """Get AI usage statistics for today."""
    from datetime import date

    today_start = datetime.combine(date.today(), datetime.min.time())

    logs = db.query(AILog).filter(AILog.timestamp >= today_start).all()

    total_cost = sum(log.cost_usd for log in logs)
    total_tokens = sum(log.tokens_used for log in logs)
    avg_latency = sum(log.latency_ms for log in logs) / len(logs) if logs else 0

    by_provider = {}
    for log in logs:
        if log.provider not in by_provider:
            by_provider[log.provider] = {"calls": 0, "cost": 0, "tokens": 0}
        by_provider[log.provider]["calls"] += 1
        by_provider[log.provider]["cost"] += log.cost_usd
        by_provider[log.provider]["tokens"] += log.tokens_used

    return {
        "today": {
            "total_calls": len(logs),
            "total_cost_usd": round(total_cost, 4),
            "total_tokens": total_tokens,
            "avg_latency_ms": round(avg_latency, 2),
            "by_provider": by_provider
        },
        "budget": {
            "daily_limit_usd": settings.AI_DAILY_BUDGET_USD if hasattr(settings, 'AI_DAILY_BUDGET_USD') else 10.0,
            "remaining_usd": round((settings.AI_DAILY_BUDGET_USD if hasattr(settings, 'AI_DAILY_BUDGET_USD') else 10.0) - total_cost, 4)
        }
    }


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """WebSocket endpoint for real-time event streaming."""
    await ws_manager.connect(websocket)

    try:
        # Send initial connection message
        await websocket.send_json({
            "timestamp": datetime.utcnow().isoformat(),
            "type": "success",
            "message": "Connected to trading bot"
        })

        # Send recent events
        from backend.core.scheduler import get_recent_events
        for event in get_recent_events(20):
            await websocket.send_json(event)

        # Keep connection alive and broadcast new events
        last_event_count = len(get_recent_events(200))
        while True:
            await asyncio.sleep(2)

            # Check for new events
            current_events = get_recent_events(200)
            if len(current_events) > last_event_count:
                # Send new events
                new_events = current_events[last_event_count - len(current_events):]
                for event in new_events:
                    await websocket.send_json(event)
                last_event_count = len(current_events)

            # Send heartbeat
            await websocket.send_json({
                "type": "heartbeat",
                "timestamp": datetime.utcnow().isoformat()
            })

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        import logging
        logger = logging.getLogger("trading_bot")
        logger.warning(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


@app.get("/api/dashboard", response_model=DashboardData)
async def get_dashboard(db: Session = Depends(get_db)):
    """Get all dashboard data in one call."""

    # Fetch all data concurrently
    stats_task = get_stats(db)
    weather_task = get_weather()
    signals_task = get_actionable_signals()

    stats = await stats_task
    cities = await weather_task
    signals = await signals_task

    # Get recent trades
    trades = db.query(Trade).order_by(Trade.timestamp.desc()).limit(20).all()
    recent_trades = [
        TradeResponse(
            id=t.id,
            market_ticker=t.market_ticker,
            platform=t.platform,
            direction=t.direction,
            entry_price=t.entry_price,
            size=t.size,
            timestamp=t.timestamp,
            settled=t.settled,
            result=t.result,
            pnl=t.pnl
        )
        for t in trades
    ]

    # Get equity curve
    equity_trades = db.query(Trade).filter(Trade.settled == True).order_by(Trade.timestamp).all()
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

    return DashboardData(
        stats=stats,
        cities=cities,
        active_signals=signals,
        recent_trades=recent_trades,
        equity_curve=equity_curve
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
