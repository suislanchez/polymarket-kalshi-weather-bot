"""Kalshi weather temperature market fetcher."""
import asyncio
from dataclasses import dataclass
import logging
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from backend.data.kalshi_client import KalshiClient
from backend.data.weather_markets import WeatherMarket
from backend.data.weather_station_map import KALSHI_WEATHER_STATION_MAP, get_station_mapping_for_city

# How many cities are crawled at once. Each city walks its series with cursor
# pagination and fetches an orderbook per market, so this bounds a fan-out that
# is several requests deep per city rather than one.
MAX_CONCURRENT_CITY_FETCHES = 4

logger = logging.getLogger("trading_bot")


@dataclass(frozen=True)
class KalshiBookTop:
    """Normalized top-of-book fields for a Kalshi Yes contract."""

    best_bid: Optional[float]
    best_ask: Optional[float]
    top_bid_size: Optional[float]
    top_ask_size: Optional[float]

# Kalshi primary high-temperature series tickers by city.  Derived from the
# checked-in exact settlement station map so series/station/product metadata stay
# synchronized.
CITY_SERIES: Dict[str, str] = {
    city_key: mapping.series_tickers[0]
    for city_key, mapping in KALSHI_WEATHER_STATION_MAP.items()
}

CITY_NAMES: Dict[str, str] = {
    city_key: mapping.city_name
    for city_key, mapping in KALSHI_WEATHER_STATION_MAP.items()
}

CITY_STATION_CODES: Dict[str, str] = {
    city_key: mapping.observation_station
    for city_key, mapping in KALSHI_WEATHER_STATION_MAP.items()
}

CITY_CLI_PRODUCTS: Dict[str, str] = {
    city_key: mapping.cli_product_code
    for city_key, mapping in KALSHI_WEATHER_STATION_MAP.items()
}

# Month abbreviation mapping for ticker parsing
MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _as_probability(price, *, dollar_ladder: bool) -> float:
    """Normalize Kalshi cent or dollar ladder prices to 0-1 probability."""
    value = float(price)
    return value if dollar_ladder else value / 100.0


def _sorted_ladder(ladder, *, dollar_ladder: bool) -> List[tuple[float, float]]:
    normalized: List[tuple[float, float]] = []
    for row in ladder or []:
        if len(row) < 2:
            continue
        try:
            normalized.append((_as_probability(row[0], dollar_ladder=dollar_ladder), float(row[1])))
        except (TypeError, ValueError):
            continue
    return sorted(normalized, key=lambda item: item[0], reverse=True)


def _parse_kalshi_orderbook_fp(orderbook_fp: Optional[dict]) -> KalshiBookTop:
    """Parse Kalshi orderbook_fp into Yes best bid/ask and top sizes.

    Kalshi exposes bid ladders for both sides. A Yes ask is derived from the
    best No bid: buying Yes at ask costs ``1 - best_no_bid``. The API has been
    observed with both cent ladders (``yes``/``no``) and dollar ladders
    (``yes_dollars``/``no_dollars``), so this parser accepts either shape.
    """
    if not orderbook_fp:
        return KalshiBookTop(None, None, None, None)

    yes_dollar_ladder = orderbook_fp.get("yes_dollars")
    no_dollar_ladder = orderbook_fp.get("no_dollars")
    yes_ladder = _sorted_ladder(
        yes_dollar_ladder if yes_dollar_ladder is not None else orderbook_fp.get("yes"),
        dollar_ladder=yes_dollar_ladder is not None,
    )
    no_ladder = _sorted_ladder(
        no_dollar_ladder if no_dollar_ladder is not None else orderbook_fp.get("no"),
        dollar_ladder=no_dollar_ladder is not None,
    )

    best_bid = yes_ladder[0][0] if yes_ladder else None
    top_bid_size = yes_ladder[0][1] if yes_ladder else None

    best_ask = None
    top_ask_size = None
    if no_ladder:
        best_ask = round(1.0 - no_ladder[0][0], 6)
        top_ask_size = no_ladder[0][1]

    return KalshiBookTop(best_bid, best_ask, top_bid_size, top_ask_size)


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


def _direction_from_title(title: str, fallback: str) -> str:
    """Infer Kalshi YES semantics from the human-readable title.

    Kalshi weather tickers alone are not enough: ``T`` tails can represent
    either over or under questions, while ``B`` contracts are mutually exclusive
    buckets (for example 78-79°) rather than simple ``above threshold`` bets.
    """
    text = (title or "").lower()
    if re.search(r"\d+\s*-\s*\d+", text) or "between" in text:
        return "bucket"
    if ">" in text or "above" in text or "higher" in text or "greater than" in text:
        return "above"
    if "<" in text or "below" in text or "under" in text or "less than" in text:
        return "below"
    return fallback


def _bucket_range_from_title(title: str) -> tuple[Optional[float], Optional[float]]:
    """Extract inclusive Fahrenheit bucket bounds from a Kalshi title/subtitle."""
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:°|degrees?)?\s*(?:-|to)\s*(\d+(?:\.\d+)?)",
        title or "",
        re.IGNORECASE,
    )
    if not match:
        return None, None
    low = float(match.group(1))
    high = float(match.group(2))
    return min(low, high), max(low, high)


def _metric_from_title_or_series(title: str, series_ticker: str, fallback: str) -> str:
    """Infer high/low metric from Kalshi human title and series ticker."""
    text = f"{title or ''} {series_ticker or ''}".lower()
    if "lowest" in text or "low temperature" in text or "kxlow" in text:
        return "low"
    if "highest" in text or "high temperature" in text or "maximum" in text or "kxhigh" in text:
        return "high"
    return fallback


