"""BTC-specific open-position risk policy."""
from __future__ import annotations

from dataclasses import dataclass

from backend.core.position_risk import (
    PositionEvidence,
    PositionQuote,
    ExitRecommendation,
    RiskAction,
    choose_exit_action,
)


BTC_EXIT_MODEL_PROB_THRESHOLD = 0.20
BTC_EXIT_NEAR_CLOSE_SECONDS = 90


@dataclass(frozen=True)
class BtcRiskInput:
    direction: str
    entry_price: float
    size: float
    up_bid: float | None
    up_ask: float | None
    down_bid: float | None
    down_ask: float | None
    top_bid_size: float | None
    model_probability_up: float | None
    seconds_to_close: int | None
    chainlink_boundary_status: str | None = None


def _spread(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    return max(0.0, round(ask - bid, 4))


def analyze_btc_position(position: BtcRiskInput) -> ExitRecommendation:
    direction = (position.direction or "").lower()
    held_is_up = direction in ("up", "yes")
    exit_price = position.up_bid if held_is_up else position.down_bid
    held_ask = position.up_ask if held_is_up else position.down_ask

    model_probability = None
    if position.model_probability_up is not None:
        model_probability = position.model_probability_up if held_is_up else round(1.0 - position.model_probability_up, 4)

    thesis_status = "unknown"
    if model_probability is not None:
        thesis_status = "broken" if model_probability < BTC_EXIT_MODEL_PROB_THRESHOLD else "intact"

    recommendation = choose_exit_action(
        quote=PositionQuote(
            exit_price=exit_price,
            spread=_spread(exit_price, held_ask),
            top_bid_size=position.top_bid_size,
            market_probability=exit_price,
        ),
        evidence=PositionEvidence(
            model_probability=model_probability,
            thesis_status=thesis_status,
            source_status=position.chainlink_boundary_status or "unknown",
            metadata={"seconds_to_close": position.seconds_to_close},
        ),
        entry_price=position.entry_price,
        size=position.size,
        model_threshold=BTC_EXIT_MODEL_PROB_THRESHOLD,
    )

    reasons = list(recommendation.reasons)
    if (
        recommendation.action == RiskAction.EXIT
        and position.seconds_to_close is not None
        and position.seconds_to_close <= BTC_EXIT_NEAR_CLOSE_SECONDS
    ):
        reasons.insert(0, "near close with model flip against held side")
        return ExitRecommendation(**{**recommendation.__dict__, "reasons": reasons})

    return recommendation
