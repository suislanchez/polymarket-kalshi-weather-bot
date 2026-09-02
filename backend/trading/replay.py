"""Replay a strategy over stored bars and measure whether it is worth running.

This is the strategy-side counterpart to ``backend.core.weather_audit``, and it
exists for the same reason that module does: the weather strategy was deployed,
traded, and lost money, and nobody measured it until long afterwards. The audit
is what eventually found the defect. This module is the equivalent instrument
for the trend lane, built before that lane trades rather than after.

Three design commitments, each of which a naive backtest gets wrong.

**No lookahead.** At bar ``i`` the replay constructs a series from bars ``0..i``
and hands the real strategy exactly that. It cannot consult a later bar because
it does not hold one. This is enforced by construction rather than by care.

**The benchmark is buy-and-hold, not zero.** A long-only crossover on a rising
market shows a profit while underperforming the market it traded. Reporting the
profit alone converts a losing decision into a winning headline, so
``excess_return`` -- the difference -- is the number this module leads with.

**Cadence is part of the rule.** ``TrendFollowingStrategy`` compares two adjacent
bars and keeps no memory of the earlier relationship, so a crossover occurring
between two evaluations is not delayed, it is destroyed. Measuring at one cadence
and trading at another measures a different strategy than the one that runs,
which is why ``cadence_sensitivity`` exists and why the report shows it.

Everything here is exact ``Decimal`` arithmetic and deterministic: the same bars
produce a byte-identical result. No clock is read, no randomness is used, and
nothing touches a network, a session, or the scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from typing import Sequence

from backend.trading.domain import Side
from backend.trading.market_data import BarSeries

__all__ = [
    "CadenceSample",
    "ReplayResult",
    "ReplayTrade",
    "cadence_sensitivity",
    "replay_series",
    "wilson_interval",
]

# Fractional shares are supported by the venues this lane targets; a floor keeps
# the notional at or under the cap the caller authorised, never above it.
DEFAULT_SHARE_INCREMENT = Decimal("0.000001")

# Wide enough that the divisions below cannot silently round a price or a ratio.
_PRECISION = 60


@dataclass(frozen=True)
class ReplayTrade:
    """One entry, and its exit if the replay ever produced one.

    ``exit_index is None`` means the position was still open when the bars ran
    out. That is reported, but it is not a result, and it is never counted as a
    round trip.
    """

    symbol: str
    side: Side
    entry_index: int
    entry_price: Decimal
    quantity: Decimal
    exit_index: int | None = None
    exit_price: Decimal | None = None
    pnl: Decimal | None = None


@dataclass(frozen=True)
class CadenceSample:
    """How many signals survive when the lane only looks every N bars."""

    every_n_bars: int
    signals: int
    signals_lost: int
    fraction_lost: Decimal


@dataclass(frozen=True)
class ReplayResult:
    symbol: str
    bars: int
    evaluated_bars: int
    first_evaluable_index: int
    insufficient_history: bool
    signals: int
    round_trips: int
    wins: int
    losses: int
    win_rate: Decimal | None
    win_rate_low: Decimal | None
    win_rate_high: Decimal | None
    strategy_return: Decimal
    buy_and_hold_return: Decimal
    excess_return: Decimal
    max_drawdown: Decimal
    fees_paid: Decimal
    open_position_quantity: Decimal
    trades: tuple[ReplayTrade, ...] = field(default_factory=tuple)


def _divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Divide in a context wide enough that the result is not silently rounded."""
    if denominator == 0:
        return Decimal("0")
    with localcontext() as context:
        context.prec = _PRECISION
        return numerator / denominator