async def fetch_kalshi_weather_markets(
    city_keys: Optional[List[str]] = None,
) -> List[WeatherMarket]:
    """
    Fetch open weather temperature markets from Kalshi.

    Queries the KXHIGH{city} series for each configured city,
    handles cursor-based pagination, and returns WeatherMarket objects.
    """
    client = KalshiClient()
    markets: List[WeatherMarket] = []
    today = date.today()

    cities = city_keys or list(CITY_SERIES.keys())

    async def collect_city(city_key: str) -> List[WeatherMarket]:
        city_markets: List[WeatherMarket] = []
        station_mapping = get_station_mapping_for_city(city_key)
        if station_mapping:
            series_tickers = station_mapping.series_tickers
        else:
            primary_series = CITY_SERIES.get(city_key)
            series_tickers = (primary_series,) if primary_series else ()
        if not series_tickers:
            return city_markets

        city_name = CITY_NAMES.get(city_key, city_key)

        for series in series_tickers:
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

                        volume = float(m.get("volume", 0) or 0)
                        book_top = KalshiBookTop(None, None, None, None)
                        try:
                            orderbook_data = await client.get_orderbook(ticker)
                            orderbook = orderbook_data.get("orderbook", orderbook_data)
                            book_top = _parse_kalshi_orderbook_fp(orderbook.get("orderbook_fp"))
                        except Exception as e:
                            logger.debug(f"Failed to fetch Kalshi orderbook for {ticker}: {e}")

                        yes_price = (m.get("yes_ask") or 0) / 100.0
                        no_price = (m.get("no_ask") or 0) / 100.0

                        # Prefer executable top-of-book when market fields omit asks.
                        # Falling back to 50c makes the review queue noisy and can
                        # manufacture false apparent edge.
                        if book_top.best_ask is not None:
                            yes_price = book_top.best_ask
                        if book_top.best_bid is not None:
                            no_price = max(0.0, 1.0 - book_top.best_bid)

                        # Fallback to last/mid prices only when no orderbook side is
                        # available; no-trade gates will still block missing depth.
                        if yes_price <= 0:
                            yes_price = (m.get("last_price") or 50) / 100.0
                        if no_price <= 0:
                            no_price = 1.0 - yes_price

                        # Skip fully resolved or illiquid tails after using CLOB ask.
                        if yes_price > 0.98 or yes_price < 0.02:
                            continue

                        title = m.get("title", ticker)
                        direction = _direction_from_title(title, parsed["direction"])
                        metric = _metric_from_title_or_series(title, series, parsed["metric"])
                        bucket_low_f, bucket_high_f = _bucket_range_from_title(
                            " ".join(str(part or "") for part in [title, m.get("subtitle")])
                        )

                        no_best_bid = max(0.0, 1.0 - book_top.best_ask) if book_top.best_ask is not None else None
                        no_best_ask = max(0.0, 1.0 - book_top.best_bid) if book_top.best_bid is not None else None

                        city_markets.append(WeatherMarket(
                            slug=ticker,
                            market_id=ticker,
                            platform="kalshi",
                            title=title,
                            city_key=city_key,
                            city_name=city_name,
                            target_date=parsed["target_date"],
                            threshold_f=parsed["threshold_f"],
                            metric=metric,
                            direction=direction,
                            yes_price=yes_price,
                            no_price=no_price,
                            bucket_low_f=bucket_low_f if direction == "bucket" else None,
                            bucket_high_f=bucket_high_f if direction == "bucket" else None,
                            volume=volume,
                            settlement_source=station_mapping.settlement_source if station_mapping else "nws_cli",
                            settlement_station=station_mapping.observation_station if station_mapping else CITY_STATION_CODES.get(city_key),
                            settlement_station_name=station_mapping.station_name if station_mapping else city_name,
                            settlement_product_code=station_mapping.cli_product_code if station_mapping else CITY_CLI_PRODUCTS.get(city_key),
                            settlement_source_url=station_mapping.settlement_source_url if station_mapping else None,
                            settlement_precision=station_mapping.precision if station_mapping else None,
                            best_bid=book_top.best_bid,
                            best_ask=book_top.best_ask,
                            top_ask_size=book_top.top_ask_size,
                            no_best_bid=no_best_bid,
                            no_best_ask=no_best_ask,
                            no_top_ask_size=book_top.top_bid_size,
                        ))

                    # Handle pagination
                    cursor = data.get("cursor")
                    if not cursor or not raw_markets:
                        break

            except Exception as e:
                logger.warning(f"Failed to fetch Kalshi markets for {city_key} ({series}): {e}")

        return city_markets

    # Cities are independent -- each queries its own series and its own
    # orderbooks, and nothing downstream depends on completion order. Bounded
    # so a 17-city slate does not open 17 paginated crawls at Kalshi at once.
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CITY_FETCHES)

    async def guarded(city_key: str) -> List[WeatherMarket]:
        async with semaphore:
            return await collect_city(city_key)

    # gather preserves input order, so the resulting slate is ordered exactly as
    # the serial loop left it.
    for result in await asyncio.gather(
        *(guarded(city_key) for city_key in cities), return_exceptions=True
    ):
        if isinstance(result, BaseException):
            # One city failing must not cost the rest of the slate.
            logger.warning(f"Kalshi city fetch failed: {result}")
            continue
        markets.extend(result)

    logger.info(f"Found {len(markets)} Kalshi weather markets")
    return markets
