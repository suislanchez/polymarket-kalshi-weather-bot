"""Background scheduler for BTC 5-min autonomous trading."""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import List, NamedTuple, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func
import logging

from backend.config import settings
from backend.models.database import SessionLocal, Trade, BotState, Signal
from backend.core.signals import scan_for_signals
from backend.trading.domain import (
    AssetClass,
    OrderStatus,
    OrderType,
    Side,
    TradeProposal,
    Venue,
)
from backend.trading.risk import PortfolioState, RiskContext, RiskLimits

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


WEATHER_STRATEGY_ID = "weather-ensemble-v1"

# Only these platforms have a simulated paper venue. Anything else is refused
# rather than guessed at, so a new venue cannot reach execution by accident.
_WEATHER_PAPER_VENUES = {
    "polymarket": Venue.POLYMARKET_PAPER,
    "kalshi": Venue.KALSHI_PAPER,
}


def weather_paper_venue(platform: object) -> Optional[Venue]:
    """Map a weather market platform onto its simulated paper venue."""
    if not isinstance(platform, str):
        return None
    return _WEATHER_PAPER_VENUES.get(platform.strip().lower())


def _finite_float(value: object) -> Optional[float]:
    """Return a finite float, rejecting bools, non-numbers, NaN and infinities."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError, InvalidOperation):
        return None
    return number if isfinite(number) else None


def _exact_decimal(value: object) -> Optional[Decimal]:
    """Convert a finite number to Decimal via its shortest round-tripping text.

    Going through ``str`` keeps 0.56 as ``Decimal("0.56")`` rather than the binary
    expansion ``Decimal(0.56)`` would produce, so identical inputs always digest
    to identical proposal identifiers.
    """
    number = _finite_float(value)
    if number is None:
        return None
    try:
        converted = Decimal(str(number))
    except InvalidOperation:
        return None
    return converted if converted.is_finite() else None


def _open_interval_price(value: object) -> Optional[Decimal]:
    price = _exact_decimal(value)
    if price is None or not (Decimal("0") < price < Decimal("1")):
        return None
    return price


def _positive_amount(value: object) -> Optional[Decimal]:
    amount = _exact_decimal(value)
    if amount is None or amount <= 0:
        return None
    return amount


def _as_utc(value: object) -> Optional[datetime]:
    """Normalize a signal timestamp to UTC, reading naive values as UTC."""
    if type(value) is not datetime:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_weather_paper_proposal(
    signal,
    *,
    size: float,
    entry_price: float,
    created_at: datetime,
) -> Optional[TradeProposal]:
    """Translate a gated weather signal into the normalized proposal contract.

    Returns ``None`` whenever the signal is not executable. Refusal is delegated
    to :func:`_weather_paper_execution_blockers` so the legacy venue reliability
    gates stay the single authority over what may execute; this function adds
    only the structural checks the normalized contract itself requires.

    This is a pure translation. It reads no storage and writes no ledger: routing
    accepted proposals into the unified event log is a later integration step.
    """
    if _weather_paper_execution_blockers(signal):
        return None

    market = getattr(signal, "market", None)
    if market is None:
        return None

    venue = weather_paper_venue(getattr(market, "platform", None))
    if venue is None:
        return None

    market_id = str(getattr(market, "market_id", "") or "").strip()
    if not market_id:
        return None

    outcome = str(getattr(signal, "direction", "") or "").strip().lower()
    if outcome not in {"yes", "no"}:
        return None

    price = _open_interval_price(entry_price)
    notional = _positive_amount(size)
    market_data_at = _as_utc(getattr(signal, "timestamp", None))
    created_at_utc = _as_utc(created_at)
    if price is None or notional is None or market_data_at is None or created_at_utc is None:
        return None

    target_date = getattr(market, "target_date", None)
    target_date_text = target_date.isoformat() if hasattr(target_date, "isoformat") else None
    metric = str(getattr(market, "metric", "") or "") or None
    market_direction = str(getattr(market, "direction", "") or "") or None
    threshold_f = _finite_float(getattr(market, "threshold_f", None))

    metadata = {
        "market_id": market_id,
        "platform": str(getattr(market, "platform", "") or "").strip().lower(),
        "slug": str(getattr(market, "slug", "") or "") or None,
        "outcome": outcome,
        "city_key": str(getattr(market, "city_key", "") or "") or None,
        "city_name": str(getattr(market, "city_name", "") or "") or None,
        "target_date": target_date_text,
        "metric": metric,
        "market_direction": market_direction,
        "threshold_f": threshold_f,
        "model_probability": _finite_float(getattr(signal, "model_probability", None)),
        "market_probability": _finite_float(getattr(signal, "market_probability", None)),
        "edge": _finite_float(getattr(signal, "edge", None)),
        "confidence": _finite_float(getattr(signal, "confidence", None)),
        "ensemble_mean": _finite_float(getattr(signal, "ensemble_mean", None)),
        "ensemble_std": _finite_float(getattr(signal, "ensemble_std", None)),
        "ensemble_members": int(getattr(signal, "ensemble_members", 0) or 0),
        "settlement_source": str(getattr(market, "settlement_source", "") or "") or None,
        "settlement_station": str(getattr(market, "settlement_station", "") or "") or None,
        "execution_spread": _finite_float(getattr(signal, "execution_spread", None)),
        "top_ask_size": _finite_float(getattr(signal, "top_ask_size", None)),
        "bucket_set_probability_mass": _finite_float(
            getattr(signal, "bucket_set_probability_mass", None)
        ),
        "bucket_set_sanity_passed": bool(getattr(signal, "bucket_set_sanity_passed", False)),
    }

    # Everything that distinguishes one order from another must be digested, or
    # two different orders collide on one identifier the ledger keys by.
    identity = json.dumps(
        {
            "strategy_id": WEATHER_STRATEGY_ID,
            "venue": venue.value,
            "market_id": market_id,
            "outcome": outcome,
            "side": Side.BUY.value,
            "order_type": OrderType.LIMIT.value,
            "notional": str(notional),
            "limit_price": str(price),
            "market_data_at": market_data_at.isoformat(),
            "target_date": target_date_text,
            "metric": metric,
            "market_direction": market_direction,
            "threshold_f": None if threshold_f is None else str(threshold_f),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    proposal_id = "wx-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()

    threshold_text = "?" if threshold_f is None else f"{threshold_f:.1f}"
    edge = _finite_float(getattr(signal, "edge", None))
    rationale = (
        f"weather {metric or 'temp'} {market_direction or '?'} {threshold_text}F "
        f"buy {outcome} at {price}"
        + ("" if edge is None else f" on edge {edge:+.4f}")
    )

    return TradeProposal(
        proposal_id=proposal_id,
        strategy_id=WEATHER_STRATEGY_ID,
        venue=venue,
        asset_class=AssetClass.PREDICTION_WEATHER,
        symbol=f"{market_id}:{outcome}",
        side=Side.BUY,
        notional=notional,
        order_type=OrderType.LIMIT,
        limit_price=price,
        reference_price=price,
        market_data_at=market_data_at,
        created_at=created_at_utc,
        rationale=rationale,
        metadata=metadata,
    )


STOCK_CRYPTO_JOB_ID = "stock_crypto_paper"


def paper_clock() -> datetime:
    """Current UTC instant for the unified paper lanes.

    A named seam rather than an inline datetime.now() call, so a test can place
    the run at a chosen moment relative to its market data instead of having to
    weaken the strategy's staleness bound to make a fixture usable.
    """
    return datetime.now(timezone.utc)

# Weather quotes are slow-moving relative to equities, and the weather scan
# cadence is five minutes; a tighter bound would reject every real proposal.
_WEATHER_MAX_QUOTE_AGE_SECONDS = Decimal("900")
_STOCK_CRYPTO_MAX_QUOTE_AGE_SECONDS = Decimal("30")


def stock_crypto_symbols() -> tuple:
    """Parse the configured symbol list, trimmed and deduplicated in order."""
    raw = str(getattr(settings, "STOCK_CRYPTO_SYMBOLS", "") or "")
    ordered: list[str] = []
    for candidate in raw.split(","):
        symbol = candidate.strip()
        if symbol and symbol not in ordered:
            ordered.append(symbol)
    return tuple(ordered)


def load_stock_crypto_bars(symbol: str):
    """Return a bar-series payload for ``symbol``, or None if none is available.

    There is no market-data source wired yet: broker credentials are gated behind
    a later user-approved step, and this runtime must never reach a live endpoint.
    Returning None is the honest answer, and it makes "a run produced zero
    proposals" the ordinary production outcome rather than an error. Tests and the
    later credentialed lane replace this seam.
    """
    return None


def paper_allowed_venues() -> frozenset:
    """Venues the risk layer may approve, mirroring the venue safety toggles.

    Kalshi is admitted only when its paper-execution flag is on, so the
    monitor-only boundary is enforced at the risk layer as well as at the
    scheduler gate and inside the adapter.
    """
    venues = {Venue.POLYMARKET_PAPER}
    if settings.WEATHER_KALSHI_PAPER_EXECUTION_ENABLED:
        venues.add(Venue.KALSHI_PAPER)
    if settings.STOCK_CRYPTO_LANE_ENABLED:
        venues.add(Venue.ALPACA_PAPER)
    return frozenset(venues)


def partition_stock_and_crypto_symbols(symbols) -> tuple:
    """Split configured symbols into disjoint stock and crypto allowlists.

    The risk layer requires these two allowlists to be non-empty and disjoint, so
    the split has to be total rather than best-effort. A pair separator is the
    discriminator the strategy already uses: BTC/USD and ETH/USD are crypto,
    SPY and QQQ are not. Each side falls back to a single conservative default
    when the configuration names nothing on that side, which keeps the
    allowlists non-empty without silently widening the other one.
    """
    stock = frozenset(symbol for symbol in symbols if "/" not in symbol)
    crypto = frozenset(symbol for symbol in symbols if "/" in symbol)
    return (stock or frozenset({"SPY"}), crypto or frozenset({"BTC/USD"}))


def paper_risk_limits() -> RiskLimits:
    """Deterministic risk policy for the shadow ledger route."""
    bankroll = _positive_amount(getattr(settings, "INITIAL_BANKROLL", 0.0)) or Decimal("1000")
    daily_loss = _positive_amount(getattr(settings, "WEATHER_DAILY_LOSS_LIMIT", 0.0))
    daily_loss_fraction = Decimal("0.05") if daily_loss is None else min(
        Decimal("0.95"), max(Decimal("0.001"), daily_loss / bankroll)
    )
    max_order = _positive_amount(getattr(settings, "WEATHER_MAX_TRADE_SIZE", 0.0)) or Decimal("100")
    stock_symbols, crypto_symbols = partition_stock_and_crypto_symbols(
        stock_crypto_symbols()
    )
    return RiskLimits(
        max_order_notional=max_order,
        max_order_equity_fraction=Decimal("0.03"),
        max_symbol_exposure_fraction=Decimal("0.10"),
        max_gross_exposure_fraction=Decimal("0.50"),
        max_crypto_exposure_fraction=Decimal("0.20"),
        daily_loss_fraction=daily_loss_fraction,
        stock_crypto_max_quote_age_seconds=_STOCK_CRYPTO_MAX_QUOTE_AGE_SECONDS,
        weather_max_quote_age_seconds=_WEATHER_MAX_QUOTE_AGE_SECONDS,
        allowed_stock_symbols=stock_symbols,
        allowed_crypto_symbols=crypto_symbols,
        allowed_venues=paper_allowed_venues(),
    )


def weather_portfolio_state(session):
    """Read real account state for the risk evaluation, or None if unavailable.

    Returning None rather than a placeholder is deliberate. A risk decision made
    against invented exposure would be recorded in an append-only audit ledger as
    though it were real, which is worse than not recording it at all.
    """
    failed = False
    equity = None
    gross = Decimal("0")
    realized = Decimal("0")
    try:
        state = session.query(BotState).first()
        if state is not None:
            equity = _positive_amount(getattr(state, "bankroll", None))
            realized = _exact_decimal(getattr(state, "total_pnl", 0.0)) or Decimal("0")
        pending = session.query(func.coalesce(func.sum(Trade.size), 0.0)).filter(
            Trade.settled == False,  # noqa: E712 - SQLAlchemy column comparison
            Trade.market_type == "weather",
        ).scalar()
        gross = _exact_decimal(pending) or Decimal("0")
    except Exception:
        failed = True
    if failed or equity is None or gross < 0:
        return None
    try:
        return PortfolioState(
            equity=equity,
            start_of_day_nlv=equity,
            daily_realized_pnl=realized,
            gross_exposure=gross,
            crypto_exposure=Decimal("0"),
        )
    except Exception:
        return None


_SERVICE_SESSION_KEY = "paper_execution_service"


def build_paper_execution_service(session):
    """Return this session's PaperExecutionService, or None when one cannot exist.

    One service per session, not one per order. The prediction adapters number
    their broker references from an instance counter, so an adapter rebuilt for
    every proposal restarts that counter and stamps every order in a run with the
    same reference -- four filled orders reading as one in an append-only audit
    ledger. Holding the service for the life of the session also restores the
    service's own duplicate-replay caches, which a service discarded after a
    single execute can never reach.

    The service is stored on the session, so it lives and dies with the session
    and nothing outlives the tick that opened it. A module-level weak-keyed
    mapping does not achieve that here: the service holds the session, so every
    entry would pin its own key, the weak reference could never fire, and a
    scheduler that opens a session per tick would retain all of them for the life
    of the process.

    Imported lazily so the scheduler keeps importing cleanly in environments where
    Archives is unbound; the service fails closed on Archives by design.
    """
    try:
        cached = session.info.get(_SERVICE_SESSION_KEY)
    except Exception:
        # Not a real Session. Build one anyway; it simply will not be reused.
        cached = None
    if cached is not None:
        return cached

    failed = False
    service = None
    try:
        from backend.trading.adapters.kalshi_paper import KalshiPaperAdapter
        from backend.trading.adapters.polymarket_paper import PolymarketPaperAdapter
        from backend.trading.execution_mode import archives_runtime_guard
        from backend.trading.service import PaperExecutionService, PaperExecutionSettings

        def clock():
            return datetime.now(timezone.utc)

        adapters = {
            Venue.POLYMARKET_PAPER: PolymarketPaperAdapter(clock=clock),
            Venue.KALSHI_PAPER: KalshiPaperAdapter(
                clock=clock,
                execution_enabled=bool(settings.WEATHER_KALSHI_PAPER_EXECUTION_ENABLED),
            ),
        }
        service = PaperExecutionService(
            session=session,
            adapters=adapters,
            settings=PaperExecutionSettings(execution_mode=str(settings.EXECUTION_MODE)),
            clock=clock,
            kill_switch=lambda: bool(getattr(settings, "LIVE_TRADING_ENABLED", False)),
            # Without this the service's own Archives checks return immediately and
            # both of them are dead code. A scheduler job outlives API startup, so
            # the re-check before each write is the only one that sees a mount lost
            # while the process is running.
            archives_guard=archives_runtime_guard(settings),
        )
    except Exception:
        failed = True
    if failed:
        return None
    try:
        session.info[_SERVICE_SESSION_KEY] = service
    except Exception:  # pragma: no cover - a stand-in with no usable info mapping
        pass
    return service


def weather_upstream_evidence(signal) -> tuple:
    """Name the authority that approved this weather signal for execution.

    The risk layer refuses every prediction-weather proposal without upstream
    approval evidence. That evidence must record *what* approved, so an auditor
    reading the ledger can check the claim rather than take it. It is derived
    from the shipped execution gate: when that gate refuses, there is no evidence
    to give, and the empty tuple makes the risk layer refuse too.
    """
    if _weather_paper_execution_blockers(signal):
        return ()
    market = getattr(signal, "market", None)
    if market is None:
        return ()
    platform = str(getattr(market, "platform", "") or "").strip().lower()
    source = str(getattr(market, "settlement_source", "") or "").strip()
    station = str(getattr(market, "settlement_station", "") or "").strip()
    if not platform or not source or not station:
        return ()
    return (
        f"weather-execution-gate:{platform}",
        f"settlement-source:{source}",
        f"settlement-station:{station}",
    )


def _weather_idempotency_key(proposal: TradeProposal) -> str:
    """One key per proposal. The proposal id already digests everything that
    distinguishes one order from another, so deriving from it makes a replay of
    the same proposal share a key while a different order cannot borrow one."""
    return f"weather:{proposal.proposal_id}"


def _shadow_route_outcome(result) -> tuple[str, dict | None]:
    """Read what the unified path actually decided, rather than that it returned.

    A call that comes back without raising is not agreement. The risk gate can
    refuse, the venue can be monitor-only, and the adapter's report can be
    rejected as unusable -- and in every one of those cases the legacy lane has
    already written its Trade row. Reporting them as a successful route is how
    the two paths diverge in silence.
    """
    decision = getattr(result, "decision", None)
    report = getattr(result, "report", None)
    approved = getattr(decision, "approved", None) is True
    status_name = getattr(getattr(report, "status", None), "value", None)
    if not isinstance(status_name, str):
        status_name = ""

    if approved and status_name == OrderStatus.FILLED.value:
        return "routed", None

    reason_codes = getattr(decision, "reason_codes", ()) or ()
    # Both vocabularies are fixed: Task 4's reason codes and the service's own
    # sanitized rejection label. Neither carries upstream text.
    return "refused", {
        "approved": approved,
        "status": status_name or "none",
        "reason_codes": [str(code) for code in reason_codes][:8],
        "rejection_reason": str(getattr(report, "rejection_reason", "") or ""),
    }


def shadow_route_weather_proposal(session, signal, proposal, *, now) -> str:
    """Mirror an accepted weather proposal into the unified event ledger.

    This is a shadow write during the compatibility phase: the legacy ``Trade``
    row remains authoritative, and this function must never raise, because the
    lane that already worked must not be taken down by the lane being added.

    Divergence between the two paths is therefore possible -- the legacy row can
    be written while this refuses -- so every non-routed outcome is logged with
    its reason. Disagreement is allowed to happen; it is not allowed to be
    silent.

    Returns one of: ``disabled``, ``no_proposal``, ``unavailable``, ``failed``,
    ``refused``, ``routed``. Only ``routed`` means the unified path agreed with
    the legacy one.
    """
    if not settings.WEATHER_UNIFIED_LEDGER_ENABLED:
        return "disabled"
    if proposal is None:
        log_event(
            "info",
            "Weather shadow ledger skipped: the execution gate produced no proposal",
            {"market_id": str(getattr(getattr(signal, "market", None), "market_id", "") or "")},
        )
        return "no_proposal"

    evidence = weather_upstream_evidence(signal)
    if not evidence:
        log_event(
            "info",
            "Weather shadow ledger skipped: no upstream approval evidence",
            {"proposal_id": proposal.proposal_id},
        )
        return "no_proposal"

    outcome = "failed"
    try:
        service = build_paper_execution_service(session)
        portfolio = weather_portfolio_state(session)
        if service is None or portfolio is None:
            log_event(
                "warning",
                "Weather shadow ledger unavailable; legacy paper path is unaffected",
                {
                    "proposal_id": proposal.proposal_id,
                    "service": service is not None,
                    "portfolio": portfolio is not None,
                },
            )
            return "unavailable"
        context = RiskContext(
            now=now,
            execution_mode="paper",
            idempotency_key=_weather_idempotency_key(proposal),
            weather_upstream_approved=True,
            weather_approval_evidence=evidence,
        )
        # The route borrows the caller's session, and the caller commits
        # authoritative legacy rows on it. A savepoint bounds the damage: a
        # failure in here rolls back only what this route wrote, and leaves the
        # session usable so the legacy commit still lands. Without it a failed
        # flush poisons the session and takes the legacy rows down with it, and a
        # failed read leaves a durable event chain with no order behind it.
        with session.begin_nested():
            result = service.execute(
                proposal, portfolio=portfolio, context=context, limits=paper_risk_limits()
            )
        outcome, refusal = _shadow_route_outcome(result)
        if refusal is not None:
            log_event(
                "warning",
                "Weather shadow ledger refused a proposal the legacy lane executed",
                {"proposal_id": proposal.proposal_id, **refusal},
            )
    except Exception as error:
        # Sanitized: record the failure type, never the upstream message, which
        # can carry request payloads.
        log_event(
            "warning",
            "Weather shadow ledger route failed; legacy paper path is unaffected",
            {"proposal_id": proposal.proposal_id, "error_type": type(error).__name__},
        )
        return "failed"
    return outcome


class PaperLaneResult(NamedTuple):
    """One proposal's outcome, read from the service rather than assumed."""

    proposal: object
    outcome: str
    status: Optional[str]
    reason_codes: tuple
    rejection_reason: Optional[str]


