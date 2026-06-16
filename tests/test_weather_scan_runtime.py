"""Tests for the weather scan runtime: forecast dedup + bounded concurrency."""
import asyncio
from datetime import date
from types import SimpleNamespace

from backend.core.weather_scan_runtime import (
    ScanRuntimeStats,
    forecast_keys,
    map_concurrently,
    prefetch_forecasts,
)


def _market(city: str, day: int):
    return SimpleNamespace(city_key=city, target_date=date(2026, 6, day))


def test_forecast_keys_dedups_by_city_and_date():
    markets = [
        _market("nyc", 16),
        _market("nyc", 16),
        _market("nyc", 17),
        _market("la", 16),
    ]
    keys = forecast_keys(markets)
    assert keys == [("nyc", date(2026, 6, 16)), ("nyc", date(2026, 6, 17)), ("la", date(2026, 6, 16))]


def test_prefetch_forecasts_calls_fetcher_once_per_unique_key():
    # 10 markets sharing 2 (city,date) keys must trigger only 2 fetches.
    markets = [_market("nyc", 16) for _ in range(7)] + [_market("la", 16) for _ in range(3)]
    calls = []

    async def fetcher(city, target_date):
        calls.append((city, target_date))
        return SimpleNamespace(city_key=city, target_date=target_date)

    forecasts, stats = asyncio.run(prefetch_forecasts(markets, fetcher=fetcher, concurrency=4))

    assert isinstance(stats, ScanRuntimeStats)
    assert stats.market_count == 10
    assert stats.unique_forecast_keys == 2
    assert stats.forecast_fetches == 2
    assert len(calls) == 2
    assert set(forecasts.keys()) == {("nyc", date(2026, 6, 16)), ("la", date(2026, 6, 16))}


def test_prefetch_forecasts_handles_fetch_errors_without_crashing():
    markets = [_market("nyc", 16), _market("boom", 16)]

    async def fetcher(city, target_date):
        if city == "boom":
            raise RuntimeError("provider down")
        return SimpleNamespace(city_key=city)

    forecasts, stats = asyncio.run(prefetch_forecasts(markets, fetcher=fetcher, concurrency=4))

    assert stats.forecast_errors == 1
    assert ("nyc", date(2026, 6, 16)) in forecasts
    assert ("boom", date(2026, 6, 16)) not in forecasts


def test_map_concurrently_respects_bound_and_preserves_order():
    state = {"current": 0, "max": 0}

    async def worker(n):
        state["current"] += 1
        state["max"] = max(state["max"], state["current"])
        await asyncio.sleep(0.005)
        state["current"] -= 1
        return n * 2

    items = list(range(12))
    results = asyncio.run(map_concurrently(items, worker, concurrency=3))

    assert results == [n * 2 for n in items]  # order preserved
    assert state["max"] <= 3  # never exceeded the bound


def test_map_concurrently_empty_is_safe():
    async def worker(n):  # pragma: no cover - never called
        return n

    assert asyncio.run(map_concurrently([], worker, concurrency=4)) == []
