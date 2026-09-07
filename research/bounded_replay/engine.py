"""Bounded single-signal replay engine.

Mirrors the three Upthriving Strategy Lab templates (price breakout, SMA
crossover, pullback recovery) and their shared exit model (maximum hold,
percentage stop, percentage target) with fixed dollar sizing per signal.
Every trade is independent; there is no portfolio, no cash constraint.

All semantic choices that Upthriving does not document are explicit
``Semantics`` fields so calibration can search over them.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Semantics:
    entry: str = "next_close"          # next_close | signal_close
    breakout_level: str = "close"      # close | high  (what "prior N-session high" means)
    hold_count: str = "inclusive"      # inclusive: exit at entry+hold-1 (calibrated to Upthriving T1); exclusive: entry+hold
    overlap: str = "one_per_symbol"    # one_per_symbol (calibrated to T1) | independent
    shares: str = "fractional"         # fractional | whole
    cross: str = "loose"               # loose: prev fast<=slow ; strict: prev fast<slow
    recovery: str = "close_cross_slow" # close_cross_slow | fast_cross_slow | close_above_slow
    pullback_ref: str = "close"        # close | high  (what the pullback is measured from)
    pullback_mode: str = "any_in_window"  # any_in_window: some trough >= p% below an earlier high inside the lookback; depth_at_signal: prior close >= p% below the lookback high
    cost_model: str = "split"          # split: half bps each leg on that leg's notional; entry: full bps on entry notional
    warmup: str = "none"               # none: only bars inside [start,end] (Upthriving cache starts 2023-09-03); history: use earlier bars

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExitRules:
    hold: int = 30
    stop_pct: float = 0.0    # percent, 0 disables
    target_pct: float = 0.0  # percent, 0 disables
    notional: float = 1000.0
    cost_bps: float = 25.0   # round trip


@dataclass
class Trade:
    symbol: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry: float
    exit: float
    shares: float
    gross_pnl: float
    cost: float
    net_pnl: float
    sessions_held: int
    exit_reason: str

    @property
    def return_pct(self) -> float:
        base = self.shares * self.entry
        return 100.0 * self.net_pnl / base if base else 0.0


# ---------------------------------------------------------------- signals

def breakout_signals(df: pd.DataFrame, n: int, volume_multiple: float = 0.0, sem: Semantics = Semantics()) -> pd.DatetimeIndex:
    level = df["high"] if sem.breakout_level == "high" else df["close"]
    prior_high = level.shift(1).rolling(n).max()
    cond = df["close"] > prior_high
    if volume_multiple and volume_multiple > 0:
        avg_vol = df["volume"].shift(1).rolling(n).mean()
        cond &= df["volume"] >= volume_multiple * avg_vol
    return df.index[cond.fillna(False).to_numpy()]


def sma_crossover_signals(df: pd.DataFrame, fast: int, slow: int, sem: Semantics = Semantics()) -> pd.DatetimeIndex:
    if fast >= slow:
        raise ValueError("fast must be shorter than slow")
    f = df["close"].rolling(fast).mean()
    s = df["close"].rolling(slow).mean()
    now_above = f > s
    if sem.cross == "strict":
        prev_below = f.shift(1) < s.shift(1)
    else:
        prev_below = f.shift(1) <= s.shift(1)
    cond = now_above & prev_below & s.shift(1).notna()
    return df.index[cond.fillna(False).to_numpy()]


def _qualifying_pullback(ref: np.ndarray, lookback: int, pullback_pct: float) -> np.ndarray:
    """True on day t when, within the prior ``lookback`` sessions (t-lookback..t-1),
    some trough sits at least ``pullback_pct`` percent below an earlier high in that window."""
    n = len(ref)
    out = np.zeros(n, dtype=bool)
    thresh = 1.0 - pullback_pct / 100.0
    for t in range(lookback, n):
        w = ref[t - lookback : t]
        run_max = np.maximum.accumulate(w)
        dd = w / run_max
        out[t] = bool((dd <= thresh).any())
    return out


def pullback_recovery_signals(
    df: pd.DataFrame,
    lookback: int,
    pullback_pct: float,
    slow: int,
    fast: int | None = None,
    volume_multiple: float = 0.0,
    sem: Semantics = Semantics(),
) -> pd.DatetimeIndex:
    close = df["close"]
    ref = (df["high"] if sem.pullback_ref == "high" else close).to_numpy(dtype=float)
    if sem.pullback_mode == "depth_at_signal":
        ref_s = pd.Series(ref, index=df.index)
        window_high = ref_s.shift(1).rolling(lookback).max()
        pulled = (close.shift(1) / window_high - 1.0) <= -pullback_pct / 100.0
        pulled = pulled.fillna(False)
    else:
        pulled = pd.Series(_qualifying_pullback(ref, lookback, pullback_pct), index=df.index)
    s = close.rolling(slow).mean()
    if sem.recovery == "close_cross_slow":
        rec = (close > s) & (close.shift(1) <= s.shift(1))
    elif sem.recovery == "fast_cross_slow":
        if not fast:
            raise ValueError("fast window required for fast_cross_slow")
        f = close.rolling(fast).mean()
        rec = (f > s) & (f.shift(1) <= s.shift(1))
    elif sem.recovery == "close_above_slow":
        rec = close > s
    else:
        raise ValueError(f"unknown recovery mode {sem.recovery}")
    cond = pulled & rec & s.shift(1).notna()
    if volume_multiple and volume_multiple > 0:
        avg_vol = df["volume"].shift(1).rolling(lookback).mean()
        cond &= df["volume"] >= volume_multiple * avg_vol
    return df.index[cond.fillna(False).to_numpy()]


def unconditional_signals(df: pd.DataFrame, every: int = 1) -> pd.DatetimeIndex:
    """Benchmark: a signal on every ``every``-th session. With one_per_symbol overlap this is
    'always long with the same exit rules', i.e. the unconditional return of the basket + exits."""
    return df.index[::every]


def signals_for(template: str, df: pd.DataFrame, params: dict, sem: Semantics) -> pd.DatetimeIndex:
    if template == "unconditional":
        return unconditional_signals(df, int(params.get("every", 1)))
    if template == "breakout":
        return breakout_signals(df, int(params["n"]), float(params.get("volume_multiple", 0) or 0), sem)
    if template == "sma_crossover":
        return sma_crossover_signals(df, int(params["fast"]), int(params["slow"]), sem)
    if template == "pullback_recovery":
        return pullback_recovery_signals(
            df,
            int(params["lookback"]),
            float(params["pullback_pct"]),
            int(params["slow"]),
            int(params["fast"]) if params.get("fast") else None,
            float(params.get("volume_multiple", 0) or 0),
            sem,
        )
    raise ValueError(f"unknown template {template}")


# ------------------------------------------------------------- simulation

def simulate(
    symbol: str,
    df: pd.DataFrame,
    signals: Iterable[pd.Timestamp],
    rules: ExitRules,
    sem: Semantics = Semantics(),
) -> tuple[list[Trade], list[dict]]:
    """Replay each signal as an independent fixed-notional long.

    Returns (closed trades, open positions at data end). ``df`` must already
    be sliced to the evaluation window; signals must be members of its index.
    """
    closes = df["close"].to_numpy(dtype=float)
    idx = df.index
    pos = {ts: i for i, ts in enumerate(idx)}
    trades: list[Trade] = []
    open_positions: list[dict] = []
    blocked_until = -1  # index of the last exit while a position is open (one_per_symbol)
    stop_mult = 1.0 - rules.stop_pct / 100.0 if rules.stop_pct else None
    target_mult = 1.0 + rules.target_pct / 100.0 if rules.target_pct else None
    for ts in signals:
        si = pos.get(ts)
        if si is None:
            continue
        ei = si + 1 if sem.entry == "next_close" else si
        if ei >= len(idx):
            continue
        if sem.overlap == "one_per_symbol" and ei <= blocked_until:
            continue
        entry = closes[ei]
        if sem.shares == "whole":
            shares = float(np.floor(rules.notional / entry))
            if shares <= 0:
                continue
        else:
            shares = rules.notional / entry
        last_hold_i = ei + rules.hold if sem.hold_count == "exclusive" else ei + rules.hold - 1
        exit_i = None
        reason = None
        for j in range(ei + 1, min(last_hold_i, len(idx) - 1) + 1):
            c = closes[j]
            if stop_mult is not None and c <= entry * stop_mult:
                exit_i, reason = j, "stop"
                break
            if target_mult is not None and c >= entry * target_mult:
                exit_i, reason = j, "target"
                break
            if j == last_hold_i:
                exit_i, reason = j, "hold"
                break
        if exit_i is None:
            open_positions.append({"symbol": symbol, "signal_date": ts, "entry_date": idx[ei], "entry": entry, "shares": shares,
                                   "mark": closes[-1], "unrealized": shares * (closes[-1] - entry)})
            if sem.overlap == "one_per_symbol":
                blocked_until = len(idx)
            continue
        exit_px = closes[exit_i]
        gross = shares * (exit_px - entry)
        if sem.cost_model == "entry":
            cost = shares * entry * rules.cost_bps / 1e4
        else:
            cost = (shares * entry + shares * exit_px) * rules.cost_bps / 2e4
        trades.append(Trade(symbol, ts, idx[ei], idx[exit_i], entry, exit_px, shares, gross, cost, gross - cost, exit_i - ei, reason))
        if sem.overlap == "one_per_symbol":
            blocked_until = exit_i
    return trades, open_positions


def run_symbol(symbol: str, df: pd.DataFrame, template: str, params: dict, rules: ExitRules, sem: Semantics,
               start: str, end: str, warmup: int = 260) -> tuple[list[Trade], list[dict]]:
    """Compute signals with warm-up history, then simulate only inside [start, end]."""
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    window = df.loc[:end_ts] if sem.warmup == "history" else df.loc[start_ts:end_ts]
    if window.empty:
        return [], []
    sig = signals_for(template, window, params, sem)
    sig = sig[(sig >= start_ts) & (sig <= end_ts)]
    eval_df = window.loc[start_ts:end_ts]
    return simulate(symbol, eval_df, sig, rules, sem)
