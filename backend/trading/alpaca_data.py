"""Alpaca historical bars, decoded exactly and shaped for the strategy loader.

This lives outside ``backend/trading/adapters/`` on purpose. That package is
under an AST policy test that pins its exact file list and allowlists its
imports, and reaching the Alpaca SDK from inside it would violate both. Market
data is a read path with no order authority, so it belongs beside the strategy
rather than beside the brokers.

**The float problem, and why the fix is two halves.** ``alpaca-py`` declares
``Bar.open/high/low/close`` as ``float``, and worse, the float appears one layer
below the model: ``alpaca/common/rest.py`` decodes every response with
``response.json()``, whose default parser turns JSON numbers into floats. So
``raw_data=True`` alone still yields floats, and building a model from Decimals
re-coerces them back. The only working path is raw mode *plus* a decoder that
parses numbers as ``Decimal`` -- both halves, or the money path silently carries
a float. Round-tripping through ``str()`` would mask the loss for two-decimal
equity prices without preventing it, so this module refuses floats instead.

**The shape problem.** Alpaca names bar fields with single letters and adds ``n``
(trade count) and ``vw`` (VWAP). ``load_bar_series`` requires exactly six named
fields and refuses both missing and unexpected keys, so the transform is load
bearing rather than cosmetic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from backend.trading.strategies.trend_following import TrendFollowingStrategy

__all__ = [
    "ALPACA_DATA_HOST",
    "AlpacaMarketDataError",
    "bars_payload_from_alpaca",
    "decimal_stock_client",
    "merge_bar_pages",
]

# Market data comes from the same host for paper and live accounts; there is no
# paper data endpoint. (DATA_SANDBOX is the Broker API sandbox, not this.)
ALPACA_DATA_HOST = "https://data.alpaca.markets"

# Alpaca field letter -> the name load_bar_series requires.
_FIELD_MAP = (("t", "timestamp"), ("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume"))


class AlpacaMarketDataError(RuntimeError):
    """Raised when a response cannot be turned into an exact, loadable series."""


def _exact(value: Any, field: str) -> str:
    """Accept only exact numeric types, and hand the loader a string.

    A float is refused rather than converted. ``str(0.3)`` happens to read
    "0.3", but the value behind it is not, and accepting it here would put an
    inexact number on a money path the rest of the system forbids.
    """
    if type(value) is float:
        raise AlpacaMarketDataError(
            f"market data field {field} arrived as a float and is not exact; "
            "the client must decode with parse_float=Decimal and raw_data=True"
        )
    if type(value) is Decimal:
        if not value.is_finite():
            raise AlpacaMarketDataError(f"market data field {field} was not finite")
        return str(value)
    if type(value) is int:
        return str(value)
    if type(value) is str and value.strip():
        return value.strip()
    raise AlpacaMarketDataError(f"market data field {field} was not an exact value")


def _timestamp(value: Any) -> str:
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise AlpacaMarketDataError("market data timestamp was not a UTC instant")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if type(value) is str and value.strip():
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise AlpacaMarketDataError("market data timestamp was not a UTC instant") from None
        if parsed.tzinfo is None:
            raise AlpacaMarketDataError("market data timestamp was not a UTC instant")
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise AlpacaMarketDataError("market data timestamp was not a UTC instant")


def merge_bar_pages(pages: Iterable[Sequence[Mapping[str, Any]]]) -> list[dict]:
    """Flatten paginated responses into one ordered, duplicate-free run.

    Alpaca can repeat the boundary bar across a page break, and the loader
    refuses a series whose timestamps are not strictly increasing, so the
    de-duplication is required rather than defensive.
    """
    seen: dict[str, dict] = {}
    for page in pages:
        for bar in page or ():
            if not isinstance(bar, Mapping):
                raise AlpacaMarketDataError("each bar must be a mapping")
            key = _timestamp(bar.get("t"))
            seen[key] = dict(bar)
    return [seen[key] for key in sorted(seen)]


def bars_payload_from_alpaca(
    symbol: str,
    asset_class: str,
    raw_bars: Sequence[Mapping[str, Any]],
) -> dict:
    """Build the exact payload ``load_bar_series`` accepts, or refuse clearly."""
    if symbol not in TrendFollowingStrategy.SUPPORTED_SYMBOLS:
        raise AlpacaMarketDataError(f"symbol {symbol!r} is not in the supported set")
    if not raw_bars:
        raise AlpacaMarketDataError(f"response carried no bars for {symbol}")

    bars: list[dict] = []
    for raw in raw_bars:
        if not isinstance(raw, Mapping):
            raise AlpacaMarketDataError("each bar must be a mapping")
        missing = [letter for letter, _ in _FIELD_MAP if letter not in raw]
        if missing:
            raise AlpacaMarketDataError(f"bar is missing required fields: {sorted(missing)}")
        bar = {"timestamp": _timestamp(raw["t"])}
        for letter, name in _FIELD_MAP:
            if name == "timestamp":
                continue
            bar[name] = _exact(raw[letter], name)
        # n and vw are deliberately absent: load_bar_series refuses unknown keys.
        bars.append(bar)

    return {"symbol": symbol, "asset_class": asset_class, "bars": bars}


def decimal_stock_client(*, api_key: str, secret_key: str):
    """An Alpaca stock-data client whose JSON numbers decode as Decimal.

    Imported lazily so this module stays importable, and its pure transform
    stays testable, in an environment where the SDK is absent.

    Both halves are required. ``raw_data=True`` bypasses the float-typed ``Bar``
    model, and the ``_one_request`` override replaces the decode point that
    produces the floats in the first place. Either alone still yields floats.
    """
    import json

    from alpaca.data.historical.stock import StockHistoricalDataClient

    class _DecimalStockHistoricalDataClient(StockHistoricalDataClient):
        def _one_request(self, method, url, opts, retry):  # noqa: ANN001 - SDK signature
            response = self._session.request(method, url, **opts)
            # Keep the SDK's retry semantics for 429/504 by raising as it does.
            response.raise_for_status()
            if response.text != "":
                return json.loads(response.text, parse_float=Decimal)
            return None

    return _DecimalStockHistoricalDataClient(
        api_key=api_key, secret_key=secret_key, raw_data=True
    )
