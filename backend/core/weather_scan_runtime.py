"""Scan-runtime helpers: forecast de-duplication and bounded concurrency.

A single weather scan can produce dozens of market lines that share the same
``(city, target_date)`` forecast (every temperature bucket for a city/day). The
naive scan fetches the ensemble forecast per line and processes lines serially.
This module:

* de-duplicates forecast fetches to one per unique ``(city, target_date)`` and
  runs them under a bounded concurrency cap, and
* runs per-market signal generation under the same cap,

so forecast-fetch count tracks unique city/days (not market count) and wall-clock
drops without unbounded fan-out against public APIs.

Pure/async and dependency-light so it is unit-testable with fake fetchers.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Hashable, Iterable, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")

DEFAULT_SCAN_CONCURRENCY = 8


@dataclass(frozen=True)
class ScanRuntimeStats:
    market_count: int
    unique_forecast_keys: int
    forecast_fetches: int
    forecast_errors: int


def forecast_keys(markets: Iterable[object]) -> list[tuple[str, object]]:
    """Ordered, de-duplicated ``(city_key, target_date)`` keys for the markets."""
    seen: set[tuple[str, object]] = set()
    keys: list[tuple[str, object]] = []
    for market in markets:
        city = getattr(market, "city_key", None)
        target = getattr(market, "target_date", None)
        if not city or target is None:
            continue
        key = (city, target)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


async def map_concurrently(
    items: Sequence[T],
    fn: Callable[[T], Awaitable[R]],
    *,
    concurrency: int = DEFAULT_SCAN_CONCURRENCY,
) -> list[R]:
    """Apply ``fn`` to each item concurrently under a semaphore, preserving order."""
    items = list(items)
    if not items:
        return []
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _run(item: T) -> R:
        async with semaphore:
            return await fn(item)

    return await asyncio.gather(*[_run(item) for item in items])


async def prefetch_forecasts(
    markets: Sequence[object],
    *,
    fetcher: Callable[[str, object], Awaitable[object]],
    concurrency: int = DEFAULT_SCAN_CONCURRENCY,
) -> tuple[dict[tuple[str, object], object], ScanRuntimeStats]:
    """Fetch one forecast per unique ``(city, target_date)`` under a concurrency cap.

    Failures are isolated: a fetcher exception (or ``None`` result) drops that key
    from the map and is counted in ``forecast_errors`` rather than aborting the
    scan. Returns the forecast map plus :class:`ScanRuntimeStats`.
    """
    keys = forecast_keys(markets)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _fetch(key: tuple[str, object]):
        city, target = key
        async with semaphore:
            try:
                forecast = await fetcher(city, target)
                return key, forecast, None
            except Exception as exc:  # noqa: BLE001 - isolate per-key failures
                return key, None, exc

    gathered = await asyncio.gather(*[_fetch(key) for key in keys])

    forecasts: dict[tuple[str, object], object] = {}
    errors = 0
    for key, forecast, exc in gathered:
        if exc is not None or forecast is None:
            errors += 1
            continue
        forecasts[key] = forecast

    stats = ScanRuntimeStats(
        market_count=len(list(markets)),
        unique_forecast_keys=len(keys),
        forecast_fetches=len(keys),
        forecast_errors=errors,
    )
    return forecasts, stats
