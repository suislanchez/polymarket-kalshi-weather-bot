"""Summary statistics for bounded replays (per symbol and pooled)."""
from __future__ import annotations

import math
from collections import defaultdict

import pandas as pd

from .engine import Trade


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a win rate; mirrors backend/trading/replay.py."""
    if trials <= 0:
        return (0.0, 0.0)
    p = successes / trials
    denom = 1 + z * z / trials
    centre = p + z * z / (2 * trials)
    spread = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return ((centre - spread) / denom, (centre + spread) / denom)


def drawdown(trades: list[Trade], reference_capital: float) -> tuple[float, float]:
    """Peak-to-trough on the cumulative closed-trade P&L path ordered by exit date.
    Returns (dollars, percent of reference capital plus peak P&L)."""
    if not trades:
        return 0.0, 0.0
    ordered = sorted(trades, key=lambda t: (t.exit_date, t.entry_date))
    equity = 0.0
    peak = 0.0
    worst = 0.0
    worst_pct = 0.0
    for t in ordered:
        equity += t.net_pnl
        peak = max(peak, equity)
        dd = equity - peak
        if dd < worst:
            worst = dd
            base = reference_capital + peak
            worst_pct = 100.0 * dd / base if base else 0.0
    return worst, worst_pct


def exposure(trades: list[Trade], open_positions: list[dict], index: pd.DatetimeIndex) -> float:
    if len(index) == 0:
        return 0.0
    held = pd.Series(False, index=index)
    for t in trades:
        held.loc[t.entry_date : t.exit_date] = True
    for o in open_positions:
        held.loc[o["entry_date"] :] = True
    return 100.0 * held.mean()


def summarize(trades: list[Trade], open_positions: list[dict], *, reference_capital: float = 5000.0,
              index: pd.DatetimeIndex | None = None) -> dict:
    n = len(trades)
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]
    rets = [t.return_pct for t in trades]
    gross_win = sum(t.net_pnl for t in wins)
    gross_loss = -sum(t.net_pnl for t in losses)
    lo, hi = wilson_interval(len(wins), n)
    dd_usd, dd_pct = drawdown(trades, reference_capital)
    avg_win = (sum(t.return_pct for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(t.return_pct for t in losses) / len(losses)) if losses else 0.0
    by_year: dict[int, dict] = defaultdict(lambda: {"trades": 0, "net_pnl": 0.0, "wins": 0})
    for t in trades:
        y = t.exit_date.year
        by_year[y]["trades"] += 1
        by_year[y]["net_pnl"] += t.net_pnl
        by_year[y]["wins"] += int(t.net_pnl > 0)
    reasons = defaultdict(int)
    for t in trades:
        reasons[t.exit_reason] += 1
    return {
        "trades": n,
        "wins": len(wins),
        "win_rate_pct": 100.0 * len(wins) / n if n else 0.0,
        "win_rate_ci95": [100 * lo, 100 * hi],
        "gross_pnl": sum(t.gross_pnl for t in trades),
        "costs": sum(t.cost for t in trades),
        "net_pnl": sum(t.net_pnl for t in trades),
        "avg_return_pct": sum(rets) / n if n else 0.0,
        "median_return_pct": float(pd.Series(rets).median()) if n else 0.0,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "payoff_ratio": (avg_win / -avg_loss) if avg_loss < 0 else None,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "max_drawdown_usd": dd_usd,
        "max_drawdown_pct": dd_pct,
        "avg_sessions_held": sum(t.sessions_held for t in trades) / n if n else 0.0,
        "exit_reasons": dict(reasons),
        "open_positions": len(open_positions),
        "open_unrealized": sum(o["unrealized"] for o in open_positions),
        "exposure_pct": exposure(trades, open_positions, index) if index is not None else None,
        "by_year": {str(k): v for k, v in sorted(by_year.items())},
    }
