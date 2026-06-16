from backend.core.position_risk import RiskAction
from backend.core.position_risk_weather import WeatherRiskInput, analyze_weather_position


def test_weather_direct_source_contradiction_and_bad_model_exits():
    recommendation = analyze_weather_position(
        WeatherRiskInput(
            direction="yes",
            entry_price=0.45,
            size=100.0,
            held_side_bid=0.10,
            held_side_ask=0.12,
            top_bid_size=40.0,
            model_probability_for_held_side=0.05,
            settlement_source_known=True,
            station_known=True,
            direct_source_status="final_contradicts_held_side",
            source_model_market_alignment_count=3,
        )
    )

    assert recommendation.action == RiskAction.EXIT
    assert "direct weather source contradicts held side" in recommendation.reasons


def test_weather_market_collapse_without_source_context_watches():
    recommendation = analyze_weather_position(
        WeatherRiskInput(
            direction="yes",
            entry_price=0.45,
            size=100.0,
            held_side_bid=0.08,
            held_side_ask=0.10,
            top_bid_size=100.0,
            model_probability_for_held_side=None,
            settlement_source_known=False,
            station_known=False,
            direct_source_status="missing",
            source_model_market_alignment_count=1,
        )
    )

    assert recommendation.action == RiskAction.WATCH
    assert "weather source/station context incomplete" in recommendation.reasons


def test_weather_model_low_but_source_incomplete_watches_not_auto_exit():
    recommendation = analyze_weather_position(
        WeatherRiskInput(
            direction="yes",
            entry_price=0.45,
            size=100.0,
            held_side_bid=0.10,
            held_side_ask=0.12,
            top_bid_size=100.0,
            model_probability_for_held_side=0.05,
            settlement_source_known=True,
            station_known=False,
            direct_source_status="near_final_uncertain",
            source_model_market_alignment_count=1,
        )
    )

    assert recommendation.action == RiskAction.WATCH
    assert "weather source/station context incomplete" in recommendation.reasons


def test_weather_preliminary_contradiction_reduces_instead_of_exiting():
    recommendation = analyze_weather_position(
        WeatherRiskInput(
            direction="yes",
            entry_price=0.45,
            size=100.0,
            held_side_bid=0.10,
            held_side_ask=0.12,
            top_bid_size=100.0,
            model_probability_for_held_side=0.05,
            settlement_source_known=True,
            station_known=True,
            direct_source_status="preliminary_contradicts_held_side",
            source_model_market_alignment_count=2,
        )
    )

    assert recommendation.action == RiskAction.REDUCE
    assert "weather source is not final; downgrade exit to reduce" in recommendation.reasons
