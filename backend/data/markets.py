"""Market data fetchers for Kalshi and Polymarket."""
import httpx
import re
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Set
from dataclasses import dataclass
import asyncio

from backend.core.classifier import classify_market, is_sports_market, MarketCategory

logger = logging.getLogger(__name__)


@dataclass
class MarketData:
    """Structured market data."""
    platform: str
    ticker: str
    title: str
    category: str
    subcategory: Optional[str]  # city name for weather, series for econ

    yes_price: float  # 0-1
    no_price: float
    volume: float
    settlement_time: Optional[datetime]

    # Parsed from title
    threshold: Optional[float] = None
    direction: Optional[str] = None  # "above" or "below"

    # For Polymarket URL generation
    event_slug: Optional[str] = None


def parse_weather_market(title: str) -> Dict:
    """
    Parse weather market title to extract city, threshold, direction.

    Examples:
    - "Highest temperature in NYC on February 10?" -> NYC, high temp market
    - "Will NYC high exceed 45°F tomorrow?" -> NYC, 45, above
    """
    result = {
        "category": "weather",
        "subcategory": None,
        "threshold": None,
        "direction": None
    }

    # City patterns
    city_patterns = {
        "nyc": ["nyc", "new york", "manhattan"],
        "chicago": ["chicago"],
        "miami": ["miami"],
        "austin": ["austin"],
        "los_angeles": ["los angeles", "la", "l.a."],
        "atlanta": ["atlanta"],
        "denver": ["denver"],
        "seattle": ["seattle"],
        "dallas": ["dallas"],
        "boston": ["boston"],
        "london": ["london"],
        "seoul": ["seoul"],
        "buenos_aires": ["buenos aires"],
    }

    title_lower = title.lower()

    # Find city
    for city_key, patterns in city_patterns.items():
        for pattern in patterns:
            if pattern in title_lower:
                result["subcategory"] = city_key
                break
        if result["subcategory"]:
            break

    # Find temperature threshold
    temp_match = re.search(r'(\d+)\s*°?[fF]', title)
    if temp_match:
        result["threshold"] = float(temp_match.group(1))

    # Find direction
    if any(word in title_lower for word in ["above", "exceed", "over", "higher than", "warmer"]):
        result["direction"] = "above"
    elif any(word in title_lower for word in ["below", "under", "lower than", "colder", "cooler"]):
        result["direction"] = "below"

    return result


async def fetch_polymarket_weather_markets() -> List[MarketData]:
    """Fetch active weather markets from Polymarket."""
    url = "https://gamma-api.polymarket.com/events"
    params = {
        "active": "true",
        "closed": "false",
        "limit": 100
    }

    markets = []

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            events = response.json()

            logger.info(f"Polymarket returned {len(events)} events")

            for event in events:
                title = event.get("title", "")
                title_lower = title.lower()
                event_slug = event.get("slug", "")  # Capture event slug for URLs

                # Check if it's a weather/temperature market
                is_weather = any(kw in title_lower for kw in [
                    "temperature", "temp", "weather", "highest temp", "high temp",
                    "°f", "°c", "degrees"
                ])

                if not is_weather:
                    continue

                logger.debug(f"Found weather event: {title[:60]}...")

                # Get markets within this event
                event_markets = event.get("markets", [])
                for market in event_markets:
                    parsed = parse_weather_market(market.get("question", title))

                    # Parse prices safely (no eval!)
                    outcome_prices = market.get("outcomePrices", "")
                    yes_price = 0.5
                    if outcome_prices:
                        try:
                            # Use json.loads instead of dangerous eval()
                            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                            if isinstance(prices, list) and len(prices) >= 1:
                                yes_price = float(prices[0])
                        except (json.JSONDecodeError, ValueError, TypeError) as e:
                            print(f"Price parse error for {market.get('id', 'unknown')}: {e}")

                    markets.append(MarketData(
                        platform="polymarket",
                        ticker=market.get("id", ""),
                        title=market.get("question", title),
                        category="weather",
                        subcategory=parsed.get("subcategory"),
                        yes_price=yes_price,
                        no_price=1 - yes_price,
                        volume=float(market.get("volume", 0) or 0),
                        settlement_time=None,  # Parse from endDate if available
                        threshold=parsed.get("threshold"),
                        direction=parsed.get("direction"),
                        event_slug=event_slug  # For URL generation
                    ))

        except Exception as e:
            print(f"Polymarket fetch error: {e}")

    return markets


async def fetch_kalshi_markets_public() -> List[MarketData]:
    """
    Fetch Kalshi market data.

    Note: Kalshi requires authenticated API access.
    To enable real Kalshi markets, add KALSHI_API_KEY and KALSHI_API_SECRET to .env
    and implement their API: https://trading-api.readme.io/reference/getting-started

    Currently returns empty list - only Polymarket data is used.
    """
    # Kalshi requires API authentication - return empty for now
    # Real implementation would use: https://trading-api.kalshi.com/trade-api/v2/markets
    return []


