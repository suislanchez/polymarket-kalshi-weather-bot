"""Tests for unified-paper startup safety and scheduler lane gating.

These guard safety properties for the unified paper-trading runtime:
1. FastAPI startup must be able to construct the app without launching any
   background scan/settlement jobs (read-only API smokes / TestClient), via
   ``SCHEDULER_AUTOSTART=false``.
2. The legacy BTC 5-min lane must be disabled by an explicit flag
   (``BTC_LANE_ENABLED``), not by relying on ``MIN_EDGE_THRESHOLD=999``.
3. Live execution settings must fail before database or scheduler startup.
"""
import asyncio

import pytest

from backend.core import scheduler as scheduler_module
from backend.trading.execution_mode import ExecutionModeError


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


def test_settings_default_to_unified_paper_safe_lifecycle():
    from backend.config import Settings

    s = Settings(_env_file=None)
    assert s.ACTIVE_PRODUCT_SCOPE == "unified_paper"
    # Autostart stays on for real local runs, but is overridable for smokes.
    assert s.SCHEDULER_AUTOSTART is True
    # The legacy BTC prediction-market lane stays off in unified-paper scope.
    assert s.BTC_LANE_ENABLED is False


def test_startup_rejects_live_mode_before_database_or_scheduler(monkeypatch):
    from backend.api import main

    calls = {"database": 0, "scheduler": 0}

    def fake_init_db():
        calls["database"] += 1

    def fake_scheduler_start():
        calls["scheduler"] += 1
        return True

    monkeypatch.setattr(main, "init_db", fake_init_db)
    monkeypatch.setattr(main, "_maybe_start_scheduler", fake_scheduler_start)
    monkeypatch.setattr(main.settings, "EXECUTION_MODE", "live")
    monkeypatch.setattr(main.settings, "LIVE_TRADING_ENABLED", False)

    with pytest.raises(ExecutionModeError, match="paper-only"):
        asyncio.run(main.startup())

    assert calls == {"database": 0, "scheduler": 0}


def test_startup_in_paper_mode_retains_scheduler_autostart(monkeypatch):
    from backend.api import main

    calls = {"database": 0, "scheduler": 0}

    class FakeQuery:
        @staticmethod
        def first():
            return main.BotState(
                bankroll=main.settings.INITIAL_BANKROLL,
                total_trades=0,
                winning_trades=0,
                total_pnl=0.0,
                is_running=True,
            )

    class FakeSession:
        @staticmethod
        def query(_model):
            return FakeQuery()

        @staticmethod
        def commit():
            return None

        @staticmethod
        def close():
            return None

    def fake_init_db():
        calls["database"] += 1

    def fake_scheduler_start():
        calls["scheduler"] += 1
        return True

    monkeypatch.setattr(main, "init_db", fake_init_db)
    monkeypatch.setattr(main, "SessionLocal", FakeSession)
    monkeypatch.setattr(main, "_maybe_start_scheduler", fake_scheduler_start)
    monkeypatch.setattr(main.settings, "EXECUTION_MODE", "paper")
    monkeypatch.setattr(main.settings, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(main.settings, "SCHEDULER_AUTOSTART", True)

    asyncio.run(main.startup())

    assert calls == {"database": 1, "scheduler": 1}
