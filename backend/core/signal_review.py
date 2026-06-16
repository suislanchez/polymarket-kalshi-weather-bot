"""Read-only signal review queue helpers.

The dashboard needs a vertical-agnostic way to inspect why paper candidates are
blocked without making any trade executable.  This module only summarizes gate
failures; it does not size, place, or simulate trades.
"""

from collections import Counter
from typing import Any, Iterable, Optional


_HIGH_PRIORITY_PHRASES = (
    "missing settlement",
    "settlement source",
    "source/station",
    "missing line-level",
    "bid/ask",
    "clob",
)
_MEDIUM_PRIORITY_PHRASES = (
    "threshold",
    "spread",
    "top ask",
    "liquidity",
    "source state only",
    "current market quote",
    "stale",
)


def _get(obj: Any, attr: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _market_key(signal: Any, *, vertical: str) -> str:
    if vertical == "btc":
        market = _get(signal, "market")
        return _get(market, "market_id") or _get(market, "slug") or _get(signal, "market_ticker") or "unknown-btc"
    if vertical == "weather":
        market = _get(signal, "market")
        return (
            _get(signal, "market_id")
            or _get(signal, "market_ticker")
            or _get(signal, "market_key")
            or _get(signal, "condition_id")
            or _get(signal, "event_slug")
            or _get(market, "market_id")
            or _get(market, "slug")
            or "unknown-weather"
        )
    return _get(signal, "event_slug") or _get(signal, "title") or "unknown-rt-entertainment"


def _title(signal: Any, *, vertical: str) -> str:
    if vertical == "btc":
        return _get(signal, "market_title") or _market_key(signal, vertical=vertical)
    if vertical == "weather":
        market = _get(signal, "market")
        city = _get(signal, "city_name") or _get(signal, "city") or _get(market, "city_name")
        market_key = _market_key(signal, vertical=vertical)
        if not city and _get(signal, "question"):
            return _get(signal, "question")
        return f"{city} — {market_key}" if city else market_key
    return _get(signal, "title") or _market_key(signal, vertical=vertical)


def _reasons(signal: Any, *, vertical: str) -> list[str]:
    if vertical == "rt_entertainment":
        reasons = _get(signal, "no_trade_reasons") or []
        if reasons:
            return [str(reason) for reason in reasons if reason]
        reason = _get(signal, "no_trade_reason")
        return [reason] if reason else []
    reasons = _get(signal, "no_trade_reasons", []) or []
    normalized = [str(reason) for reason in reasons if reason]
    if vertical == "weather" and not normalized:
        source_state_label = _get(signal, "source_state_label")
        if source_state_label:
            normalized.append(str(source_state_label))
    return normalized


def _is_blocked(signal: Any, *, vertical: str) -> bool:
    if vertical == "rt_entertainment":
        return _get(signal, "paper_actionable", False) is False and bool(_reasons(signal, vertical=vertical))
    passes_threshold = _get(signal, "passes_threshold")
    if passes_threshold is None:
        passes_threshold = _get(signal, "actionable", False)
    return passes_threshold is False and bool(_reasons(signal, vertical=vertical))


def _priority(reasons: Iterable[str]) -> int:
    joined = " | ".join(reasons).lower()
    priority = 1
    if any(phrase in joined for phrase in _MEDIUM_PRIORITY_PHRASES):
        priority = max(priority, 2)
    if any(phrase in joined for phrase in _HIGH_PRIORITY_PHRASES):
        priority = max(priority, 3)
    if "not chainlink settlement source" in joined:
        priority = max(priority, 4)
    if "missing settlement source/station" in joined:
        priority = max(priority, 5)
    return priority


def _review_item(signal: Any, *, vertical: str) -> dict[str, Any]:
    reasons = _reasons(signal, vertical=vertical)
    primary_blocker = reasons[0] if reasons else "blocked by no-trade gate"
    return {
        "vertical": vertical,
        "market_key": _market_key(signal, vertical=vertical),
        "title": _title(signal, vertical=vertical),
        "primary_blocker": primary_blocker,
        "no_trade_reasons": reasons,
        "review_priority": _priority(reasons),
        "edge": _get(signal, "edge"),
        "best_bid": _get(signal, "best_bid"),
        "best_ask": _get(signal, "best_ask"),
        "threshold": _get(signal, "threshold"),
        "box_office_lower_m": _get(signal, "box_office_lower_m"),
        "box_office_upper_m": _get(signal, "box_office_upper_m"),
        "box_office_bucket_label": _get(signal, "box_office_bucket_label"),
        "box_office_bucket_type": _get(signal, "box_office_bucket_type"),
        "box_office_bucket_set_size": _get(signal, "box_office_bucket_set_size"),
        "box_office_bucket_set_probability_mass": _get(signal, "box_office_bucket_set_probability_mass"),
        "box_office_bucket_set_sanity_passed": _get(signal, "box_office_bucket_set_sanity_passed"),
        "box_office_resolved_yes_count": _get(signal, "box_office_resolved_yes_count"),
        "box_office_resolved_winner_label": _get(signal, "box_office_resolved_winner_label"),
        "market_closed": _get(signal, "market_closed", _get(signal, "closed")),
        "execution_spread": _get(signal, "execution_spread"),
        "top_ask_size": _get(signal, "top_ask_size"),
        "hours_since_source_refresh": _get(signal, "hours_since_source_refresh"),
        "settlement_source": _get(signal, "settlement_source"),
        "settlement_url": _get(signal, "settlement_url") or _get(signal, "settlement_source_url"),
        "settlement_station": _get(signal, "settlement_station"),
        "settlement_station_name": _get(signal, "settlement_station_name"),
        "settlement_units": _get(signal, "settlement_units"),
        "settlement_precision": _get(signal, "settlement_precision"),
        "source_capture_status": _get(signal, "source_capture_status"),
        "source_observed_value": _get(signal, "source_observed_value"),
        "source_observed_unit": _get(signal, "source_observed_unit"),
        "source_observed_at": _get(signal, "source_observed_at"),
        "source_capture_snapshot": _get(signal, "source_capture_snapshot"),
        "station_anomaly_status": _get(signal, "station_anomaly_status"),
        "station_anomaly_neighbor_count": _get(signal, "station_anomaly_neighbor_count"),
        "station_anomaly_max_delta": _get(signal, "station_anomaly_max_delta"),
        "model_price_source": _get(signal, "model_price_source"),
        "chainlink_feed_id": _get(signal, "chainlink_feed_id"),
        "chainlink_capture_method": _get(signal, "chainlink_capture_method"),
        "chainlink_source_url": _get(signal, "chainlink_source_url"),
        "chainlink_start_price": _get(signal, "chainlink_start_price"),
        "chainlink_end_price": _get(signal, "chainlink_end_price"),
        "chainlink_start_observed_at": _get(signal, "chainlink_start_observed_at"),
        "chainlink_end_observed_at": _get(signal, "chainlink_end_observed_at"),
        "chainlink_start_source_snapshot_path": _get(signal, "chainlink_start_source_snapshot_path"),
        "chainlink_end_source_snapshot_path": _get(signal, "chainlink_end_source_snapshot_path"),
        "source_url": _get(signal, "source_url"),
        "source_method": _get(signal, "source_method"),
        "direct_source_status": _get(signal, "direct_source_status"),
        "tomatometer_score": _get(signal, "tomatometer_score"),
        "review_count": _get(signal, "review_count"),
        "previous_captured_at": _get(signal, "previous_captured_at"),
        "previous_tomatometer_score": _get(signal, "previous_tomatometer_score"),
        "previous_review_count": _get(signal, "previous_review_count"),
        "score_delta": _get(signal, "score_delta"),
        "review_count_delta": _get(signal, "review_count_delta"),
        "hours_since_previous_source": _get(signal, "hours_since_previous_source"),
        "captured_at": _get(signal, "captured_at"),
        "cutoff_time": _get(signal, "cutoff_time"),
        "timing_risk_label": _get(signal, "timing_risk_label"),
        "source_state_label": _get(signal, "source_state_label"),
        "model_probability": _get(signal, "model_probability"),
        "market_probability": _get(signal, "market_probability"),
    }


def summarize_signal_review_queue(
    *,
    btc_signals: Optional[Iterable[Any]] = None,
    weather_signals: Optional[Iterable[Any]] = None,
    weather_review_candidates: Optional[Iterable[Any]] = None,
    weather_source_states: Optional[Iterable[Any]] = None,
    rt_source_states: Optional[Iterable[Any]] = None,
    limit: int = 12,
) -> dict[str, Any]:
    """Summarize blocked paper candidates for a dashboard review queue.

    The output intentionally stays non-actionable: it only surfaces failed gate
    reasons, vertical counts, and priority hints so the next research/buildout
    task can focus on the bottleneck with the most repeated failures.
    """
    raw_items: list[dict[str, Any]] = []
    vertical_sources = [
        ("btc", "btc_signal", btc_signals or []),
        ("weather", "weather_signal", weather_signals or []),
        ("weather", "weather_review_candidate", weather_review_candidates or []),
        ("weather", "polymarket_weather_source_state", weather_source_states or []),
        ("rt_entertainment", "rt_source_state", rt_source_states or []),
    ]

    for vertical, source_kind, signals in vertical_sources:
        for signal in signals:
            if _is_blocked(signal, vertical=vertical):
                item = _review_item(signal, vertical=vertical)
                item["source_kind"] = source_kind
                raw_items.append(item)

    raw_items.sort(
        key=lambda item: (
            item["review_priority"],
            abs(item["edge"] or 0.0),
            -(item["execution_spread"] or 0.0),
        ),
        reverse=True,
    )
    items = raw_items[: max(limit, 0)]

    blocked_by_vertical = Counter(item["vertical"] for item in raw_items)
    blocked_by_source = Counter(item["source_kind"] for item in raw_items)
    blocker_counts = Counter(reason for item in raw_items for reason in item["no_trade_reasons"])
    top_blockers = sorted(
        blocker_counts.items(),
        key=lambda pair: (_priority([pair[0]]), pair[1], pair[0]),
        reverse=True,
    )[:5]

    return {
        "total_blocked": len(raw_items),
        "blocked_by_vertical": dict(blocked_by_vertical),
        "blocked_by_source": dict(blocked_by_source),
        "top_blockers": [
            {"reason": reason, "count": count}
            for reason, count in top_blockers
        ],
        "items": items,
    }
