"""Dependency-light helpers for persisting BTC signal audit rows.

Keep this module free of ORM imports so cron/schema tests can verify the shape of
BTC signal rows even when optional runtime dependencies (for example SQLAlchemy)
are unavailable.
"""
from __future__ import annotations

from typing import Any


def btc_signal_to_db_kwargs(signal: Any) -> dict[str, Any]:
    """Return ORM constructor kwargs for a BTC signal row.

    The BTC lane needs persisted rows to retain the market type and event slug so
    later quote/outcome/calibration joins can distinguish BTC from weather/RT
    rows and map back to the exact 5-minute Polymarket window.
    """
    market = getattr(signal, "market", None)
    return {
        "market_ticker": str(getattr(market, "market_id", "") or ""),
        "platform": "polymarket",
        "market_type": "btc",
        "event_slug": getattr(market, "slug", None),
        "timestamp": getattr(signal, "timestamp", None),
        "direction": getattr(signal, "direction", None),
        "model_probability": getattr(signal, "model_probability", None),
        "market_price": getattr(signal, "market_probability", None),
        "edge": getattr(signal, "edge", None),
        "confidence": getattr(signal, "confidence", None),
        "kelly_fraction": getattr(signal, "kelly_fraction", None),
        "suggested_size": getattr(signal, "suggested_size", None),
        "sources": list(getattr(signal, "sources", []) or []),
        "reasoning": getattr(signal, "reasoning", "") or "",
        "executed": False,
    }
