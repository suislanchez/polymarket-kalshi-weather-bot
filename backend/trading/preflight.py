"""Answer one question: is it safe to let this process trade on paper?

Every operator command in this system runs these checks before doing anything
else, which is the point -- a guard that each script reimplements is a guard
that drifts. The checks are ordered cheapest-and-most-fatal first: a live
execution mode makes the rest irrelevant.

Absent broker credentials are deliberately NOT a failure. The system is meant to
be operable, testable and verifiable before Alpaca keys exist, so credential
readiness is a reported field rather than a gate. Nothing here ever puts a
credential value into the report; only whether both halves are non-empty.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.trading.execution_mode import (
    KILL_SWITCH_SOURCE,
    ArchivesRuntimeError,
    ExecutionModeError,
    archives_required_directories,
    archives_runtime_paths,
    kill_switch_engaged,
    require_archives_runtime,
    require_paper_mode,
)

# Venues this runtime knows about. Robinhood and Coinbase are absent on purpose:
# they are deferred, and a preflight that listed them would imply they are
# reachable.
KNOWN_VENUES = ("alpaca_paper", "polymarket_paper", "kalshi_paper")


@dataclass
class Preflight:
    paper_mode: bool = False
    paper_mode_error: str | None = None
    archives: dict[str, bool] = field(default_factory=dict)
    database: dict[str, Any] = field(default_factory=dict)
    dependencies: dict[str, bool] = field(default_factory=dict)
    kill_switch: dict[str, Any] = field(default_factory=dict)
    adapters: list[dict[str, Any]] = field(default_factory=list)
    credential_ready: bool = False
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "paper_mode": self.paper_mode,
            "paper_mode_error": self.paper_mode_error,
            "archives": self.archives,
            "database": self.database,
            "dependencies": self.dependencies,
            "kill_switch": self.kill_switch,
            "adapters": self.adapters,
            "credential_ready": self.credential_ready,
            "failures": self.failures,
            "ok": self.ok,
        }


def _archives(settings) -> tuple[dict[str, bool], str | None]:
    binding = {
        "root_configured": False,
        "root_available": False,
        "runtime_paths_contained": False,
        "required_directories_present": False,
    }
    root = str(getattr(settings, "TRADING_ARCHIVES_ROOT", "") or "").strip()
    binding["root_configured"] = bool(root)
    if not root:
        return binding, "Archives root is not configured"
    try:
        require_archives_runtime(
            root,
            archives_runtime_paths(settings),
            required_directories=archives_required_directories(settings),
        )
    except ArchivesRuntimeError as error:
        # The message names the setting boundary, never the offending path.
        return binding, str(error)
    except Exception:
        return binding, "Archives runtime check could not be completed"
    binding.update(
        root_available=True,
        runtime_paths_contained=True,
        required_directories_present=True,
    )
    return binding, None


def _database(settings) -> tuple[dict[str, Any], str | None]:
    url = str(getattr(settings, "DATABASE_URL", "") or "")
    if not url.startswith("sqlite"):
        # Nothing to integrity-check, and the URL may carry credentials, so it
        # is reported by kind rather than echoed.
        return {"kind": "non-sqlite", "integrity": "skipped"}, None
    path = Path(url.split("sqlite:///")[-1])
    if not path.exists():
        return {"kind": "sqlite", "integrity": "missing"}, "ledger database is missing"
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        return {"kind": "sqlite", "integrity": "unreadable"}, "ledger database is unreadable"
    verdict = row[0] if row else "unknown"
    failure = None if verdict == "ok" else "ledger database failed its integrity check"
    return {"kind": "sqlite", "integrity": verdict}, failure


def _dependencies() -> dict[str, bool]:
    names = ("alpaca", "fastapi", "sqlalchemy", "pydantic", "httpx")
    found: dict[str, bool] = {}
    for name in names:
        try:
            __import__(name)
            found[name] = True
        except Exception:
            found[name] = False
    return found


def _adapters(settings) -> list[dict[str, Any]]:
    stock_lane = bool(getattr(settings, "STOCK_CRYPTO_LANE_ENABLED", False))
    kalshi_exec = bool(getattr(settings, "WEATHER_KALSHI_PAPER_EXECUTION_ENABLED", False))
    return [
        {
            "venue": "alpaca_paper",
            "simulation": False,
            "execution_enabled": stock_lane,
            "monitor_only": not stock_lane,
        },
        {
            "venue": "polymarket_paper",
            "simulation": True,
            "execution_enabled": True,
            "monitor_only": False,
        },
        {
            "venue": "kalshi_paper",
            "simulation": True,
            "execution_enabled": kalshi_exec,
            "monitor_only": not kalshi_exec,
        },
    ]


def credentials_present(settings) -> bool:
    """Both halves, non-empty. The values are never returned or logged."""
    key = str(getattr(settings, "ALPACA_API_KEY", "") or "").strip()
    secret = str(getattr(settings, "ALPACA_API_SECRET", "") or "").strip()
    return bool(key) and bool(secret)


def run_preflight(settings) -> Preflight:
    report = Preflight()

    try:
        require_paper_mode(
            getattr(settings, "EXECUTION_MODE", None),
            bool(getattr(settings, "LIVE_TRADING_ENABLED", False)),
        )
        report.paper_mode = True
    except ExecutionModeError as error:
        report.paper_mode = False
        report.paper_mode_error = str(error)
        report.failures.append("execution mode is not paper-only")

    report.archives, archives_failure = _archives(settings)
    if archives_failure:
        report.failures.append(archives_failure)

    report.database, database_failure = _database(settings)
    if database_failure:
        report.failures.append(database_failure)

    report.dependencies = _dependencies()
    for name, present in report.dependencies.items():
        if not present:
            report.failures.append(f"dependency not importable: {name}")

    # An engaged kill switch is a deliberate operator state, not a broken
    # runtime, so it is reported and does not fail preflight.
    #
    # Both the state and the reported name come from execution_mode, which is
    # also what the execution service is built with. Computing this locally is
    # how preflight came to print "ENGAGED" for a flag that stopped nothing.
    report.kill_switch = {
        "engaged": kill_switch_engaged(settings),
        "source": KILL_SWITCH_SOURCE,
    }

    report.adapters = _adapters(settings)
    report.credential_ready = credentials_present(settings)
    return report


def render(report: Preflight) -> str:
    lines = ["Trading preflight", "=" * 40]
    lines.append(f"paper mode          {'yes' if report.paper_mode else 'NO'}")
    lines.append(f"archives available  {'yes' if report.archives.get('root_available') else 'NO'}")
    lines.append(f"ledger integrity    {report.database.get('integrity', 'unknown')}")
    lines.append(
        f"kill switch         {'ENGAGED' if report.kill_switch.get('engaged') else 'disengaged'}"
    )
    missing = [name for name, ok in report.dependencies.items() if not ok]
    lines.append(f"dependencies        {'all importable' if not missing else 'MISSING: ' + ', '.join(missing)}")
    # Presence only. The values are never read into this report.
    lines.append(
        f"credential ready    {'yes' if report.credential_ready else 'no (Alpaca keys absent)'}"
    )
    lines.append("")
    lines.append("adapters")
    for adapter in report.adapters:
        state = "execution enabled" if adapter["execution_enabled"] else "monitor only"
        kind = "simulation" if adapter["simulation"] else "paper broker"
        lines.append(f"  {adapter['venue']:<20} {kind}, {state}")
    if report.failures:
        lines.append("")
        lines.append("FAILURES")
        for failure in report.failures:
            lines.append(f"  - {failure}")
    return "\n".join(lines)


__all__ = ["KNOWN_VENUES", "Preflight", "credentials_present", "render", "run_preflight"]
