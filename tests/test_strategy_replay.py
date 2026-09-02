"""Replay the trend strategy over stored bars and measure whether it is worth running.

This exists because of what the weather audit found. That strategy was deployed,
traded, and lost money, and nobody measured whether its probabilities were
truthful until months later. The rule being wired now -- a 20/50 moving-average
crossover -- has no backtest either, and it is one of the most studied and most
arbitraged rules in existence. Measuring it before automating it is the whole
point of this module.

Three properties matter more than the rest, and each has a test below.

No lookahead. At bar i the replay may see bars 0..i and nothing after. A
backtest that peeks is not pessimistic or optimistic, it is meaningless.

The comparison is against buy-and-hold, not against zero. A long-only crossover
on a rising index will show a profit while underperforming simply holding the
index, and reporting only the profit turns a losing decision into a winning
headline.

Cadence changes the rule. The strategy compares two adjacent bars with no memory
of earlier state, so a crossover that happens between two evaluations is not
delayed -- it is invisible forever. Measuring at one cadence and trading at
another measures a different strategy than the one that runs.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.trading.domain import Side
from backend.trading.market_data import load_bar_series
from backend.trading.replay import (
    CadenceSample,
    ReplayResult,
    ReplayTrade,
    cadence_sensitivity,
    replay_series,
    wilson_interval,
)
from backend.trading.strategies.trend_following import TrendFollowingStrategy

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def series_from(closes, *, symbol="SPY", asset_class="stock", step=timedelta(days=1)):
    """A bar series whose closes are exactly the values given.

    Open, high and low are pinned to the close so the replay's fill price is
    unambiguous and no test result depends on an intrabar assumption.
    """
    bars = []
    for index, close in enumerate(closes):
        value = Decimal(str(close))
        bars.append(
            {
                "timestamp": (START + step * index).isoformat().replace("+00:00", "Z"),
                "open": str(value),
                "high": str(value),
                "low": str(value),
                "close": str(value),
                "volume": "1000",
            }
        )
    return load_bar_series({"symbol": symbol, "asset_class": asset_class, "bars": bars})


def ramp(start, end, count):
    """A straight line from start to end over count bars, in exact Decimals."""
    start, end = Decimal(str(start)), Decimal(str(end))
    if count == 1:
        return [start]
    step = (end - start) / (count - 1)
    return [start + step * i for i in range(count)]


def two_round_trips():
    """Down, up, down, up, down: enough for two completed buy/sell pairs.

    Note the opening leg declines rather than sitting flat. On a perfectly flat
    series the two moving averages are exactly equal, and the strategy treats
    equality as no cross on either side -- so a flat market followed by a rally
    produces no golden cross at all. That is a real property of the rule, worth
    knowing, and it means a flat warm-up makes a useless fixture.
    """
    return (
        ramp("110", "100", 60)
        + ramp("100", "140", 40)
        + ramp("140", "100", 40)
        + ramp("100", "150", 40)
        + ramp("150", "100", 40)
    )


@pytest.fixture
def strategy():
    return TrendFollowingStrategy()


# ---------------------------------------------------------------------------
# The three properties that decide whether the measurement means anything
# ---------------------------------------------------------------------------


def test_the_replay_cannot_see_past_the_bar_it_is_evaluating(strategy):
    """Truncating the future must not change the past.

    If a trade recorded at bar 120 changes when bars after 120 are removed, the
    replay is reading the future and every number it produces is fiction.
    """
    closes = two_round_trips()
    full = replay_series(series_from(closes), strategy=strategy, notional_cap=Decimal("1000"))
    assert full.trades, "fixture must produce at least one trade or this proves nothing"

    cut = len(closes) - 20
    truncated = replay_series(
        series_from(closes[:cut]), strategy=strategy, notional_cap=Decimal("1000")
    )

    kept = [t for t in full.trades if t.entry_index < cut and (t.exit_index or 0) < cut]
    assert kept, "the cut must leave at least one completed trade to compare"
    for original, replayed in zip(kept, truncated.trades):
        assert original.entry_index == replayed.entry_index
        assert original.entry_price == replayed.entry_price
        assert original.exit_index == replayed.exit_index
        assert original.exit_price == replayed.exit_price


def test_buy_and_hold_is_measured_over_the_same_span(strategy):
    """A strategy that ends flat on a rising series must show negative excess.

    This is the comparison that turns 'we made money' into 'we made less money
    than doing nothing', and it is the one a naive report omits.
    """
    # Rises throughout after a declining warm-up: holding is strictly better
    # than any round trip that exits.
    closes = ramp("110", "100", 60) + ramp("100", "200", 120)
    result = replay_series(series_from(closes), strategy=strategy, notional_cap=Decimal("1000"))

    assert result.buy_and_hold_return > 0
    assert result.excess_return == result.strategy_return - result.buy_and_hold_return
    assert result.first_evaluable_index == strategy.slow_window

    # Assert the benchmark is COMPUTED from the first evaluable bar, not merely
    # that the index is reported. Checking the reported field alone passes for a
    # benchmark measured from bar 0, which flatters or penalises the strategy by
    # charging it for a warm-up it was never allowed to trade. The fixture's
    # warm-up declines, so the two starting points give different answers.
    series = series_from(closes)
    entry = series.bars[strategy.slow_window].close
    expected = (series.bars[-1].close - entry) / entry
    assert result.buy_and_hold_return == pytest.approx(expected, rel=Decimal("1e-20"))

    from_bar_zero = (series.bars[-1].close - series.bars[0].close) / series.bars[0].close
    assert result.buy_and_hold_return != from_bar_zero, (
        "fixture must distinguish the two starting points or this asserts nothing"
    )


def test_evaluating_less_often_silently_loses_signals(strategy):
    """The finding that makes cadence a correctness issue, not a tuning knob.

    _crossover compares two adjacent bars and keeps no memory of the earlier
    relationship, so a cross that happens between evaluations is never seen
    again. This is not a delay; the signal is destroyed.
    """
    closes = two_round_trips()
    series = series_from(closes)

    every_bar = replay_series(series, strategy=strategy, notional_cap=Decimal("1000"))
    every_fifth = replay_series(
        series, strategy=strategy, notional_cap=Decimal("1000"), every_n_bars=5
    )

    assert every_bar.signals > every_fifth.signals, (
        "if these are equal the fixture does not exercise the defect"
    )

    samples = cadence_sensitivity(
        series, strategy=strategy, notional_cap=Decimal("1000"), cadences=(1, 2, 5, 10)
    )
    assert [s.every_n_bars for s in samples] == [1, 2, 5, 10]
    assert samples[0].signals_lost == 0
    assert samples[0].fraction_lost == Decimal("0")
    assert samples[-1].signals_lost > 0
    # Monotone: evaluating less often can never find MORE signals.
    assert all(
        later.signals <= earlier.signals for earlier, later in zip(samples, samples[1:])
    )


# ---------------------------------------------------------------------------
# Trade accounting
# ---------------------------------------------------------------------------


def test_a_completed_round_trip_is_priced_off_the_signal_bar(strategy):
    closes = two_round_trips()
    result = replay_series(series_from(closes), strategy=strategy, notional_cap=Decimal("1000"))

    assert result.round_trips >= 1
    first = result.trades[0]
    assert first.side is Side.BUY
    assert first.exit_index is not None and first.exit_index > first.entry_index
    # Filled at the close of the bar that produced the signal.
    assert first.entry_price == series_from(closes).bars[first.entry_index].close
    assert first.exit_price == series_from(closes).bars[first.exit_index].close
    # Quantity is the cap divided by the entry price, floored to the increment.
    assert first.quantity > 0
    assert first.quantity * first.entry_price <= Decimal("1000")


def test_an_unclosed_position_is_reported_but_not_counted_as_a_round_trip(strategy):
    """A buy with no matching sell is not a result, and must not be scored as one."""
    closes = ramp("110", "100", 60) + ramp("100", "200", 80)
    result = replay_series(series_from(closes), strategy=strategy, notional_cap=Decimal("1000"))

    open_trades = [t for t in result.trades if t.exit_index is None]
    assert open_trades, "a rising series should leave a position open at the end"
    assert result.round_trips == len([t for t in result.trades if t.exit_index is not None])
    assert result.open_position_quantity == open_trades[-1].quantity


def test_fees_are_charged_on_both_legs_and_reduce_the_result(strategy):
    closes = two_round_trips()
    series = series_from(closes)

    free = replay_series(series, strategy=strategy, notional_cap=Decimal("1000"))
    charged = replay_series(
        series, strategy=strategy, notional_cap=Decimal("1000"), fee_per_trade=Decimal("1")
    )

    legs = sum(1 for t in charged.trades) + charged.round_trips
    assert charged.fees_paid == Decimal(legs)
    assert charged.strategy_return < free.strategy_return


# ---------------------------------------------------------------------------
# Honesty of the numbers themselves
# ---------------------------------------------------------------------------


def test_the_win_rate_carries_an_interval_because_the_sample_is_tiny(strategy):
    """A 20/50 crossover on daily bars yields roughly 27 round trips a decade.

    At that sample size a bare win rate cannot distinguish an edge from a coin
    flip, and a number reported without its interval will be read as evidence.
    """
    low, high = wilson_interval(5, 10)
    assert low < Decimal("0.5") < high
    assert high - low > Decimal("0.4"), "10 trials cannot be precise; say so"

    tighter_low, tighter_high = wilson_interval(50, 100)
    assert (tighter_high - tighter_low) < (high - low)

    # Degenerate inputs must not explode or invent certainty.
    assert wilson_interval(0, 0) == (Decimal("0"), Decimal("1"))


def test_every_money_figure_is_a_decimal_never_a_float(strategy):
    result = replay_series(
        series_from(two_round_trips()), strategy=strategy, notional_cap=Decimal("1000")
    )
    money = (
        result.strategy_return,
        result.buy_and_hold_return,
        result.excess_return,
        result.max_drawdown,
        result.fees_paid,
        result.open_position_quantity,
    )
    for value in money:
        assert isinstance(value, Decimal), f"{value!r} is {type(value)}, not Decimal"
    for trade in result.trades:
        assert isinstance(trade.entry_price, Decimal)
        assert trade.exit_price is None or isinstance(trade.exit_price, Decimal)
        assert isinstance(trade.quantity, Decimal)


def test_replaying_the_same_bars_twice_gives_an_identical_result(strategy):
    series = series_from(two_round_trips())
    first = replay_series(series, strategy=strategy, notional_cap=Decimal("1000"))
    second = replay_series(series, strategy=strategy, notional_cap=Decimal("1000"))
    assert first == second


def test_max_drawdown_is_the_worst_peak_to_trough_not_the_final_loss(strategy):
    """A run that recovers still had a drawdown, and hiding it hides the risk.

    The fall has to happen while the strategy is HOLDING, or a drawdown of zero
    is the correct answer -- being out of the market during a crash is not risk
    the report should charge for.
    """
    closes = (
        ramp("110", "100", 60)
        + ramp("100", "160", 60)
        + ramp("160", "90", 50)
        + ramp("90", "165", 50)
    )
    result = replay_series(series_from(closes), strategy=strategy, notional_cap=Decimal("1000"))

    # Structural precondition: some trade must span the series high and exit
    # below it, or the strategy was never exposed to the fall and a drawdown of
    # zero would be the correct answer.
    peak_index = max(range(len(closes)), key=lambda i: closes[i])
    spans_the_top = any(
        t.entry_index <= peak_index <= (t.exit_index if t.exit_index is not None else len(closes))
        and (t.exit_price is None or t.exit_price < closes[peak_index])
        for t in result.trades
    )
    assert spans_the_top, "fixture must make the strategy hold through the series high"
    assert result.max_drawdown > 0, "holding through the top and giving it back is a drawdown"


def test_a_series_too_short_to_evaluate_reports_nothing_rather_than_zero(strategy):
    """Fewer than 51 bars is 'not measured', which is different from 'no trades'."""
    result = replay_series(
        series_from(ramp("100", "110", 30)), strategy=strategy, notional_cap=Decimal("1000")
    )
    assert result.evaluated_bars == 0
    assert result.trades == ()
    assert result.round_trips == 0
    assert result.buy_and_hold_return == Decimal("0")
    assert result.insufficient_history is True
