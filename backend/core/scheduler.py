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
_weather_threshold_state_cache: dict[str, str] = {}
_weather_observation_hash_by_station: dict[str, str] = {}


def _today():
    return datetime.utcnow().date()


def weather_threshold_state(signal) -> str:
    """Classify a weather market's current threshold state for state-change logs."""
    explicit = getattr(signal, "threshold_state", None)
    if explicit:
        return explicit

    source_observations = getattr(signal, "source_observations", None)
    source_fusion_policy = getattr(signal, "source_fusion_policy", None)
    if source_observations and source_fusion_policy:
        from backend.core.weather_source_fusion import fuse_weather_observations
        market = getattr(signal, "market", None)
        fused = fuse_weather_observations(
            observations=source_observations,
            policy=source_fusion_policy,
            threshold_f=getattr(market, "threshold_f", 0.0),
            metric=getattr(market, "metric", "high"),
        )
        if fused.lock_state == "locked":
            return "locked"
        if fused.lock_state == "below":
            return "below"

    observation = getattr(signal, "weather_observation", None)
    if observation is None:
        return "unavailable"
    if getattr(signal, "signal_source", None) == "METAR-lock":
        return "locked"

    threshold_f = getattr(getattr(signal, "market", None), "threshold_f", None)
    temp_f = getattr(observation, "temp_f", None)
    if threshold_f is None or temp_f is None:
        return "unavailable"

    metric = getattr(getattr(signal, "market", None), "metric", "")
    if metric == "low":
        if temp_f <= threshold_f:
            return "crossed"
        if temp_f <= threshold_f + 2:
            return "near"
        return "below"

    if temp_f >= threshold_f:
        return "crossed"
    if temp_f >= threshold_f - 2:
        return "near"
    return "below"


def plan_nowcast_impacted_recomputes(signals) -> list:
    """Plan event-driven recomputes only for stations whose raw observation changed."""
    from backend.core.weather_signals import plan_impacted_weather_recompute

    plans = []
    observations_by_station = {}
    for signal in signals:
        observation = getattr(signal, "weather_observation", None)
        if observation is None:
            continue
        observations_by_station[observation.station_id.upper()] = observation

    for station, observation in observations_by_station.items():
        plan = plan_impacted_weather_recompute(
            observation,
            signals,
            as_of_date=_today(),
            previous_hash_by_station=_weather_observation_hash_by_station,
        )
        if not plan.changed:
            continue
        _weather_observation_hash_by_station[station] = observation.raw_hash
        plans.append(plan)
    return plans


async def execute_nowcast_recompute_plans(plans) -> list:
    """Run scoped recomputes for changed-station plans with impacted market ids."""
    from backend.core.weather_signals import recompute_weather_signals_for_tickers

    recomputed = []
    seen_tickers = set()
    for plan in plans:
        tickers = [ticker for ticker in getattr(plan, "market_ids", []) if ticker not in seen_tickers]
        if not tickers:
            continue
        seen_tickers.update(tickers)
        signals = await recompute_weather_signals_for_tickers(tickers)
        recomputed.append({
            "station_id": getattr(plan, "station_id", None),
            "market_ids": tickers,
            "signals_recomputed": len(signals),
        })
    return recomputed


def emit_weather_threshold_state_changes(signals) -> list[dict]:
    """Log only changed weather threshold states; suppress unchanged refresh noise."""
    changes = []
    for signal in signals:
        market = getattr(signal, "market", None)
        market_id = getattr(market, "market_id", None)
        if not market_id:
            continue

        state = weather_threshold_state(signal)
        previous = _weather_threshold_state_cache.get(market_id)
        if previous == state:
            continue

        _weather_threshold_state_cache[market_id] = state
        observation = getattr(signal, "weather_observation", None)
        data = {
            "market_id": market_id,
            "previous_state": previous,
            "state": state,
            "city": getattr(market, "city_name", ""),
            "metric": getattr(market, "metric", ""),
            "threshold_f": getattr(market, "threshold_f", None),
            "temp_f": getattr(observation, "temp_f", None),
            "station_id": getattr(observation, "station_id", None),
            "observed_at": observation.observed_at.isoformat() if observation else None,
            "signal_source": getattr(signal, "signal_source", None),
            "metar_note": getattr(signal, "metar_note", ""),
        }
        changes.append(data)
        log_event(
            "weather_state_change",
            f"Weather threshold state changed: {market_id} {previous or 'new'} → {state}",
            data,
        )
    return changes


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

                if signal.suggested_size <= 0:
                    log_event("data", f"Skipping zero-size BTC signal: {signal.market.slug}")
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

            # Check weather allocation limit
            weather_pending = db.query(func.coalesce(func.sum(Trade.size), 0.0)).filter(
                Trade.settled == False,
                Trade.market_type == "weather",
            ).scalar()

            if weather_pending >= MAX_WEATHER_ALLOCATION:
                # Silently skip — allocation limit enforced without log noise
                return

            # INV-414: track running total inside loop to prevent overshoot
            running_weather_exposure = weather_pending
            trades_executed = 0
            for signal in actionable[:MAX_TRADES_PER_SCAN]:
                if running_weather_exposure >= MAX_WEATHER_ALLOCATION:
                    break

                # Check if we already have a trade for this market
                existing = db.query(Trade).filter(
                    Trade.market_ticker == signal.market.market_id,
                    Trade.settled == False,
                ).first()

                if existing:
                    continue

                if signal.suggested_size <= 0:
                    log_event("data", f"Skipping zero-size weather signal: {signal.market.slug}")
                    continue

                remaining_capacity = MAX_WEATHER_ALLOCATION - running_weather_exposure
                if remaining_capacity < MIN_TRADE_SIZE:
                    break

                trade_size = min(signal.suggested_size, settings.WEATHER_MAX_TRADE_SIZE, remaining_capacity)
                if trade_size < MIN_TRADE_SIZE:
                    continue
                trade_size = max(trade_size, MIN_TRADE_SIZE)

                if state.bankroll < MIN_TRADE_SIZE:
                    log_event("warning", f"Bankroll too low: ${state.bankroll:.2f}")
                    break

                if trades_executed >= MAX_TRADES_PER_SCAN:
                    break

                entry_price = signal.market.yes_price if signal.direction == "yes" else signal.market.no_price

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
                    edge_at_entry=signal.edge,
                )

                db.add(trade)
                db.flush()
                running_weather_exposure += trade_size

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


