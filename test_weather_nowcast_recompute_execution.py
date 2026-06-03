from datetime import date, datetime, timezone
import asyncio
import sys
import types

from backend.core import weather_signals as ws


class FakeScheduler:
    running = False

    def add_job(self, *_args, **_kwargs):
        return None

    def start(self):
        self.running = True

    def shutdown(self, wait=False):
        self.running = False


class FakeIntervalTrigger:
    def __init__(self, seconds=None, minutes=None):
        self.seconds = seconds
        self.minutes = minutes


def _install_fake_apscheduler(monkeypatch):
    apscheduler = types.ModuleType("apscheduler")
    schedulers = types.ModuleType("apscheduler.schedulers")
    schedulers_asyncio = types.ModuleType("apscheduler.schedulers.asyncio")
    triggers = types.ModuleType("apscheduler.triggers")
    triggers_interval = types.ModuleType("apscheduler.triggers.interval")
    schedulers_asyncio.AsyncIOScheduler = FakeScheduler
    triggers_interval.IntervalTrigger = FakeIntervalTrigger
    monkeypatch.setitem(sys.modules, "apscheduler", apscheduler)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers", schedulers)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers.asyncio", schedulers_asyncio)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers", triggers)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.interval", triggers_interval)


def _observation(raw_hash="new-hash", temp_f=86.0):
    return ws.WeatherObservation(
        source="aviationweather_metar",
        station_id="KJFK",
        observed_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc),
        temp_f=temp_f,
        raw={"rawOb": "KJFK 031551Z AUTO"},
        raw_hash=raw_hash,
        source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
    )


def _signal(market_id="KXHIGHTNY-26JUN03-T85", city_key="nyc", raw_hash="new-hash"):
    return ws.WeatherTradingSignal(
        market=ws.KalshiWeatherMarket(
            market_id=market_id,
            slug=market_id,
            city_key=city_key,
            city_name=city_key.upper(),
            target_date=date(2026, 6, 3),
            threshold_f=85.0,
            metric="high",
        ),
        edge=0.1,
        weather_observation=_observation(raw_hash=raw_hash),
    )


def _raw_market(ticker, title="NYC high temperature above 85°F"):
    return {
        "ticker": ticker,
        "title": title,
        "rules_primary": "on June 3, 2026",
        "yes_bid_dollars": "0.40",
        "yes_ask_dollars": "0.42",
        "last_price_dollars": "0.41",
        "open_interest_fp": "100",
    }


def test_recompute_weather_signals_for_tickers_fetches_only_impacted_tickers(monkeypatch):
    fetched = []
    built_raw_markets = []

    def fake_fetch(tickers):
        fetched.extend(tickers)
        return [_raw_market(ticker) for ticker in tickers]

    def fake_build(raw_markets=None):
        built_raw_markets.extend(raw_markets or [])
        return [_signal(raw_markets[0]["ticker"])] if raw_markets else []

    monkeypatch.setattr(ws, "fetch_kalshi_weather_markets_for_tickers", fake_fetch)
    monkeypatch.setattr(ws, "_build_signals_sync", fake_build)
    monkeypatch.setattr(ws, "_persist_weather_signals", lambda signals: None)
    ws._last_signal_results = [_signal("KXHIGHTLA-26JUN03-T85", city_key="los angeles")]

    result = asyncio.run(ws.recompute_weather_signals_for_tickers(["KXHIGHTNY-26JUN03-T85"]))

    assert fetched == ["KXHIGHTNY-26JUN03-T85"]
    assert [m["ticker"] for m in built_raw_markets] == ["KXHIGHTNY-26JUN03-T85"]
    assert [s.market.market_id for s in result] == ["KXHIGHTNY-26JUN03-T85"]
    assert {s.market.market_id for s in ws._last_signal_results} == {
        "KXHIGHTLA-26JUN03-T85",
        "KXHIGHTNY-26JUN03-T85",
    }


def test_nowcast_job_executes_scoped_recompute_for_changed_station_only(monkeypatch):
    _install_fake_apscheduler(monkeypatch)
    from backend.core import scheduler as scheduler_mod

    scheduler_mod._weather_observation_hash_by_station.clear()
    scheduler_mod._weather_threshold_state_cache.clear()
    monkeypatch.setattr(scheduler_mod, "_today", lambda: date(2026, 6, 3))

    events = []
    recompute_calls = []

    async def fake_scan():
        return [
            _signal("KXHIGHTNY-26JUN03-T85", "nyc"),
            _signal("KXHIGHTLA-26JUN03-T85", "los angeles"),
        ]

    async def fake_recompute(tickers):
        recompute_calls.append(list(tickers))
        return [_signal(ticker) for ticker in tickers]

    monkeypatch.setattr("backend.core.weather_signals.scan_for_weather_signals", fake_scan)
    monkeypatch.setattr("backend.core.weather_signals.recompute_weather_signals_for_tickers", fake_recompute)
    monkeypatch.setattr(scheduler_mod, "log_event", lambda typ, msg, data=None: events.append((typ, msg, data or {})))

    asyncio.run(scheduler_mod.weather_nowcast_job())

    assert recompute_calls == [["KXHIGHTNY-26JUN03-T85"]]
    summary_events = [e for e in events if e[0] == "data" and "Weather nowcast refreshed" in e[1]]
    assert summary_events
    payload = summary_events[-1][2]
    assert payload["recompute_results"] == [
        {
            "station_id": "KJFK",
            "market_ids": ["KXHIGHTNY-26JUN03-T85"],
            "signals_recomputed": 1,
        }
    ]

    asyncio.run(scheduler_mod.weather_nowcast_job())
    assert recompute_calls == [["KXHIGHTNY-26JUN03-T85"]]
