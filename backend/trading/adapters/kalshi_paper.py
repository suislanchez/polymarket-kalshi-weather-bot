"""Kalshi paper venue: a deterministic simulation of binary weather contracts.

``execution_enabled`` has no default. Kalshi weather is monitor-only until its
venue calibration improves, and the caller must state which side of that boundary
it is on rather than inheriting a default it did not think about. The refusal is
independent of the scheduler's ``WEATHER_KALSHI_PAPER_EXECUTION_ENABLED`` gate:
either one alone is enough to keep the venue from simulating a fill.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from decimal import Decimal

from backend.trading.adapters.prediction_paper import PredictionMarketPaperAdapter
from backend.trading.domain import PositionSnapshot, Venue

ADAPTER_NAME = "kalshi-paper"
# Kalshi trades whole contracts. A fractional contract does not exist, so a
# notional that cannot buy one is refused rather than rounded into being.
SHARE_INCREMENT = Decimal("1")


class KalshiPaperAdapter(PredictionMarketPaperAdapter):
    """Simulated Kalshi weather venue, pinned to ``Venue.KALSHI_PAPER``."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        execution_enabled: bool,
        cash: Decimal = Decimal("10000.00"),
        equity: Decimal = Decimal("10000.00"),
        buying_power: Decimal = Decimal("10000.00"),
        positions: Iterable[PositionSnapshot] = (),
    ) -> None:
        super().__init__(
            clock=clock,
            venue=Venue.KALSHI_PAPER,
            adapter_name=ADAPTER_NAME,
            execution_enabled=execution_enabled,
            share_increment=SHARE_INCREMENT,
            cash=cash,
            equity=equity,
            buying_power=buying_power,
            positions=positions,
        )

    def __repr__(self) -> str:
        # The monitor-only state is the whole point of this venue; keep it visible.
        return (
            f"KalshiPaperAdapter(name='{ADAPTER_NAME}', venue='{Venue.KALSHI_PAPER.value}', "
            f"paper_only=True, execution_enabled={self.execution_enabled})"
        )


__all__ = ["ADAPTER_NAME", "SHARE_INCREMENT", "KalshiPaperAdapter"]
