"""A kill switch that reports ENGAGED while orders submit is worse than none.

GLOBAL_TRADING_KILL_SWITCH was declared in config and read by no production
code path. backend/api/main.py knew this and worked around it by reporting
LIVE_TRADING_ENABLED as the authoritative source, with a comment saying so.

backend/trading/preflight.py then reported the dead flag as the source AND
treated it as engaging the switch, so `trading_preflight.py` printed
"kill switch ENGAGED" while `run_paper_strategy.py` submitted an order in the
same configuration.

The fix is to make the flag real rather than to correct the report: an operator
reaching for something named GLOBAL_TRADING_KILL_SWITCH is trying to stop
trading, and the safe reading of that intent is to stop trading.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_cli(script: str, *args, **env_overrides) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONPATH"] = str(ROOT)
    env.setdefault("EXECUTION_MODE", "paper")
    env.setdefault("LIVE_TRADING_ENABLED", "false")
    env.update({k: v for k, v in env_overrides.items()})
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        capture_output=True, text=True, cwd=str(ROOT), env=env,
    )


def test_the_engaged_switch_actually_stops_an_order(tmp_path):
    """The end-to-end assertion: same config, no submitted order."""
    result = run_cli(
        "run_paper_strategy.py", "--adapter", "fake", "--symbols", "SPY",
        "--once", "--json",
        GLOBAL_TRADING_KILL_SWITCH="true", STOCK_CRYPTO_LANE_ENABLED="true",
    )

    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    for entry in body["results"]:
        assert entry.get("order_status") != "submitted", (
            "an order was submitted while the global kill switch was engaged"
        )


def test_without_the_switch_the_same_order_does_submit():
    """Control. Without this, the test above passes for the wrong reason."""
    result = run_cli(
        "run_paper_strategy.py", "--adapter", "fake", "--symbols", "SPY",
        "--once", "--json",
        GLOBAL_TRADING_KILL_SWITCH="false", STOCK_CRYPTO_LANE_ENABLED="true",
    )

    body = json.loads(result.stdout)
    statuses = [entry.get("order_status") for entry in body["results"]]
    assert "submitted" in statuses, f"control run did not submit: {statuses}"


def test_every_flag_preflight_names_actually_gates():
    """Each flag in the reported source must stop an order on its own.

    The source is a compound name because more than one flag gates. Naming a
    flag that stops nothing is the exact defect this file exists to prevent, so
    every name is exercised rather than the string as a whole.
    """
    from backend.config import Settings
    from backend.trading.preflight import run_preflight

    source = run_preflight(Settings()).kill_switch["source"]
    flags = [part.strip() for part in source.split(" or ")]
    assert flags, f"no flag names in reported source {source!r}"

    for flag in flags:
        assert flag.replace("_", "").isalnum(), f"{flag!r} is not an env var name"
        result = run_cli(
            "run_paper_strategy.py", "--adapter", "fake", "--symbols", "SPY",
            "--once", "--json",
            STOCK_CRYPTO_LANE_ENABLED="true", **{flag: "true"},
        )
        if result.returncode != 0:
            continue  # refusing outright also stops the order
        for entry in json.loads(result.stdout)["results"]:
            assert entry.get("order_status") != "submitted", (
                f"preflight names {flag} as a kill switch, but setting it did "
                "not stop an order"
            )


def test_the_scheduler_service_observes_the_global_switch(monkeypatch):
    """The production builder, not just the CLI."""
    from backend.core import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module.settings, "GLOBAL_TRADING_KILL_SWITCH", True)
    monkeypatch.setattr(scheduler_module.settings, "LIVE_TRADING_ENABLED", False)

    assert scheduler_module.trading_kill_switch_engaged() is True


def test_live_trading_enabled_still_engages_it(monkeypatch):
    """The pre-existing gate must keep working."""
    from backend.core import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module.settings, "GLOBAL_TRADING_KILL_SWITCH", False)
    monkeypatch.setattr(scheduler_module.settings, "LIVE_TRADING_ENABLED", True)

    assert scheduler_module.trading_kill_switch_engaged() is True


def test_neither_flag_means_disengaged(monkeypatch):
    from backend.core import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module.settings, "GLOBAL_TRADING_KILL_SWITCH", False)
    monkeypatch.setattr(scheduler_module.settings, "LIVE_TRADING_ENABLED", False)

    assert scheduler_module.trading_kill_switch_engaged() is False


def test_the_api_reports_a_source_naming_both_gates():
    """The API's reported source must not name a flag that does nothing."""
    from backend.api import main as main_module

    source = main_module._KILL_SWITCH_SOURCE
    assert "GLOBAL_TRADING_KILL_SWITCH" in source
    assert "LIVE_TRADING_ENABLED" in source
