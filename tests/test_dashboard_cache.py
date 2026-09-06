"""The dashboard aggregate is computed at most once per TTL, and once at a time.

/api/dashboard fans out to Polymarket, Kalshi and 17 ensemble forecasts. Even
parallelised that is tens of seconds, and the frontend polls it every 10
seconds -- so without a cache every poll, every reload and every open tab
starts its own full crawl and they queue behind each other. That is what made
the page take ~108s to first paint and never get faster.

Two properties, and the second is the one that is easy to get wrong: a plain
TTL cache still lets N simultaneous misses each do the full work. The single
-flight lock is what stops a reload storm from multiplying upstream load.
"""

import asyncio
import time

import pytest

from backend.api import main as main_module


@pytest.fixture(autouse=True)
def clear_cache():
    main_module._dashboard_cache = None
    yield
    main_module._dashboard_cache = None


def test_a_second_call_inside_the_ttl_does_not_recompute(monkeypatch):
    calls = {"n": 0}

    async def build():
        calls["n"] += 1
        return {"payload": calls["n"]}

    monkeypatch.setattr(main_module, "DASHBOARD_CACHE_TTL_SECONDS", 60.0)

    async def scenario():
        first = await main_module._cached_dashboard(build)
        second = await main_module._cached_dashboard(build)
        return first, second

    first, second = asyncio.run(scenario())

    assert calls["n"] == 1, "the aggregate was rebuilt inside the TTL"
    assert first is second


def test_the_cache_expires(monkeypatch):
    calls = {"n": 0}

    async def build():
        calls["n"] += 1
        return {"payload": calls["n"]}

    monkeypatch.setattr(main_module, "DASHBOARD_CACHE_TTL_SECONDS", 0.05)

    async def scenario():
        await main_module._cached_dashboard(build)
        await asyncio.sleep(0.1)
        await main_module._cached_dashboard(build)

    asyncio.run(scenario())

    assert calls["n"] == 2, "the cache never expired"


def test_simultaneous_misses_share_one_computation(monkeypatch):
    """The reload-storm case: N tabs must not start N crawls."""
    calls = {"n": 0}

    async def slow_build():
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return {"payload": "x"}

    monkeypatch.setattr(main_module, "DASHBOARD_CACHE_TTL_SECONDS", 60.0)

    async def scenario():
        return await asyncio.gather(
            *(main_module._cached_dashboard(slow_build) for _ in range(8))
        )

    results = asyncio.run(scenario())

    assert calls["n"] == 1, f"{calls['n']} concurrent crawls started instead of 1"
    assert all(r is results[0] for r in results)


def test_a_zero_ttl_disables_the_cache(monkeypatch):
    calls = {"n": 0}

    async def build():
        calls["n"] += 1
        return {"payload": calls["n"]}

    monkeypatch.setattr(main_module, "DASHBOARD_CACHE_TTL_SECONDS", 0.0)

    async def scenario():
        await main_module._cached_dashboard(build)
        await main_module._cached_dashboard(build)

    asyncio.run(scenario())

    assert calls["n"] == 2, "a zero TTL still served a cached value"


def test_a_failed_build_is_not_cached(monkeypatch):
    """Caching an exception would pin the dashboard broken for the whole TTL."""
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("upstream down")
        return {"payload": "recovered"}

    monkeypatch.setattr(main_module, "DASHBOARD_CACHE_TTL_SECONDS", 60.0)

    async def scenario():
        with pytest.raises(RuntimeError):
            await main_module._cached_dashboard(flaky)
        return await main_module._cached_dashboard(flaky)

    result = asyncio.run(scenario())

    assert result == {"payload": "recovered"}
    assert calls["n"] == 2


def test_the_ttl_is_a_declared_setting_that_takes_effect(monkeypatch):
    """A knob read through getattr with a default is a knob nothing backs.

    This whole codebase has shipped several settings that were declared and
    never read; the inverse -- read but never declared -- is the same defect
    from the other side, and it also breaks the moment someone puts the name
    in .env under a forbid-extras settings model.
    """
    from backend.config import Settings

    assert "DASHBOARD_CACHE_TTL_SECONDS" in Settings.model_fields
    assert Settings().DASHBOARD_CACHE_TTL_SECONDS == main_module.DASHBOARD_CACHE_TTL_SECONDS
