"""Weather temperature market fetcher from Polymarket."""
import httpx
import json
import re
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

from backend.core.weather_methodology import parse_settlement_metadata
from backend.data.polymarket_client import PolymarketClient, map_outcome_tokens

logger = logging.getLogger("trading_bot")

# Map city names/variants found in market titles to our city keys
CITY_ALIASES = {
    "new york": "nyc",
    "nyc": "nyc",
    "new york city": "nyc",
    "chicago": "chicago",
    "miami": "miami",
    "los angeles": "los_angeles",
    "la": "los_angeles",
    "denver": "denver",
    "seattle": "seattle",
    "boston": "boston",
    "san francisco": "san_francisco",
    "sfo": "san_francisco",
    "philadelphia": "philadelphia",
    "philly": "philadelphia",
    "atlanta": "atlanta",
    "dallas": "dallas",
    "new orleans": "new_orleans",
    "nola": "new_orleans",
    "oklahoma city": "oklahoma_city",
    "okc": "oklahoma_city",
    "las vegas": "las_vegas",
    "seoul": "seoul",
    "tokyo": "tokyo",
    "beijing": "beijing",
    "shanghai": "shanghai",
    "london": "london",
    "paris": "paris",
    "singapore": "singapore",
    "hong kong": "hong_kong",
    "austin": "austin",
    "houston": "houston",
}

# Month name to number
MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


@dataclass
class WeatherMarket:
    """A weather temperature prediction market."""
    slug: str
    market_id: str
    platform: str
    title: str
    city_key: str
    city_name: str
    target_date: date
    threshold_f: float       # Temperature threshold in Fahrenheit
    metric: str              # "high" or "low"
    direction: str           # "above", "below", or "bucket"
    yes_price: float         # Price of YES outcome (0-1)
    no_price: float          # Price of NO outcome (0-1)
    bucket_low_f: Optional[float] = None
    bucket_high_f: Optional[float] = None
    volume: float = 0.0
    closed: bool = False
    rule_text: str = ""
    settlement_source: Optional[str] = None
    settlement_station: Optional[str] = None
    settlement_station_name: Optional[str] = None
    settlement_product_code: Optional[str] = None
    settlement_source_url: Optional[str] = None
    settlement_precision: Optional[str] = None
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    top_ask_size: Optional[float] = None
    no_best_bid: Optional[float] = None
    no_best_ask: Optional[float] = None
    no_top_ask_size: Optional[float] = None
    yes_midpoint: Optional[float] = None
    yes_last_price: Optional[float] = None
    recent_trades_count: int = 0


