from datetime import date, datetime, timezone
import sys
import types
from types import SimpleNamespace

from backend.core.weather_source_benchmark import SourceObservation


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


def _install_fake_apscheduler():
    apscheduler = types.ModuleType("apscheduler")
    schedulers = types.ModuleType("apscheduler.schedulers")
    schedulers_asyncio = types.ModuleType("apscheduler.schedulers.asyncio")
    triggers = types.ModuleType("apscheduler.triggers")
    triggers_interval = types.ModuleType("apscheduler.triggers.interval")
    schedulers_asyncio.AsyncIOScheduler = FakeScheduler
    triggers_interval.IntervalTrigger = FakeIntervalTrigger
    sys.modules["apscheduler"] = apscheduler
    sys.modules["apscheduler.schedulers"] = schedulers
    sys.modules["apscheduler.schedulers.asyncio"] = schedulers_asyncio
    sys.modules["apscheduler.triggers"] = triggers
    sys.modules["apscheduler.triggers.interval"] = triggers_interval


def _obs(source, temp_f):
    return SourceObservation(
        source=source,
        station_id="KJFK",
        observed_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc),
        temp_f=temp_f,
        source_url=f"https://example.com/{source}",
        raw_hash=f"{source}-{temp_f}",
    )


def test_threshold_state_uses_fused_authority_lock_not_watch_crossing():
    _install_fake_apscheduler()
    from backend.core import scheduler as scheduler_mod

    policy = {
        "aviationweather_metar": {"role": "lock_authority"},
        "nws_latest_observation": {"role": "watch_only"},
    }
    market = SimpleNamespace(
        market_id="KXHIGHTNY-26JUN03-T85",
        city_name="New York City",
        metric="high",
        threshold_f=85.0,
        target_date=date(2026, 6, 3),
    )
    signal = SimpleNamespace(
        market=market,
        source_observations=[
            _obs("nws_latest_observation", 86.0),
            _obs("aviationweather_metar", 84.0),
        ],
        source_fusion_policy=policy,
    )

    assert scheduler_mod.weather_threshold_state(signal) == "below"

    signal.source_observations = [
        _obs("nws_latest_observation", 84.0),
        _obs("aviationweather_metar", 86.0),
    ]
    assert scheduler_mod.weather_threshold_state(signal) == "locked"
