#!/usr/bin/env python3
"""Verify Alpaca Paper connectivity, and refuse anything that is not paper.

    python scripts/verify_alpaca_paper.py --read-only
    python scripts/verify_alpaca_paper.py --submit-cancel SPY

The endpoint check is exact, not a substring match. ``paper-api.alpaca.markets``
appears inside ``paper-api.alpaca.markets.evil.com`` and inside a query
parameter on any host at all, so the host is parsed and compared whole, and the
scheme must be https. That check runs before a client is constructed, so a
misconfigured endpoint never receives the credentials.

Credential values are never printed. Every account identifier in the output is
truncated.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import settings  # noqa: E402
from backend.trading.adapters.alpaca_paper import PAPER_BASE_URL  # noqa: E402
from backend.trading.preflight import credentials_present, run_preflight  # noqa: E402

PAPER_HOST = urlparse(PAPER_BASE_URL).netloc


def is_paper_endpoint(url: object) -> bool:
    """Exact host and scheme. Substring matching accepts hostile lookalikes."""
    if not isinstance(url, str) or not url.strip():
        return False
    parsed = urlparse(url.strip())
    return parsed.scheme == "https" and parsed.netloc == PAPER_HOST


def redact(value: object, keep: int = 4) -> str:
    text = str(value or "")
    return f"{text[:keep]}…{len(text)}" if text else "—"


def fail(message: str) -> int:
    print(f"refused: {message}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--read-only", action="store_true")
    mode.add_argument("--submit-cancel", metavar="SYMBOL")
    args = parser.parse_args(argv)

    report = run_preflight(settings)
    if not report.ok:
        return fail("; ".join(report.failures))

    endpoint = getattr(settings, "ALPACA_PAPER_BASE_URL", "")
    if not is_paper_endpoint(endpoint):
        # Deliberately does not echo the endpoint: it came from configuration
        # and may carry a query string.
        return fail(
            f"configured endpoint is not the Alpaca paper endpoint ({PAPER_BASE_URL}); "
            "no client was constructed"
        )

    if not credentials_present(settings):
        return fail(
            "Alpaca paper credentials are absent; set ALPACA_API_KEY and "
            "ALPACA_API_SECRET (values are never printed)"
        )

    import requests

    headers = {
        "APCA-API-KEY-ID": str(settings.ALPACA_API_KEY),
        "APCA-API-SECRET-KEY": str(settings.ALPACA_API_SECRET),
    }
    account_url = f"{PAPER_BASE_URL}/v2/account"
    response = requests.get(account_url, headers=headers, timeout=30)
    if response.status_code != 200:
        return fail(f"account request returned HTTP {response.status_code}")
    account = response.json()

    print("Alpaca paper account")
    print(f"  endpoint        {PAPER_BASE_URL}")
    print(f"  account         {redact(account.get('account_number'))}")
    print(f"  status          {account.get('status')}")
    print(f"  currency        {account.get('currency')}")
    print(f"  cash            {account.get('cash')}")
    print(f"  buying power    {account.get('buying_power')}")
    print(f"  trading blocked {account.get('trading_blocked')}")

    if args.read_only:
        return 0

    symbol = args.submit_cancel
    allowlist = str(getattr(settings, "TRADING_SYMBOL_ALLOWLIST", "") or "")
    if symbol not in [part.strip() for part in allowlist.split(",")]:
        return fail(f"{symbol} is not on TRADING_SYMBOL_ALLOWLIST")

    # A far-from-market limit so the order rests rather than filling: this
    # verifies the submit/cancel round trip, not the ability to acquire a
    # position.
    quote = requests.get(
        f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest",
        headers=headers, timeout=30,
    )
    if quote.status_code != 200:
        return fail(f"latest trade request returned HTTP {quote.status_code}")
    last = quote.json().get("trade", {}).get("p")
    if last is None:
        return fail("no reference price available; refusing to size an order blindly")
    limit_price = round(float(last) * 0.5, 2)

    submit = requests.post(
        f"{PAPER_BASE_URL}/v2/orders",
        headers=headers,
        json={
            "symbol": symbol, "qty": "1", "side": "buy", "type": "limit",
            "time_in_force": "day", "limit_price": str(limit_price),
        },
        timeout=30,
    )
    if submit.status_code not in (200, 201):
        return fail(f"order submit returned HTTP {submit.status_code}")
    order = submit.json()
    order_id = order.get("id")
    print("\nsubmit")
    print(f"  order           {redact(order_id, keep=8)}")
    print(f"  status          {order.get('status')}")
    print(f"  limit           {limit_price} (deliberately far from market)")

    cancel = requests.delete(f"{PAPER_BASE_URL}/v2/orders/{order_id}", headers=headers, timeout=30)
    if cancel.status_code not in (200, 204):
        return fail(f"order cancel returned HTTP {cancel.status_code}; order {redact(order_id, 8)} may rest")
    print("cancel")
    print(f"  status          HTTP {cancel.status_code} (canceled)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
