from backend.core.position_risk import RiskAction
from backend.core.position_risk_entertainment import EntertainmentRiskInput, analyze_entertainment_position


def test_rt_score_crossing_with_enough_reviews_exits():
    recommendation = analyze_entertainment_position(
        EntertainmentRiskInput(
            market_kind="rt",
            direction="yes",
            entry_price=0.55,
            size=100.0,
            held_side_bid=0.08,
            held_side_ask=0.10,
            top_bid_size=25.0,
            model_probability_for_held_side=0.08,
            threshold=80,
            tomatometer_score=65,
            review_count=100,
            direct_source_status="fresh",
        )
    )

    assert recommendation.action == RiskAction.EXIT
    assert "RT direct source crossed threshold against held side" in recommendation.reasons


def test_rt_low_review_count_watches_even_when_score_is_bad():
    recommendation = analyze_entertainment_position(
        EntertainmentRiskInput(
            market_kind="rt",
            direction="yes",
            entry_price=0.55,
            size=100.0,
            held_side_bid=0.08,
            held_side_ask=0.10,
            top_bid_size=25.0,
            model_probability_for_held_side=0.08,
            threshold=80,
            tomatometer_score=65,
            review_count=8,
            direct_source_status="fresh",
        )
    )

    assert recommendation.action == RiskAction.WATCH
    assert "review count below exit confidence threshold" in recommendation.reasons


def test_box_office_direct_source_contradiction_exits():
    recommendation = analyze_entertainment_position(
        EntertainmentRiskInput(
            market_kind="box_office",
            direction="yes",
            entry_price=0.50,
            size=100.0,
            held_side_bid=0.12,
            held_side_ask=0.14,
            top_bid_size=50.0,
            model_probability_for_held_side=0.06,
            direct_source_status="final_contradicts_held_side",
        )
    )

    assert recommendation.action == RiskAction.EXIT
    assert "box-office direct source contradicts held bucket" in recommendation.reasons
