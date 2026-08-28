"""LumiBot runtime smoke checks.

Import-only: this must never read credentials, construct a broker, or start
network I/O. LumiBot is a pinned dependency of the paper runtime, not an
execution path -- orders route through PaperExecutionService and the deterministic
risk gate, never through a LumiBot broker.
"""

from __future__ import annotations

import os
import socket

import pytest

lumibot = pytest.importorskip(
    "lumibot",
    reason=(
        "LumiBot install is DEFERRED: see docs/blockers/2026-08-28-lumibot-dependency.md. "
        "requirements-trading.txt pins the resolved tree; installing it into the shared "
        "environment would change 19 packages, downgrade certifi, and add 25 CVEs. These "
        "checks run as soon as the dependency decision is made."
    ),
)


def test_lumibot_imports_without_starting_a_broker():
    import lumibot

    assert lumibot.__version__


def test_lumibot_import_does_not_open_network_connections(monkeypatch):
    """Importing LumiBot must not perform network I/O."""
    opened: list[object] = []

    real_connect = socket.socket.connect

    def recording_connect(self, address):  # pragma: no cover - guard path
        opened.append(address)
        raise AssertionError(f"network connection attempted during import: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", recording_connect)
    import importlib

    import lumibot

    importlib.reload(lumibot)
    monkeypatch.setattr(socket.socket, "connect", real_connect)
    assert opened == []


def test_lumibot_import_does_not_require_broker_credentials():
    """No Alpaca or broker credential may be needed to import the runtime."""
    for name in (
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
    ):
        assert not os.environ.get(name), f"{name} must not be required or set in tests"

    import lumibot

    assert lumibot.__version__


def test_pinned_requirements_file_exists_and_pins_lumibot():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    compiled = (root / "requirements-trading.txt").read_text()
    assert "lumibot==" in compiled.lower()
    source = (root / "requirements-trading.in").read_text()
    assert "lumibot" in source.lower()


def test_readme_records_the_resolved_lumibot_version():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text()
    assert lumibot.__version__ in readme
    assert "GPL" in readme
