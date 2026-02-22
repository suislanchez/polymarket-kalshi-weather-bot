"""BTC 5-minute market fetcher for Polymarket."""
import httpx
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional, List
from dataclasses import dataclass

logger = logging.getLogger("trading_bot")

GAMMA_API = "https://gamma-api.polymarket.com"
SERIES_SLUG = "btc-up-or-down-5m"

# Strict regex: only match real BTC 5-min window slugs (e.g. btc-updown-5m-1708531200)
_BTC_SLUG_RE = re.compile(r"^btc-updown-5m-\d{10}$")


def is_valid_btc_slug(slug: str) -> bool:
    """Return True only if slug matches the exact BTC 5-min pattern."""
    return bool(_BTC_SLUG_RE.match(slug))


@dataclass
class BtcMarket:
    """A single BTC 5-minute Up/Down market."""
    slug: str
    market_id: str
    up_price: float
    down_price: float
    window_start: datetime
    window_end: datetime
    volume: float
    closed: bool

    @property
    def event_slug(self) -> str:
        return self.slug

    @property
    def spread(self) -> float:
        return abs(1.0 - self.up_price - self.down_price)

    @property
    def time_until_end(self) -> float:
        """Seconds until this window ends."""
        now = datetime.now(timezone.utc)
        return (self.window_end - now).total_seconds()

    @property
    def is_active(self) -> bool:
        """Window is currently in progress."""
        now = datetime.now(timezone.utc)
        return self.window_start <= now <= self.window_end and not self.closed

    @property
    def is_upcoming(self) -> bool:
        """Window hasn't started yet."""
        now = datetime.now(timezone.utc)
        return now < self.window_start and not self.closed


def _round_to_5min(ts: float) -> int:
    """Round a unix timestamp down to the nearest 5-minute boundary."""
    return int(ts) // 300 * 300


def _compute_window_slugs(count: int = 5) -> List[str]:
    """
    Compute event slugs for the current and upcoming 5-min windows.

    Slug pattern: btc-updown-5m-{unix_timestamp}
    where timestamp is the END of the 5-min window.
    """
    now = time.time()
    current_boundary = _round_to_5min(now)

    # The current window ends at the next boundary
    next_boundary = current_boundary + 300

    slugs = []
    for i in range(count):
        end_ts = next_boundary + (i * 300)
        slugs.append(f"btc-updown-5m-{end_ts}")

    return slugs


def _parse_event_to_btc_market(event: dict) -> Optional[BtcMarket]:
    """Parse a Polymarket event into a BtcMarket."""
    markets = event.get("markets", [])
    if not markets:
        return None

    market = markets[0]

    # Parse outcome prices
    outcome_prices = market.get("outcomePrices", "")
    up_price = 0.5
    down_price = 0.5
    if outcome_prices:
        try:
            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            if isinstance(prices, list) and len(prices) >= 2:
                up_price = float(prices[0])
                down_price = float(prices[1])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Parse timestamps
    slug = event.get("slug", "")
    start_str = event.get("startDate") or market.get("startDate")
    end_str = event.get("endDate") or market.get("endDate")

    window_start = datetime.now(timezone.utc)
    window_end = datetime.now(timezone.utc)

    if start_str:
        try:
            window_start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

    if end_str:
        try:
            window_end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

    return BtcMarket(
        slug=slug,
        market_id=str(market.get("id", "")),
        up_price=up_price,
        down_price=down_price,
        window_start=window_start,
        window_end=window_end,
        volume=float(market.get("volume", 0) or 0),
        closed=bool(market.get("closed", False) or event.get("closed", False)),
    )


async def fetch_btc_market_by_slug(slug: str) -> Optional[BtcMarket]:
    """Fetch a single BTC 5-min market by its event slug."""
    if not is_valid_btc_slug(slug):
        logger.debug(f"Rejected invalid BTC slug: {slug}")
        return None

    url = f"{GAMMA_API}/events"
    params = {"slug": slug}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            events = response.json()

            if not events:
                return None

            event = events[0] if isinstance(events, list) else events
            return _parse_event_to_btc_market(event)

        except Exception as e:
            logger.debug(f"Failed to fetch BTC market {slug}: {e}")
            return None


async def fetch_active_btc_markets() -> List[BtcMarket]:
    """
    Fetch current and upcoming BTC 5-min markets from Polymarket.

    Strategy: compute expected slugs from current time and fetch them,
    plus do a series search as fallback.
    """
    markets: List[BtcMarket] = []
    seen_slugs = set()

    # Method 1: Compute expected slugs and fetch directly
    expected_slugs = _compute_window_slugs(count=6)
    for slug in expected_slugs:
        market = await fetch_btc_market_by_slug(slug)
        if market and market.slug not in seen_slugs:
            seen_slugs.add(market.slug)
            markets.append(market)

    # Method 2: Search by series as fallback/supplement
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{GAMMA_API}/events",
                params={
                    "active": "true",
                    "closed": "false",
                    "slug_contains": "btc-updown-5m",
                    "limit": 20,
                }
            )
            response.raise_for_status()
            events = response.json()

            for event in events:
                market = _parse_event_to_btc_market(event)
                if market and market.slug not in seen_slugs and is_valid_btc_slug(market.slug):
                    seen_slugs.add(market.slug)
                    markets.append(market)

    except Exception as e:
        logger.debug(f"BTC series search fallback failed: {e}")

    # Sort by window end time (soonest first)
    markets.sort(key=lambda m: m.window_end)

    # Filter out already-closed markets
    markets = [m for m in markets if not m.closed]

    logger.info(f"Fetched {len(markets)} active BTC 5-min markets")
    return markets


async def fetch_btc_market_for_settlement(slug: str) -> Optional[BtcMarket]:
    """
    Fetch a BTC market for settlement purposes (includes closed markets).
    """
    url = f"{GAMMA_API}/events"
    params = {"slug": slug}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            events = response.json()

            if not events:
                return None

            event = events[0] if isinstance(events, list) else events
            return _parse_event_to_btc_market(event)

        except Exception as e:
            logger.warning(f"Failed to fetch BTC market for settlement {slug}: {e}")
            return None


if __name__ == "__main__":
    import asyncio

    async def test():
        print("Fetching active BTC 5-min markets...")
        markets = await fetch_active_btc_markets()
        print(f"Found {len(markets)} markets")

        for m in markets:
            print(f"\n  {m.slug}")
            print(f"  Up: {m.up_price:.2%} | Down: {m.down_price:.2%}")
            print(f"  Window: {m.window_start} -> {m.window_end}")
            print(f"  Volume: ${m.volume:,.0f}")
            print(f"  Active: {m.is_active} | Upcoming: {m.is_upcoming}")

    asyncio.run(test())