def _parse_weather_market_title(title: str) -> Optional[dict]:
    """
    Parse a weather market title to extract city, threshold, metric, date.

    Handles patterns like:
    - "Will the high temperature in New York exceed 75°F on March 5?"
    - "NYC high temperature above 80°F on March 10, 2026"
    - "Chicago daily high over 60°F on March 3"
    - "Will Miami's low be above 65°F on March 7?"
    - "Temperature in Denver above 70°F on March 5, 2026"
    """
    title_lower = title.lower()

    # Must be temperature-related
    if not any(kw in title_lower for kw in ["temperature", "temp", "°f", "°c", "degrees", "high", "low"]):
        return None

    # Extract city
    city_key = None
    city_name = None
    for alias, key in sorted(CITY_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in title_lower:
            city_key = key
            from backend.data.weather import CITY_CONFIG
            city_name = CITY_CONFIG[key]["name"]
            break

    if not city_key:
        return None

    def to_fahrenheit(value: float, unit: str) -> float:
        return value * 9.0 / 5.0 + 32.0 if unit == "celsius" else value

    # Extract threshold/bucket temperature. Polymarket international weather
    # markets are usually Celsius ("24°C"), while Kalshi/US rows are
    # Fahrenheit.  Polymarket daily-weather slates often express mutually
    # exclusive bucket rows as "between 72-73°F" or exact rows like "25°C";
    # preserve those bucket bounds so downstream grouping does not treat them
    # as one-sided above/below thresholds.
    temp_unit = "fahrenheit"
    bucket_low_f: float | None = None
    bucket_high_f: float | None = None
    range_match = re.search(
        r'between\s+(\d+(?:\.\d+)?)\s*(?:-|to|and)\s*(\d+(?:\.\d+)?)\s*°?\s*([fc])',
        title_lower,
    )
    if not range_match:
        range_match = re.search(
            r'(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*°\s*([fc])',
            title_lower,
        )
    if range_match:
        unit = "celsius" if range_match.group(3) == "c" else "fahrenheit"
        low = to_fahrenheit(float(range_match.group(1)), unit)
        high = to_fahrenheit(float(range_match.group(2)), unit)
        bucket_low_f = min(low, high)
        bucket_high_f = max(low, high)
        threshold_f = bucket_low_f
    else:
        temp_match = re.search(r'(\d+(?:\.\d+)?)\s*°?\s*f', title_lower)
        if not temp_match:
            temp_match = re.search(r'(\d+(?:\.\d+)?)\s*°?\s*c', title_lower)
            if temp_match:
                temp_unit = "celsius"
        if not temp_match:
            temp_match = re.search(r'(\d+(?:\.\d+)?)\s*degrees', title_lower)
        if not temp_match:
            return None
        threshold = float(temp_match.group(1))
        threshold_f = to_fahrenheit(threshold, temp_unit)

    # Determine metric (high vs low)
    metric = "high"  # default
    if "low" in title_lower:
        metric = "low"

    # Determine direction
    directional_keywords = [
        "above",
        "over",
        "exceed",
        "greater than",
        "or higher",
        "or above",
        "below",
        "under",
        "less than",
        "drop below",
        "or below",
    ]
    direction = "bucket" if bucket_low_f is not None else "above"
    if any(kw in title_lower for kw in ["below", "under", "less than", "drop below", "or below"]):
        direction = "below"
    elif bucket_low_f is None and not any(kw in title_lower for kw in directional_keywords):
        direction = "bucket"
        bucket_low_f = threshold_f
        bucket_high_f = threshold_f

    # Extract date
    target_date = _extract_date(title_lower)
    if not target_date:
        return None

    return {
        "city_key": city_key,
        "city_name": city_name,
        "threshold_f": threshold_f,
        "metric": metric,
        "direction": direction,
        "target_date": target_date,
        "bucket_low_f": bucket_low_f,
        "bucket_high_f": bucket_high_f,
    }


def _extract_date(text: str) -> Optional[date]:
    """Extract a date from market title text."""
    today = date.today()

    # Build month name pattern for precise matching
    month_names = "|".join(MONTH_MAP.keys())

    # Pattern: "March 5, 2026" or "March 5 2026" or "March 5"
    for match in re.finditer(rf'({month_names})\s+(\d{{1,2}})(?:\s*,?\s*(\d{{4}}))?', text):
        month_str = match.group(1)
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year

        month = MONTH_MAP.get(month_str)
        if month and 1 <= day <= 31:
            try:
                return date(year, month, day)
            except ValueError:
                continue

    # Pattern: "3/5/2026" or "03/05"
    match = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?', text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        try:
            return date(year, month, day)
        except ValueError:
            pass

    return None


async def fetch_polymarket_weather_markets(city_keys: Optional[List[str]] = None) -> List[WeatherMarket]:
    """
    Search Polymarket for weather temperature markets.
    Searches for temperature/weather events and parses their titles.
    """
    markets = []
    seen_market_ids: set[str] = set()

    try:
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            pm_client = PolymarketClient(client=client)  # type: ignore[arg-type]
            # public-search currently surfaces active grouped daily weather slates
            # more reliably than /events?tag=Weather for Polymarket weather.
            for query in ["highest temperature", "lowest temperature", "temperature"]:
                try:
                    response = await client.get(
                        "https://gamma-api.polymarket.com/public-search",
                        params={"q": query},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    events = payload.get("events", []) if isinstance(payload, dict) else []

                    for event in events:
                        if event.get("closed"):
                            continue
                        event_slug = event.get("slug", "")
                        for market_data in event.get("markets", []) or []:
                            market = await _parse_polymarket_weather(market_data, event_slug, city_keys, event, client, pm_client)
                            if market and market.market_id not in seen_market_ids:
                                seen_market_ids.add(market.market_id)
                                markets.append(market)
                except Exception as e:
                    logger.debug(f"Polymarket public-search for '{query}' failed: {e}")

            # Search for weather/temperature events
            for search_term in ["temperature", "weather high", "weather low"]:
                try:
                    response = await client.get(
                        "https://gamma-api.polymarket.com/events",
                        params={
                            "closed": "false",
                            "limit": 100,
                            "tag": "Weather",
                        }
                    )
                    response.raise_for_status()
                    events = response.json()

                    for event in events:
                        event_slug = event.get("slug", "")
                        for market_data in event.get("markets", []):
                            market = await _parse_polymarket_weather(market_data, event_slug, city_keys, event, client, pm_client)
                            if market and market.market_id not in seen_market_ids:
                                seen_market_ids.add(market.market_id)
                                markets.append(market)

                except Exception as e:
                    logger.debug(f"Weather market search for '{search_term}' failed: {e}")

            # Also try slug-based search for known patterns
            for slug_pattern in ["weather", "temperature", "temp-"]:
                try:
                    response = await client.get(
                        "https://gamma-api.polymarket.com/events",
                        params={
                            "closed": "false",
                            "limit": 100,
                            "slug_contains": slug_pattern,
                        }
                    )
                    response.raise_for_status()
                    events = response.json()

                    for event in events:
                        event_slug = event.get("slug", "")
                        for market_data in event.get("markets", []):
                            market = await _parse_polymarket_weather(market_data, event_slug, city_keys, event, client, pm_client)
                            if market and market.market_id not in seen_market_ids:
                                seen_market_ids.add(market.market_id)
                                markets.append(market)

                except Exception as e:
                    logger.debug(f"Weather slug search for '{slug_pattern}' failed: {e}")

    except Exception as e:
        logger.warning(f"Failed to fetch weather markets: {e}")

    logger.info(f"Found {len(markets)} weather temperature markets")
    return markets


def _parse_json_list(value) -> list:
    """Parse Gamma fields that may arrive as JSON strings or native lists."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return []
    return []


def _parse_polymarket_clob_book(book: dict) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return best bid, best ask, and top ask size from a Polymarket token book."""
    bids: list[float] = []
    asks: list[tuple[float, float]] = []

    for row in book.get("bids", []) or []:
        try:
            bids.append(float(row.get("price")))
        except (AttributeError, TypeError, ValueError):
            continue
    for row in book.get("asks", []) or []:
        try:
            asks.append((float(row.get("price")), float(row.get("size", 0) or 0)))
        except (AttributeError, TypeError, ValueError):
            continue

    best_bid = max(bids) if bids else None
    best_ask = min((price for price, _ in asks), default=None)
    top_ask_size = None
    if best_ask is not None:
        top_ask_size = next((size for price, size in asks if price == best_ask), None)
    return best_bid, best_ask, top_ask_size


async def _fetch_outcome_token_book(
    market_data: dict,
    client: httpx.AsyncClient,
    outcome_name: str,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Fetch line-level CLOB book for a named Polymarket outcome token."""
    outcome_token_map = map_outcome_tokens(market_data.get("outcomes"), market_data.get("clobTokenIds"))
    token = outcome_token_map.get(outcome_name.strip().lower())
    if not token:
        return None, None, None

    try:
        response = await client.get(
            "https://clob.polymarket.com/book",
            params={"token_id": token.token_id},
        )
        response.raise_for_status()
        return _parse_polymarket_clob_book(response.json())
    except Exception as e:
        logger.debug(
            f"Failed to fetch Polymarket {outcome_name} CLOB book for {market_data.get('id')}: {e}"
        )
        return None, None, None


async def _fetch_yes_token_book(
    market_data: dict,
    client: httpx.AsyncClient,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Fetch line-level Yes book for a Polymarket market when clobTokenIds exist."""
    return await _fetch_outcome_token_book(market_data, client, "yes")


async def _parse_polymarket_weather(
    market_data: dict,
    event_slug: str,
    city_keys: Optional[List[str]] = None,
    event_data: Optional[dict] = None,
    client: Optional[httpx.AsyncClient] = None,
    pm_client: Optional[PolymarketClient] = None,
) -> Optional[WeatherMarket]:
    """Parse a Polymarket market dict into a WeatherMarket if it's a temp market."""
    question = market_data.get("question", "") or market_data.get("groupItemTitle", "")
    if not question:
        return None

    parsed = _parse_weather_market_title(question)
    if not parsed:
        return None

    # Filter by requested cities
    if city_keys and parsed["city_key"] not in city_keys:
        return None

    # Only trade markets for dates in the future (or today)
    if parsed["target_date"] < date.today():
        return None

    # Parse prices
    outcome_prices = _parse_json_list(market_data.get("outcomePrices", []))

    if not outcome_prices or len(outcome_prices) < 2:
        return None

    try:
        yes_price = float(outcome_prices[0])
        no_price = float(outcome_prices[1])
    except (ValueError, IndexError):
        return None

    # Skip resolved markets
    if market_data.get("closed", False):
        return None
    if yes_price > 0.98 or yes_price < 0.02:
        return None

    volume = float(market_data.get("volume", 0) or 0)
    rule_text = "\n".join(
        str(part or "")
        for part in [
            market_data.get("description"),
            market_data.get("rules"),
            market_data.get("resolutionSource"),
            (event_data or {}).get("description"),
        ]
        if part
    )
    settlement = parse_settlement_metadata(rule_text)
    best_bid = best_ask = top_ask_size = None
    no_best_bid = no_best_ask = no_top_ask_size = None
    yes_midpoint = yes_last_price = None
    recent_trades_count = 0

    outcome_token_map = map_outcome_tokens(market_data.get("outcomes"), market_data.get("clobTokenIds"))
    yes_token = outcome_token_map.get("yes")
    yes_token_id = yes_token.token_id if yes_token else None

    if client is not None:
        best_bid, best_ask, top_ask_size = await _fetch_yes_token_book(market_data, client)
        no_best_bid, no_best_ask, no_top_ask_size = await _fetch_outcome_token_book(market_data, client, "no")
    if pm_client is not None and yes_token_id:
        yes_midpoint = await pm_client.fetch_midpoint(yes_token_id)
        yes_last_price = await pm_client.fetch_price(yes_token_id)
        recent_trades = await pm_client.fetch_trades(market=str(market_data.get("id", "")), limit=100)
        recent_trades_count = len(recent_trades)

    return WeatherMarket(
        slug=event_slug,
        market_id=str(market_data.get("id", "")),
        platform="polymarket",
        title=question,
        city_key=parsed["city_key"],
        city_name=parsed["city_name"],
        target_date=parsed["target_date"],
        threshold_f=parsed["threshold_f"],
        metric=parsed["metric"],
        direction=parsed["direction"],
        yes_price=yes_price,
        no_price=no_price,
        bucket_low_f=parsed.get("bucket_low_f"),
        bucket_high_f=parsed.get("bucket_high_f"),
        volume=volume,
        rule_text=rule_text,
        settlement_source=settlement.source,
        settlement_station=settlement.station_code,
        settlement_station_name=settlement.station_name,
        settlement_product_code=settlement.product_code,
        settlement_source_url=settlement.source_url,
        settlement_precision=settlement.precision,
        best_bid=best_bid,
        best_ask=best_ask,
        top_ask_size=top_ask_size,
        no_best_bid=no_best_bid,
        no_best_ask=no_best_ask,
        no_top_ask_size=no_top_ask_size,
        yes_midpoint=yes_midpoint,
        yes_last_price=yes_last_price,
        recent_trades_count=recent_trades_count,
    )
