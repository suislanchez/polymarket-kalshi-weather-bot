"""Trading runtime dependency checks for the Alpaca paper SDK.

Import-only: nothing here performs network I/O or reads credentials. alpaca-py is
a pinned SDK used to build a real paper client at runtime, not an execution path
-- orders route through PaperExecutionService and the deterministic risk gate, and
the adapter takes an injected client factory so the whole suite runs without a
live client.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_alpaca_sdk_imports_without_constructing_a_client():
    import alpaca

    assert alpaca.__version__


def test_alpaca_import_does_not_open_network_connections(monkeypatch):
    """Importing the SDK must not perform network I/O."""
    attempted: list[object] = []

    def refusing_connect(self, address):  # pragma: no cover - guard path
        attempted.append(address)
        raise AssertionError(f"network connection attempted during import: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", refusing_connect)
    import importlib

    import alpaca

    importlib.reload(alpaca)
    assert attempted == []


def test_alpaca_import_does_not_require_broker_credentials():
    for name in (
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
    ):
        assert not os.environ.get(name), f"{name} must not be required or set in tests"

    import alpaca

    assert alpaca.__version__


def test_pinned_requirements_pin_alpaca_and_not_lumibot():
    compiled = (ROOT / "requirements-trading.txt").read_text().lower()
    source = (ROOT / "requirements-trading.in").read_text().lower()
    assert "alpaca-py==" in compiled
    assert "alpaca-py" in source
    # LumiBot was dropped deliberately; it must not creep back in transitively.
    assert "lumibot" not in compiled


def test_trading_runtime_does_not_disturb_the_application_stack():
    """The trading pins must never move a version the application pins."""
    app: dict[str, str] = {}
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            app[name.split("[")[0].strip().lower()] = version.strip()

    for line in (ROOT / "requirements-trading.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        key = name.split("[")[0].strip().lower()
        if key in app:
            assert version.strip() == app[key], (
                f"trading runtime would move {key} from {app[key]} to {version.strip()}"
            )


def test_readme_records_the_resolved_alpaca_version():
    import alpaca

    readme = (ROOT / "README.md").read_text()
    assert alpaca.__version__ in readme
