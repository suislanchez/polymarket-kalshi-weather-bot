"""Open-position risk scan orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session

from backend.config import settings
from backend.core.position_exit_executor import record_paper_exit
from backend.core.position_risk import ExitRecommendation, RiskAction
from backend.core.position_risk_weather import WeatherRiskInput, analyze_weather_position
from backend.core.weather_exit_quotes import WeatherExitQuote
from backend.models.database import Signal, Trade

RiskAnalyzer = Callable[[Trade], ExitRecommendation]
WeatherQuoteProvider = Callable[[Trade], WeatherExitQuote | None]


@dataclass(frozen=True)
class OpenPositionRiskSummary:
    total_open_positions: int
    action_counts: dict[str, int] = field(default_factory=dict)
    exited_count: int = 0
    live_exit_quote_error_count: int = 0
    closed_market_or_stale_token_count: int = 0
    source_status_counts: dict[str, int] = field(default_factory=dict)
    rows: list[dict] = field(default_factory=list)


def _default_watch_analyzer(trade: Trade) -> ExitRecommendation:
    return ExitRecommendation(
        action=RiskAction.WATCH,
        reasons=["live risk analyzer not wired for this market type yet"],
        exit_price=None,
        exit_pnl=None,
        unrealized_pnl=None,
        model_probability_for_held_side=getattr(trade, "model_probability", None),
        market_probability_for_held_side=None,
        source_status="missing_live_quote",
        evidence={"market_type": getattr(trade, "market_type", None)},
    )


def _latest_weather_signal_for_trade(db: Session, trade: Trade) -> Signal | None:
    return (
        db.query(Signal)
        .filter(Signal.market_type == "weather")
        .filter(Signal.market_ticker == trade.market_ticker)
        .order_by(Signal.timestamp.desc(), Signal.id.desc())
        .first()
    )


def _weather_source_fields(signal: Signal | None) -> dict:
    sources = list(getattr(signal, "sources", None) or [])
    settlement_tags = [source for source in sources if isinstance(source, str) and source.startswith("settlement:")]
    settlement_url = next(
        (source.removeprefix("settlement_url:") for source in sources if isinstance(source, str) and source.startswith("settlement_url:")),
        None,
    )
    settlement_source_known = bool(settlement_tags)
    station_known = any(tag.count(":") >= 2 and bool(tag.rsplit(":", 1)[-1]) for tag in settlement_tags)
    return {
        "settlement_source_known": settlement_source_known,
        "station_known": station_known,
        "settlement_tags": settlement_tags,
        "settlement_url": settlement_url,
    }


def _weather_model_probability_for_held_side(trade: Trade, signal: Signal) -> float | None:
    model_probability = getattr(signal, "model_probability", None)
    if model_probability is None:
        return getattr(trade, "model_probability", None)
    direction = (getattr(trade, "direction", None) or getattr(signal, "direction", "") or "").lower()
    if direction in {"no", "down", "under", "below"}:
        return round(1.0 - model_probability, 6)
    return model_probability


def _build_latest_weather_signal_analyzer(
    db: Session,
    quote_provider: WeatherQuoteProvider | None = None,
) -> RiskAnalyzer:
    """Return a safe weather analyzer backed by the latest persisted signal.

    Persisted weather signals contain source/model context but not executable
    current sell-side bid/depth. Therefore this analyzer intentionally labels the
    source status as quote-not-executable and never creates exits on its own; the
    policy may still return HOLD when the latest thesis/model context is intact.
    """

    def analyzer(trade: Trade) -> ExitRecommendation:
        signal = _latest_weather_signal_for_trade(db, trade)
        if signal is None:
            return _default_watch_analyzer(trade)

        source_fields = _weather_source_fields(signal)
        model_probability_for_held_side = _weather_model_probability_for_held_side(trade, signal)
        exit_quote = None
        if quote_provider is not None:
            exit_quote = quote_provider(trade)
        exit_quote_status = (
            exit_quote.source_status
            if exit_quote is not None
            else "latest_weather_signal_quote_not_executable"
        )
        direct_source_status = (
            "latest_weather_signal_with_live_quote"
            if exit_quote is not None and exit_quote.held_side_bid is not None
            else exit_quote_status
        )
        recommendation = analyze_weather_position(
            WeatherRiskInput(
                direction=getattr(trade, "direction", "yes") or "yes",
                entry_price=getattr(trade, "entry_price", None) or 0.0,
                size=getattr(trade, "size", None) or 0.0,
                held_side_bid=exit_quote.held_side_bid if exit_quote is not None else None,
                held_side_ask=(
                    exit_quote.held_side_ask
                    if exit_quote is not None
                    else getattr(signal, "market_price", None)
                ),
                top_bid_size=exit_quote.top_bid_size if exit_quote is not None else None,
                model_probability_for_held_side=model_probability_for_held_side,
                settlement_source_known=source_fields["settlement_source_known"],
                station_known=source_fields["station_known"],
                direct_source_status=direct_source_status,
                source_model_market_alignment_count=(
                    2 if exit_quote is not None and source_fields["settlement_source_known"] else
                    1 if source_fields["settlement_source_known"] else
                    0
                ),
            )
        )
        evidence = {
            **recommendation.evidence,
            **source_fields,
            **(exit_quote.evidence if exit_quote is not None else {}),
            "live_exit_quote_bid": exit_quote.held_side_bid if exit_quote is not None else None,
            "live_exit_quote_ask": exit_quote.held_side_ask if exit_quote is not None else None,
            "live_exit_quote_top_bid_size": exit_quote.top_bid_size if exit_quote is not None else None,
            "live_exit_quote_top_ask_size": exit_quote.top_ask_size if exit_quote is not None else None,
            "latest_signal_id": signal.id,
            "latest_signal_timestamp": signal.timestamp.isoformat() if signal.timestamp else None,
            "latest_signal_market_price": signal.market_price,
            "latest_signal_edge": signal.edge,
            "latest_signal_suggested_size": signal.suggested_size,
            "latest_signal_model_probability_for_held_side": model_probability_for_held_side,
            "latest_signal_reasoning": signal.reasoning,
        }
        return ExitRecommendation(
            **{
                **recommendation.__dict__,
                "source_status": exit_quote_status,
                "evidence": evidence,
            }
        )

    return analyzer


def _default_analyzers(
    db: Session,
    weather_quote_provider: WeatherQuoteProvider | None = None,
) -> dict[str, RiskAnalyzer]:
    return {"weather": _build_latest_weather_signal_analyzer(db, weather_quote_provider)}


def _persist_mark(trade: Trade, recommendation: ExitRecommendation, checked_at: datetime) -> None:
    trade.last_risk_action = recommendation.action.value
    trade.last_risk_reasons = list(recommendation.reasons)
    trade.last_mark_price = recommendation.exit_price
    trade.last_mark_time = checked_at
    trade.unrealized_pnl = recommendation.unrealized_pnl
    trade.last_risk_source_status = recommendation.source_status
    trade.last_risk_evidence = dict(recommendation.evidence or {})


def _row_for_trade(trade: Trade, recommendation: ExitRecommendation, checked_at: datetime) -> dict:
    evidence = dict(recommendation.evidence or {})
    return {
        "trade_id": trade.id,
        "market_type": trade.market_type,
        "market_ticker": trade.market_ticker,
        "event_slug": trade.event_slug,
        "direction": trade.direction,
        "entry_price": trade.entry_price,
        "size": trade.size,
        "current_exit_price": recommendation.exit_price,
        "unrealized_pnl": recommendation.unrealized_pnl,
        "model_probability_for_held_side": recommendation.model_probability_for_held_side,
        "market_probability_for_held_side": recommendation.market_probability_for_held_side,
        "action": recommendation.action.value,
        "reasons": list(recommendation.reasons),
        "source_status": recommendation.source_status,
        "risk_evidence": evidence,
        "live_exit_quote_bid": evidence.get("live_exit_quote_bid"),
        "live_exit_quote_ask": evidence.get("live_exit_quote_ask"),
        "live_exit_quote_top_bid_size": evidence.get("live_exit_quote_top_bid_size"),
        "live_exit_quote_top_ask_size": evidence.get("live_exit_quote_top_ask_size"),
        "live_exit_quote_source": evidence.get("quote_source"),
        "live_exit_quote_error": evidence.get("quote_error"),
        "settlement_source_known": evidence.get("settlement_source_known"),
        "station_known": evidence.get("station_known"),
        "settlement_url": evidence.get("settlement_url"),
        "settlement_tags": evidence.get("settlement_tags") or [],
        "latest_signal_id": evidence.get("latest_signal_id"),
        "latest_signal_timestamp": evidence.get("latest_signal_timestamp"),
        "latest_signal_market_price": evidence.get("latest_signal_market_price"),
        "latest_signal_edge": evidence.get("latest_signal_edge"),
        "latest_signal_suggested_size": evidence.get("latest_signal_suggested_size"),
        "latest_signal_model_probability_for_held_side": evidence.get("latest_signal_model_probability_for_held_side"),
        "checked_at": checked_at,
    }


def run_open_position_risk_scan(
    db: Session,
    *,
    analyzers: dict[str, RiskAnalyzer] | None = None,
    auto_exit_enabled: bool | None = None,
    weather_quote_provider: WeatherQuoteProvider | None = None,
) -> OpenPositionRiskSummary:
    """Run a recommendations-first risk scan over open paper positions.

    Auto-exit is opt-in and paper-only. With auto-exit disabled, this only writes
    mark-to-market/recommendation fields on each open trade.
    """
    analyzers = {**_default_analyzers(db, weather_quote_provider), **(analyzers or {})}
    should_auto_exit = settings.PAPER_AUTO_EXIT_ENABLED if auto_exit_enabled is None else auto_exit_enabled
    checked_at = datetime.utcnow()

    open_trades = (
        db.query(Trade)
        .filter(Trade.settled == False)  # noqa: E712 - SQLAlchemy comparison
        .filter(Trade.closed_early == False)  # noqa: E712 - SQLAlchemy comparison
        .all()
    )

    action_counts = {action.value: 0 for action in RiskAction}
    rows: list[dict] = []
    exited_count = 0
    live_exit_quote_error_count = 0
    closed_market_or_stale_token_count = 0
    source_status_counts: dict[str, int] = {}

    for trade in open_trades:
        market_type = getattr(trade, "market_type", "btc") or "btc"
        analyzer = analyzers.get(market_type, _default_watch_analyzer)
        recommendation = analyzer(trade)
        action_counts[recommendation.action.value] = action_counts.get(recommendation.action.value, 0) + 1

        _persist_mark(trade, recommendation, checked_at)
        row = _row_for_trade(trade, recommendation, checked_at)
        if row.get("live_exit_quote_error"):
            live_exit_quote_error_count += 1
        source_status = row.get("source_status")
        if source_status:
            source_status_counts[source_status] = source_status_counts.get(source_status, 0) + 1
        if source_status == "closed_market_or_stale_token":
            closed_market_or_stale_token_count += 1
        rows.append(row)

        if should_auto_exit and recommendation.action == RiskAction.EXIT:
            record_paper_exit(db, trade, recommendation, policy=f"{market_type}_open_position_risk_v1", exit_time=checked_at)
            exited_count += 1

    db.commit()
    return OpenPositionRiskSummary(
        total_open_positions=len(open_trades),
        action_counts=action_counts,
        exited_count=exited_count,
        live_exit_quote_error_count=live_exit_quote_error_count,
        closed_market_or_stale_token_count=closed_market_or_stale_token_count,
        source_status_counts=source_status_counts,
        rows=rows,
    )
