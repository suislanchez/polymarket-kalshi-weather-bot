"""Background scheduler for autonomous 24/7 trading."""
import asyncio
from datetime import datetime
from typing import List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

from backend.config import settings
from backend.models.database import SessionLocal, Trade, BotState
from backend.core.signals import scan_for_signals

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trading_bot")

# Global scheduler instance
scheduler: Optional[AsyncIOScheduler] = None

# Event log for terminal display (in-memory, last 200 events)
event_log: List[dict] = []
MAX_LOG_SIZE = 200


def log_event(event_type: str, message: str, data: dict = None):
    """
    Log an event for terminal display.
    event_type: 'info', 'success', 'warning', 'error', 'data', 'trade'
    """
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": event_type,
        "message": message,
        "data": data or {}
    }
    event_log.append(event)

    # Keep log size bounded
    while len(event_log) > MAX_LOG_SIZE:
        event_log.pop(0)

    # Also log to console
    log_func = {
        "error": logger.error,
        "warning": logger.warning,
        "success": logger.info,
        "info": logger.info,
        "data": logger.debug,
        "trade": logger.info
    }.get(event_type, logger.info)

    log_func(f"[{event_type.upper()}] {message}")


def get_recent_events(limit: int = 50) -> List[dict]:
    """Get recent events for terminal display."""
    return event_log[-limit:]


async def scan_and_trade_job():
    """
    Background job: Scan markets, generate signals, execute simulated trades.
    Runs every 5 minutes.
    """
    log_event("info", "Starting market scan...")
    logger.info("=" * 60)
    logger.info("MARKET SCAN STARTED")
    logger.info("=" * 60)

    try:
        # Scan for signals
        signals = await scan_for_signals()
        actionable = [s for s in signals if s.passes_threshold]

        log_event("data", f"Found {len(signals)} signals, {len(actionable)} actionable", {
            "total_signals": len(signals),
            "actionable": len(actionable)
        })

        if not actionable:
            log_event("info", "No actionable signals found")
            return

        # Get database session
        db = SessionLocal()
        try:
            state = db.query(BotState).first()
            if not state:
                log_event("error", "Bot state not initialized")
                return

            if not state.is_running:
                log_event("info", "Bot is paused, skipping trades")
                return

            # Execute trades for top signals (max 3 per scan)
            trades_executed = 0
            for signal in actionable[:3]:
                # Check if we already have a pending trade for this market
                existing = db.query(Trade).filter(
                    Trade.market_ticker == signal.market.ticker,
                    Trade.settled == False
                ).first()

                if existing:
                    log_event("info", f"Skipping {signal.market.ticker} - already have pending trade")
                    continue

                # Calculate trade size
                trade_size = min(signal.suggested_size, state.bankroll * 0.05)

                if trade_size < 10:
                    log_event("warning", f"Trade size too small: ${trade_size:.2f}")
                    continue

                # Create trade
                trade = Trade(
                    market_ticker=signal.market.ticker,
                    platform=signal.market.platform,
                    direction=signal.direction,
                    entry_price=signal.market.yes_price if signal.direction == "yes" else signal.market.no_price,
                    size=trade_size,
                    model_probability=signal.model_probability,
                    market_price_at_entry=signal.market_probability,
                    edge_at_entry=signal.edge
                )

                db.add(trade)
                state.total_trades += 1
                trades_executed += 1

                log_event("trade", f"Executed: {signal.direction.upper()} {signal.market.ticker}", {
                    "ticker": signal.market.ticker,
                    "direction": signal.direction,
                    "size": trade_size,
                    "edge": signal.edge,
                    "entry_price": trade.entry_price
                })

            state.last_run = datetime.utcnow()
            db.commit()

            if trades_executed > 0:
                log_event("success", f"Executed {trades_executed} trade(s)")
            else:
                log_event("info", "No new trades executed")

        finally:
            db.close()

    except Exception as e:
        log_event("error", f"Scan error: {str(e)}")
        logger.exception("Error in scan_and_trade_job")


