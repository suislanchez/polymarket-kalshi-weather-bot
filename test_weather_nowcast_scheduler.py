import sys
import types

from backend.config import settings


class FakeScheduler:
    instances = []

    def __init__(self):
        self.jobs = []
        self.running = False
        FakeScheduler.instances.append(self)

    def add_job(self, func, trigger, id=None, replace_existing=False, max_instances=None):
        self.jobs.append({
            "func": func,
            "trigger": trigger,
            "id": id,
            "replace_existing": replace_existing,
            "max_instances": max_instances,
        })

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


def test_weather_nowcast_has_separate_fast_scheduler_lane(monkeypatch):
    _install_fake_apscheduler(monkeypatch)
    from backend.core import scheduler as scheduler_mod

    FakeScheduler.instances.clear()
    monkeypatch.setattr(scheduler_mod, "AsyncIOScheduler", FakeScheduler)
    monkeypatch.setattr(scheduler_mod, "IntervalTrigger", FakeIntervalTrigger)
    monkeypatch.setattr(scheduler_mod, "scheduler", None)
    def close_created_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(scheduler_mod.asyncio, "create_task", close_created_task)
    monkeypatch.setattr(settings, "BTC_ENABLED", False)
    monkeypatch.setattr(settings, "WEATHER_ENABLED", True)
    monkeypatch.setattr(settings, "WEATHER_SCAN_INTERVAL_SECONDS", 300)
    monkeypatch.setattr(settings, "WEATHER_NOWCAST_INTERVAL_SECONDS", 60, raising=False)

    scheduler_mod.start_scheduler()

    jobs = {job["id"]: job for job in FakeScheduler.instances[0].jobs}
    assert jobs["weather_nowcast"]["trigger"].seconds == 60
    assert jobs["weather_scan"]["trigger"].seconds == 300
    assert jobs["weather_nowcast"]["func"] is scheduler_mod.weather_nowcast_job
