"""The operator's way to run one paper strategy pass, and to refuse to.

Two properties are load-bearing.

The runtime guard runs BEFORE evaluation, not after. A strategy that proposes
first and checks second has already read market data and built an order by the
time it discovers it should not have; the service's pre-submit recheck is the
backstop, not the gate.

A run producing zero orders is a success. The plan is explicit that there are no
forced trades, so an exit code that treated "no proposal" as failure would push
an operator toward loosening the thing that made it decline.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_paper_strategy.py"
VERIFY = ROOT / "scripts" / "verify_alpaca_paper.py"

SECRET_KEY = "PKCLILEAKCANARY000000"
SECRET_VALUE = "CLISECRETLEAKCANARY00000000000000000000"


def run(script: Path, *args, **env_overrides) -> subprocess.CompletedProcess:
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
        [sys.executable, str(script), *args],
        capture_output=True, text=True, cwd=str(ROOT), env=env,
    )


# --- run_paper_strategy ----------------------------------------------------


def test_the_fake_adapter_completes_a_run(tmp_path):
    result = run(SCRIPT, "--adapter", "fake", "--symbols", "SPY", "--once", "--json")

    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["adapter"] == "fake"
    assert body["symbols"] == ["SPY"]


def test_a_run_with_no_proposal_is_still_a_success():
    """No forced trades: declining to trade is a valid outcome, not an error."""
    result = run(SCRIPT, "--adapter", "fake", "--symbols", "SPY", "--once", "--json")

    assert result.returncode == 0
    body = json.loads(result.stdout)
    assert "results" in body


def test_the_fake_adapter_run_is_deterministic():
    first = run(SCRIPT, "--adapter", "fake", "--symbols", "SPY", "--once", "--json")
    second = run(SCRIPT, "--adapter", "fake", "--symbols", "SPY", "--once", "--json")

    assert first.returncode == second.returncode == 0
    a, b = json.loads(first.stdout), json.loads(second.stdout)
    assert [r["reason"] for r in a["results"]] == [r["reason"] for r in b["results"]]


def test_alpaca_without_credentials_refuses_cleanly():
    result = run(
        SCRIPT, "--adapter", "alpaca", "--symbols", "SPY", "--once",
        ALPACA_API_KEY="", ALPACA_API_SECRET="",
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "credential" in (result.stdout + result.stderr).lower()


@pytest.mark.parametrize(
    "override",
    [{"EXECUTION_MODE": "live"}, {"LIVE_TRADING_ENABLED": "true"}],
)
def test_a_live_flag_exits_nonzero_before_doing_anything(override):
    result = run(SCRIPT, "--adapter", "fake", "--symbols", "SPY", "--once", **override)

    assert result.returncode != 0
    assert "Traceback" not in result.stderr


def test_an_unavailable_archives_root_stops_the_run_before_evaluation():
    result = run(
        SCRIPT, "--adapter", "fake", "--symbols", "SPY", "--once",
        TRADING_ARCHIVES_ROOT="/Volumes/ArchivesThatDoesNotExist",
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr


def test_a_symbol_outside_the_allowlist_is_refused():
    result = run(SCRIPT, "--adapter", "fake", "--symbols", "TSLA", "--once")

    assert result.returncode != 0
    assert "Traceback" not in result.stderr


def test_credentials_never_appear_in_output():
    result = run(
        SCRIPT, "--adapter", "fake", "--symbols", "SPY", "--once", "--json",
        ALPACA_API_KEY=SECRET_KEY, ALPACA_API_SECRET=SECRET_VALUE,
    )

    assert SECRET_KEY not in result.stdout + result.stderr
    assert SECRET_VALUE not in result.stdout + result.stderr


# --- verify_alpaca_paper ---------------------------------------------------


def test_verification_refuses_a_non_paper_endpoint_before_building_a_client():
    result = run(
        VERIFY, "--read-only",
        ALPACA_PAPER_BASE_URL="https://api.alpaca.markets",
        ALPACA_API_KEY=SECRET_KEY, ALPACA_API_SECRET=SECRET_VALUE,
    )

    assert result.returncode != 0
    assert "paper" in (result.stdout + result.stderr).lower()
    assert SECRET_KEY not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "hostile",
    [
        "https://paper-api.alpaca.markets.evil.com",
        "http://paper-api.alpaca.markets",
        "https://evil.com/?x=https://paper-api.alpaca.markets",
    ],
)
def test_verification_refuses_lookalike_endpoints(hostile):
    """Substring matching on the paper host would accept all of these."""
    result = run(
        VERIFY, "--read-only", ALPACA_PAPER_BASE_URL=hostile,
        ALPACA_API_KEY=SECRET_KEY, ALPACA_API_SECRET=SECRET_VALUE,
    )

    assert result.returncode != 0, f"{hostile} was accepted as the paper endpoint"


def test_verification_without_credentials_refuses_cleanly():
    result = run(VERIFY, "--read-only", ALPACA_API_KEY="", ALPACA_API_SECRET="")

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "credential" in (result.stdout + result.stderr).lower()


def test_submit_cancel_is_unavailable_without_credentials():
    result = run(VERIFY, "--submit-cancel", "SPY", ALPACA_API_KEY="", ALPACA_API_SECRET="")

    assert result.returncode != 0
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("override", [{"EXECUTION_MODE": "live"}, {"LIVE_TRADING_ENABLED": "true"}])
def test_verification_refuses_a_live_runtime(override):
    result = run(VERIFY, "--read-only", **override)

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
