from backend.config import Settings


def test_weather_architecture_defaults_present():
    s = Settings()

    assert s.WEATHER_DAILY_LOSS_LIMIT == 200.0
    assert s.WEATHER_MAX_OPEN_POSITIONS_PER_CITY == 2
    assert s.WEATHER_COMPOSITE_MIN_SCORE == 0.10

    assert s.WEATHER_WEIGHT_MISPRICING == 0.60
    assert s.WEATHER_WEIGHT_SPREAD == 0.20
    assert s.WEATHER_WEIGHT_LIQUIDITY == 0.15
    assert s.WEATHER_WEIGHT_IMBALANCE == 0.05

    assert s.WEATHER_USE_AIGEFS is False
    assert s.WEATHER_AIGEFS_WEIGHT == 0.50
