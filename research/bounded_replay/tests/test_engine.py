"""Synthetic-bar tests for the bounded replay engine. No network, no ledger."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.bounded_replay.engine import (
    ExitRules, Semantics, breakout_signals, pullback_recovery_signals, run_symbol, simulate, sma_crossover_signals,
)
from research.bounded_replay.metrics import summarize, wilson_interval


def bars(closes, volumes=None, start="2024-01-01"):
    closes = np.asarray(closes, dtype=float)
    idx = pd.bdate_range(start, periods=len(closes))
    vol = np.asarray(volumes, dtype=float) if volumes is not None else np.full(len(closes), 1000.0)
    return pd.DataFrame({"open": closes, "high": closes * 1.01, "low": closes * 0.99, "close": closes, "volume": vol,
                         "trade_count": 1, "vwap": closes}, index=idx)


def test_breakout_needs_close_above_prior_n_max_and_cannot_see_ahead():
    closes = [10, 11, 12, 11, 11.5, 13, 12, 14]
    df = bars(closes)
    sig = breakout_signals(df, n=3)
    # day 5 (13) beats max(12,11,11.5); day 7 (14) beats max(11.5,13,12); day 2 lacks 3 prior bars
    assert list(sig) == [df.index[5], df.index[7]]


def test_breakout_volume_filter_uses_prior_n_average():
    closes = [10, 11, 12, 11, 11.5, 13, 12, 14]
    vols = [100, 100, 100, 100, 100, 150, 100, 250]
    df = bars(closes, vols)
    assert list(breakout_signals(df, n=3, volume_multiple=2.0)) == [df.index[7]]
    assert list(breakout_signals(df, n=3, volume_multiple=1.5)) == [df.index[5], df.index[7]]


def test_next_close_entry_and_hold_exit_exclusive():
    closes = [10, 10, 10, 10, 11, 12, 13, 14, 15, 16, 17]
    df = bars(closes)
    trades, opens = simulate("X", df, [df.index[3]], ExitRules(hold=3, notional=1000, cost_bps=0), Semantics(hold_count="exclusive"))
    assert not opens and len(trades) == 1
    t = trades[0]
    assert t.entry_date == df.index[4] and t.entry == 11
    assert t.exit_date == df.index[7] and t.exit == 14 and t.exit_reason == "hold"
    assert t.sessions_held == 3
    assert t.net_pnl == pytest.approx(1000 / 11 * 3)


def test_hold_inclusive_is_default_and_exits_one_session_earlier():
    df = bars([10, 10, 10, 10, 11, 12, 13, 14, 15])
    assert Semantics().hold_count == "inclusive" and Semantics().overlap == "one_per_symbol"
    trades, _ = simulate("X", df, [df.index[3]], ExitRules(hold=3, cost_bps=0), Semantics(hold_count="inclusive"))
    assert trades[0].exit_date == df.index[6]


def test_stop_and_target_are_evaluated_on_daily_close():
    df = bars([10, 10, 10, 10, 10, 9.5, 9.2, 8.9, 12])
    trades, _ = simulate("X", df, [df.index[3]], ExitRules(hold=10, stop_pct=10, cost_bps=0))
    assert trades[0].exit_reason == "stop" and trades[0].exit == 8.9
    df2 = bars([10, 10, 10, 10, 10, 10.5, 11.2, 9])
    trades2, _ = simulate("X", df2, [df2.index[3]], ExitRules(hold=10, target_pct=10, cost_bps=0))
    assert trades2[0].exit_reason == "target" and trades2[0].exit == 11.2


def test_costs_are_charged_on_both_legs():
    df = bars([10, 10, 10, 10, 10, 10, 10, 10])
    trades, _ = simulate("X", df, [df.index[2]], ExitRules(hold=2, notional=1000, cost_bps=20))
    assert trades[0].gross_pnl == 0
    assert trades[0].cost == pytest.approx(2.0)  # 10 bp on $1000 in + 10 bp on $1000 out
    assert trades[0].net_pnl == pytest.approx(-2.0)


def test_open_position_at_end_is_excluded_from_closed_trades():
    df = bars([10, 10, 10, 11, 12])
    trades, opens = simulate("X", df, [df.index[2]], ExitRules(hold=5, cost_bps=0))
    assert trades == [] and len(opens) == 1 and opens[0]["unrealized"] == pytest.approx(1000 / 11 * 1)


def test_one_per_symbol_skips_signals_while_open():
    df = bars([10] * 16)
    sigs = [df.index[1], df.index[2], df.index[3], df.index[8]]
    ind, _ = simulate("X", df, sigs, ExitRules(hold=3, cost_bps=0), Semantics(overlap="independent"))
    one, _ = simulate("X", df, sigs, ExitRules(hold=3, cost_bps=0), Semantics(overlap="one_per_symbol"))
    assert len(ind) == 4 and len(one) == 2


def test_sma_crossover_loose_vs_strict():
    closes = [10, 10, 10, 10, 10, 10, 12, 13]
    df = bars(closes)
    loose = sma_crossover_signals(df, 2, 4, Semantics(cross="loose"))
    strict = sma_crossover_signals(df, 2, 4, Semantics(cross="strict"))
    assert list(loose) == [df.index[6]]
    assert list(strict) == []  # previous day fast == slow, not strictly below


def test_pullback_recovery_requires_depth_then_reclaim():
    closes = [100, 101, 102, 100, 95, 90, 89, 91, 94, 97, 99, 101, 103]
    df = bars(closes)
    deep = pullback_recovery_signals(df, lookback=6, pullback_pct=10, slow=5)
    shallow = pullback_recovery_signals(df, lookback=6, pullback_pct=20, slow=5)
    assert len(deep) >= 1 and all(d >= df.index[7] for d in deep)
    assert len(shallow) == 0


def test_run_symbol_respects_window_and_warmup():
    closes = list(range(10, 40))
    df = bars(closes)
    start, end = str(df.index[10].date()), str(df.index[25].date())
    with_hist, _ = run_symbol("X", df, "breakout", {"n": 5}, ExitRules(hold=2, cost_bps=0), Semantics(warmup="history"), start, end)
    no_hist, _ = run_symbol("X", df, "breakout", {"n": 5}, ExitRules(hold=2, cost_bps=0), Semantics(warmup="none"), start, end)
    assert all(start <= str(t.signal_date.date()) <= end for t in with_hist)
    assert len(no_hist) < len(with_hist)


def test_replay_is_deterministic():
    rng = np.random.default_rng(7)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
    df = bars(closes, rng.integers(500, 2000, 400))
    a = simulate("X", df, breakout_signals(df, 20, 1.5), ExitRules(hold=20, stop_pct=8, target_pct=20, cost_bps=25))
    assert len(a[0]) > 0
    b = simulate("X", df, breakout_signals(df, 20, 1.5), ExitRules(hold=20, stop_pct=8, target_pct=20, cost_bps=25))
    assert [t.net_pnl for t in a[0]] == [t.net_pnl for t in b[0]]


def test_summary_metrics_and_wilson():
    lo, hi = wilson_interval(6, 10)
    assert 0.31 < lo < 0.35 and 0.83 < hi < 0.86
    df = bars([10, 10, 10, 11, 12, 13, 9, 9, 9, 9])
    trades, opens = simulate("X", df, [df.index[2], df.index[4]], ExitRules(hold=2, cost_bps=0), Semantics(overlap="independent", hold_count="exclusive"))
    m = summarize(trades, opens, index=df.index)
    assert m["trades"] == 2 and m["wins"] == 1 and m["win_rate_pct"] == 50.0
    assert m["max_drawdown_usd"] < 0 and m["profit_factor"] is not None
