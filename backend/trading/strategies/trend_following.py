"""Deterministic 20/50 simple-moving-average crossover proposal generation.

This module PROPOSES ONLY. It holds no broker reference, no database handle and no
credentials, and it cannot submit anything: a proposal still has to pass the
deterministic risk gate and the execution service before it becomes an order.

Determinism is a hard requirement. Identical inputs must produce a byte-identical
serialized proposal, so every value is derived from the bars and the caller's
arguments -- never from wall-clock time, randomness, or iteration order. Moving
averages are compared by cross-multiplication rather than division, so the
comparison is exact and no rounding policy is needed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import (
    Clamped,
    Context,
    Decimal,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Underflow,
    localcontext,
)

from backend.trading.domain import (
    AssetClass,
    Side,
    TradeProposal,
    Venue,
)
from backend.trading.market_data import BarSeries

STRATEGY_ID = "trend-following-sma"


@dataclass(frozen=True)
class StrategySignal:
    """A proposal, or an explicit machine-readable reason there is none."""

    proposal: TradeProposal | None
    reason: str


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class TrendFollowingStrategy:
    """Fixed-rule SMA crossover over a validated bar series."""

    SUPPORTED_SYMBOLS: frozenset[str] = frozenset({"SPY", "QQQ", "BTC/USD", "ETH/USD"})

    def __init__(
        self,
        *,
        fast_window: int = 20,
        slow_window: int = 50,
        max_bar_age: timedelta = timedelta(seconds=30),
    ) -> None:
        if type(fast_window) is not int or type(slow_window) is not int:
            raise ValueError("moving-average windows must be integers")
        if fast_window < 1 or slow_window <= fast_window:
            raise ValueError("slow window must exceed a positive fast window")
        if type(max_bar_age) is not timedelta or max_bar_age < timedelta(0):
            raise ValueError("max bar age must be a non-negative timedelta")
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.max_bar_age = max_bar_age

    @staticmethod
    def _exact_context(values: tuple[Decimal, ...], window: int) -> Context:
        """A context wide enough that summing and scaling `values` cannot round.

        The ambient process context is NOT trusted: a caller running at reduced
        precision must never change which signal this strategy reports.
        """
        widest = max((len(v.as_tuple().digits) for v in values), default=1)
        # digits for the widest value, plus room for the sum and the window scaling
        return Context(
            prec=widest + len(str(len(values))) + len(str(window)) + 16,
            traps=[Inexact, Rounded, Clamped, Overflow, Underflow, InvalidOperation],
        )

    def _crossover(self, closes: tuple[Decimal, ...]) -> str:
        """Compare SMAs exactly: fast/f vs slow/s becomes fast*s vs slow*f.

        Cross-multiplication avoids division entirely, so there is no rounding
        policy to get wrong, and the whole comparison runs in a pinned context.
        """
        fast, slow = self.fast_window, self.slow_window
        failed = False
        previous: Decimal | None = None
        current: Decimal | None = None
        try:
            with localcontext(self._exact_context(closes, slow)):
                current_fast = sum(closes[-fast:], Decimal(0))
                current_slow = sum(closes[-slow:], Decimal(0))
                previous_fast = sum(closes[-fast - 1 : -1], Decimal(0))
                previous_slow = sum(closes[-slow - 1 : -1], Decimal(0))
                previous = previous_fast * slow - previous_slow * fast
                current = current_fast * slow - current_slow * fast
        except Exception:
            failed = True
        if failed or previous is None or current is None:
            return "indeterminate_signal"

        if previous <= 0 and current > 0:
            return "golden_cross"
        if previous >= 0 and current < 0:
            return "death_cross"
        return "no_crossover"

    def _proposal_id(self, series: BarSeries, side: Side, reason: str) -> str:
        """Deterministic identity: same inputs, same id, on every machine and run."""
        material = "\x1f".join(
            (
                STRATEGY_ID,
                series.symbol,
                side.value,
                reason,
                _timestamp(series.latest.timestamp),
                str(self.fast_window),
                str(self.slow_window),
            )
        ).encode("utf-8")
        return f"trend-{hashlib.sha256(material).hexdigest()[:32]}"

    def propose(
        self,
        series: BarSeries,
        *,
        now: datetime,
        notional_cap: Decimal,
        position_quantity: Decimal,
    ) -> StrategySignal:
        """Return a typed proposal, or a reason why none is warranted."""

        if type(series) is not BarSeries:
            return StrategySignal(None, "invalid_series")
        if series.symbol not in self.SUPPORTED_SYMBOLS:
            return StrategySignal(None, "symbol_not_supported")
        if type(notional_cap) is not Decimal or not notional_cap.is_finite() or notional_cap <= 0:
            return StrategySignal(None, "invalid_notional_cap")
        if (
            type(position_quantity) is not Decimal
            or not position_quantity.is_finite()
            or position_quantity < 0
        ):
            return StrategySignal(None, "invalid_position_quantity")
        if type(now) is not datetime or now.tzinfo is None:
            return StrategySignal(None, "invalid_clock")

        # One extra bar is required beyond the slow window so the PREVIOUS
        # relationship is defined; without it a cross cannot be distinguished
        # from a series that merely starts on the far side.
        if len(series.bars) <= self.slow_window:
            return StrategySignal(None, "insufficient_history")

        latest = series.latest
        age = now - latest.timestamp
        if age < timedelta(0):
            return StrategySignal(None, "market_data_not_yet_valid")
        if age > self.max_bar_age:
            return StrategySignal(None, "market_data_stale")

        reason = self._crossover(series.closes())
        if reason in {"no_crossover", "indeterminate_signal"}:
            return StrategySignal(None, reason)

        side = Side.BUY if reason == "golden_cross" else Side.SELL
        if side is Side.SELL and position_quantity <= 0:
            # Long-only: a sell may reduce an existing position, never open a short.
            return StrategySignal(None, "no_long_to_reduce")

        rationale = (
            f"{self.fast_window}/{self.slow_window} SMA {reason} on {series.symbol} "
            f"at bar {_timestamp(latest.timestamp)}; close={latest.close}"
        )
        proposal = TradeProposal(
            proposal_id=self._proposal_id(series, side, reason),
            strategy_id=STRATEGY_ID,
            venue=Venue.ALPACA_PAPER,
            asset_class=series.asset_class,
            symbol=series.symbol,
            side=side,
            # Buys are sized by the caller's cap; sells reduce exactly what is held.
            notional=notional_cap if side is Side.BUY else None,
            quantity=None if side is Side.BUY else position_quantity,
            reference_price=latest.close,
            market_data_at=latest.timestamp,
            created_at=latest.timestamp,
            rationale=rationale,
            metadata={
                "rule": f"sma_{self.fast_window}_{self.slow_window}",
                "signal": reason,
                "bars_considered": str(len(series.bars)),
            },
        )
        return StrategySignal(proposal, reason)


__all__ = ["STRATEGY_ID", "StrategySignal", "TrendFollowingStrategy"]
