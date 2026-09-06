"""The weather slate is fetched concurrently, and politely.

/api/dashboard took 104-108 SECONDS against the live upstream. The cause was
serialization at two levels, neither of them necessary:

  1. `_parse_polymarket_weather` awaited five independent lookups one after
     another -- yes book, no book, midpoint, last price, recent trades -- for
     every market.
  2. The caller awaited `_parse_polymarket_weather` once per market, inside a
     loop over events, inside a loop over search queries.

With ~99 markets that is ~495 sequential round trips. Nothing about them is
ordered: every one is a read keyed off a market that is already in hand.

These tests assert overlap rather than elapsed time. A duration assertion on a
network-shaped workload is a flake generator, and it would also pass for a
version that got fast by dropping data. Each fake records how many calls are
in flight at once, so "did these actually run together" is measured directly.

The bound matters as much as the parallelism: unbounded fan-out would put ~500
requests at Polymarket at once, and the client swallows failures and returns
None, so a rate-limited run would quietly produce a slate with missing prices
rather than an error.
"""

import asyncio
from datetime import date, timedelta

import pytest

from backend.data import weather_markets
from backend.data.weather_markets import (
    MAX_CONCURRENT_MARKET_FETCHES,
    _parse_polymarket_weather,
    fetch_polymarket_weather_markets,
)


class Tracker:
    """Records how many fake calls overlap."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.peak = 0
        self.calls = 0

    async def slot(self, delay: float = 0.02):
        self.calls += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(delay)
        finally:
            self.in_flight -= 1


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


BOOK = {"bids": [{"price": "0.43", "size": "7"}], "asks": [{"price": "0.46", "size": "8.25"}]}


def market(index: int) -> dict:
    """A market the real parser accepts, with distinct tokens per outcome.

    The date in the title is load-bearing: without it the parser returns None
    and every assertion below would pass against nothing.
    """
    target = date.today() + timedelta(days=2)
    when = f"{target.strftime('%B')} {target.day}"
    return {
        "id": f"mkt-{index}",
        "question": (
            f"Will the highest temperature in Hong Kong be {20 + index}°C "
            f"or above on {when}?"
        ),
        "outcomePrices": '["0.55", "0.45"]',
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": f'["yes-token-{index}", "no-token-{index}"]',
        "closed": False,
        "endDate": target.isoformat(),
    }


class FakeAsyncClient:
    """Dispatches on URL; every call is recorded by the tracker."""

    def __init__(self, tracker: Tracker, markets: list[dict]):
        self.tracker = tracker
        self.markets = markets

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str, params=None, **kwargs):
        await self.tracker.slot()
        if "public-search" in url:
            return FakeResponse({"events": [{"slug": "slate", "markets": self.markets}]})
        if url.endswith("/events"):
            return FakeResponse([])
        if "/book" in url:
            return FakeResponse(BOOK)
        return FakeResponse({})


class FakePolymarketClient:
    def __init__(self, tracker: Tracker, **kwargs):
        self.tracker = tracker

    async def fetch_midpoint(self, token_id):
        await self.tracker.slot()
        return 0.44

    async def fetch_price(self, token_id):
        await self.tracker.slot()
        return 0.45

    async def fetch_trades(self, **kwargs):
        await self.tracker.slot()
        return []


# --- level 1: the five lookups for one market -------------------------------


def test_the_five_lookups_for_one_market_overlap():
    tracker = Tracker()
    result = asyncio.run(
        _parse_polymarket_weather(
            market(1), "slate", None, {}, FakeAsyncClient(tracker, []), FakePolymarketClient(tracker)
        )
    )

    assert result is not None, "the fixture no longer parses; the test would be vacuous"
    assert tracker.calls == 5, f"expected 5 lookups per market, saw {tracker.calls}"
    assert tracker.peak > 1, "the five independent lookups still run one at a time"


def test_one_market_still_produces_the_same_fields():
    """Concurrency must not change what is returned."""
    tracker = Tracker()
    result = asyncio.run(
        _parse_polymarket_weather(
            market(1), "slate", None, {}, FakeAsyncClient(tracker, []), FakePolymarketClient(tracker)
        )
    )

    assert result.best_bid == 0.43
    assert result.best_ask == 0.46
    assert result.top_ask_size == 8.25
    assert result.yes_midpoint == 0.44
    assert result.yes_last_price == 0.45


# --- level 2: markets across the slate --------------------------------------


@pytest.fixture
def patched(monkeypatch):
    tracker = Tracker()
    markets = [market(i) for i in range(12)]
    monkeypatch.setattr(
        weather_markets, "httpx", type("m", (), {"AsyncClient": lambda *a, **k: FakeAsyncClient(tracker, markets)})
    )
    monkeypatch.setattr(
        weather_markets, "PolymarketClient", lambda *a, **k: FakePolymarketClient(tracker)
    )
    return tracker, markets


def test_markets_across_the_slate_are_fetched_concurrently(patched):
    tracker, markets = patched

    asyncio.run(fetch_polymarket_weather_markets())

    assert tracker.peak > 5, (
        f"peak overlap was {tracker.peak}; the slate is still being walked serially"
    )


def test_concurrency_is_bounded(patched):
    """Unbounded fan-out would put hundreds of requests at the upstream at once."""
    tracker, markets = patched

    asyncio.run(fetch_polymarket_weather_markets())

    ceiling = MAX_CONCURRENT_MARKET_FETCHES * 5
    assert tracker.peak <= ceiling, (
        f"peak overlap {tracker.peak} exceeds {MAX_CONCURRENT_MARKET_FETCHES} markets "
        f"x 5 lookups = {ceiling}"
    )


def test_every_market_is_still_returned_and_deduplicated(patched):
    tracker, markets = patched

    result = asyncio.run(fetch_polymarket_weather_markets())

    returned = [m.market_id for m in result]
    assert sorted(returned) == sorted(m["id"] for m in markets)
    assert len(returned) == len(set(returned)), "concurrency broke the dedup"


def test_one_failing_market_does_not_lose_the_others(patched, monkeypatch):
    """gather must not let a single bad market take down the slate."""
    tracker, markets = patched
    real = weather_markets._parse_polymarket_weather

    async def sometimes_explodes(market_data, *args, **kwargs):
        if market_data.get("id") == "mkt-3":
            raise RuntimeError("upstream said no")
        return await real(market_data, *args, **kwargs)

    monkeypatch.setattr(weather_markets, "_parse_polymarket_weather", sometimes_explodes)

    result = asyncio.run(fetch_polymarket_weather_markets())

    returned = {m.market_id for m in result}
    assert "mkt-3" not in returned
    assert len(returned) == len(markets) - 1, "one failure discarded more than its own market"
