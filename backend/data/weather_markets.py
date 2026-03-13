"""Weather temperature market fetcher from Polymarket."""
import httpx
import re
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

logger = logging.getLogger("trading_bot")

# Map city names found in market titles to our city keys
CITY_ALIASES = {
    "new york city": "nyc",
    "new york": "nyc",
    "nyc": "nyc",
    "chicago": "chicago",
    "miami": "miami",
    "los angeles": "los_angeles",
    "dallas": "dallas",
    "paris": "paris",
    "london": "london",
    "tokyo": "tokyo",
    "sao paulo": "sao_paulo",
    "singapore": "singapore",
    "wellington": "wellington",
    "buenos aires": "buenos_aires",
    "tel aviv": "tel_aviv",
    "sydney": "sydney",
    "toronto": "toronto",
    "berlin": "berlin",
    "dubai": "dubai",
    "amsterdam": "amsterdam",
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
    direction: str           # "above", "below", or "range"
    yes_price: float         # Price of YES outcome (0-1)
    no_price: float          # Price of NO outcome (0-1)
    volume: float = 0.0
    closed: bool = False
    # For range markets: low end of range (threshold_f is the high end)
    threshold_f_low: Optional[float] = None
    # CLOB token IDs for order placement (Polymarket only)
    yes_token_id: Optional[str] = None
    no_token_id: Optional[str] = None


def _celsius_to_fahrenheit(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def _parse_weather_market_title(title: str) -> Optional[dict]:
    """
    Parse a Polymarket weather market title.

    Handles the actual Polymarket format:
    - "Will the highest temperature in New York City be between 56-57°F on March 12?"
    - "Will the highest temperature in Paris be 8°C on March 14?"
    - "Will the highest temperature in Wellington be 10°C or below on March 14?"
    - "Will the highest temperature in Dallas be 84°F or higher on March 13?"
    """
    title_lower = title.lower()

    # Must be a temperature market
    if "temperature" not in title_lower:
        return None

    # Extract city (try longest alias first to avoid partial matches)
    city_key = None
    city_name = None
    for alias in sorted(CITY_ALIASES.keys(), key=len, reverse=True):
        if alias in title_lower:
            city_key = CITY_ALIASES[alias]
            from backend.data.weather import CITY_CONFIG
            city_name = CITY_CONFIG[city_key]["name"]
            break

    if not city_key:
        return None

    # Determine metric — "highest" or "lowest" temperature
    metric = "high"
    if "lowest" in title_lower or "minimum" in title_lower:
        metric = "low"

    # Extract date
    target_date = _extract_date(title_lower)
    if not target_date:
        return None

    # ── Pattern 1: "between X-Y°F" ────────────────────────────────────────
    range_f = re.search(r'between\s+(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\s*°?\s*f', title_lower)
    if range_f:
        low_f = float(range_f.group(1))
        high_f = float(range_f.group(2))
        return {
            "city_key": city_key,
            "city_name": city_name,
            "threshold_f": high_f,
            "threshold_f_low": low_f,
            "metric": metric,
            "direction": "range",
            "target_date": target_date,
        }

    # ── Pattern 2: "between X-Y°C" ────────────────────────────────────────
    range_c = re.search(r'between\s+(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\s*°?\s*c\b', title_lower)
    if range_c:
        low_f = _celsius_to_fahrenheit(float(range_c.group(1)))
        high_f = _celsius_to_fahrenheit(float(range_c.group(2)))
        return {
            "city_key": city_key,
            "city_name": city_name,
            "threshold_f": high_f,
            "threshold_f_low": low_f,
            "metric": metric,
            "direction": "range",
            "target_date": target_date,
        }

    # Temperature number pattern — allows negative values
    _NUM = r'-?\d+(?:\.\d+)?'

    # ── Pattern 3: "X°F or higher" / "X°F or above" ───────────────────────
    above_f = re.search(rf'({_NUM})\s*°?\s*f\s+or\s+(?:higher|above)', title_lower)
    if above_f:
        return {
            "city_key": city_key,
            "city_name": city_name,
            "threshold_f": float(above_f.group(1)),
            "threshold_f_low": None,
            "metric": metric,
            "direction": "above",
            "target_date": target_date,
        }

    # ── Pattern 4: "X°C or higher" / "X°C or above" ───────────────────────
    above_c = re.search(rf'({_NUM})\s*°?\s*c\b\s+or\s+(?:higher|above)', title_lower)
    if above_c:
        return {
            "city_key": city_key,
            "city_name": city_name,
            "threshold_f": _celsius_to_fahrenheit(float(above_c.group(1))),
            "threshold_f_low": None,
            "metric": metric,
            "direction": "above",
            "target_date": target_date,
        }

    # ── Pattern 5: "X°F or below" / "X°F or under" ───────────────────────
    below_f = re.search(rf'({_NUM})\s*°?\s*f\s+or\s+(?:below|under|less)', title_lower)
    if below_f:
        return {
            "city_key": city_key,
            "city_name": city_name,
            "threshold_f": float(below_f.group(1)),
            "threshold_f_low": None,
            "metric": metric,
            "direction": "below",
            "target_date": target_date,
        }

    # ── Pattern 6: "X°C or below" / "X°C or under" ───────────────────────
    below_c = re.search(rf'({_NUM})\s*°?\s*c\b\s+or\s+(?:below|under|less)', title_lower)
    if below_c:
        return {
            "city_key": city_key,
            "city_name": city_name,
            "threshold_f": _celsius_to_fahrenheit(float(below_c.group(1))),
            "threshold_f_low": None,
            "metric": metric,
            "direction": "below",
            "target_date": target_date,
        }

    # ── Pattern 7: exact "X°C" (no qualifier = exact match market) ────────
    exact_c = re.search(rf'be\s+({_NUM})\s*°?\s*c\b', title_lower)
    if exact_c:
        val_c = float(exact_c.group(1))
        return {
            "city_key": city_key,
            "city_name": city_name,
            "threshold_f": _celsius_to_fahrenheit(val_c + 0.5),
            "threshold_f_low": _celsius_to_fahrenheit(val_c - 0.5),
            "metric": metric,
            "direction": "range",
            "target_date": target_date,
        }

    # ── Pattern 8: exact "X°F" (no qualifier) ─────────────────────────────
    exact_f = re.search(rf'be\s+({_NUM})\s*°?\s*f\b', title_lower)
    if exact_f:
        val = float(exact_f.group(1))
        return {
            "city_key": city_key,
            "city_name": city_name,
            "threshold_f": val + 0.5,
            "threshold_f_low": val - 0.5,
            "metric": metric,
            "direction": "range",
            "target_date": target_date,
        }

    return None


def _extract_date(text: str) -> Optional[date]:
    """Extract a date from market title text."""
    today = date.today()
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
    Fetch active weather temperature markets from Polymarket.

    Polymarket temperature markets are standalone markets (no event grouping, no tags).
    We page through /markets filtering by question content.
    """
    markets = []
    seen_ids: set = set()

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Temperature markets have low 24h volume and appear at offset 1000-2000.
            # Scan all pages up to 2500 entries.
            for offset in range(0, 2500, 500):
                try:
                    response = await client.get(
                        "https://gamma-api.polymarket.com/markets",
                        params={
                            "closed": "false",
                            "active": "true",
                            "limit": 500,
                            "offset": offset,
                            "order": "volume24hr",
                            "ascending": "false",
                        }
                    )
                    response.raise_for_status()
                    batch = response.json()
                    if not isinstance(batch, list) or not batch:
                        break

                    for market_data in batch:
                        question = market_data.get("question", "")
                        if "temperature" not in question.lower():
                            continue

                        market = _parse_polymarket_weather(market_data, city_keys)
                        if market and market.market_id not in seen_ids:
                            markets.append(market)
                            seen_ids.add(market.market_id)

                except Exception as e:
                    logger.debug(f"Weather market fetch at offset {offset} failed: {e}")
                    break

    except Exception as e:
        logger.warning(f"Failed to fetch weather markets: {e}")

    logger.info(f"Found {len(markets)} weather temperature markets on Polymarket")
    return markets


def _parse_polymarket_weather(
    market_data: dict,
    city_keys: Optional[List[str]] = None,
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
    outcome_prices = market_data.get("outcomePrices", [])
    if isinstance(outcome_prices, str):
        import json
        try:
            outcome_prices = json.loads(outcome_prices)
        except Exception:
            outcome_prices = []

    if not outcome_prices or len(outcome_prices) < 2:
        return None

    try:
        yes_price = float(outcome_prices[0])
        no_price = float(outcome_prices[1])
    except (ValueError, IndexError):
        return None

    # Skip resolved or near-resolved markets
    if market_data.get("closed", False):
        return None
    if yes_price > 0.97 or yes_price < 0.03:
        return None

    # Skip markets not accepting orders
    if not market_data.get("acceptingOrders", True):
        return None

    volume = float(market_data.get("volume", 0) or 0)

    # Extract CLOB token IDs for real order placement
    clob_token_ids = market_data.get("clobTokenIds", [])
    if isinstance(clob_token_ids, str):
        import json as _json
        try:
            clob_token_ids = _json.loads(clob_token_ids)
        except Exception:
            clob_token_ids = []
    yes_token_id = clob_token_ids[0] if len(clob_token_ids) > 0 else None
    no_token_id = clob_token_ids[1] if len(clob_token_ids) > 1 else None

    event_slug = ""
    events = market_data.get("events", [])
    if events and isinstance(events, list):
        event_slug = events[0].get("slug", "") if events else ""

    return WeatherMarket(
        slug=event_slug or market_data.get("slug", ""),
        market_id=str(market_data.get("id", "")),
        platform="polymarket",
        title=question,
        city_key=parsed["city_key"],
        city_name=parsed["city_name"],
        target_date=parsed["target_date"],
        threshold_f=parsed["threshold_f"],
        threshold_f_low=parsed.get("threshold_f_low"),
        metric=parsed["metric"],
        direction=parsed["direction"],
        yes_price=yes_price,
        no_price=no_price,
        volume=volume,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
    )
