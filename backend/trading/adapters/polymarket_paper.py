"""Polymarket paper venue: a deterministic simulation of binary weather shares.

Polymarket's real venue is an on-chain CLOB requiring a funded wallet and signed
orders. None of that exists here and none of it may be added: this adapter
simulates fills locally so the weather research lane can run end to end without
credentials, funds, or a network path to any venue.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from decimal import Decimal

from backend.trading.adapters.prediction_paper import PredictionMarketPaperAdapter
from backend.trading.domain import PositionSnapshot, Venue

ADAPTER_NAME = "polymarket-paper"


class PolymarketPaperAdapter(PredictionMarketPaperAdapter):
    """Simulated Polymarket weather venue, pinned to ``Venue.POLYMARKET_PAPER``."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        execution_enabled: bool = True,
        cash: Decimal = Decimal("10000.00"),
        equity: Decimal = Decimal("10000.00"),
        buying_power: Decimal = Decimal("10000.00"),
        positions: Iterable[PositionSnapshot] = (),
    ) -> None:
        super().__init__(
            clock=clock,
            venue=Venue.POLYMARKET_PAPER,
            adapter_name=ADAPTER_NAME,
            execution_enabled=execution_enabled,
            cash=cash,
            equity=equity,
            buying_power=buying_power,
            positions=positions,
        )


__all__ = ["ADAPTER_NAME", "PolymarketPaperAdapter"]
