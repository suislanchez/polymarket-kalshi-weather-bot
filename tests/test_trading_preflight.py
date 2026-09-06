"""Preflight answers one question: is it safe to let this process trade on paper?

The answers that matter are the negative ones. A preflight that reports "ready"
because a check threw and was swallowed is worse than no preflight, so several
tests here break a precondition deliberately and require a nonzero exit and a
named reason -- not a traceback, and never a credential value.

Absent credentials are NOT a failure. The system is meant to be operable and
verifiable before Alpaca keys exist; credential_ready is a separate field from
the exit status for exactly that reason.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "trading_preflight.py"

SECRET_KEY = "PKLEAKCANARY0000000000"
SECRET_VALUE = "SECRETLEAKCANARYVALUE0000000000000000000"


def run(**env_overrides) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONPATH"] = str(ROOT)
    env.setdefault("EXECUTION_MODE", "paper")
    env.setdefault("LIVE_TRADING_ENABLED", "false")
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True, cwd=str(ROOT), env=env,
    )


def report(result: subprocess.CompletedProcess) -> dict:
    return json.loads(result.stdout)


def test_a_clean_paper_runtime_passes():
    result = run()
    assert result.returncode == 0, result.stderr
    assert report(result)["paper_mode"] is True


def test_absent_credentials_report_not_ready_rather_than_failing():
    """Code must be verifiable before Alpaca keys exist."""
    result = run(ALPACA_API_KEY="", ALPACA_API_SECRET="")

    assert result.returncode == 0, "missing credentials must not fail preflight"
    assert report(result)["credential_ready"] is False
    assert "Traceback" not in result.stderr


def test_present_credentials_report_ready_without_echoing_them():
    result = run(ALPACA_API_KEY=SECRET_KEY, ALPACA_API_SECRET=SECRET_VALUE)

    assert result.returncode == 0, result.stderr
    assert report(result)["credential_ready"] is True
    assert SECRET_KEY not in result.stdout
    assert SECRET_VALUE not in result.stdout
    assert SECRET_KEY not in result.stderr
    assert SECRET_VALUE not in result.stderr


@pytest.mark.parametrize(
    "override",
    [{"EXECUTION_MODE": "live"}, {"LIVE_TRADING_ENABLED": "true"}],
)
def test_a_non_paper_runtime_fails_closed(override):
    result = run(**override)

    assert result.returncode != 0
    assert report(result)["paper_mode"] is False
    assert "Traceback" not in result.stderr


def test_an_unavailable_archives_root_fails_closed():
    result = run(TRADING_ARCHIVES_ROOT="/Volumes/ArchivesThatDoesNotExist")

    assert result.returncode != 0
    assert report(result)["archives"]["root_available"] is False


def test_the_filesystem_root_is_refused_as_an_archives_root():
    """Containment against '/' is vacuous: everything is inside it."""
    result = run(TRADING_ARCHIVES_ROOT="/")

    assert result.returncode != 0
    assert report(result)["archives"]["root_available"] is False


def test_preflight_reports_database_integrity():
    result = run()
    assert report(result)["database"]["integrity"] == "ok"


def test_preflight_reports_the_kill_switch_and_its_source():
    body = report(run())
    assert body["kill_switch"]["engaged"] is False
    assert body["kill_switch"]["source"]


def test_an_engaged_kill_switch_is_reported_without_failing_preflight():
    """The kill switch is a deliberate operator state, not a broken runtime."""
    result = run(GLOBAL_TRADING_KILL_SWITCH="true")

    assert report(result)["kill_switch"]["engaged"] is True


def test_preflight_reports_dependency_import_state():
    body = report(run())
    assert body["dependencies"]["alpaca"] is True


def test_preflight_reports_adapter_state():
    body = report(run())
    venues = {entry["venue"] for entry in body["adapters"]}
    assert "alpaca_paper" in venues


def test_human_output_is_the_default_and_still_hides_credentials():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(
        PYTHONPATH=str(ROOT), EXECUTION_MODE="paper", LIVE_TRADING_ENABLED="false",
        ALPACA_API_KEY=SECRET_KEY, ALPACA_API_SECRET=SECRET_VALUE,
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True,
        cwd=str(ROOT), env=env,
    )

    assert result.returncode == 0, result.stderr
    assert SECRET_KEY not in result.stdout
    assert SECRET_VALUE not in result.stdout
    assert "credential" in result.stdout.lower()
