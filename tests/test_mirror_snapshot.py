"""A mirrored brokerage account is an observation, never portfolio state.

Three things this file exists to hold:

1. Raw account numbers cannot enter storage or the API. The agent masks them
   before the boundary; the boundary refuses anything that still carries one.
2. The mirror's schema is an allowlist. A broker adding a field must not leak
   it through.
3. Nothing the paper risk gate uses can read the mirror. A mirrored balance
   sized into a paper order would be the system trading against money it does
   not hold.

The fixtures use synthetic account numbers on purpose. Real ones must never be
committed, and the assertions below are exactly the ones that would catch it.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base, MirroredPortfolioSnapshot
from backend.trading.mirror import (
    MirrorValidationError,
    latest_snapshot,
    record_snapshot,
    validate_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mirror_robinhood.py"
NOW = datetime(2026, 9, 7, 0, 40, tzinfo=timezone.utc)


def account(**overrides):
    base = {
        "label": "individual",
        "account_ref": "••••6789",
        "tradable_by_agent": False,
        "currency": "USD",
        "total_value": "5673.84004803",
        "cash": "1435.21",
        "buying_power": "830.2100",
        "positions": [
            {"asset_class": "stock", "symbol": "AAPL", "quantity": "1.402732", "average_cost": "182.850000"},
        ],
    }
    base.update(overrides)
    return base


def snapshot(**overrides):
    base = {
        "venue": "robinhood",
        "captured_at": NOW.isoformat(),
        "source_agent": "test-agent",
        "accounts": [account()],
    }
    base.update(overrides)
    return base


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'mirror.sqlite'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


# --- the boundary refuses identifiers -----------------------------------------


@pytest.mark.parametrize(
    "bad_ref", ["409330651", "••••40933", "4093", "acct-409330651", ""]
)
def test_an_unmasked_or_malformed_account_ref_is_refused(bad_ref):
    with pytest.raises(MirrorValidationError):
        validate_snapshot(snapshot(accounts=[account(account_ref=bad_ref)]))


@pytest.mark.parametrize(
    "field,value",
    [("label", "individual 409330651"), ("source_agent", "agent-311161340229")],
)
def test_a_digit_run_smuggled_into_a_text_field_is_refused(field, value):
    payload = snapshot()
    if field == "label":
        payload["accounts"] = [account(label=value)]
    else:
        payload[field] = value
    with pytest.raises(MirrorValidationError):
        validate_snapshot(payload)


def test_the_error_never_echoes_the_payload():
    try:
        validate_snapshot(snapshot(accounts=[account(account_ref="409330651")]))
    except MirrorValidationError as error:
        assert "409330651" not in str(error)
        assert error.__cause__ is None
    else:
        pytest.fail("accepted an unmasked account number")


# --- the schema is an allowlist -----------------------------------------------


def test_unknown_fields_are_refused_at_every_level():
    with pytest.raises(MirrorValidationError):
        validate_snapshot({**snapshot(), "account_number": "x"})
    with pytest.raises(MirrorValidationError):
        validate_snapshot(snapshot(accounts=[{**account(), "rhc_account_number": "x"}]))
    pos = {**account()["positions"][0], "shares_held_for_sells": "0"}
    with pytest.raises(MirrorValidationError):
        validate_snapshot(snapshot(accounts=[account(positions=[pos])]))


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "abc", 12.5, None])
def test_money_and_quantity_must_be_finite_nonnegative_decimal_strings(value):
    with pytest.raises(MirrorValidationError):
        validate_snapshot(snapshot(accounts=[account(total_value=value)]))
    pos = {**account()["positions"][0], "quantity": value}
    with pytest.raises(MirrorValidationError):
        validate_snapshot(snapshot(accounts=[account(positions=[pos])]))


def test_only_mirror_venues_are_accepted():
    with pytest.raises(MirrorValidationError):
        validate_snapshot(snapshot(venue="alpaca_paper"))


def test_captured_at_must_be_timezone_aware():
    with pytest.raises(MirrorValidationError):
        validate_snapshot(snapshot(captured_at="2026-09-07T00:40:00"))


def test_a_valid_snapshot_round_trips_exactly():
    s = validate_snapshot(snapshot())
    assert s.accounts[0].total_value == "5673.84004803"
    assert s.accounts[0].positions[0].quantity == "1.402732"
    assert s.total_value == "5673.84004803"
    assert s.position_count == 1


# --- storage -----------------------------------------------------------------


def test_record_then_latest_returns_the_newest_by_capture_time(session):
    older = validate_snapshot(snapshot(captured_at="2026-09-06T00:00:00+00:00"))
    newer = validate_snapshot(snapshot(captured_at="2026-09-07T00:00:00+00:00",
                                       accounts=[account(total_value="1")]))
    record_snapshot(session, newer)
    record_snapshot(session, older)  # inserted second, but older
    session.commit()

    row = latest_snapshot(session, "robinhood")
    assert row is not None and row.total_value == "1"
    assert latest_snapshot(session, "alpaca_paper") is None


def test_stored_payload_carries_no_identifier(session):
    record_snapshot(session, validate_snapshot(snapshot()))
    session.commit()
    row = session.query(MirroredPortfolioSnapshot).one()
    # ensure_ascii=False: the default escapes the mask bullets to \u2022, and
    # "\u2022\u20226789" reads as an eight-digit run. Pydantic and Starlette
    # both emit the literal character, so this reflects what is actually stored
    # and served.
    text = json.dumps(row.payload, ensure_ascii=False)
    import re
    text = re.sub(r'"(quantity|average_cost|total_value|cash|buying_power|captured_at)": ?"[^"]*"', "", text)
    assert not re.search(r"\d{5,}", text)


# --- isolation from the risk gate ---------------------------------------------


def test_the_risk_gate_and_execution_service_cannot_see_the_mirror():
    for name in ("risk.py", "service.py", "strategies/trend_following.py"):
        source = (ROOT / "backend" / "trading" / name).read_text()
        assert "mirror" not in source.lower(), f"{name} references the mirror"
        assert "MirroredPortfolioSnapshot" not in source


# --- the agent-side mapper ---------------------------------------------------


RAW = {
    "accounts": {"accounts": [
        {"account_number": "123456789", "rhs_account_number": "123456789", "brokerage_account_type": "individual", "is_default": True, "agentic_allowed": False},
        {"account_number": "987654321", "rhs_account_number": "987654321", "brokerage_account_type": "individual", "nickname": "Agentic", "agentic_allowed": True},
    ]},
    "portfolios": {
        "123456789": {"total_value": "5673.84004803", "cash": "1435.21", "currency": "USD", "buying_power": {"buying_power": "830.2100"}},
        "987654321": {"total_value": "0", "cash": "0", "currency": "USD", "buying_power": {"buying_power": "0.0000"}},
    },
    "equity_positions": {
        "123456789": {"positions": [
            {"symbol": "AAPL", "quantity": "1.402732", "average_buy_price": "182.850000", "type": "long"},
            {"symbol": "STDN", "quantity": "0.000000", "type": "empty"},
        ]},
        "987654321": {"positions": []},
    },
    "crypto_positions": {"123456789": {"results": []}, "987654321": {"results": []}},
}


def test_the_mapper_masks_refs_and_drops_empty_positions():
    import importlib.util, sys as _sys
    spec = importlib.util.spec_from_file_location("mirror_robinhood", SCRIPT)
    mod = importlib.util.module_from_spec(spec); _sys.modules[spec.name] = mod; spec.loader.exec_module(mod)

    out = mod.map_raw(RAW, source_agent="test-agent", captured_at=NOW)
    refs = {a["account_ref"] for a in out["accounts"]}
    assert refs == {"••••6789", "••••4321"}
    by = {a["account_ref"]: a for a in out["accounts"]}
    assert [p["symbol"] for p in by["••••6789"]["positions"]] == ["AAPL"], "empty position leaked"
    assert by["••••4321"]["positions"] == []
    assert by["••••4321"]["tradable_by_agent"] is True
    assert by["••••4321"]["label"] == "agentic"
    assert "123456789" not in json.dumps(out) and "987654321" not in json.dumps(out)
    validate_snapshot(out)  # the mapped form must pass the boundary


def test_the_script_end_to_end_with_a_dry_run(tmp_path):
    raw = tmp_path / "raw.json"; raw.write_text(json.dumps(RAW))
    import os
    env = dict(os.environ); env.pop("PYTHONPATH", None); env["PYTHONPATH"] = str(ROOT)
    env.setdefault("EXECUTION_MODE", "paper"); env.setdefault("LIVE_TRADING_ENABLED", "false")
    r = subprocess.run([sys.executable, str(SCRIPT), "--from-raw", str(raw), "--source-agent", "test-agent", "--dry-run"],
                       capture_output=True, text=True, cwd=str(ROOT), env=env)
    assert r.returncode == 0, r.stderr
    assert "accounts=2 positions=1" in r.stdout
    assert "dry run: nothing written" in r.stdout
    assert "123456789" not in r.stdout + r.stderr and "987654321" not in r.stdout + r.stderr


def test_the_script_refuses_a_snapshot_with_a_raw_identifier(tmp_path):
    bad = snapshot(accounts=[account(account_ref="123456789")])
    f = tmp_path / "bad.json"; f.write_text(json.dumps(bad))
    import os
    env = dict(os.environ); env.pop("PYTHONPATH", None); env["PYTHONPATH"] = str(ROOT)
    env.setdefault("EXECUTION_MODE", "paper"); env.setdefault("LIVE_TRADING_ENABLED", "false")
    r = subprocess.run([sys.executable, str(SCRIPT), "--snapshot", str(f), "--dry-run"],
                       capture_output=True, text=True, cwd=str(ROOT), env=env)
    assert r.returncode != 0
    assert "123456789" not in r.stdout + r.stderr


# --- the API ----------------------------------------------------------------


def test_api_serves_the_latest_mirror_and_leaks_no_identifier(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api import main as m
    from backend.models import database as db

    engine = create_engine(f"sqlite:///{tmp_path / 'api.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    def override():
        s = factory()
        try: yield s
        finally: s.close()
    m.app.dependency_overrides[db.get_db] = override
    try:
        c = TestClient(m.app)
        assert c.get("/api/trading/mirror/robinhood").json() == {
            "available": False, "venue": "robinhood", "captured_at": None,
            "source_agent": None, "total_value": None, "accounts": [],
        }
        with factory() as s:
            record_snapshot(s, validate_snapshot(snapshot())); s.commit()
        r = c.get("/api/trading/mirror/robinhood")
        body = r.json()
        assert body["available"] is True
        assert body["accounts"][0]["account_ref"] == "••••6789"
        import re
        scrubbed = re.sub(r'"(quantity|average_cost|total_value|cash|buying_power|captured_at)": ?"[^"]*"', "", r.text)
        assert not re.search(r"\d{5,}", scrubbed)
        assert c.get("/api/trading/mirror/alpaca_paper").status_code == 404
    finally:
        m.app.dependency_overrides.pop(db.get_db, None)
        engine.dispose()
