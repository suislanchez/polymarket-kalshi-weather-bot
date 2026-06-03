from datetime import date, datetime, timezone
import sys
import types

import pytest
from backend.core.weather_signals import KalshiWeatherMarket, WeatherObservation, WeatherTradingSignal


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
    setattr(schedulers_asyncio, "AsyncIOScheduler", FakeScheduler)
    setattr(triggers_interval, "IntervalTrigger", FakeIntervalTrigger)
    monkeypatch.setitem(sys.modules, "apscheduler", apscheduler)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers", schedulers)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers.asyncio", schedulers_asyncio)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers", triggers)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.interval", triggers_interval)


@pytest.fixture
def scheduler(monkeypatch):
    _install_fake_apscheduler(monkeypatch)
    from backend.core import scheduler as scheduler_mod
    return scheduler_mod


def test_weather_nowcast_scheduler_file_imports_without_optional_apscheduler_installed(monkeypatch):
    sys.modules.pop("backend.core.scheduler", None)
    _install_fake_apscheduler(monkeypatch)
    from backend.core import scheduler as scheduler_mod

    assert scheduler_mod.weather_nowcast_job is not None


def _signal(*, market_id="KXHIGHTNY-26JUN03-T85", temp_f=83.0, threshold_f=85.0, state=None):
    observed = datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    fetched = datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc)
    return WeatherTradingSignal(
        market=KalshiWeatherMarket(
            market_id=market_id,
            slug=market_id,
            city_key="nyc",
            city_name="New York City",
            target_date=date(2026, 6, 3),
            threshold_f=threshold_f,
            metric="high",
        ),
        model_probability=0.80,
        market_probability=0.50,
        edge=0.30,
        net_edge=0.23,
        direction="yes",
        confidence=0.80,
        suggested_size=50.0,
        signal_source="GFS-ensemble",
        threshold_state=state,
        weather_observation=WeatherObservation(
            source="aviationweather_metar",
            station_id="KJFK",
            observed_at=observed,
            fetched_at=fetched,
            temp_f=temp_f,
            raw={"temp": (temp_f - 32) * 5 / 9},
            raw_hash=f"hash-{temp_f}",
            source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
        ),
        signal_at=datetime(2026, 6, 3, 15, 52, 5, tzinfo=timezone.utc),
    )


def test_threshold_state_is_classified_from_observation_and_lock_source(scheduler):
    below = _signal(temp_f=80.0, threshold_f=85.0, state=None)
    near = _signal(temp_f=84.0, threshold_f=85.0, state=None)
    crossed = _signal(temp_f=86.0, threshold_f=85.0, state=None)
    locked = _signal(temp_f=86.0, threshold_f=85.0, state=None)
    locked.signal_source = "METAR-lock"

    assert scheduler.weather_threshold_state(below) == "below"
    assert scheduler.weather_threshold_state(near) == "near"
    assert scheduler.weather_threshold_state(crossed) == "crossed"
    assert scheduler.weather_threshold_state(locked) == "locked"


def test_nowcast_emits_state_change_once_and_suppresses_unchanged_duplicates(monkeypatch, scheduler):
    events = []
    monkeypatch.setattr(scheduler, "log_event", lambda typ, msg, data=None: events.append((typ, msg, data or {})))
    scheduler._weather_threshold_state_cache.clear()

    first = _signal(temp_f=84.0, threshold_f=85.0, state="near")
    second_same = _signal(temp_f=84.5, threshold_f=85.0, state="near")
    third_changed = _signal(temp_f=86.0, threshold_f=85.0, state="crossed")

    changes = scheduler.emit_weather_threshold_state_changes([first])
    assert [c["state"] for c in changes] == ["near"]
    assert any(e[0] == "weather_state_change" and e[2]["state"] == "near" for e in events)

    events.clear()
    changes = scheduler.emit_weather_threshold_state_changes([second_same])
    assert changes == []
    assert not any(e[0] == "weather_state_change" for e in events)

    changes = scheduler.emit_weather_threshold_state_changes([third_changed])
    assert [c["state"] for c in changes] == ["crossed"]
    assert any(e[0] == "weather_state_change" and e[2]["previous_state"] == "near" for e in events)


def test_weather_nowcast_job_logs_only_state_change_details_not_unchanged_refresh_spam(monkeypatch, scheduler):
    events = []
    monkeypatch.setattr(scheduler, "log_event", lambda typ, msg, data=None: events.append((typ, msg, data or {})))
    scheduler._weather_threshold_state_cache.clear()

    async def fake_scan():
        return [_signal(temp_f=84.0, threshold_f=85.0, state="near")]

    monkeypatch.setattr("backend.core.weather_signals.scan_for_weather_signals", fake_scan)

    import asyncio
    asyncio.run(scheduler.weather_nowcast_job())
    asyncio.run(scheduler.weather_nowcast_job())

    state_events = [e for e in events if e[0] == "weather_state_change"]
    assert len(state_events) == 1
    assert state_events[0][2]["market_id"] == "KXHIGHTNY-26JUN03-T85"
    assert state_events[0][2]["state"] == "near"
