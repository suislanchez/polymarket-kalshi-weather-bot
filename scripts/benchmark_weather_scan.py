#!/usr/bin/env python3
"""Benchmark the weather scan-runtime layer (forecast dedup + concurrency).

This is a SYNTHETIC, side-effect-free benchmark: it does not touch the network,
private accounts, or the database. It builds synthetic markets that share
``(city, date)`` forecasts (like real bucket slates), then compares:

* baseline: one forecast fetch per market, serial signal generation
* optimized: one fetch per unique (city, date) + bounded-concurrency generation

and reports the forecast-fetch ratio, wall-clock speedup, and p50/p95 per-market
signal time. Use it to validate the P4 acceptance checks without live trading.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from backend.core.weather_scan_runtime import map_concurrently, prefetch_forecasts


def _build_markets(n_markets: int, n_cities: int, n_days: int):
    cities = [f"city_{i}" for i in range(max(1, n_cities))]
    markets = []
    for i in range(n_markets):
        city = cities[i % len(cities)]
        day = date(2026, 6, 1) + timedelta(days=i % max(1, n_days))
        markets.append(SimpleNamespace(city_key=city, target_date=day, market_id=f"m{i}", title=f"m{i}"))
    return markets


def _make_fetcher(latency_s: float):
    async def fetcher(city, target_date):
        await asyncio.sleep(latency_s)
        return SimpleNamespace(city_key=city, target_date=target_date)

    return fetcher


def _make_signal_fn(compute_s: float, timings: list[float]):
    async def signal_fn(market):
        start = time.perf_counter()
        await asyncio.sleep(compute_s)
        timings.append(time.perf_counter() - start)
        return market.market_id

    return signal_fn


async def _baseline(markets, fetcher, compute_s: float) -> float:
    start = time.perf_counter()
    for market in markets:
        await fetcher(market.city_key, market.target_date)  # one fetch per market
        await asyncio.sleep(compute_s)
    return time.perf_counter() - start


async def _optimized(markets, fetcher, compute_s: float, concurrency: int):
    timings: list[float] = []
    signal_fn = _make_signal_fn(compute_s, timings)
    start = time.perf_counter()
    forecasts, stats = await prefetch_forecasts(markets, fetcher=fetcher, concurrency=concurrency)
    await map_concurrently(markets, signal_fn, concurrency=concurrency)
    elapsed = time.perf_counter() - start
    return elapsed, stats, timings


def _pct(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[k]


async def run(args) -> int:
    markets = _build_markets(args.markets, args.cities, args.days)
    fetcher = _make_fetcher(args.fetch_latency_ms / 1000.0)
    compute_s = args.signal_latency_ms / 1000.0

    baseline = await _baseline(markets, fetcher, compute_s)
    optimized, stats, timings = await _optimized(markets, fetcher, compute_s, args.concurrency)

    speedup = (baseline / optimized) if optimized > 0 else float("inf")
    print("Weather scan-runtime benchmark (synthetic, no network/DB)")
    print(f"  markets:                {stats.market_count}")
    print(f"  unique city/date keys:  {stats.unique_forecast_keys}")
    print(f"  forecast fetches:       {stats.forecast_fetches}  (baseline would do {stats.market_count})")
    print(f"  fetch dedup ratio:      {stats.market_count / max(1, stats.forecast_fetches):.1f}x")
    print(f"  concurrency:            {args.concurrency}")
    print(f"  baseline wall-clock:    {baseline * 1000:.0f} ms")
    print(f"  optimized wall-clock:   {optimized * 1000:.0f} ms")
    print(f"  speedup:                {speedup:.1f}x")
    print(f"  per-market signal p50:  {_pct(timings, 50) * 1000:.1f} ms")
    print(f"  per-market signal p95:  {_pct(timings, 95) * 1000:.1f} ms")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--markets", type=int, default=120, help="Synthetic market lines")
    p.add_argument("--cities", type=int, default=12, help="Distinct cities")
    p.add_argument("--days", type=int, default=2, help="Distinct target days")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--fetch-latency-ms", type=float, default=80.0, help="Simulated forecast fetch latency")
    p.add_argument("--signal-latency-ms", type=float, default=5.0, help="Simulated per-market compute")
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