class PaperLaneOutcome(NamedTuple):
    proposals: int
    results: tuple


def run_manual_paper_lane(session, *, now=None) -> PaperLaneOutcome:
    """Propose and route the stock/crypto paper lane on a caller-owned session.

    This never commits and never rolls back. The execution service is held to
    that contract and so is this: the caller owns the transaction boundary,
    because the caller is the only party that knows whether its own work should
    survive. Both the scheduler job and the manual API route are thin callers,
    so the lane has one implementation and one place to fix.

    The lane flag is deliberately NOT checked here. It governs whether the
    scheduler runs this on its own; an operator asking for a run has already
    made that decision, and the safety guards that actually matter -- paper
    mode, the kill switch, Archives availability -- live in the service and in
    the callers.

    A run that proposes nothing returns zero proposals and no results. That is
    success, not a failure to report.
    """
    from backend.trading.market_data import load_bar_series
    from backend.trading.strategies.trend_following import TrendFollowingStrategy

    strategy = TrendFollowingStrategy()
    now = paper_clock() if now is None else now
    notional_cap = _positive_amount(getattr(settings, "WEATHER_MAX_TRADE_SIZE", 0.0)) or Decimal("100")

    service = None
    portfolio = None
    proposals_seen = 0
    results: list = []
    for symbol in stock_crypto_symbols():
        try:
            payload = load_stock_crypto_bars(symbol)
            if payload is None:
                continue
            series = load_bar_series(payload)
            signal = strategy.propose(
                series,
                now=now,
                notional_cap=notional_cap,
                position_quantity=Decimal("0"),
            )
        except Exception as error:
            log_event(
                "warning",
                f"Stock/crypto market data unavailable for {symbol}",
                {"symbol": symbol, "error_type": type(error).__name__},
            )
            continue

        if signal.proposal is None:
            log_event("info", f"No {symbol} proposal: {signal.reason}", {"symbol": symbol})
            continue

        proposals_seen += 1
        try:
            if service is None:
                service = build_paper_execution_service(session)
                portfolio = weather_portfolio_state(session)
            if service is None or portfolio is None:
                log_event(
                    "warning",
                    "Stock/crypto paper service unavailable; no order was routed",
                    {"symbol": symbol},
                )
                results.append(
                    PaperLaneResult(signal.proposal, "unavailable", None, (), None)
                )
                continue
            context = RiskContext(
                now=now,
                execution_mode="paper",
                idempotency_key=f"stock-crypto:{signal.proposal.proposal_id}",
            )
            result = service.execute(
                signal.proposal,
                portfolio=portfolio,
                context=context,
                limits=paper_risk_limits(),
            )
            # Read what the service decided rather than that it returned, the
            # same way the weather shadow route does.
            outcome, refusal = _shadow_route_outcome(result)
            if refusal is not None:
                log_event(
                    "warning",
                    f"Stock/crypto paper lane refused {symbol}",
                    {"symbol": symbol, **refusal},
                )
            results.append(
                PaperLaneResult(
                    signal.proposal,
                    outcome,
                    (refusal or {}).get("status"),
                    tuple((refusal or {}).get("reason_codes", ())),
                    (refusal or {}).get("rejection_reason") or None,
                )
            )
        except Exception as error:
            log_event(
                "warning",
                f"Stock/crypto paper route failed for {symbol}",
                {"symbol": symbol, "error_type": type(error).__name__},
            )
            results.append(PaperLaneResult(signal.proposal, "failed", None, (), None))

    if proposals_seen == 0:
        log_event("info", "Stock/crypto paper run produced zero proposals")

    return PaperLaneOutcome(proposals_seen, tuple(results))