async def weather_nowcast_job():
    """
    Fast weather-observation refresh lane.

    Keeps same-day METAR/current-observation data fresh independently from the
    slower full Kalshi+GFS scan. It deliberately reuses the weather signal path
    for now so fresh observations, raw hashes, and latency records are emitted
    without a separate trading loop.
    """
    log_event("info", "Refreshing fast weather nowcast observations...")
    try:
        from backend.core.weather_signals import scan_for_weather_signals
        signals = await scan_for_weather_signals()
        observed = sum(1 for s in signals if getattr(s, "weather_observation", None) is not None)
        recompute_plans = plan_nowcast_impacted_recomputes(signals)
        recompute_results = await execute_nowcast_recompute_plans(recompute_plans)
        changes = emit_weather_threshold_state_changes(signals)
        if changes or recompute_plans:
            log_event("data", f"Weather nowcast refreshed: {observed} observed signal(s), {len(changes)} state change(s), {len(recompute_plans)} recompute plan(s)", {
                "total_signals": len(signals),
                "observed_signals": observed,
                "state_changes": len(changes),
                "recompute_plans": [plan.__dict__ for plan in recompute_plans],
                "recompute_results": recompute_results,
            })
        else:
            logger.debug("Weather nowcast refreshed: %s observed signal(s), no state changes", observed)
            return
    except Exception as e:
        log_event("error", f"Weather nowcast error: {str(e)}")
        logger.exception("Error in weather_nowcast_job")


async def settlement_job():
    """
    Background job: Check and settle pending trades.
    Runs every 2 minutes (BTC 5-min markets resolve fast).
    Also handles weather trade settlement when WEATHER_ENABLED.
    """
    # BTC_ENABLED=False only disables BTC scanning, NOT settlement
    # Weather trades also need to settle, so never skip entirely

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


def start_scheduler():
    """Start the background scheduler for BTC 5-min trading."""
    global scheduler

    if scheduler is not None and scheduler.running:
        log_event("warning", "Scheduler already running")
        return

    scheduler = AsyncIOScheduler()

    scan_seconds = settings.SCAN_INTERVAL_SECONDS
    settle_seconds = settings.SETTLEMENT_INTERVAL_SECONDS

    # Scan BTC markets every minute (gated by BTC_ENABLED)
    if settings.BTC_ENABLED:
        scheduler.add_job(
            scan_and_trade_job,
            IntervalTrigger(seconds=scan_seconds),
            id="market_scan",
            replace_existing=True,
            max_instances=1
        )
    else:
        log_event("info", "BTC trading DISABLED (BTC_ENABLED=False) — weather-only mode")

    # Check settlements every 2 minutes
    scheduler.add_job(
        settlement_job,
        IntervalTrigger(seconds=settle_seconds),
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

    # Weather trading jobs (gated by WEATHER_ENABLED)
    if settings.WEATHER_ENABLED:
        weather_scan_seconds = settings.WEATHER_SCAN_INTERVAL_SECONDS
        weather_nowcast_seconds = settings.WEATHER_NOWCAST_INTERVAL_SECONDS
        weather_settle_seconds = settings.WEATHER_SETTLEMENT_INTERVAL_SECONDS

        scheduler.add_job(
            weather_nowcast_job,
            IntervalTrigger(seconds=weather_nowcast_seconds),
            id="weather_nowcast",
            replace_existing=True,
            max_instances=1,
        )

        scheduler.add_job(
            weather_scan_and_trade_job,
            IntervalTrigger(seconds=weather_scan_seconds),
            id="weather_scan",
            replace_existing=True,
            max_instances=1,
        )

    scheduler.start()
    log_event("success", "Weather Edge scheduler started", {
        "btc_enabled": settings.BTC_ENABLED,
        "scan_interval": f"{scan_seconds}s",
        "settlement_interval": f"{settle_seconds}s",
        "min_edge": f"{settings.MIN_EDGE_THRESHOLD:.0%}",
        "weather_enabled": settings.WEATHER_ENABLED,
    })

    if settings.BTC_ENABLED:
        asyncio.create_task(scan_and_trade_job())

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
    """Trigger a manual market scan."""
    log_event("info", "Manual scan triggered")
    await scan_and_trade_job()


async def run_manual_settlement():
    """Trigger a manual settlement check."""
    log_event("info", "Manual settlement triggered")
    await settlement_job()
