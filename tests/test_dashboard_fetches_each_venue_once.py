"""The dashboard fetches each weather venue exactly once.

_build_dashboard called scan_for_weather_signals(), which fetched Polymarket
and Kalshi internally, then fetched both AGAIN itself for the divergence panel
-- and it ran every step in sequence. Kalshi is ~11s even parallelised, so the
duplicate alone was a fifth of the cold load.

These tests count calls rather than time elapsed: a duration assertion on a
network-shaped path flakes, and it would also pass for a version that got fast
by fetching nothing.
"""

import asyncio
from datetime import date, timedelta

import pytest

from backend.core import weather_signals as ws
from backend.data import kalshi_markets as km
from backend.data.weather_markets import WeatherMarket


def market(platform: str, index: int) -> WeatherMarket:
    return WeatherMarket(
        slug=f"{platform}-{index}",
        market_id=f"{platform}-{index}",
        platform=platform,
        title=f"{platform} market {index}",
        city_key="nyc",
        city_name="New York City",
        target_date=date.today() + timedelta(days=2),
        threshold_f=80.0,
        metric="high",
        direction="above",
        yes_price=0.5,
        no_price=0.5,
    )


class Counter:
    def __init__(self):
        self.poly = 0
        self.kalshi = 0

    async def fetch_poly(self, city_keys=None):
        self.poly += 1
        return [market("polymarket", 1)]

    async def fetch_kalshi(self, city_keys=None):
        self.kalshi += 1
        return [market("kalshi", 1)]


@pytest.fixture
def counted(monkeypatch):
    counter = Counter()
    monkeypatch.setattr(ws, "fetch_polymarket_weather_markets", counter.fetch_poly)
    # Imported lazily inside scan_for_weather_signals, so patch the source module.
    monkeypatch.setattr(km, "fetch_kalshi_weather_markets", counter.fetch_kalshi)
    monkeypatch.setattr(ws.settings, "KALSHI_ENABLED", True)

    # Keep the scan itself cheap and network-free.
    from backend.core.weather_scan_runtime import ScanRuntimeStats

    async def no_forecasts(markets, fetcher=None, concurrency=1):
        return {}, ScanRuntimeStats(
            market_count=len(markets),
            unique_forecast_keys=0,
            forecast_fetches=0,
            forecast_errors=0,
        )

    monkeypatch.setattr(ws, "prefetch_forecasts", no_forecasts)
    monkeypatch.setattr(ws, "load_venue_reliability_weights_from_ledger", lambda: {})

    async def no_signal(market, forecast=None, venue_reliability=1.0):
        return None

    monkeypatch.setattr(ws, "generate_weather_signal", no_signal)
    return counter


# --- scan_for_weather_signals accepts a pre-fetched slate --------------------


def test_scan_with_prefetched_markets_does_not_refetch(counted):
    slate = [market("polymarket", 9), market("kalshi", 9)]

    asyncio.run(ws.scan_for_weather_signals(markets=slate))

    assert counted.poly == 0, "scan refetched Polymarket despite being handed the slate"
    assert counted.kalshi == 0, "scan refetched Kalshi despite being handed the slate"


def test_scan_without_markets_still_fetches_them(counted):
    """Backward compatibility: the scheduler and three endpoints call it bare."""
    asyncio.run(ws.scan_for_weather_signals())

    assert counted.poly == 1
    assert counted.kalshi == 1


def test_an_empty_prefetched_slate_is_respected_not_treated_as_absent(counted):
    """[] means 'nothing to scan', not 'go and fetch'. None means fetch."""
    asyncio.run(ws.scan_for_weather_signals(markets=[]))

    assert counted.poly == 0
    assert counted.kalshi == 0


# --- the dashboard's weather section ----------------------------------------


def test_the_dashboard_weather_section_fetches_each_venue_exactly_once(counted, monkeypatch):
    from backend.api import main as main_module

    monkeypatch.setattr(main_module, "fetch_polymarket_weather_markets", counted.fetch_poly)
    monkeypatch.setattr(main_module, "fetch_kalshi_weather_markets", counted.fetch_kalshi)

    async def no_forecast(city_key):
        return None

    monkeypatch.setattr(main_module, "fetch_ensemble_forecast", no_forecast)
    monkeypatch.setattr(main_module.settings, "KALSHI_ENABLED", True)

    asyncio.run(main_module._build_weather_section(["nyc"]))

    assert counted.poly == 1, f"Polymarket fetched {counted.poly} times"
    assert counted.kalshi == 1, f"Kalshi fetched {counted.kalshi} times"


def test_the_two_venue_fetches_overlap(monkeypatch):
    """They are independent, so they must not run one after the other."""
    from backend.api import main as main_module

    state = {"in_flight": 0, "peak": 0}

    async def slow(city_keys=None, platform="x"):
        state["in_flight"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        await asyncio.sleep(0.02)
        state["in_flight"] -= 1
        return [market(platform, 1)]

    async def poly(city_keys=None):
        return await slow(city_keys, "polymarket")

    async def kalshi(city_keys=None):
        return await slow(city_keys, "kalshi")

    monkeypatch.setattr(main_module, "fetch_polymarket_weather_markets", poly)
    monkeypatch.setattr(main_module, "fetch_kalshi_weather_markets", kalshi)
    monkeypatch.setattr(main_module.settings, "KALSHI_ENABLED", True)

    async def no_forecast(city_key):
        return None

    monkeypatch.setattr(main_module, "fetch_ensemble_forecast", no_forecast)

    async def no_scan(markets=None):
        return []

    monkeypatch.setattr(main_module, "scan_for_weather_signals", no_scan)

    asyncio.run(main_module._build_weather_section(["nyc"]))

    assert state["peak"] == 2, "Polymarket and Kalshi were fetched serially"
