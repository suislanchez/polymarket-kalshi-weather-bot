"""Daily bar access for the bounded replay engine.

Fetches split-adjusted daily OHLCV from Alpaca Market Data (SIP feed for
equities, the US crypto feed for pairs) and caches one CSV per symbol under
``$TRADING_ROOT/data/bars``. Research-only: this module never imports the
trading backend and never touches the ledger.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

DEFAULT_ROOT = Path("/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system")
DATA_HOST = "https://data.alpaca.markets"
EQUITY_FLOOR = date(2016, 1, 1)
CRYPTO_FLOOR = date(2021, 1, 1)
COLUMNS = ["open", "high", "low", "close", "volume", "trade_count", "vwap"]


def trading_root() -> Path:
    return Path(os.environ.get("TRADING_ROOT", str(DEFAULT_ROOT)))


def load_credentials(path: Path | None = None) -> dict[str, str]:
    """Read ALPACA_API_KEY / ALPACA_API_SECRET from the secrets env file."""
    if os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_API_SECRET"):
        return {"key": os.environ["ALPACA_API_KEY"], "secret": os.environ["ALPACA_API_SECRET"]}
    path = path or trading_root() / "secrets" / "alpaca-paper.env"
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    try:
        return {"key": values["ALPACA_API_KEY"], "secret": values["ALPACA_API_SECRET"]}
    except KeyError as exc:  # pragma: no cover - configuration error
        raise RuntimeError(f"missing {exc} in {path}") from exc


def _headers() -> dict[str, str]:
    creds = load_credentials()
    return {"APCA-API-KEY-ID": creds["key"], "APCA-API-SECRET-KEY": creds["secret"]}


def cache_path(symbol: str, asset_class: str, adjustment: str) -> Path:
    folder = trading_root() / "data" / "bars" / f"{asset_class}_1D" / adjustment
    return folder / f"{symbol.replace('/', '-')}.csv"


def _get(url: str, params: dict) -> dict:
    for attempt in range(5):
        resp = requests.get(url, params=params, headers=_headers(), timeout=30)
        if resp.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"rate limited fetching {url}")


def _frame(raw: list[dict]) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame(columns=COLUMNS, index=pd.Index([], name="date"))
    rows = [
        {
            "date": r["t"][:10],
            "open": r["o"],
            "high": r["h"],
            "low": r["l"],
            "close": r["c"],
            "volume": r["v"],
            "trade_count": r.get("n"),
            "vwap": r.get("vw"),
        }
        for r in raw
    ]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates("date").set_index("date").sort_index()
    return df[COLUMNS].astype({"open": float, "high": float, "low": float, "close": float, "volume": float})


def fetch_remote(symbol: str, asset_class: str, adjustment: str, start: date, end: date) -> pd.DataFrame:
    """Pull every daily bar from Alpaca between ``start`` and ``end`` inclusive."""
    bars: list[dict] = []
    if asset_class == "equity":
        url = f"{DATA_HOST}/v2/stocks/bars"
        params = {
            "symbols": symbol,
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": adjustment,
            "feed": "sip",
            "limit": 10000,
            "sort": "asc",
        }
        key = symbol
    elif asset_class == "crypto":
        url = f"{DATA_HOST}/v1beta3/crypto/us/bars"
        params = {
            "symbols": symbol,
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 10000,
            "sort": "asc",
        }
        key = symbol
    else:
        raise ValueError(f"unknown asset_class {asset_class!r}")
    token = None
    while True:
        if token:
            params["page_token"] = token
        payload = _get(url, params)
        bars.extend(payload.get("bars", {}).get(key, []) or [])
        token = payload.get("next_page_token")
        if not token:
            break
    return _frame(bars)


def load_daily_bars(
    symbol: str,
    *,
    asset_class: str = "equity",
    adjustment: str = "split",
    refresh: bool = False,
    end: date | None = None,
) -> pd.DataFrame:
    """Return the full cached daily history for ``symbol``.

    The cache is refetched in full when it is missing, when ``refresh`` is
    set, or when its last bar is more than one session behind ``end`` and the
    file is older than 12 hours. Split adjustment changes history
    retroactively, so partial appends are never used.
    """
    end = end or date.today()
    if asset_class == "crypto":
        adjustment = "raw"
    path = cache_path(symbol, asset_class, adjustment)
    if path.exists() and not refresh:
        df = pd.read_csv(path, parse_dates=["date"], index_col="date")
        last = df.index.max().date() if len(df) else None
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        stale = last is None or (end - last > timedelta(days=4) and age_hours > 12)
        if not stale:
            return df
    floor = CRYPTO_FLOOR if asset_class == "crypto" else EQUITY_FLOOR
    df = fetch_remote(symbol, asset_class, adjustment, floor, end)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)
    return df


def slice_window(df: pd.DataFrame, start: str | date, end: str | date) -> pd.DataFrame:
    return df.loc[pd.Timestamp(start) : pd.Timestamp(end)]


def warm_cache(symbols: list[tuple[str, str]], adjustment: str = "split") -> dict[str, int]:
    """Fetch and cache every (symbol, asset_class) pair; return bar counts."""
    counts = {}
    for symbol, asset_class in symbols:
        df = load_daily_bars(symbol, asset_class=asset_class, adjustment=adjustment)
        counts[symbol] = len(df)
    return counts
