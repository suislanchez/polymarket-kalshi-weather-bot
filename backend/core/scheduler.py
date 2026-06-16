"""Background scheduler for BTC 5-min autonomous trading."""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func
import logging

from backend.config import settings
from backend.models.database import SessionLocal, Trade, BotState, Signal
from backend.core.signals import scan_for_signals

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trading_bot")

# Global scheduler instance
scheduler: Optional[AsyncIOScheduler] = None

# Event log for terminal display (in-memory, last 200 events)
event_log: List[dict] = []
MAX_LOG_SIZE = 200


def log_event(event_type: str, message: str, data: dict = None):
    """Log an event for terminal display."""
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": event_type,
        "message": message,
        "data": data or {}
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
        "trade": logger.info
    }.get(event_type, logger.info)

    log_func(f"[{event_type.upper()}] {message}")


def get_recent_events(limit: int = 50) -> List[dict]:
    """Get recent events for terminal display."""
    return event_log[-limit:]


def _weather_daily_settled_pnl(db, today_start: datetime) -> float:
    return db.query(func.coalesce(func.sum(Trade.pnl), 0.0)).filter(
        Trade.settled == True,
        Trade.market_type == "weather",
        Trade.settlement_time >= today_start,
    ).scalar()


def _open_weather_positions_by_city(db, signals) -> dict[str, int]:
    """Count open weather positions by city key for markets in current scan."""
    ticker_to_city = {
        s.market.market_id: s.market.city_key
        for s in signals
        if getattr(s, "market", None) and getattr(s.market, "market_id", None) and getattr(s.market, "city_key", None)
    }
    if not ticker_to_city:
        return {}

    rows = db.query(Trade.market_ticker).filter(
        Trade.settled == False,
        Trade.market_type == "weather",
        Trade.market_ticker.in_(list(ticker_to_city.keys())),
    ).all()

    counts: dict[str, int] = {}
    for (market_ticker,) in rows:
        city = ticker_to_city.get(market_ticker)
        if city:
            counts[city] = counts.get(city, 0) + 1
    return counts


def _weather_paper_execution_blockers(signal) -> list[str]:
    """Final paper-execution blockers for weather signals.

    Signal generation can still label a row `[ACTIONABLE]` for research review,
    but the paper ledger has an additional execution boundary. This keeps
    venue-level safety toggles and persistence/sizing safeguards in one place
    immediately before a Trade row would be created.
    """
    blockers: list[str] = []
    platform = str(getattr(getattr(signal, "market", None), "platform", "") or "").lower()
    if platform == "kalshi" and not settings.WEATHER_KALSHI_PAPER_EXECUTION_ENABLED:
        blockers.append("Kalshi weather paper execution is monitor-only until venue calibration improves")
    if float(getattr(signal, "suggested_size", 0.0) or 0.0) <= 0.0:
        blockers.append("weather signal suggested size is zero")
    no_trade_reasons = list(getattr(signal, "no_trade_reasons", []) or [])
    blockers.extend(str(reason) for reason in no_trade_reasons if reason)
    return blockers


