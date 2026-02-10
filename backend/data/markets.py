"""Market data fetchers for Kalshi and Polymarket."""
import httpx
import re
import json
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass
import asyncio


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
    Fetch Kalshi market data from public sources.
    Note: Full API requires auth, but we can scrape public data.
    """
    # For simulation, we'll generate realistic mock data based on real market structures
    # In production, you'd use authenticated Kalshi API

    markets = []

    # Known Kalshi weather market structure
    cities = ["nyc", "chicago", "miami", "austin"]
    today = datetime.now()

    for city in cities:
        # Kalshi typically offers bracket markets for temperature
        # e.g., "High temp 40-44°F", "High temp 45-49°F", etc.
        base_temps = [30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]

        for i, temp in enumerate(base_temps[:-1]):
            upper = base_temps[i + 1]

            # Simulate realistic prices based on typical weather
            # This would be replaced with real API data
            markets.append(MarketData(
                platform="kalshi",
                ticker=f"KXHIGH{city.upper()}-{today.strftime('%y%b%d').upper()}-T{temp}",
                title=f"Highest temperature in {city.upper()} today {temp}-{upper}°F",
                category="weather",
                subcategory=city,
                yes_price=0.15,  # Placeholder - real data from API
                no_price=0.85,
                volume=10000,
                settlement_time=today.replace(hour=23, minute=59),
                threshold=float(temp),
                direction="above"
            ))

    return markets


async def fetch_all_weather_markets() -> List[MarketData]:
    """Fetch weather markets from all platforms."""
    polymarket_task = fetch_polymarket_weather_markets()
    kalshi_task = fetch_kalshi_markets_public()

    polymarket_markets, kalshi_markets = await asyncio.gather(
        polymarket_task, kalshi_task
    )

    return polymarket_markets + kalshi_markets


# Quick test
if __name__ == "__main__":
    async def test():
        markets = await fetch_polymarket_weather_markets()
        print(f"Found {len(markets)} Polymarket weather markets")
        for m in markets[:5]:
            print(f"  {m.title[:60]}... - ${m.volume:,.0f} volume")

    asyncio.run(test())