async def fetch_all_weather_markets() -> List[MarketData]:
    """Fetch weather markets from all platforms."""
    polymarket_task = fetch_polymarket_weather_markets()
    kalshi_task = fetch_kalshi_markets_public()

    polymarket_markets, kalshi_markets = await asyncio.gather(
        polymarket_task, kalshi_task
    )

    return polymarket_markets + kalshi_markets


async def fetch_polymarket_markets(
    categories: Optional[Set[str]] = None,
    exclude_sports: bool = True,
    limit: int = 200
) -> List[MarketData]:
    """
    Fetch markets from Polymarket with category filtering.

    Args:
        categories: Set of categories to include (None = all except sports)
        exclude_sports: Whether to exclude sports markets
        limit: Maximum events to fetch

    Returns:
        List of MarketData for matching markets
    """
    url = "https://gamma-api.polymarket.com/events"
    params = {
        "active": "true",
        "closed": "false",
        "limit": limit
    }

    markets = []

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            events = response.json()

            for event in events:
                title = event.get("title", "")
                event_slug = event.get("slug", "")

                # Skip sports if excluded
                if exclude_sports and is_sports_market(title):
                    continue

                # Classify the market
                category, confidence = classify_market(title)

                # Filter by requested categories
                if categories and category.value not in categories:
                    continue

                # Get markets within this event
                event_markets = event.get("markets", [])
                for market in event_markets:
                    market_title = market.get("question", title)

                    # Parse weather details if applicable
                    parsed = {}
                    if category == MarketCategory.WEATHER:
                        parsed = parse_weather_market(market_title)

                    # Parse prices safely
                    outcome_prices = market.get("outcomePrices", "")
                    yes_price = 0.5
                    if outcome_prices:
                        try:
                            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                            if isinstance(prices, list) and len(prices) >= 1:
                                yes_price = float(prices[0])
                        except (json.JSONDecodeError, ValueError, TypeError) as e:
                            logger.debug(f"Price parse error for {market.get('id', 'unknown')}: {e}")

                    markets.append(MarketData(
                        platform="polymarket",
                        ticker=market.get("id", ""),
                        title=market_title,
                        category=category.value,
                        subcategory=parsed.get("subcategory"),
                        yes_price=yes_price,
                        no_price=1 - yes_price,
                        volume=float(market.get("volume", 0) or 0),
                        settlement_time=None,
                        threshold=parsed.get("threshold"),
                        direction=parsed.get("direction"),
                        event_slug=event_slug
                    ))

        except Exception as e:
            logger.error(f"Polymarket fetch error: {e}")

    logger.info(f"Fetched {len(markets)} Polymarket markets")
    return markets


async def fetch_all_markets(
    categories: Optional[Set[str]] = None,
    exclude_sports: bool = True
) -> List[MarketData]:
    """
    Fetch markets from all platforms.

    Args:
        categories: Set of categories to include (e.g., {"weather", "crypto"})
        exclude_sports: Whether to exclude sports markets (default True)

    Returns:
        Combined list of markets from all platforms
    """
    # Default categories from config
    if categories is None:
        from backend.config import settings
        categories = set(settings.ENABLED_CATEGORIES)

    # Fetch from all platforms in parallel
    polymarket_task = fetch_polymarket_markets(categories, exclude_sports)
    kalshi_task = fetch_kalshi_markets_public()

    polymarket_markets, kalshi_markets = await asyncio.gather(
        polymarket_task, kalshi_task
    )

    # Filter Kalshi markets by category too
    if categories:
        kalshi_markets = [m for m in kalshi_markets if m.category in categories]

    all_markets = polymarket_markets + kalshi_markets
    logger.info(f"Total markets fetched: {len(all_markets)} (Polymarket: {len(polymarket_markets)}, Kalshi: {len(kalshi_markets)})")

    return all_markets


# Quick test
if __name__ == "__main__":
    async def test():
        # Test multi-category fetch
        print("Fetching all markets (excluding sports)...")
        markets = await fetch_polymarket_markets(exclude_sports=True)
        print(f"Found {len(markets)} Polymarket markets")

        # Group by category
        by_category: Dict[str, List[MarketData]] = {}
        for m in markets:
            if m.category not in by_category:
                by_category[m.category] = []
            by_category[m.category].append(m)

        for cat, cat_markets in by_category.items():
            print(f"\n{cat.upper()} ({len(cat_markets)} markets):")
            for m in cat_markets[:3]:
                print(f"  {m.title[:60]}... - ${m.volume:,.0f}")

    asyncio.run(test())