async def stock_crypto_paper_job():
    """Bounded unified paper lane for stocks and spot crypto.

    Obtains market data, asks the strategy for proposals, and hands each to
    ``PaperExecutionService``. It never calls a broker adapter directly.

    This job owns the session it opens, so it is the party that must commit.
    It previously closed without committing, which discarded every ledger row
    the lane wrote -- invisible only because the market-data seam returns None
    and the lane has never produced a proposal in production.
    """
    if not settings.STOCK_CRYPTO_LANE_ENABLED:
        return

    session = SessionLocal()
    try:
        run_manual_paper_lane(session)
        session.commit()
    except Exception as error:
        try:
            session.rollback()
        except Exception:
            pass
        log_event(
            "warning",
            "Stock/crypto paper job failed; nothing was recorded",
            {"error_type": type(error).__name__},
        )
    finally:
        try:
            session.close()
        except Exception:
            pass


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

                # Shadow-write the same decision into the unified event ledger.
                # The legacy Trade row above stays authoritative for the
                # compatibility phase; this cannot raise, and any refusal is
                # logged with its reason so the two paths cannot disagree quietly.
                routed_at = paper_clock()
                shadow_route_weather_proposal(
                    db,
                    signal,
                    build_weather_paper_proposal(
                        signal,
                        size=trade_size,
                        entry_price=entry_price,
                        created_at=routed_at,
                    ),
                    now=routed_at,
                )

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
    if settings.STOCK_CRYPTO_LANE_ENABLED:
        jobs.append(STOCK_CRYPTO_JOB_ID)
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
    # Unified stock/crypto paper lane — only when explicitly enabled.
    if settings.STOCK_CRYPTO_LANE_ENABLED:
        scheduler.add_job(
            stock_crypto_paper_job,
            IntervalTrigger(seconds=settings.STOCK_CRYPTO_SCAN_INTERVAL_SECONDS),
            id=STOCK_CRYPTO_JOB_ID,
            replace_existing=True,
        )

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
