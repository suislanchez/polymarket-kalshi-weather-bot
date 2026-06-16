from backend.core.position_risk import RiskAction
from backend.core.position_risk_btc import BtcRiskInput, analyze_btc_position


def test_btc_model_flip_near_close_exits_when_bid_is_executable():
    recommendation = analyze_btc_position(
        BtcRiskInput(
            direction="up",
            entry_price=0.48,
            size=100.0,
            up_bid=0.18,
            up_ask=0.20,
            down_bid=0.80,
            down_ask=0.82,
            top_bid_size=50.0,
            model_probability_up=0.12,
            seconds_to_close=80,
            chainlink_boundary_status="pending",
        )
    )

    assert recommendation.action == RiskAction.EXIT
    assert "near close with model flip against held side" in recommendation.reasons


def test_btc_wide_spread_watches_even_with_bad_model_probability():
    recommendation = analyze_btc_position(
        BtcRiskInput(
            direction="up",
            entry_price=0.48,
            size=100.0,
            up_bid=0.18,
            up_ask=0.55,
            down_bid=0.45,
            down_ask=0.82,
            top_bid_size=50.0,
            model_probability_up=0.12,
            seconds_to_close=80,
            chainlink_boundary_status="pending",
        )
    )

    assert recommendation.action == RiskAction.WATCH
    assert "spread too wide for clean exit" in recommendation.reasons


def test_btc_direction_down_uses_down_probability_and_bid():
    recommendation = analyze_btc_position(
        BtcRiskInput(
            direction="down",
            entry_price=0.50,
            size=40.0,
            up_bid=0.82,
            up_ask=0.84,
            down_bid=0.16,
            down_ask=0.18,
            top_bid_size=20.0,
            model_probability_up=0.91,
            seconds_to_close=70,
            chainlink_boundary_status="pending",
        )
    )

    assert recommendation.action == RiskAction.EXIT
    assert recommendation.exit_price == 0.16
    assert recommendation.model_probability_for_held_side == 0.09
