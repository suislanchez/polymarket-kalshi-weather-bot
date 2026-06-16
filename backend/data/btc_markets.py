"""BTC 5-minute market fetcher for Polymarket."""
import httpx
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional, List, Any
from dataclasses import dataclass

from backend.core.btc_methodology import CHAINLINK_BTC_USD_FEED_ID
from backend.data.polymarket_client import PolymarketClient

logger = logging.getLogger("trading_bot")

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
SERIES_SLUG = "btc-up-or-down-5m"

# Strict regex: only match real BTC 5-min window slugs (e.g. btc-updown-5m-1708531200)
_BTC_SLUG_RE = re.compile(r"^btc-updown-5m-\d{10}$")


def is_valid_btc_slug(slug: str) -> bool:
    """Return True only if slug matches the exact BTC 5-min pattern."""
    return bool(_BTC_SLUG_RE.match(slug))


@dataclass
class BtcBookTop:
    """Top-of-book depth for one BTC Up/Down outcome token."""
    token_id: str
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    best_bid_size: Optional[float] = None
    best_ask_size: Optional[float] = None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return round(self.best_ask - self.best_bid, 6)


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
    up_token_id: Optional[str] = None
    down_token_id: Optional[str] = None
    up_bid: Optional[float] = None
    up_ask: Optional[float] = None
    up_ask_size: Optional[float] = None
    down_bid: Optional[float] = None
    down_ask: Optional[float] = None
    down_ask_size: Optional[float] = None
    up_midpoint: Optional[float] = None
    down_midpoint: Optional[float] = None
    up_last_price: Optional[float] = None
    down_last_price: Optional[float] = None
    recent_trades_count: int = 0
    settlement_source: str = "unknown"
    settlement_url: Optional[str] = None
    chainlink_feed_id: Optional[str] = None
    chainlink_capture_method: Optional[str] = None
    chainlink_source_url: Optional[str] = None
    chainlink_start_price: Optional[float] = None
    chainlink_end_price: Optional[float] = None
    chainlink_start_observed_at: Optional[int] = None
    chainlink_end_observed_at: Optional[int] = None
    chainlink_start_source_snapshot_path: Optional[str] = None
    chainlink_end_source_snapshot_path: Optional[str] = None

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
    where timestamp is the START of the 5-min window.
    """
    now = time.time()
    current_boundary = _round_to_5min(now)

    # The current window starts at the current boundary; include current and
    # upcoming windows. Polymarket BTC 5m slug suffixes are window starts.

    slugs = []
    for i in range(count):
        start_ts = current_boundary + (i * 300)
        slugs.append(f"btc-updown-5m-{start_ts}")

    return slugs


def _parse_json_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _detect_settlement_source(*texts: Optional[str]) -> tuple[str, Optional[str]]:
    combined = "\n".join(t for t in texts if t).lower()
    if "chainlink" in combined and "btc" in combined:
        return "Chainlink BTC/USD", "https://data.chain.link/streams/btc-usd"
    return "unknown", None


def _book_top_from_rows(token_id: str, book: dict) -> BtcBookTop:
    def as_float(row: Optional[dict], field: str) -> Optional[float]:
        if not row:
            return None
        try:
            return float(row[field])
        except (KeyError, TypeError, ValueError):
            return None

    bids = [r for r in (book.get("bids") or []) if as_float(r, "price") is not None]
    asks = [r for r in (book.get("asks") or []) if as_float(r, "price") is not None]
    best_bid = max(bids, key=lambda r: as_float(r, "price")) if bids else None
    best_ask = min(asks, key=lambda r: as_float(r, "price")) if asks else None
    return BtcBookTop(
        token_id=token_id,
        best_bid=as_float(best_bid, "price"),
        best_ask=as_float(best_ask, "price"),
        best_bid_size=as_float(best_bid, "size"),
        best_ask_size=as_float(best_ask, "size"),
    )


async def _fetch_clob_book_top(client: httpx.AsyncClient, token_id: Optional[str]) -> Optional[BtcBookTop]:
    if not token_id:
        return None
    try:
        response = await client.get(f"{CLOB_API}/book", params={"token_id": token_id})
        response.raise_for_status()
        return _book_top_from_rows(token_id, response.json())
    except Exception as e:
        logger.debug(f"Failed to fetch BTC CLOB book for token {token_id}: {e}")
        return None


async def _enrich_btc_market_books(
    client: httpx.AsyncClient,
    market: BtcMarket,
    pm_client: Optional[PolymarketClient] = None,
) -> BtcMarket:
    up_book = await _fetch_clob_book_top(client, market.up_token_id)
    down_book = await _fetch_clob_book_top(client, market.down_token_id)

    if up_book:
        market.up_bid = up_book.best_bid
        market.up_ask = up_book.best_ask
        market.up_ask_size = up_book.best_ask_size
    if down_book:
        market.down_bid = down_book.best_bid
        market.down_ask = down_book.best_ask
        market.down_ask_size = down_book.best_ask_size

    if pm_client is not None:
        market.up_midpoint = await pm_client.fetch_midpoint(market.up_token_id)
        market.down_midpoint = await pm_client.fetch_midpoint(market.down_token_id)
        market.up_last_price = await pm_client.fetch_price(market.up_token_id)
        market.down_last_price = await pm_client.fetch_price(market.down_token_id)
        if market.market_id:
            market.recent_trades_count = len(
                await pm_client.fetch_trades(market=market.market_id, limit=200)
            )

    return market


def _parse_event_to_btc_market(event: dict) -> Optional[BtcMarket]:
    """Parse a Polymarket event into a BtcMarket."""
    markets = event.get("markets", [])
    if not markets:
        return None

    market = markets[0]

    outcomes = [str(o).lower() for o in _parse_json_list(market.get("outcomes"))]
    token_ids = [str(t) for t in _parse_json_list(market.get("clobTokenIds"))]
    up_token_id: Optional[str] = None
    down_token_id: Optional[str] = None
    for idx, outcome in enumerate(outcomes):
        if idx >= len(token_ids):
            continue
        if "up" in outcome:
            up_token_id = token_ids[idx]
        elif "down" in outcome:
            down_token_id = token_ids[idx]
    if not up_token_id and len(token_ids) >= 1:
        up_token_id = token_ids[0]
    if not down_token_id and len(token_ids) >= 2:
        down_token_id = token_ids[1]

    settlement_source, settlement_url = _detect_settlement_source(
        event.get("description"),
        event.get("rules"),
        market.get("description"),
        market.get("rules"),
        market.get("resolutionSource"),
    )

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

    # Parse timestamps.  Gamma occasionally omits event date fields in fallback
    # responses; BTC 5m slugs encode the window start, so preserve exact
    # boundaries from the slug rather than defaulting to scrape time.
    slug = event.get("slug", "")
    start_str = event.get("startDate") or market.get("startDate")
    end_str = event.get("endDate") or market.get("endDate")

    slug_start_ts: Optional[int] = None
    if is_valid_btc_slug(slug):
        try:
            slug_start_ts = int(slug.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            slug_start_ts = None

    if slug_start_ts is not None:
        window_start = datetime.fromtimestamp(slug_start_ts, tz=timezone.utc)
        window_end = datetime.fromtimestamp(slug_start_ts + 300, tz=timezone.utc)
    else:
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
        up_token_id=up_token_id,
        down_token_id=down_token_id,
        settlement_source=settlement_source,
        settlement_url=settlement_url,
        chainlink_feed_id=CHAINLINK_BTC_USD_FEED_ID if settlement_source == "Chainlink BTC/USD" else None,
        chainlink_capture_method="chainlink_data_streams_rest" if settlement_source == "Chainlink BTC/USD" else None,
        chainlink_source_url=settlement_url if settlement_source == "Chainlink BTC/USD" else None,
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

            pm_client = PolymarketClient(client=client)  # type: ignore[arg-type]
            event = events[0] if isinstance(events, list) else events
            market = _parse_event_to_btc_market(event)
            if market:
                market = await _enrich_btc_market_books(client, market, pm_client)
            return market

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
            pm_client = PolymarketClient(client=client)  # type: ignore[arg-type]
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
                    market = await _enrich_btc_market_books(client, market, pm_client)
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

            pm_client = PolymarketClient(client=client)  # type: ignore[arg-type]
            event = events[0] if isinstance(events, list) else events
            market = _parse_event_to_btc_market(event)
            if market:
                market = await _enrich_btc_market_books(client, market, pm_client)
            return market

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
