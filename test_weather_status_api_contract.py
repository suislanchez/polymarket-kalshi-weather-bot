from datetime import date, datetime, timezone
import sys
import types

from fastapi.testclient import TestClient

from backend.api import main as api_main
from backend.api.main import app
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


def _signal(state="near", *, naive_observation=False):
    observed = datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    fetched = datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc)
    if naive_observation:
        observed = observed.replace(tzinfo=None)
        fetched = fetched.replace(tzinfo=None)
    return ws.WeatherTradingSignal(
        market=ws.KalshiWeatherMarket(
            market_id="KXHIGHTNY-26JUN03-T85",
            slug="KXHIGHTNY-26JUN03-T85",
            city_key="nyc",
            city_name="New York City",
            target_date=date(2026, 6, 3),
            threshold_f=85.0,
            metric="high",
        ),
        edge=0.1,
        threshold_state=state,
        weather_observation=ws.WeatherObservation(
            source="aviationweather_metar",
            station_id="KJFK",
            observed_at=observed,
            fetched_at=fetched,
            temp_f=84.0,
            raw={"rawOb": "KJFK 031551Z AUTO"},
            raw_hash="hash-1",
            source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
        ),
        signal_at=datetime(2026, 6, 3, 15, 52, 5, tzinfo=timezone.utc),
    )


def test_weather_status_endpoint_exposes_last_change_observation_age_and_next_fast_scan(monkeypatch):
    _install_fake_apscheduler(monkeypatch)
    from backend.core import scheduler as scheduler_mod

    scheduler_mod._weather_threshold_state_cache.clear()
    scheduler_mod._weather_observation_hash_by_station.clear()
    scheduler_mod.emit_weather_threshold_state_changes([_signal("near")])

    monkeypatch.setattr(api_main.settings, "WEATHER_ENABLED", True)
    monkeypatch.setattr(api_main.settings, "WEATHER_NOWCAST_INTERVAL_SECONDS", 60)
    monkeypatch.setattr("backend.core.weather_signals.get_cached_signals", lambda: [_signal("near")])
    monkeypatch.setattr("backend.core.weather_signals.get_signal_cache_age_seconds", lambda: 12.0)
    monkeypatch.setattr("backend.api.main.datetime", type("FakeDateTime", (), {
        "utcnow": staticmethod(lambda: datetime(2026, 6, 3, 15, 52, 30, tzinfo=timezone.utc)),
    }))

    response = TestClient(app).get("/api/weather/status")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["fast_loop_interval_seconds"] == 60
    assert body["next_fast_scan_in_seconds"] == 48.0
    assert body["cache_age_seconds"] == 12.0
    assert body["last_observation_age_seconds"] == 90.0
    assert body["last_observation"]["station_id"] == "KJFK"
    assert body["last_change"]["market_id"] == "KXHIGHTNY-26JUN03-T85"
    assert body["last_change"]["state"] == "near"


def test_weather_status_endpoint_tolerates_legacy_naive_observation_datetimes(monkeypatch):
    monkeypatch.setattr(api_main.settings, "WEATHER_ENABLED", True)
    monkeypatch.setattr(api_main.settings, "WEATHER_NOWCAST_INTERVAL_SECONDS", 60)
    monkeypatch.setattr("backend.core.weather_signals.get_cached_signals", lambda: [_signal("near", naive_observation=True)])
    monkeypatch.setattr("backend.core.weather_signals.get_signal_cache_age_seconds", lambda: 12.0)
    monkeypatch.setattr("backend.core.scheduler.get_recent_events", lambda _limit: [])
    monkeypatch.setattr("backend.api.main.datetime", type("FakeDateTime", (), {
        "utcnow": staticmethod(lambda: datetime(2026, 6, 3, 15, 52, 30, tzinfo=timezone.utc)),
    }))

    response = TestClient(app).get("/api/weather/status")

    assert response.status_code == 200
    assert response.json()["last_observation_age_seconds"] == 90.0
