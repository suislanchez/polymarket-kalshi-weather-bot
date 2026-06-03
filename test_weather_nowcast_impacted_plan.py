from datetime import date, datetime, timezone
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


def _signal(market_id, city_key, target_date):
    return ws.WeatherTradingSignal(
        market=ws.KalshiWeatherMarket(
            market_id=market_id,
            slug=market_id,
            city_key=city_key,
            city_name=city_key.upper(),
            target_date=target_date,
            threshold_f=85.0,
            metric="high",
        ),
        edge=0.1,
        weather_observation=ws.WeatherObservation(
            source="aviationweather_metar",
            station_id="KJFK",
            observed_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc),
            temp_f=86.0,
            raw={"rawOb": "KJFK 031551Z AUTO"},
            raw_hash="new-hash",
            source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
        ),
    )


def test_nowcast_builds_impacted_recompute_plans_and_updates_hash_cache(monkeypatch):
    _install_fake_apscheduler(monkeypatch)
    from backend.core import scheduler as scheduler_mod

    scheduler_mod._weather_observation_hash_by_station.clear()
    signals = [
        _signal("KXHIGHTNY-26JUN03-T85", "nyc", date(2026, 6, 3)),
        _signal("KXHIGHTLA-26JUN03-T85", "los angeles", date(2026, 6, 3)),
    ]
    monkeypatch.setattr(scheduler_mod, "_today", lambda: date(2026, 6, 3))

    plans = scheduler_mod.plan_nowcast_impacted_recomputes(signals)

    assert len(plans) == 1
    assert plans[0].station_id == "KJFK"
    assert plans[0].market_ids == ["KXHIGHTNY-26JUN03-T85"]
    assert scheduler_mod._weather_observation_hash_by_station == {"KJFK": "new-hash"}

    unchanged = scheduler_mod.plan_nowcast_impacted_recomputes(signals)
    assert unchanged == []
