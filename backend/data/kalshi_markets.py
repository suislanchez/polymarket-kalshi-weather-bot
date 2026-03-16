"""Kalshi weather temperature market fetcher."""
import logging
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from backend.data.kalshi_client import KalshiClient, kalshi_credentials_present
from backend.data.weather_markets import WeatherMarket

logger = logging.getLogger("trading_bot")

# Kalshi series tickers for high-temperature markets by city
CITY_SERIES: Dict[str, str] = {
    "nyc": "KXHIGHNY",
    "chicago": "KXHIGHCHI",
    "miami": "KXHIGHMIA",
    "los_angeles": "KXHIGHLAX",
    "denver": "KXHIGHDEN",
}

CITY_NAMES: Dict[str, str] = {
    "nyc": "New York",
    "chicago": "Chicago",
    "miami": "Miami",
    "los_angeles": "Los Angeles",
    "denver": "Denver",
}

# Month abbreviation mapping for ticker parsing
MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _parse_kalshi_ticker(ticker: str, city_key: str) -> Optional[dict]:
    """
    Parse a Kalshi bracket ticker into market parameters.

    Format: KXHIGHNY-26MAR01-B45.5
      - 26MAR01 = 2026-03-01
      - B45.5 = bracket boundary at 45.5°F (above)
      - T45.5 would be "at or below" (top boundary)
    """
    # Match: SERIES-YYMONDD-B/Tnn.n
    match = re.match(
        r'^[A-Z]+-(\d{2})([A-Z]{3})(\d{2})-([BT])([\d.]+)$',
        ticker,
    )
    if not match:
        return None

    yy = int(match.group(1))
    mon_str = match.group(2)
    dd = int(match.group(3))
    boundary_type = match.group(4)
    threshold = float(match.group(5))

    month = MONTH_ABBR.get(mon_str)
    if not month:
        return None

    year = 2000 + yy
    try:
        target_date = date(year, month, dd)
    except ValueError:
        return None

    # B = bottom boundary → "above" threshold; T = top boundary → "below" threshold
    direction = "above" if boundary_type == "B" else "below"

    return {
        "target_date": target_date,
        "threshold_f": threshold,
        "metric": "high",
        "direction": direction,
    }


async def fetch_kalshi_weather_markets(
    city_keys: Optional[List[str]] = None,
) -> List[WeatherMarket]:
    """
    Fetch open weather temperature markets from Kalshi.

    Queries the KXHIGH{city} series for each configured city,
    handles cursor-based pagination, and returns WeatherMarket objects.
    """
    if not kalshi_credentials_present():
        return []

    client = KalshiClient()
    markets: List[WeatherMarket] = []
    today = date.today()

    cities = city_keys or list(CITY_SERIES.keys())

    for city_key in cities:
        series = CITY_SERIES.get(city_key)
        if not series:
            continue

        city_name = CITY_NAMES.get(city_key, city_key)
        cursor = None

        try:
            while True:
                params = {
                    "series_ticker": series,
                    "status": "open",
                    "limit": 200,
                }
                if cursor:
                    params["cursor"] = cursor

                data = await client.get_markets(params)
                raw_markets = data.get("markets", [])

                for m in raw_markets:
                    ticker = m.get("ticker", "")
                    parsed = _parse_kalshi_ticker(ticker, city_key)
                    if not parsed:
                        continue

                    if parsed["target_date"] < today:
                        continue

                    # Kalshi API uses dollar-denominated string fields
                    yes_bid = float(m.get("yes_bid_dollars") or 0)
                    yes_ask = float(m.get("yes_ask_dollars") or 0)

                    # Use mid-price for fair value (average of bid and ask)
                    if yes_bid > 0 and yes_ask > 0:
                        yes_price = (yes_bid + yes_ask) / 2.0
                    elif yes_ask > 0:
                        yes_price = yes_ask
                    elif yes_bid > 0:
                        yes_price = yes_bid
                    else:
                        yes_price = float(m.get("last_price_dollars") or 0)

                    no_price = 1.0 - yes_price

                    # Skip markets with no price data
                    if yes_price <= 0:
                        continue

                    # Skip extreme markets (tails where both model and market agree)
                    if yes_price > 0.92 or yes_price < 0.08:
                        continue

                    # Skip wide spreads (illiquid markets produce unreliable edges)
                    if yes_bid > 0 and yes_ask > 0:
                        spread = yes_ask - yes_bid
                        if spread > 0.10:
                            continue

                    volume = float(m.get("volume", 0) or 0)

                    markets.append(WeatherMarket(
                        slug=ticker,
                        market_id=ticker,
                        platform="kalshi",
                        title=m.get("title", ticker),
                        city_key=city_key,
                        city_name=city_name,
                        target_date=parsed["target_date"],
                        threshold_f=parsed["threshold_f"],
                        metric=parsed["metric"],
                        direction=parsed["direction"],
                        yes_price=yes_price,
                        no_price=no_price,
                        volume=volume,
                    ))

                # Handle pagination
                cursor = data.get("cursor")
                if not cursor or not raw_markets:
                    break

        except Exception as e:
            logger.warning(f"Failed to fetch Kalshi markets for {city_key} ({series}): {e}")

    logger.info(f"Found {len(markets)} Kalshi weather markets")
    return markets
