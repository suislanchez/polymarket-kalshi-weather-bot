from backend.core.weather_signals import compute_weather_composite_score


def test_composite_score_rewards_tighter_spread_and_liquidity():
    strong = compute_weather_composite_score(
        mispricing_edge=0.12,
        best_bid=0.48,
        best_ask=0.52,
        top_ask_size=500.0,
        volume=5000.0,
        yes_last_price=0.50,
    )
    weak = compute_weather_composite_score(
        mispricing_edge=0.12,
        best_bid=0.40,
        best_ask=0.60,
        top_ask_size=20.0,
        volume=100.0,
        yes_last_price=0.50,
    )

    assert 0.0 <= strong <= 1.0
    assert 0.0 <= weak <= 1.0
    assert strong > weak


def test_composite_score_is_zero_without_edge():
    score = compute_weather_composite_score(
        mispricing_edge=0.0,
        best_bid=0.49,
        best_ask=0.51,
        top_ask_size=200.0,
        volume=2000.0,
        yes_last_price=0.50,
    )
    assert score == 0.0
