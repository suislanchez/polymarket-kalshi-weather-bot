"""Background scheduler for the Weather Edge scanner."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func

from backend.config import settings
from backend.models.database import BotState, Signal, SessionLocal, Trade

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trading_bot")

scheduler: Optional[AsyncIOScheduler] = None
event_log: List[dict] = []
MAX_LOG_SIZE = 200


def log_event(event_type: str, message: str, data: dict = None):
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "message": message,
        "data": data or {},
    }
    event_log.append(event)
    while len(event_log) > MAX_LOG_SIZE:
        event_log.pop(0)
    log_func = {
        "error": logger.error,
        "warning": logger.warning,
        "success": logger.info,
        "info": logger.info,
        "data": logger.debug,
        "trade": logger.info,
    }.get(event_type, logger.info)
    log_func(f"[{event_type.upper()}] {message}")


def get_recent_events(limit: int = 50) -> List[dict]:
    return event_log[-limit:]


async def weather_scan_and_trade_job():
    """Scan Kalshi weather markets, cache signals, and record simulated trades."""
    try:
        db = SessionLocal()
        try:
            state = db.query(BotState).first()
            if state is not None and not state.is_running:
                log_event("info", "Scanner is paused; skipping weather scan")
                return
        finally:
            db.close()

        log_event("info", "Scanning Kalshi weather markets...")
        from backend.core.weather_signals import scan_for_weather_signals

        signals = await scan_for_weather_signals()
        actionable = [s for s in signals if s.passes_threshold]
        log_event("data", f"Weather scan: {len(signals)} signals, {len(actionable)} actionable", {
            "total_signals": len(signals),
            "actionable": len(actionable),
        })

        if not actionable:
            log_event("info", "No actionable weather signals")
            return

        db = SessionLocal()
        try:
            state = db.query(BotState).first()
            if not state:
                log_event("error", "Bot state not initialized")
                return
            if not state.is_running:
                log_event("info", "Scanner is paused; skipping weather trades")
                return

            max_trades_per_scan = 3
            min_trade_size = 10
            max_weather_allocation = 500.0

            weather_pending = db.query(func.coalesce(func.sum(Trade.size), 0.0)).filter(
                Trade.settled == False,
                Trade.market_type == "weather",
            ).scalar()
            if weather_pending >= max_weather_allocation:
                log_event("warning", f"Weather allocation cap reached: ${weather_pending:.2f}/${max_weather_allocation:.2f}")
                return

            trades_executed = 0
            remaining_weather_allocation = max(0.0, max_weather_allocation - float(weather_pending or 0.0))
            for signal in actionable[:max_trades_per_scan]:
                existing = db.query(Trade).filter(
                    Trade.market_ticker == signal.market.market_id,
                    Trade.settled == False,
                    Trade.market_type == "weather",
                ).first()
                if existing:
                    continue
                if signal.suggested_size <= 0:
                    log_event("info", f"Skipping non-tradeable weather signal: {signal.market.market_id}")
                    continue
                if signal.net_edge <= 0:
                    log_event("info", f"Skipping non-positive-edge weather signal: {signal.market.market_id} edge={signal.net_edge:.4f}")
                    continue
                if state.bankroll < min_trade_size:
                    log_event("warning", f"Bankroll too low: ${state.bankroll:.2f}")
                    break
                if trades_executed >= max_trades_per_scan:
                    break

                trade_size = min(signal.suggested_size, settings.WEATHER_MAX_TRADE_SIZE, remaining_weather_allocation)
                if trade_size < min_trade_size:
                    log_event("info", f"Skipping weather signal below min trade size or allocation headroom: {signal.market.market_id} size=${trade_size:.2f}")
                    continue
                entry_price = signal.market.yes_price if signal.direction == "yes" else signal.market.no_price
                if entry_price > settings.WEATHER_MAX_ENTRY_PRICE:
                    log_event(
                        "info",
                        f"Skipping weather signal with entry price above max: {signal.market.market_id} price={entry_price:.2f} max={settings.WEATHER_MAX_ENTRY_PRICE:.2f}",
                    )
                    continue
                trade = Trade(
                    market_ticker=signal.market.market_id,
                    platform="kalshi",
                    event_slug=signal.market.slug,
                    market_type="weather",
                    direction=signal.direction,
                    entry_price=entry_price,
                    size=trade_size,
                    model_probability=signal.model_probability,
                    market_price_at_entry=signal.market_probability,
                    edge_at_entry=signal.net_edge,
                )
                db.add(trade)
                db.flush()

                matching_signal = db.query(Signal).filter(
                    Signal.market_ticker == signal.market.market_id,
                    Signal.market_type == "weather",
                    Signal.executed == False,
                ).order_by(Signal.timestamp.desc()).first()
                if matching_signal:
                    matching_signal.executed = True
                    trade.signal_id = matching_signal.id

                state.total_trades += 1
                trades_executed += 1
                remaining_weather_allocation = max(0.0, remaining_weather_allocation - trade_size)
                log_event(
                    "trade",
                    f"WX {signal.market.city_name}: {signal.direction.upper()} ${trade_size:.0f} @ {entry_price:.0%} | {signal.market.metric} {signal.market.threshold_f:.0f}F",
                    {"ticker": signal.market.market_id, "direction": signal.direction, "size": trade_size, "edge": signal.net_edge},
                )

            state.last_run = datetime.now(timezone.utc)
            db.commit()
            log_event("success" if trades_executed else "info", f"Executed {trades_executed} weather trade(s)" if trades_executed else "No new weather trades executed")
        finally:
            db.close()
    except Exception as e:
        log_event("error", f"Weather scan error: {str(e)}")
        logger.exception("Error in weather_scan_and_trade_job")


async def settlement_job():
    try:
        from backend.core.settlement import settle_pending_trades, update_bot_state_with_settlements
        db = SessionLocal()
        try:
            pending_count = db.query(Trade).filter(Trade.settled == False, Trade.market_type == "weather").count()
            if pending_count == 0:
                log_event("data", "No pending weather trades to settle")
                return
            log_event("data", f"Processing {pending_count} pending weather trades")
            settled = await settle_pending_trades(db)
            if settled:
                await update_bot_state_with_settlements(db, settled)
                wins = sum(1 for t in settled if t.result == "win")
                losses = sum(1 for t in settled if t.result == "loss")
                total_pnl = sum(t.pnl for t in settled if t.pnl is not None)
                log_event("success", f"Settled {len(settled)} weather trades: {wins}W/{losses}L, P&L: ${total_pnl:.2f}")
            else:
                log_event("info", "No weather trades ready for settlement")
        finally:
            db.close()
    except Exception as e:
        log_event("error", f"Settlement error: {str(e)}")
        logger.exception("Error in settlement_job")


async def heartbeat_job():
    db = None
    try:
        db = SessionLocal()
        state = db.query(BotState).first()
        pending = db.query(Trade).filter(Trade.settled == False, Trade.market_type == "weather").count()
        if state is None:
            log_event("warning", "Heartbeat: bot state not initialized")
            return
        log_event("data", f"Heartbeat: {pending} pending weather trades, bankroll: ${state.bankroll:.2f}", {
            "pending_trades": pending,
            "bankroll": state.bankroll,
            "is_running": state.is_running,
        })
    except Exception as e:
        log_event("warning", f"Heartbeat failed: {str(e)}")
    finally:
        if db:
            db.close()


def start_scheduler():
    global scheduler
    if scheduler is not None and scheduler.running:
        log_event("warning", "Scheduler already running")
        return

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        settlement_job,
        IntervalTrigger(seconds=settings.WEATHER_SETTLEMENT_INTERVAL_SECONDS),
        id="weather_settlement_check",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        heartbeat_job,
        IntervalTrigger(minutes=1),
        id="heartbeat",
        replace_existing=True,
        max_instances=1,
    )
    if settings.WEATHER_ENABLED:
        scheduler.add_job(
            weather_scan_and_trade_job,
            IntervalTrigger(seconds=settings.WEATHER_SCAN_INTERVAL_SECONDS),
            id="weather_scan",
            replace_existing=True,
            max_instances=1,
        )
    scheduler.start()
    log_event("success", "Weather Edge scheduler started", {
        "weather_enabled": settings.WEATHER_ENABLED,
        "scan_interval": f"{settings.WEATHER_SCAN_INTERVAL_SECONDS}s",
        "settlement_interval": f"{settings.WEATHER_SETTLEMENT_INTERVAL_SECONDS}s",
    })


def stop_scheduler():
    global scheduler
    if scheduler is None or not scheduler.running:
        log_event("info", "Scheduler not running")
        return
    scheduler.shutdown(wait=False)
    scheduler = None
    log_event("info", "Scheduler stopped")


def is_scheduler_running() -> bool:
    return scheduler is not None and scheduler.running


async def run_manual_scan():
    log_event("info", "Manual weather scan triggered")
    await weather_scan_and_trade_job()


async def run_manual_settlement():
    log_event("info", "Manual weather settlement triggered")
    await settlement_job()