async def scan_and_trade_job():
    """
    Background job: Scan BTC 5-min markets, generate signals, execute trades.
    Runs every minute.
    """
    log_event("info", "Scanning BTC 5-min markets...")

    try:
        signals = await scan_for_signals()
        actionable = [s for s in signals if s.passes_threshold]

        log_event("data", f"Found {len(signals)} signals, {len(actionable)} actionable", {
            "total_signals": len(signals),
            "actionable": len(actionable),
        })

        if not actionable:
            log_event("info", "No actionable BTC signals")
            return

        db = SessionLocal()
        try:
            state = db.query(BotState).first()
            if not state:
                log_event("error", "Bot state not initialized")
                return

            if not state.is_running:
                log_event("info", "Bot is paused, skipping trades")
                return

            MAX_TRADES_PER_SCAN = 2
            MIN_TRADE_SIZE = 10
            MAX_TRADE_FRACTION = 0.03  # 3% max per trade
            MAX_TOTAL_PENDING = settings.MAX_TOTAL_PENDING_TRADES

            # --- Daily loss circuit breaker ---
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            daily_pnl = db.query(func.coalesce(func.sum(Trade.pnl), 0.0)).filter(
                Trade.settled == True,
                Trade.settlement_time >= today_start
            ).scalar()

            if daily_pnl <= -settings.DAILY_LOSS_LIMIT:
                log_event("warning", f"Daily loss limit hit: ${daily_pnl:.2f} (limit: -${settings.DAILY_LOSS_LIMIT:.0f}). Stopping trades.")
                return

            total_pending = db.query(Trade).filter(Trade.settled == False).count()
            if total_pending >= MAX_TOTAL_PENDING:
                log_event("info", f"Max pending trades reached ({total_pending}/{MAX_TOTAL_PENDING})")
                return

            trades_executed = 0
            for signal in actionable[:MAX_TRADES_PER_SCAN]:
                # Check if we already have a trade for this market window
                existing = db.query(Trade).filter(
                    Trade.event_slug == signal.market.slug,
                    Trade.settled == False
                ).first()

                if existing:
                    continue

                trade_size = min(signal.suggested_size, state.bankroll * MAX_TRADE_FRACTION)
                trade_size = max(trade_size, MIN_TRADE_SIZE)

                if state.bankroll < MIN_TRADE_SIZE:
                    log_event("warning", f"Bankroll too low: ${state.bankroll:.2f}")
                    break

                if trades_executed >= MAX_TRADES_PER_SCAN:
                    break

                # Map up/down to yes/no for storage
                entry_price = signal.market.up_price if signal.direction == "up" else signal.market.down_price

                trade = Trade(
                    market_ticker=signal.market.market_id,
                    platform="polymarket",
                    event_slug=signal.market.slug,
                    direction=signal.direction,
                    entry_price=entry_price,
                    size=trade_size,
                    model_probability=signal.model_probability,
                    market_price_at_entry=signal.market_probability,
                    edge_at_entry=signal.edge
                )

                db.add(trade)
                db.flush()  # get trade.id

                # Link trade to the most recent matching Signal and mark it executed
                matching_signal = db.query(Signal).filter(
                    Signal.market_ticker == signal.market.market_id,
                    Signal.executed == False,
                ).order_by(Signal.timestamp.desc()).first()
                if matching_signal:
                    matching_signal.executed = True
                    trade.signal_id = matching_signal.id

                state.total_trades += 1
                trades_executed += 1

                log_event("trade",
                    f"BTC {signal.direction.upper()} ${trade_size:.0f} @ {entry_price:.0%} | {signal.market.slug}",
                    {
                        "slug": signal.market.slug,
                        "direction": signal.direction,
                        "size": trade_size,
                        "edge": signal.edge,
                        "entry_price": entry_price,
                        "btc_price": signal.btc_price,
                    }
                )

            state.last_run = datetime.utcnow()
            db.commit()

            if trades_executed > 0:
                log_event("success", f"Executed {trades_executed} BTC trade(s)")
            else:
                log_event("info", "No new trades executed")

        finally:
            db.close()

    except Exception as e:
        log_event("error", f"Scan error: {str(e)}")
        logger.exception("Error in scan_and_trade_job")