def _floor_to(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        return value
    with localcontext() as context:
        context.prec = _PRECISION
        return (value // increment) * increment


def wilson_interval(successes: int, trials: int) -> tuple[Decimal, Decimal]:
    """A 95% Wilson score interval, returned as exact Decimals.

    A bare win rate over the handful of round trips a 20/50 crossover produces
    is indistinguishable from a coin flip, and a number printed without its
    interval gets read as evidence. With no trials the honest interval is the
    whole range, not a confident zero.
    """
    if trials <= 0:
        return (Decimal("0"), Decimal("1"))

    with localcontext() as context:
        context.prec = _PRECISION
        z = Decimal("1.959964")
        n = Decimal(trials)
        p = Decimal(successes) / n
        z2 = z * z
        denominator = 1 + z2 / n
        centre = (p + z2 / (2 * n)) / denominator
        inner = (p * (1 - p) / n) + (z2 / (4 * n * n))
        try:
            margin = (z * inner.sqrt()) / denominator
        except InvalidOperation:  # pragma: no cover - inner is non-negative by construction
            margin = Decimal("0")
        low = max(Decimal("0"), centre - margin)
        high = min(Decimal("1"), centre + margin)
    return (low, high)


def _evaluation_indices(bar_count: int, first_evaluable: int, every_n_bars: int) -> list[int]:
    if bar_count <= first_evaluable:
        return []
    step = max(1, int(every_n_bars))
    return list(range(first_evaluable, bar_count, step))


def replay_series(
    series: BarSeries,
    *,
    strategy,
    notional_cap: Decimal,
    every_n_bars: int = 1,
    fee_per_trade: Decimal = Decimal("0"),
    share_increment: Decimal = DEFAULT_SHARE_INCREMENT,
) -> ReplayResult:
    """Drive the real strategy over stored bars and score what it did.

    ``notional_cap`` doubles as the starting capital, so the strategy and the
    buy-and-hold benchmark are compared over the same money and the same span.
    """
    all_bars = series.bars
    first_evaluable = strategy.slow_window
    insufficient = len(all_bars) <= first_evaluable

    if insufficient:
        return ReplayResult(
            symbol=series.symbol,
            bars=len(all_bars),
            evaluated_bars=0,
            first_evaluable_index=first_evaluable,
            insufficient_history=True,
            signals=0,
            round_trips=0,
            wins=0,
            losses=0,
            win_rate=None,
            win_rate_low=None,
            win_rate_high=None,
            strategy_return=Decimal("0"),
            buy_and_hold_return=Decimal("0"),
            excess_return=Decimal("0"),
            max_drawdown=Decimal("0"),
            fees_paid=Decimal("0"),
            open_position_quantity=Decimal("0"),
            trades=(),
        )

    indices = _evaluation_indices(len(all_bars), first_evaluable, every_n_bars)

    cash = Decimal(notional_cap)
    position = Decimal("0")
    entry_price = Decimal("0")
    entry_index = -1
    fees = Decimal("0")
    signals = 0
    trades: list[ReplayTrade] = []

    peak = cash
    max_drawdown = Decimal("0")

    for index in indices:
        # The strategy sees bars 0..index and nothing after. Lookahead is
        # impossible here because the future is not in the object handed over.
        window = series.model_copy(update={"bars": all_bars[: index + 1]})
        bar = all_bars[index]

        signal = strategy.propose(
            window,
            now=bar.timestamp,
            notional_cap=Decimal(notional_cap),
            position_quantity=position,
        )
        proposal = signal.proposal
        if proposal is not None:
            signals += 1
            _apply_signal = True
        else:
            _apply_signal = False

        if _apply_signal and proposal.side is Side.BUY and position == 0:
            quantity = _floor_to(_divide(Decimal(notional_cap), bar.close), share_increment)
            if quantity > 0:
                cost = quantity * bar.close
                cash -= cost + fee_per_trade
                fees += fee_per_trade
                position = quantity
                entry_price = bar.close
                entry_index = index
        elif _apply_signal and proposal.side is Side.SELL and position > 0:
            proceeds = position * bar.close
            cash += proceeds - fee_per_trade
            fees += fee_per_trade
            pnl = proceeds - (position * entry_price) - (fee_per_trade * 2)
            trades.append(
                ReplayTrade(
                    symbol=series.symbol,
                    side=Side.BUY,
                    entry_index=entry_index,
                    entry_price=entry_price,
                    quantity=position,
                    exit_index=index,
                    exit_price=bar.close,
                    pnl=pnl,
                )
            )
            position = Decimal("0")
            entry_price = Decimal("0")
            entry_index = -1

        # Mark to market on EVERY evaluated bar, not only the ones that produced
        # a signal. Sampling the equity curve only at the moments the strategy
        # acted reports a drawdown of zero for a position held straight through
        # a crash -- it measures when it traded, not what it risked.
        equity = cash + position * bar.close
        if equity > peak:
            peak = equity
        elif peak > 0:
            drawdown = _divide(peak - equity, peak)
            if drawdown > max_drawdown:
                max_drawdown = drawdown

    if position > 0:
        # Reported so the reader knows capital is still committed, but never
        # scored: an unclosed position is not a result.
        trades.append(
            ReplayTrade(
                symbol=series.symbol,
                side=Side.BUY,
                entry_index=entry_index,
                entry_price=entry_price,
                quantity=position,
                exit_index=None,
                exit_price=None,
                pnl=None,
            )
        )

    final_equity = cash + position * all_bars[-1].close
    strategy_return = _divide(final_equity - Decimal(notional_cap), Decimal(notional_cap))

    # The benchmark starts where the strategy could first have acted, not at bar
    # zero -- charging the strategy for a warm-up period it was never allowed to
    # trade would flatter it.
    benchmark_entry = all_bars[first_evaluable].close
    buy_and_hold_return = _divide(all_bars[-1].close - benchmark_entry, benchmark_entry)

    closed = [t for t in trades if t.exit_index is not None]
    wins = sum(1 for t in closed if (t.pnl or Decimal("0")) > 0)
    losses = len(closed) - wins
    win_rate = _divide(Decimal(wins), Decimal(len(closed))) if closed else None
    low, high = wilson_interval(wins, len(closed)) if closed else (None, None)

    return ReplayResult(
        symbol=series.symbol,
        bars=len(all_bars),
        evaluated_bars=len(indices),
        first_evaluable_index=first_evaluable,
        insufficient_history=False,
        signals=signals,
        round_trips=len(closed),
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        win_rate_low=low,
        win_rate_high=high,
        strategy_return=strategy_return,
        buy_and_hold_return=buy_and_hold_return,
        excess_return=strategy_return - buy_and_hold_return,
        max_drawdown=max_drawdown,
        fees_paid=fees,
        open_position_quantity=position,
        trades=tuple(trades),
    )


def cadence_sensitivity(
    series: BarSeries,
    *,
    strategy,
    notional_cap: Decimal,
    cadences: Sequence[int] = (1, 2, 5, 10),
    fee_per_trade: Decimal = Decimal("0"),
) -> tuple[CadenceSample, ...]:
    """How many signals the lane destroys by looking less often.

    Evaluating every bar is the baseline because it is the only cadence at which
    the rule sees every crossing it was written to see. Anything sparser is
    measured against that, and the loss is not recoverable later: the strategy
    has no memory of a relationship it never observed.
    """
    baseline = replay_series(
        series,
        strategy=strategy,
        notional_cap=notional_cap,
        every_n_bars=1,
        fee_per_trade=fee_per_trade,
    ).signals

    samples: list[CadenceSample] = []
    for cadence in cadences:
        found = replay_series(
            series,
            strategy=strategy,
            notional_cap=notional_cap,
            every_n_bars=cadence,
            fee_per_trade=fee_per_trade,
        ).signals
        lost = max(0, baseline - found)
        samples.append(
            CadenceSample(
                every_n_bars=int(cadence),
                signals=found,
                signals_lost=lost,
                fraction_lost=_divide(Decimal(lost), Decimal(baseline)) if baseline else Decimal("0"),
            )
        )
    return tuple(samples)
