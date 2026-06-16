"""Entertainment/RT/box-office-specific open-position risk policy."""
from __future__ import annotations

from dataclasses import dataclass

from backend.core.position_risk import ExitRecommendation, PositionEvidence, PositionQuote, RiskAction, choose_exit_action


ENTERTAINMENT_EXIT_MODEL_PROB_THRESHOLD = 0.15
ENTERTAINMENT_EXIT_MIN_REVIEW_COUNT = 30


@dataclass(frozen=True)
class EntertainmentRiskInput:
    market_kind: str
    direction: str
    entry_price: float
    size: float
    held_side_bid: float | None
    held_side_ask: float | None
    top_bid_size: float | None
    model_probability_for_held_side: float | None
    direct_source_status: str | None
    threshold: int | None = None
    tomatometer_score: int | None = None
    review_count: int | None = None


def _spread(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    return max(0.0, round(ask - bid, 4))


def _rt_source_contradicts(position: EntertainmentRiskInput) -> bool:
    if position.threshold is None or position.tomatometer_score is None:
        return False
    direction = (position.direction or "").lower()
    held_yes = direction in ("yes", "up")
    if held_yes:
        return position.tomatometer_score < position.threshold
    return position.tomatometer_score >= position.threshold


def analyze_entertainment_position(position: EntertainmentRiskInput) -> ExitRecommendation:
    kind = (position.market_kind or "").lower()
    direct_status = (position.direct_source_status or "unknown").lower()
    review_count = position.review_count or 0

    source_contradicts = False
    source_reason: str | None = None
    if kind == "rt":
        if review_count < ENTERTAINMENT_EXIT_MIN_REVIEW_COUNT:
            source_reason = "review count below exit confidence threshold"
        elif _rt_source_contradicts(position):
            source_contradicts = True
            source_reason = "RT direct source crossed threshold against held side"
    elif kind == "box_office" and direct_status == "final_contradicts_held_side":
        source_contradicts = True
        source_reason = "box-office direct source contradicts held bucket"

    model_probability = position.model_probability_for_held_side
    thesis_status = "broken" if source_contradicts else "unknown"
    if not source_contradicts and model_probability is not None and model_probability >= ENTERTAINMENT_EXIT_MODEL_PROB_THRESHOLD:
        thesis_status = "intact"

    recommendation = choose_exit_action(
        quote=PositionQuote(
            exit_price=position.held_side_bid,
            spread=_spread(position.held_side_bid, position.held_side_ask),
            top_bid_size=position.top_bid_size,
            market_probability=position.held_side_bid,
        ),
        evidence=PositionEvidence(
            model_probability=model_probability if source_reason != "review count below exit confidence threshold" else None,
            thesis_status=thesis_status if source_reason != "review count below exit confidence threshold" else "unknown",
            source_status=direct_status,
            metadata={"market_kind": kind, "review_count": position.review_count},
        ),
        entry_price=position.entry_price,
        size=position.size,
        model_threshold=ENTERTAINMENT_EXIT_MODEL_PROB_THRESHOLD,
    )

    reasons = list(recommendation.reasons)
    action = recommendation.action
    if source_reason and source_reason not in reasons:
        reasons.insert(0, source_reason)
    if source_reason == "review count below exit confidence threshold":
        action = RiskAction.WATCH

    return ExitRecommendation(**{**recommendation.__dict__, "action": action, "reasons": reasons})
