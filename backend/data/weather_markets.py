"""Weather temperature market fetcher from Polymarket.

Polymarket lists "highest temperature" markets as negRisk ladders: one
event per city+date (e.g. "Highest temperature in Miami on August 31?")
containing ~10-11 mutually exclusive bracket markets ("79F or below",
"80-81F", ..., "98F or higher"). Verified live 2026-09-01 against the
Gamma API.
"""
import httpx
import re
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple

logger = logging.getLogger("trading_bot")

# Map city names/variants found in event titles to our city keys.
# Longest alias first so "new york city" matches before "new york".
CITY_ALIASES = {
    "new york city": "nyc",
    "new york": "nyc",
    "nyc": "nyc",
    "chicago": "chicago",
    "miami": "miami",
    "los angeles": "los_angeles",
    "la": "los_angeles",
    "denver": "denver",
}

# Month name to number
MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "Highest temperature in {City} on {Date}?" - the event-level title.
_EVENT_TITLE_RE = re.compile(r'highest temperature in\s+(.+?)\s+on\s+(.+?)\??$', re.IGNORECASE)

# Bracket forms found in a market's groupItemTitle, e.g. "79°F or below",
# "80-81°F", "98°F or higher".
_BELOW_RE = re.compile(r'(\d+)\s*°?\s*f\s*or\s*below', re.IGNORECASE)
_ABOVE_RE = re.compile(r'(\d+)\s*°?\s*f\s*or\s*higher', re.IGNORECASE)
_RANGE_RE = re.compile(r'(\d+)\s*-\s*(\d+)\s*°?\s*f', re.IGNORECASE)


@dataclass
class WeatherMarket:
    """A weather temperature prediction market (one bracket of a ladder)."""
    slug: str
    market_id: str
    platform: str
    title: str
    city_key: str
    city_name: str
    target_date: date
    threshold_f: float       # Temperature threshold in Fahrenheit
    metric: str              # "high" or "low"
    direction: str           # "above", "below", or "between" (range bracket)
    yes_price: float         # Price of YES outcome (0-1)
    no_price: float          # Price of NO outcome (0-1)
    volume: float = 0.0
    closed: bool = False
    # Upper bound of the bracket, only set when direction == "between"
    # (e.g. threshold_f=80, threshold_high_f=81 for the "80-81F" bracket).
    threshold_high_f: Optional[float] = None


def _match_city(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Match a city name fragment (from an event title) to our city keys."""
    text_lower = text.lower().strip()
    for alias, key in sorted(CITY_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in text_lower:
            from backend.data.weather import CITY_CONFIG
            return key, CITY_CONFIG[key]["name"]
    return None, None


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


def _parse_bracket(label: str) -> Optional[dict]:
    """Parse a ladder bracket label ("79°F or below" / "80-81°F" /
    "98°F or higher") into a threshold/direction pair."""
    match = _BELOW_RE.search(label)
    if match:
        return {"direction": "below", "threshold_f": float(match.group(1)), "threshold_high_f": None}

    match = _ABOVE_RE.search(label)
    if match:
        return {"direction": "above", "threshold_f": float(match.group(1)), "threshold_high_f": None}

    match = _RANGE_RE.search(label)
    if match:
        lo, hi = float(match.group(1)), float(match.group(2))
        return {"direction": "between", "threshold_f": lo, "threshold_high_f": hi}

    return None


async def fetch_polymarket_weather_markets(city_keys: Optional[List[str]] = None) -> List[WeatherMarket]:
    """
    Fetch "highest temperature" ladder markets from Polymarket.

    Uses tag_slug=highest-temperature - the only query parameter that
    actually filters this endpoint (verified live 2026-09-01: tag=Weather
    and slug_contains=weather/temperature/temp- are silently ignored by
    Gamma API, which just returns its unfiltered default event feed for
    those - that's why this fetcher previously always found 0 markets).
    Paginated via offset since the endpoint caps at 100 events/page.
    """
    markets: List[WeatherMarket] = []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            offset = 0
            while offset < 1000:  # safety cap, well above the current ~150 total events
                response = await client.get(
                    "https://gamma-api.polymarket.com/events",
                    params={
                        "tag_slug": "highest-temperature",
                        "closed": "false",
                        "limit": 100,
                        "offset": offset,
                    },
                )
                response.raise_for_status()
                events = response.json()
                if not events:
                    break

                for event in events:
                    markets.extend(_parse_weather_event(event, city_keys))

                if len(events) < 100:
                    break
                offset += 100

    except Exception as e:
        logger.warning(f"Failed to fetch weather markets: {e}")

    logger.info(f"Found {len(markets)} weather temperature markets")
    return markets


def _parse_weather_event(event: dict, city_keys: Optional[List[str]]) -> List[WeatherMarket]:
    """Parse one "highest temperature" ladder event into its bracket markets."""
    event_title = event.get("title", "") or ""
    event_slug = event.get("slug", "")

    match = _EVENT_TITLE_RE.search(event_title)
    if not match:
        return []

    city_key, city_name = _match_city(match.group(1))
    if not city_key:
        return []
    if city_keys and city_key not in city_keys:
        return []

    target_date = _extract_date(match.group(2).lower())
    if not target_date or target_date < date.today():
        return []

    out = []
    for market_data in event.get("markets", []):
        market = _parse_bracket_market(market_data, event_slug, city_key, city_name, target_date)
        if market:
            out.append(market)
    return out


def _parse_bracket_market(
    market_data: dict,
    event_slug: str,
    city_key: str,
    city_name: str,
    target_date: date,
) -> Optional[WeatherMarket]:
    """Parse one bracket market dict (a single row of the ladder) into a WeatherMarket."""
    bracket_label = market_data.get("groupItemTitle", "") or ""
    bracket = _parse_bracket(bracket_label)
    if not bracket:
        return None

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

    # Skip resolved markets
    if market_data.get("closed", False):
        return None
    if yes_price > 0.98 or yes_price < 0.02:
        return None

    volume = float(market_data.get("volume", 0) or 0)
    question = market_data.get("question", "") or bracket_label

    return WeatherMarket(
        slug=event_slug,
        market_id=str(market_data.get("id", "")),
        platform="polymarket",
        title=question,
        city_key=city_key,
        city_name=city_name,
        target_date=target_date,
        threshold_f=bracket["threshold_f"],
        metric="high",
        direction=bracket["direction"],
        yes_price=yes_price,
        no_price=no_price,
        volume=volume,
        threshold_high_f=bracket["threshold_high_f"],
    )
