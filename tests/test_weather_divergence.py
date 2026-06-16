from datetime import date

from backend.data.weather_markets import WeatherMarket
from backend.core.weather_divergence import find_cross_venue_weather_divergences


def _market(
    *,
    market_id: str,
    platform: str,
    city_key: str = "nyc",
    target_date: date = date(2026, 6, 1),
    metric: str = "high",
    direction: str = "above",
    threshold_f: float = 80.0,
    yes_price: float = 0.55,
    volume: float = 1000.0,
) -> WeatherMarket:
    return WeatherMarket(
        slug=market_id,
        market_id=market_id,
        platform=platform,
        title=f"{city_key} {metric} {direction} {threshold_f}",
        city_key=city_key,
        city_name=city_key.upper(),
        target_date=target_date,
        threshold_f=threshold_f,
        metric=metric,
        direction=direction,
        yes_price=yes_price,
        no_price=1.0 - yes_price,
        volume=volume,
    )


def test_find_cross_venue_weather_divergences_matches_same_line_and_sorts_by_gap():
    markets = [
        _market(market_id="poly-1", platform="polymarket", threshold_f=80.0, yes_price=0.62, volume=3000),
        _market(market_id="kalshi-1", platform="kalshi", threshold_f=80.0, yes_price=0.49, volume=2500),
        _market(market_id="poly-2", platform="polymarket", threshold_f=82.0, yes_price=0.70, volume=2000),
        _market(market_id="kalshi-2", platform="kalshi", threshold_f=82.0, yes_price=0.68, volume=5000),
    ]

    divergences = find_cross_venue_weather_divergences(markets, min_probability_gap=0.05)

    assert len(divergences) == 1
    top = divergences[0]
    assert top.polymarket_market_id == "poly-1"
    assert top.kalshi_market_id == "kalshi-1"
    assert round(top.probability_gap, 4) == 0.13
    assert top.buy_yes_venue == "kalshi"


def test_find_cross_venue_weather_divergences_respects_threshold_tolerance():
    markets = [
        _market(market_id="poly", platform="polymarket", threshold_f=80.0, yes_price=0.60),
        _market(market_id="kalshi", platform="kalshi", threshold_f=80.8, yes_price=0.45),
    ]

    strict = find_cross_venue_weather_divergences(markets, threshold_tolerance_f=0.5)
    loose = find_cross_venue_weather_divergences(markets, threshold_tolerance_f=1.0)

    assert strict == []
    assert len(loose) == 1


def test_find_cross_venue_weather_divergences_skips_bucket_and_invalid_prices():
    markets = [
        _market(market_id="poly-bucket", platform="polymarket", direction="bucket", yes_price=0.52),
        _market(market_id="kalshi-valid", platform="kalshi", yes_price=0.48),
        _market(market_id="poly-invalid", platform="polymarket", yes_price=1.2),
    ]

    divergences = find_cross_venue_weather_divergences(markets, min_probability_gap=0.01)
    assert divergences == []
