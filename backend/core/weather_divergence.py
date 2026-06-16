"""Cross-venue weather-line divergence scanner (Polymarket vs Kalshi)."""

from dataclasses import dataclass
from datetime import date
from typing import List

from backend.data.weather_markets import WeatherMarket


@dataclass(frozen=True)
class WeatherLineDivergence:
    city_key: str
    target_date: date
    metric: str
    direction: str
    threshold_f: float

    polymarket_market_id: str
    kalshi_market_id: str
    polymarket_yes_price: float
    kalshi_yes_price: float
    probability_gap: float

    buy_yes_venue: str
    sell_yes_venue: str
    min_volume: float


def _is_valid_probability(value: float) -> bool:
    return 0.0 <= value <= 1.0


def _is_comparable_weather_line(market: WeatherMarket) -> bool:
    # Bucket contracts are not equivalent to single-threshold yes/no lines.
    if market.direction == "bucket":
        return False
    if not _is_valid_probability(market.yes_price):
        return False
    return market.platform in {"polymarket", "kalshi"}


def find_cross_venue_weather_divergences(
    markets: List[WeatherMarket],
    *,
    min_probability_gap: float = 0.05,
    threshold_tolerance_f: float = 0.5,
) -> List[WeatherLineDivergence]:
    """Return sorted Polymarket-vs-Kalshi line divergences.

    Matching key:
    - same city/date/metric/direction
    - threshold within ``threshold_tolerance_f``.
    """
    polymarket_lines = [m for m in markets if m.platform == "polymarket" and _is_comparable_weather_line(m)]
    kalshi_lines = [m for m in markets if m.platform == "kalshi" and _is_comparable_weather_line(m)]

    divergences: List[WeatherLineDivergence] = []

    for poly in polymarket_lines:
        for kalshi in kalshi_lines:
            if poly.city_key != kalshi.city_key:
                continue
            if poly.target_date != kalshi.target_date:
                continue
            if poly.metric != kalshi.metric:
                continue
            if poly.direction != kalshi.direction:
                continue
            if abs(poly.threshold_f - kalshi.threshold_f) > threshold_tolerance_f:
                continue

            gap = abs(poly.yes_price - kalshi.yes_price)
            if gap < min_probability_gap:
                continue

            buy_yes_venue = "polymarket" if poly.yes_price < kalshi.yes_price else "kalshi"
            sell_yes_venue = "kalshi" if buy_yes_venue == "polymarket" else "polymarket"

            divergences.append(
                WeatherLineDivergence(
                    city_key=poly.city_key,
                    target_date=poly.target_date,
                    metric=poly.metric,
                    direction=poly.direction,
                    threshold_f=round((poly.threshold_f + kalshi.threshold_f) / 2.0, 2),
                    polymarket_market_id=poly.market_id,
                    kalshi_market_id=kalshi.market_id,
                    polymarket_yes_price=poly.yes_price,
                    kalshi_yes_price=kalshi.yes_price,
                    probability_gap=gap,
                    buy_yes_venue=buy_yes_venue,
                    sell_yes_venue=sell_yes_venue,
                    min_volume=min(poly.volume, kalshi.volume),
                )
            )

    divergences.sort(key=lambda row: (row.probability_gap, row.min_volume), reverse=True)
    return divergences
