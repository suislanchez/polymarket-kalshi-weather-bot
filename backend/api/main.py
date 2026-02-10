"""FastAPI backend for the trading bot dashboard."""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import asyncio

from backend.config import settings
from backend.models.database import (
    get_db, init_db, SessionLocal,
    Market, Signal, Trade, WeatherForecast, BotState
)
from backend.core.signals import scan_for_signals, TradingSignal
from backend.data.weather import fetch_all_cities, WeatherPrediction
from backend.data.markets import fetch_all_weather_markets

from pydantic import BaseModel

app = FastAPI(
    title="Prediction Market Trading Bot",
    description="Weather-based prediction market trading bot with simulation mode",
    version="1.0.0"
)

# CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# Initialize database on startup
@app.on_event("startup")
async def startup():
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
                total_pnl=0.0
            )
            db.add(state)
            db.commit()
    finally:
        db.close()


@app.get("/")
async def root():
    return {"status": "ok", "message": "Trading Bot API", "simulation_mode": settings.SIMULATION_MODE}


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


@app.get("/api/markets", response_model=List[MarketResponse])
async def get_markets():
    """Get all active weather markets."""
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


@app.get("/api/signals", response_model=List[SignalResponse])
async def get_signals():
    """Get current trading signals."""
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
            timestamp=s.timestamp
        )
        for s in signals
    ]


@app.get("/api/signals/actionable", response_model=List[SignalResponse])
async def get_actionable_signals():
    """Get only signals that pass the edge threshold."""
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
            timestamp=s.timestamp
        )
        for s in actionable
    ]


@app.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Get recent trades."""
    trades = db.query(Trade).order_by(Trade.timestamp.desc()).limit(limit).all()

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
    db.commit()

    return {"status": "ok", "trade_id": trade.id, "size": trade.size}


@app.post("/api/run-scan")
async def run_scan(db: Session = Depends(get_db)):
    """Manually trigger a market scan."""
    state = db.query(BotState).first()
    if state:
        state.last_run = datetime.utcnow()
        db.commit()

    signals = await scan_for_signals()
    actionable = [s for s in signals if s.passes_threshold]

    return {
        "status": "ok",
        "total_signals": len(signals),
        "actionable_signals": len(actionable),
        "timestamp": datetime.utcnow().isoformat()
    }


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
