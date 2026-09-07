#!/usr/bin/env python3
"""Push a read-only Robinhood snapshot into the trading system.

    python scripts/mirror_robinhood.py --from-raw raw.json --source-agent claude-desktop-mcp
    python scripts/mirror_robinhood.py --snapshot normalized.json

``--from-raw`` takes a JSON object with the raw outputs of the Robinhood MCP
read tools and MAPS them to the normalised form here, on the agent side,
before anything reaches the backend:

    {"accounts": <get_accounts data>,
     "portfolios": {"<account_number>": <get_portfolio data>},
     "equity_positions": {"<account_number>": <get_equity_positions data>},
     "crypto_positions": {"<rhs_account_number>": <get_crypto_positions data>}}

Account numbers are consumed here to join the pieces and are then reduced to
the last four digits. The backend refuses any snapshot that still carries one.

This script performs no writes against Robinhood. It has no order tools, and
it is not given the MCP -- it is handed JSON the agent already read.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import settings  # noqa: E402
from backend.trading.mirror import MirrorValidationError, record_snapshot, validate_snapshot  # noqa: E402
from backend.trading.preflight import run_preflight  # noqa: E402


def mask(account_number: str) -> str:
    digits = "".join(ch for ch in str(account_number) if ch.isdigit())
    return "••••" + digits[-4:] if len(digits) >= 4 else "••••0000"


def map_raw(raw: dict, *, source_agent: str, captured_at: datetime) -> dict:
    """Raw MCP read outputs -> normalised, masked snapshot. Pure; no I/O."""
    accounts_out = []
    for account in (raw.get("accounts") or {}).get("accounts", []):
        number = str(account.get("account_number", ""))
        rhs = str(account.get("rhs_account_number", number))
        portfolio = ((raw.get("portfolios") or {}).get(number) or {})
        positions = []
        for pos in ((raw.get("equity_positions") or {}).get(number) or {}).get("positions", []):
            if pos.get("type") == "empty":
                continue
            try:
                if float(pos.get("quantity", "0") or 0) <= 0:
                    continue
            except ValueError:
                continue
            positions.append(
                {
                    "asset_class": "stock",
                    "symbol": str(pos.get("symbol", "")),
                    "quantity": str(pos.get("quantity", "0")),
                    "average_cost": (
                        str(pos["average_buy_price"]) if pos.get("average_buy_price") else None
                    ),
                }
            )
        for pos in ((raw.get("crypto_positions") or {}).get(rhs) or {}).get("results", []):
            code = ((pos.get("currency") or {}).get("code") or "").strip()
            quantity = str(pos.get("quantity", "0") or "0")
            if not code or float(quantity) <= 0:
                continue
            positions.append(
                {"asset_class": "crypto", "symbol": code, "quantity": quantity, "average_cost": None}
            )
        label = (account.get("nickname") or account.get("brokerage_account_type") or "account").strip().lower()
        buying = ((portfolio.get("buying_power") or {}).get("buying_power")) or "0"
        accounts_out.append(
            {
                "label": label,
                "account_ref": mask(number),
                "tradable_by_agent": bool(account.get("agentic_allowed", False)),
                "currency": str(portfolio.get("currency") or "USD"),
                "total_value": str(portfolio.get("total_value") or "0"),
                "cash": str(portfolio.get("cash") or "0"),
                "buying_power": str(buying),
                "positions": positions,
            }
        )
    return {
        "venue": "robinhood",
        "captured_at": captured_at.isoformat(),
        "source_agent": source_agent,
        "accounts": accounts_out,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-raw", type=Path, help="raw MCP read outputs to map and push")
    group.add_argument("--snapshot", type=Path, help="an already-normalised snapshot to push")
    parser.add_argument("--source-agent", default="unknown-agent")
    parser.add_argument("--dry-run", action="store_true", help="validate and print; write nothing")
    args = parser.parse_args(argv)

    report = run_preflight(settings)
    if not report.ok:
        print(f"refused: {'; '.join(report.failures)}", file=sys.stderr)
        return 1

    if args.from_raw:
        raw = json.loads(args.from_raw.read_text())
        payload = map_raw(raw, source_agent=args.source_agent, captured_at=datetime.now(timezone.utc))
    else:
        payload = json.loads(args.snapshot.read_text())

    try:
        snapshot = validate_snapshot(payload)
    except MirrorValidationError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1

    print(f"venue={snapshot.venue} accounts={len(snapshot.accounts)} positions={snapshot.position_count} total_value={snapshot.total_value}")
    for account in snapshot.accounts:
        print(f"  {account.label:<12} {account.account_ref}  value={account.total_value:>14}  positions={len(account.positions):>3}  tradable_by_agent={account.tradable_by_agent}")
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    from backend.models.database import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        row = record_snapshot(session, snapshot)
        session.commit()
        print(f"recorded snapshot id={row.id} captured_at={row.captured_at.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
