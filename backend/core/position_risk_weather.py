"""Weather-specific open-position risk policy."""
from __future__ import annotations

from dataclasses import dataclass

from backend.core.position_risk import ExitRecommendation, PositionEvidence, PositionQuote, RiskAction, choose_exit_action


WEATHER_EXIT_MODEL_PROB_THRESHOLD = 0.15


@dataclass(frozen=True)
class WeatherRiskInput:
    direction: str
    entry_price: float
    size: float
    held_side_bid: float | None
    held_side_ask: float | None
    top_bid_size: float | None
    model_probability_for_held_side: float | None
    settlement_source_known: bool
    station_known: bool
    direct_source_status: str | None
    source_model_market_alignment_count: int = 0


def _spread(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    return max(0.0, round(ask - bid, 4))


def analyze_weather_position(position: WeatherRiskInput) -> ExitRecommendation:
    has_source_context = position.settlement_source_known and position.station_known
    direct_status = (position.direct_source_status or "unknown").lower()
    model_probability = position.model_probability_for_held_side
    preliminary_contradiction = direct_status in {
        "preliminary_contradicts_held_side",
        "near_final_contradicts_held_side",
    }

    thesis_status = "unknown"
    if direct_status == "final_contradicts_held_side":
        thesis_status = "broken"
    elif preliminary_contradiction and has_source_context:
        thesis_status = "weakened"
    elif model_probability is not None and model_probability < WEATHER_EXIT_MODEL_PROB_THRESHOLD and has_source_context:
        thesis_status = "broken"
    elif model_probability is not None and model_probability >= WEATHER_EXIT_MODEL_PROB_THRESHOLD:
        thesis_status = "intact"

    recommendation = choose_exit_action(
        quote=PositionQuote(
            exit_price=position.held_side_bid,
            spread=_spread(position.held_side_bid, position.held_side_ask),
            top_bid_size=position.top_bid_size,
            market_probability=position.held_side_bid,
        ),
        evidence=PositionEvidence(
            model_probability=model_probability if has_source_context else None,
            thesis_status=thesis_status if has_source_context else "unknown",
            source_status=direct_status,
            alignment_count=position.source_model_market_alignment_count,
            metadata={
                "settlement_source_known": position.settlement_source_known,
                "station_known": position.station_known,
            },
        ),
        entry_price=position.entry_price,
        size=position.size,
        model_threshold=WEATHER_EXIT_MODEL_PROB_THRESHOLD,
    )

    reasons = list(recommendation.reasons)
    if not has_source_context and "weather source/station context incomplete" not in reasons:
        reasons.insert(0, "weather source/station context incomplete")
        action = RiskAction.WATCH
    elif direct_status == "final_contradicts_held_side" and recommendation.action == RiskAction.EXIT:
        reasons.insert(0, "direct weather source contradicts held side")
        action = RiskAction.EXIT
    elif preliminary_contradiction and recommendation.action == RiskAction.EXIT:
        reasons.insert(0, "weather source is not final; downgrade exit to reduce")
        action = RiskAction.REDUCE
    else:
        action = recommendation.action

    return ExitRecommendation(**{**recommendation.__dict__, "action": action, "reasons": reasons})