async def settlement_job():
    """
    Background job: Check and settle pending trades.
    Runs every 30 minutes.
    """
    log_event("info", "Checking trade settlements...")

    try:
        from backend.core.settlement import settle_pending_trades, update_bot_state_with_settlements

        db = SessionLocal()
        try:
            # Get count of pending trades
            pending_count = db.query(Trade).filter(Trade.settled == False).count()

            if pending_count == 0:
                log_event("data", "No pending trades to settle")
                return

            log_event("data", f"Processing {pending_count} pending trades")

            # Settle trades
            settled = await settle_pending_trades(db)

            if settled:
                # Update bot state
                await update_bot_state_with_settlements(db, settled)

                wins = sum(1 for t in settled if t.result == "win")
                losses = sum(1 for t in settled if t.result == "loss")
                total_pnl = sum(t.pnl for t in settled if t.pnl is not None)

                log_event("success", f"Settled {len(settled)} trades: {wins}W/{losses}L, P&L: ${total_pnl:.2f}", {
                    "settled_count": len(settled),
                    "wins": wins,
                    "losses": losses,
                    "pnl": total_pnl
                })

                # Log individual settlements
                for trade in settled:
                    result_emoji = "+" if trade.pnl and trade.pnl > 0 else ""
                    log_event("data", f"  {trade.market_ticker}: {trade.result.upper()} {result_emoji}${trade.pnl:.2f}")
            else:
                log_event("info", "No trades ready for settlement")

        finally:
            db.close()

    except Exception as e:
        log_event("error", f"Settlement error: {str(e)}")
        logger.exception("Error in settlement_job")


async def heartbeat_job():
    """
    Background job: Periodic heartbeat to show system is alive.
    Runs every minute.
    """
    db = None
    try:
        db = SessionLocal()
        state = db.query(BotState).first()
        pending = db.query(Trade).filter(Trade.settled == False).count()

        if state is None:
            log_event("warning", "Heartbeat: Bot state not initialized")
            return

        log_event("data", f"Heartbeat: {pending} pending trades, bankroll: ${state.bankroll:.2f}", {
            "pending_trades": pending,
            "bankroll": state.bankroll,
            "is_running": state.is_running
        })
    except Exception as e:
        log_event("warning", f"Heartbeat failed: {str(e)}")
    finally:
        if db:
            db.close()


def start_scheduler():
    """Start the background scheduler for autonomous trading."""
    global scheduler

    if scheduler is not None and scheduler.running:
        log_event("warning", "Scheduler already running")
        return

    scheduler = AsyncIOScheduler()

    # Scan markets every 5 minutes
    scheduler.add_job(
        scan_and_trade_job,
        IntervalTrigger(minutes=5),
        id="market_scan",
        replace_existing=True,
        max_instances=1
    )

    # Check settlements every 30 minutes
    scheduler.add_job(
        settlement_job,
        IntervalTrigger(minutes=30),
        id="settlement_check",
        replace_existing=True,
        max_instances=1
    )

    # Heartbeat every minute
    scheduler.add_job(
        heartbeat_job,
        IntervalTrigger(minutes=1),
        id="heartbeat",
        replace_existing=True,
        max_instances=1
    )

    scheduler.start()
    log_event("success", "Autonomous trading scheduler started", {
        "scan_interval": "5 minutes",
        "settlement_interval": "30 minutes"
    })

    # Run initial scan
    asyncio.create_task(scan_and_trade_job())


def stop_scheduler():
    """Stop the background scheduler."""
    global scheduler

    if scheduler is None or not scheduler.running:
        log_event("info", "Scheduler not running")
        return

    scheduler.shutdown(wait=False)
    scheduler = None
    log_event("info", "Scheduler stopped")


def is_scheduler_running() -> bool:
    """Check if scheduler is currently running."""
    return scheduler is not None and scheduler.running


async def run_manual_scan():
    """Trigger a manual market scan."""
    log_event("info", "Manual scan triggered")
    await scan_and_trade_job()


async def run_manual_settlement():
    """Trigger a manual settlement check."""
    log_event("info", "Manual settlement triggered")
    await settlement_job()
