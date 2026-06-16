"""Tests for scheduler autostart gating and explicit BTC-lane enablement.

These guard two safety properties from the weather-only handoff:
1. FastAPI startup must be able to construct the app without launching any
   background scan/settlement jobs (read-only API smokes / TestClient), via
   ``SCHEDULER_AUTOSTART=false``.
2. The legacy BTC 5-min lane must be disabled by an explicit flag
   (``BTC_LANE_ENABLED``), not by relying on ``MIN_EDGE_THRESHOLD=999``.
"""
from backend.core import scheduler as scheduler_module


def test_planned_scheduler_jobs_excludes_btc_when_lane_disabled(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "BTC_LANE_ENABLED", False)
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_ENABLED", True)
    monkeypatch.setattr(scheduler_module.settings, "PAPER_POSITION_RISK_ENABLED", True)

    jobs = scheduler_module.planned_scheduler_jobs()

    assert "market_scan" not in jobs
    assert "weather_scan" in jobs
    assert "settlement_check" in jobs
    assert "heartbeat" in jobs
    assert "open_position_risk" in jobs


def test_planned_scheduler_jobs_includes_btc_only_when_lane_enabled(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "BTC_LANE_ENABLED", True)
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_ENABLED", False)
    monkeypatch.setattr(scheduler_module.settings, "PAPER_POSITION_RISK_ENABLED", False)

    jobs = scheduler_module.planned_scheduler_jobs()

    assert "market_scan" in jobs
    assert "weather_scan" not in jobs
    assert "open_position_risk" not in jobs


def test_maybe_start_scheduler_respects_autostart_flag(monkeypatch):
    from backend.api import main

    calls = {"start": 0}

    def fake_start():
        calls["start"] += 1

    monkeypatch.setattr("backend.core.scheduler.start_scheduler", fake_start)
    monkeypatch.setattr("backend.core.scheduler.log_event", lambda *a, **k: None)

    monkeypatch.setattr(main.settings, "SCHEDULER_AUTOSTART", False)
    assert main._maybe_start_scheduler() is False
    assert calls["start"] == 0

    monkeypatch.setattr(main.settings, "SCHEDULER_AUTOSTART", True)
    assert main._maybe_start_scheduler() is True
    assert calls["start"] == 1


def test_settings_default_to_weather_only_safe_lifecycle():
    from backend.config import Settings

    s = Settings()
    # Autostart stays on for real local runs, but is overridable for smokes.
    assert s.SCHEDULER_AUTOSTART is True
    # BTC lane is off by default under the weather-only product scope.
    assert s.BTC_LANE_ENABLED is False
