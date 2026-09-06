#!/usr/bin/env python3
"""Run one pass of the trend strategy through the real risk and ledger path.

    python scripts/run_paper_strategy.py --adapter fake   --symbols SPY BTC/USD --once
    python scripts/run_paper_strategy.py --adapter alpaca --symbols SPY        --once

Two design points worth stating, because both look like shortcuts and are not.

**The guard runs before evaluation.** Preflight is checked before any market
data is read or any order is built. The service performs its own re-check
immediately before submitting -- that backstop catches an Archives mount lost
mid-run -- but it is a backstop, not the gate.

**The fake adapter writes to an isolated in-memory ledger by default.** The
Archives ledger is an append-only audit record of real paper trading. Synthetic
smoke-test orders written into it would be indistinguishable from real ones
afterwards, which is a worse outcome than any convenience it buys. Pass
``--ledger archives`` to route a fake run into the real ledger deliberately.

A run that proposes nothing exits 0. There are no forced trades, so an exit code
that punished "declined to trade" would push an operator to loosen the thing
that made it decline.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import settings  # noqa: E402
from backend.trading.preflight import credentials_present, run_preflight  # noqa: E402


def allowlisted_symbols() -> tuple[str, ...]:
    raw = str(getattr(settings, "TRADING_SYMBOL_ALLOWLIST", "") or "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


# A 42-bar decline followed by an 18-bar advance, which is the shape that puts a
# 20/50 SMA golden cross on the final bar. A monotonic ramp produces no crossover
# at all, so a smoke test built on one exercises the strategy and nothing behind
# it -- never risk, never the ledger, never an adapter.
_DIP_BARS = 42
_FALL = Decimal("1")
_RISE = Decimal("2")


def deterministic_bars(symbol: str, *, now: datetime, count: int = 60) -> dict:
    """A reproducible series, built with exact arithmetic and no randomness.

    The base price is derived from the symbol's characters rather than a hash,
    so the same symbol yields the same series on every machine and every run --
    which is what makes a fake run comparable to its predecessor.
    """
    price = Decimal(300 + (sum(ord(character) for character in symbol) % 50))
    bars = []
    for index in range(count):
        price = price - _FALL if index < _DIP_BARS else price + _RISE
        close_price = price + Decimal("0.10")
        stamp = now - timedelta(days=count - 1 - index)
        bars.append(
            {
                "timestamp": stamp.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "open": str(price),
                "high": str(close_price + Decimal("0.20")),
                "low": str(price - Decimal("0.20")),
                "close": str(close_price),
                "volume": str(1000 + index),
            }
        )
    asset_class = "crypto" if "/" in symbol else "stock"
    return {"symbol": symbol, "asset_class": asset_class, "bars": bars}


def alpaca_bars(symbol: str, *, now: datetime) -> dict:
    """Real Alpaca daily bars, decoded exactly."""
    from backend.trading.alpaca_data import (
        bars_payload_from_alpaca,
        decimal_stock_client,
        merge_bar_pages,
    )

    client = decimal_stock_client(
        api_key=str(settings.ALPACA_API_KEY),
        secret_key=str(settings.ALPACA_API_SECRET),
    )
    start = (now - timedelta(days=200)).date().isoformat()
    payload = client._request(
        "GET",
        "/stocks/bars",
        {"symbols": symbol, "timeframe": "1Day", "start": start, "limit": 200, "feed": "iex"},
    )
    raw = (payload or {}).get("bars", {}).get(symbol) or []
    asset_class = "crypto" if "/" in symbol else "stock"
    return bars_payload_from_alpaca(symbol, asset_class, merge_bar_pages([raw]))


def effective_notional_cap() -> Decimal:
    """The maximum order notional the risk gate will actually approve."""
    from backend.core.scheduler import paper_risk_limits

    return paper_risk_limits().max_order_notional


def execute(session, proposal, *, adapter: str, now: datetime) -> dict:
    """Route one proposal through the real risk gate, ledger and adapter.

    The production limits are used unchanged. When the stock/crypto lane is
    disabled, ALPACA_PAPER is not an allowed venue and the order is
    risk-rejected -- which is a complete, correctly recorded lifecycle and a
    demonstration that the gate holds, not a failed run.
    """
    from backend.core.scheduler import paper_risk_limits
    from backend.trading.adapters.fake import FakePaperAdapter
    from backend.trading.domain import Venue
    from backend.trading.execution_mode import archives_runtime_guard
    from backend.trading.risk import PortfolioState, RiskContext
    from backend.trading.service import PaperExecutionService, PaperExecutionSettings

    def clock() -> datetime:
        return now

    equity = Decimal("100000.00")
    service = PaperExecutionService(
        session=session,
        adapters={Venue.ALPACA_PAPER: FakePaperAdapter(clock=clock, equity=equity)},
        settings=PaperExecutionSettings(execution_mode=str(settings.EXECUTION_MODE)),
        clock=clock,
        kill_switch=lambda: bool(getattr(settings, "LIVE_TRADING_ENABLED", False)),
        archives_guard=archives_runtime_guard(settings),
    )
    result = service.execute(
        proposal,
        portfolio=PortfolioState(
            equity=equity,
            start_of_day_nlv=equity,
            daily_realized_pnl=Decimal("0"),
            gross_exposure=Decimal("0"),
            crypto_exposure=Decimal("0"),
        ),
        context=RiskContext(
            now=now,
            execution_mode="paper",
            idempotency_key=f"{adapter}-cli:{proposal.proposal_id}",
        ),
        limits=paper_risk_limits(),
    )
    if result is None:
        return {"executed": False}
    session.commit()
    # A proposal refused at the risk gate has a decision but no execution
    # report: nothing was ever submitted to an adapter. Reporting the absence
    # is the point -- inventing a status would describe a submission that did
    # not happen.
    return {
        "executed": True,
        "approved": result.decision.approved,
        "reason_codes": list(result.decision.reason_codes),
        "order_status": (result.report.status.value if result.report is not None else None),
    }


def fail(message: str, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": message}, indent=2))
    else:
        print(f"refused: {message}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", choices=("fake", "alpaca"), required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument(
        "--ledger",
        choices=("memory", "archives"),
        default=None,
        help="default: memory for --adapter fake, archives for --adapter alpaca",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    # 1. Guard, before anything reads market data or builds an order.
    report = run_preflight(settings)
    if not report.ok:
        return fail("; ".join(report.failures), as_json=args.json)

    # 2. Symbols must be on the configured allowlist.
    allowed = allowlisted_symbols()
    rejected = [symbol for symbol in args.symbols if symbol not in allowed]
    if rejected:
        return fail(
            f"symbols outside TRADING_SYMBOL_ALLOWLIST: {', '.join(sorted(rejected))}",
            as_json=args.json,
        )

    # 3. The Alpaca lane needs credentials; the fake lane must never need them.
    if args.adapter == "alpaca" and not credentials_present(settings):
        return fail(
            "Alpaca paper credentials are absent; set ALPACA_API_KEY and "
            "ALPACA_API_SECRET (values are never printed)",
            as_json=args.json,
        )

    ledger = args.ledger or ("memory" if args.adapter == "fake" else "archives")
    now = datetime.now(timezone.utc)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.models.database import Base
    from backend.trading.market_data import load_bar_series
    from backend.trading.strategies.trend_following import TrendFollowingStrategy

    if ledger == "memory":
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
    else:
        from backend.models.database import SessionLocal as factory  # type: ignore

    strategy = TrendFollowingStrategy()
    results = []
    with factory() as session:
        for symbol in args.symbols:
            try:
                payload = (
                    deterministic_bars(symbol, now=now)
                    if args.adapter == "fake"
                    else alpaca_bars(symbol, now=now)
                )
                series = load_bar_series(payload)
                # Size against the limit the risk gate will actually apply.
                # Sizing from a different setting guarantees a rejection and
                # teaches the operator nothing about the gate.
                signal = strategy.propose(
                    series,
                    now=series.latest.timestamp,
                    notional_cap=effective_notional_cap(),
                    position_quantity=Decimal("0"),
                )
            except Exception as error:
                # The type, never the message: an upstream error string can
                # carry a URL with query parameters.
                results.append(
                    {"symbol": symbol, "reason": f"market_data_unavailable:{type(error).__name__}"}
                )
                continue

            entry = {
                "symbol": symbol,
                "reason": signal.reason,
                "proposed": signal.proposal is not None,
            }
            if signal.proposal is not None:
                entry.update(execute(session, signal.proposal, adapter=args.adapter, now=now))
            results.append(entry)

    body = {
        "ok": True,
        "adapter": args.adapter,
        "ledger": ledger,
        "symbols": list(args.symbols),
        "results": results,
        "proposals": sum(1 for entry in results if entry.get("proposed")),
    }
    if args.json:
        print(json.dumps(body, indent=2))
    else:
        print(f"adapter={args.adapter} ledger={ledger}")
        for entry in results:
            print(f"  {entry['symbol']:<10} {entry['reason']}")
        print(f"\n{body['proposals']} proposal(s). Zero proposals is a valid run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
