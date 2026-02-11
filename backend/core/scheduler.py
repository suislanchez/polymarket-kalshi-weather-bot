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

        # Group signals by category for logging
        by_cat = {}
        for s in actionable:
            cat = getattr(s.market, 'category', 'other') or 'other'
            by_cat[cat] = by_cat.get(cat, 0) + 1

        cat_summary = ", ".join(f"{c}: {n}" for c, n in sorted(by_cat.items(), key=lambda x: -x[1]))

        log_event("data", f"Found {len(signals)} signals, {len(actionable)} actionable ({cat_summary})", {
            "total_signals": len(signals),
            "actionable": len(actionable),
            "by_category": by_cat
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

            # SMART TRADING: Quality over quantity
            MAX_TRADES_PER_SCAN = 5  # Reduced - only best trades
            MIN_TRADE_SIZE = 20  # Minimum $20 per trade (meaningful size)
            MAX_TRADE_FRACTION = 0.05  # Max 5% of bankroll per trade
            MAX_PER_CATEGORY = getattr(settings, 'MAX_TRADES_PER_CATEGORY', 3)
            MAX_TOTAL_PENDING = getattr(settings, 'MAX_TOTAL_PENDING_TRADES', 15)

            # Check total pending trades
            total_pending = db.query(Trade).filter(Trade.settled == False).count()
            if total_pending >= MAX_TOTAL_PENDING:
                log_event("info", f"Max pending trades reached ({total_pending}/{MAX_TOTAL_PENDING}), skipping new trades")
                return

            # Track trades per category this scan
            category_counts = {}

            trades_executed = 0
            for signal in actionable[:MAX_TRADES_PER_SCAN * 2]:  # Check more, execute fewer
                # Category limit
                cat = getattr(signal.market, 'category', 'other') or 'other'
                if category_counts.get(cat, 0) >= MAX_PER_CATEGORY:
                    continue

                # Check if we already have a pending trade for this market
                existing = db.query(Trade).filter(
                    Trade.market_ticker == signal.market.ticker,
                    Trade.settled == False
                ).first()

                if existing:
                    continue

                # Calculate trade size (conservative)
                trade_size = min(signal.suggested_size, state.bankroll * MAX_TRADE_FRACTION)
                trade_size = max(trade_size, MIN_TRADE_SIZE)

                if state.bankroll < MIN_TRADE_SIZE:
                    log_event("warning", f"Bankroll too low: ${state.bankroll:.2f}")
                    break

                if trades_executed >= MAX_TRADES_PER_SCAN:
                    break

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
                category_counts[cat] = category_counts.get(cat, 0) + 1

                # Truncate title for display
                title_short = signal.market.title[:40] + "..." if len(signal.market.title) > 40 else signal.market.title

                log_event("trade", f"[{cat.upper()}] {signal.direction.upper()} ${trade_size:.0f} @ {trade.entry_price:.0%}: {title_short}", {
                    "ticker": signal.market.ticker,
                    "category": cat,
                    "direction": signal.direction,
                    "size": trade_size,
                    "edge": signal.edge,
                    "entry_price": trade.entry_price,
                    "title": signal.market.title
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

    # Scan markets every 5 minutes (balanced - not too aggressive)
    scheduler.add_job(
        scan_and_trade_job,
        IntervalTrigger(minutes=5),
        id="market_scan",
        replace_existing=True,
        max_instances=1
    )

    # Check settlements every 15 minutes (markets don't resolve that fast)
    scheduler.add_job(
        settlement_job,
        IntervalTrigger(minutes=15),
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
    log_event("success", "Trading scheduler started (SMART MODE - cost optimized)", {
        "scan_interval": "5 minutes",
        "settlement_interval": "15 minutes",
        "max_trades_per_scan": 5,
        "min_edge": f"{settings.MIN_EDGE_THRESHOLD:.0%}",
        "ai_provider": "groq (free)"
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