async def weather_scan_and_trade_job():
    """
    Background job: Scan weather temperature markets, generate signals, execute trades.
    Runs every 5 minutes when WEATHER_ENABLED.
    """
    log_event("info", "Scanning weather temperature markets...")

    try:
        from backend.core.weather_signals import scan_for_weather_signals

        signals = await scan_for_weather_signals()
        actionable = [s for s in signals if s.passes_threshold]

        log_event("data", f"Weather: {len(signals)} signals, {len(actionable)} actionable", {
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
                log_event("info", "Bot is paused, skipping weather trades")
                return

            MAX_TRADES_PER_SCAN = 3
            MIN_TRADE_SIZE = 10
            MAX_WEATHER_ALLOCATION = 500.0  # Max total exposure to weather markets

            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            weather_daily_pnl = _weather_daily_settled_pnl(db, today_start)
            if weather_daily_pnl <= -settings.WEATHER_DAILY_LOSS_LIMIT:
                log_event(
                    "warning",
                    f"Weather daily loss limit hit: ${weather_daily_pnl:.2f} (limit: -${settings.WEATHER_DAILY_LOSS_LIMIT:.0f}). Stopping weather trades.",
                )
                return

            # Check weather allocation limit
            weather_pending = db.query(func.coalesce(func.sum(Trade.size), 0.0)).filter(
                Trade.settled == False,
                Trade.market_type == "weather",
            ).scalar()

            if weather_pending >= MAX_WEATHER_ALLOCATION:
                log_event("info", f"Weather allocation limit reached: ${weather_pending:.0f}/${MAX_WEATHER_ALLOCATION:.0f}")
                return

            open_by_city = _open_weather_positions_by_city(db, actionable)

            trades_executed = 0
            for signal in actionable[:MAX_TRADES_PER_SCAN]:
                # Check if we already have a trade for this market
                existing = db.query(Trade).filter(
                    Trade.market_ticker == signal.market.market_id,
                    Trade.settled == False,
                ).first()

                if existing:
                    continue

                execution_blockers = _weather_paper_execution_blockers(signal)
                if execution_blockers:
                    log_event(
                        "info",
                        f"Weather paper execution blocked for {signal.market.market_id}: {execution_blockers[0]}",
                        {
                            "market_id": signal.market.market_id,
                            "platform": getattr(signal.market, "platform", None),
                            "blockers": execution_blockers,
                        },
                    )
                    continue

                city_key = getattr(signal.market, "city_key", None)
                if city_key:
                    city_open = open_by_city.get(city_key, 0)
                    if city_open >= settings.WEATHER_MAX_OPEN_POSITIONS_PER_CITY:
                        log_event(
                            "info",
                            f"Weather city cap reached for {city_key}: {city_open}/{settings.WEATHER_MAX_OPEN_POSITIONS_PER_CITY}",
                        )
                        continue

                trade_size = min(signal.suggested_size, settings.WEATHER_MAX_TRADE_SIZE)
                trade_size = max(trade_size, MIN_TRADE_SIZE)

                if state.bankroll < MIN_TRADE_SIZE:
                    log_event("warning", f"Bankroll too low: ${state.bankroll:.2f}")
                    break

                if trades_executed >= MAX_TRADES_PER_SCAN:
                    break

                if signal.direction == "yes":
                    entry_price = signal.market.best_ask if signal.market.best_ask is not None else signal.market.yes_price
                else:
                    entry_price = signal.market.no_best_ask if signal.market.no_best_ask is not None else signal.market.no_price

                trade = Trade(
                    market_ticker=signal.market.market_id,
                    platform=getattr(signal.market, "platform", "polymarket") or "polymarket",
                    event_slug=signal.market.slug,
                    market_type="weather",
                    direction=signal.direction,
                    entry_price=entry_price,
                    size=trade_size,
                    model_probability=signal.model_probability,
                    market_price_at_entry=signal.market_probability,
                    edge_at_entry=signal.edge,
                )

                db.add(trade)
                db.flush()

                # Link to signal record
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
                if city_key:
                    open_by_city[city_key] = open_by_city.get(city_key, 0) + 1

                log_event("trade",
                    f"WX {signal.market.city_name}: {signal.direction.upper()} "
                    f"${trade_size:.0f} @ {entry_price:.0%} | "
                    f"{signal.market.metric} {signal.market.direction} {signal.market.threshold_f:.0f}F",
                    {
                        "slug": signal.market.slug,
                        "direction": signal.direction,
                        "size": trade_size,
                        "edge": signal.edge,
                        "entry_price": entry_price,
                        "city": signal.market.city_name,
                    }
                )

            state.last_run = datetime.utcnow()
            db.commit()

            if trades_executed > 0:
                log_event("success", f"Executed {trades_executed} weather trade(s)")
            else:
                log_event("info", "No new weather trades executed")

        finally:
            db.close()

    except Exception as e:
        log_event("error", f"Weather scan error: {str(e)}")
        logger.exception("Error in weather_scan_and_trade_job")


async def settlement_job():
    """
    Background job: Check and settle pending trades.
    Runs every 2 minutes (BTC 5-min markets resolve fast).
    """
    log_event("info", "Checking BTC trade settlements...")

    try:
        from backend.core.settlement import settle_pending_trades, update_bot_state_with_settlements

        db = SessionLocal()
        try:
            pending_count = db.query(Trade).filter(Trade.settled == False).count()

            if pending_count == 0:
                log_event("data", "No pending trades to settle")
                return

            log_event("data", f"Processing {pending_count} pending trades")

            settled = await settle_pending_trades(db)

            if settled:
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

                for trade in settled:
                    result_prefix = "+" if trade.pnl and trade.pnl > 0 else ""
                    log_event("data", f"  {trade.event_slug}: {trade.result.upper()} {result_prefix}${trade.pnl:.2f}")
            else:
                log_event("info", "No trades ready for settlement")

        finally:
            db.close()

    except Exception as e:
        log_event("error", f"Settlement error: {str(e)}")
        logger.exception("Error in settlement_job")


async def open_position_risk_job():
    """Background job: mark open paper positions to market and record risk recommendations."""
    if not settings.PAPER_POSITION_RISK_ENABLED:
        return

    log_event("info", "Checking open-position paper risk...")
    db = None
    try:
        from backend.core.open_position_monitor import run_open_position_risk_scan
        from backend.core.weather_exit_quotes import PublicWeatherExitQuoteProvider

        db = SessionLocal()
        summary = run_open_position_risk_scan(
            db,
            weather_quote_provider=PublicWeatherExitQuoteProvider(),
        )
        log_event("data", "Open-position risk scan complete", {
            "open_positions": summary.total_open_positions,
            "actions": summary.action_counts,
            "paper_exits": summary.exited_count,
            "auto_exit_enabled": settings.PAPER_AUTO_EXIT_ENABLED,
        })
        return summary
    except Exception as e:
        log_event("error", f"Open-position risk error: {str(e)}")
        logger.exception("Error in open_position_risk_job")
    finally:
        if db:
            db.close()


async def heartbeat_job():
    """Periodic heartbeat. Runs every minute."""
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


def planned_scheduler_jobs() -> List[str]:
    """Return the job ids ``start_scheduler`` would register for current settings.

    Pure/side-effect-free so the lane configuration can be unit-tested without a
    running event loop or any network. The legacy BTC ``market_scan`` job is only
    included when ``BTC_LANE_ENABLED`` is true (the canonical off-switch), and
    ``weather_scan`` only when ``WEATHER_ENABLED`` is true.
    """
    jobs: List[str] = []
    if settings.BTC_LANE_ENABLED:
        jobs.append("market_scan")
    jobs.append("settlement_check")
    if settings.PAPER_POSITION_RISK_ENABLED:
        jobs.append("open_position_risk")
    jobs.append("heartbeat")
    if settings.WEATHER_ENABLED:
        jobs.append("weather_scan")
    return jobs


def start_scheduler():
    """Start the background scheduler.

    Lanes are gated by explicit flags: the legacy BTC scan only runs when
    ``BTC_LANE_ENABLED`` is true, weather only when ``WEATHER_ENABLED`` is true.
    Settlement and heartbeat always run so any existing pending paper trades
    (across lanes) can still settle.
    """
    global scheduler

    if scheduler is not None and scheduler.running:
        log_event("warning", "Scheduler already running")
        return

    scheduler = AsyncIOScheduler()

    scan_seconds = settings.SCAN_INTERVAL_SECONDS
    settle_seconds = settings.SETTLEMENT_INTERVAL_SECONDS

    # Legacy BTC 5-min scan — only when the lane is explicitly enabled.
    if settings.BTC_LANE_ENABLED:
        scheduler.add_job(
            scan_and_trade_job,
            IntervalTrigger(seconds=scan_seconds),
            id="market_scan",
            replace_existing=True,
            max_instances=1
        )

    # Check settlements every 2 minutes
    scheduler.add_job(
        settlement_job,
        IntervalTrigger(seconds=settle_seconds),
        id="settlement_check",
        replace_existing=True,
        max_instances=1
    )

    if settings.PAPER_POSITION_RISK_ENABLED:
        scheduler.add_job(
            open_position_risk_job,
            IntervalTrigger(seconds=settings.POSITION_RISK_SCAN_INTERVAL_SECONDS),
            id="open_position_risk",
            replace_existing=True,
            max_instances=1,
        )

    # Heartbeat every minute
    scheduler.add_job(
        heartbeat_job,
        IntervalTrigger(minutes=1),
        id="heartbeat",
        replace_existing=True,
        max_instances=1
    )

    # Weather trading jobs (gated by WEATHER_ENABLED)
    if settings.WEATHER_ENABLED:
        weather_scan_seconds = settings.WEATHER_SCAN_INTERVAL_SECONDS

        scheduler.add_job(
            weather_scan_and_trade_job,
            IntervalTrigger(seconds=weather_scan_seconds),
            id="weather_scan",
            replace_existing=True,
            max_instances=1,
        )

    scheduler.start()
    log_event("success", "Trading scheduler started", {
        "scan_interval": f"{scan_seconds}s",
        "settlement_interval": f"{settle_seconds}s",
        "btc_lane_enabled": settings.BTC_LANE_ENABLED,
        "weather_enabled": settings.WEATHER_ENABLED,
        "jobs": planned_scheduler_jobs(),
    })

    if settings.BTC_LANE_ENABLED:
        asyncio.create_task(scan_and_trade_job())
    if settings.PAPER_POSITION_RISK_ENABLED:
        asyncio.create_task(open_position_risk_job())

    if settings.WEATHER_ENABLED:
        asyncio.create_task(weather_scan_and_trade_job())


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
    """Trigger a manual market scan for all enabled lanes."""
    log_event("info", "Manual scan triggered")
    await scan_and_trade_job()
    if settings.WEATHER_ENABLED:
        await weather_scan_and_trade_job()


async def run_manual_settlement():
    """Trigger a manual settlement check."""
    log_event("info", "Manual settlement triggered")
    await settlement_job()
