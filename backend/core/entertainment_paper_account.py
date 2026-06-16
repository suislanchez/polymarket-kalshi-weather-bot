"""Paper-account helpers for Rotten Tomatoes / entertainment markets.

This module is intentionally side-effect free. It summarizes already-recorded
simulation trades without placing orders, mutating bankroll, or touching venue
credentials.
"""

import math
import sqlite3
from typing import Iterable, Mapping, Any


ENTERTAINMENT_PAPER_INITIAL_BANKROLL = 1000.0
ENTERTAINMENT_PAPER_TARGET_BANKROLL = 1100.0
ENTERTAINMENT_MARKET_TYPES = {"entertainment", "rt", "rotten_tomatoes", "box_office"}


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    if isinstance(obj, sqlite3.Row):
        return obj[name] if name in obj.keys() else default
    return getattr(obj, name, default)


def summarize_entertainment_forecast_calibration(
    settled_forecasts: Iterable[Any],
) -> dict[str, int | float | None]:
    """Compute RT/entertainment Brier/log-loss for settled forecasts only.

    Forecast calibration is observability only. It is intentionally separated
    from trades so source-resolution/backtest rows can be scored without moving
    the paper bankroll or implying actionability.
    """
    scores: list[tuple[float, float]] = []
    for forecast in settled_forecasts:
        probability = _get(forecast, "model_probability", _get(forecast, "market_probability"))
        outcome = _get(forecast, "settlement_value", _get(forecast, "resolved_yes"))
        if probability is None or outcome is None:
            continue
        try:
            p = min(max(float(probability), 1e-6), 1 - 1e-6)
            y = 1.0 if float(outcome) >= 0.5 else 0.0
        except (TypeError, ValueError):
            continue
        brier = (p - y) ** 2
        log_loss = -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
        scores.append((brier, log_loss))

    if not scores:
        return {"settled_forecasts": 0, "brier_score": None, "log_loss": None}

    return {
        "settled_forecasts": len(scores),
        "brier_score": round(sum(score[0] for score in scores) / len(scores), 4),
        "log_loss": round(sum(score[1] for score in scores) / len(scores), 4),
    }


def summarize_latest_entertainment_calibration_rows(rows: Iterable[Any]) -> dict[str, Any]:
    """Summarize the newest RT/entertainment calibration batch.

    These rows are calibration/source-resolution observability only. They are
    intentionally separate from the paper-trade ledger and default to
    ``paper_actionable=False`` even when some outcomes are scored.
    """
    rows = list(rows)
    if not rows:
        return {
            "latest_scored_at": None,
            "scoring_rows": 0,
            "pending_scoring_rows": 0,
            "settled_forecasts": 0,
            "brier_score": None,
            "log_loss": None,
            "paper_actionable": False,
            "market_scope": "rotten_tomatoes_entertainment",
            "calibration_kind": "rt_entertainment_outcome_score",
            "source_snapshot": None,
        }

    latest_scored_at = _get(rows[0], "scored_at")
    source_snapshot = _get(rows[0], "source_snapshot")
    scored_rows = []
    for row in rows:
        probability = _get(row, "model_probability", _get(row, "market_probability"))
        outcome = _get(row, "settlement_value", _get(row, "resolved_yes"))
        if probability is None or outcome is None:
            continue
        brier = _get(row, "brier_score")
        log_loss = _get(row, "log_loss")
        if brier is None or log_loss is None:
            try:
                p = min(max(float(probability), 1e-6), 1 - 1e-6)
                y = 1.0 if float(outcome) >= 0.5 else 0.0
                brier = (p - y) ** 2
                log_loss = -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
            except (TypeError, ValueError):
                continue
        scored_rows.append((float(brier), float(log_loss)))

    return {
        "latest_scored_at": latest_scored_at,
        "scoring_rows": len(rows),
        "pending_scoring_rows": len(rows) - len(scored_rows),
        "settled_forecasts": len(scored_rows),
        "brier_score": round(sum(row[0] for row in scored_rows) / len(scored_rows), 4) if scored_rows else None,
        "log_loss": round(sum(row[1] for row in scored_rows) / len(scored_rows), 4) if scored_rows else None,
        "paper_actionable": False,
        "market_scope": "rotten_tomatoes_entertainment",
        "calibration_kind": "rt_entertainment_outcome_score",
        "source_snapshot": source_snapshot,
    }


def load_latest_entertainment_calibration_summary_from_sqlite(db_path: str) -> dict[str, Any] | None:
    """Load the latest RT/entertainment calibration batch from SQLite.

    Returns ``None`` when the research DB/table/schema is absent so dashboard
    callers can treat the summary as optional instead of weakening gates.
    """
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            latest = conn.execute(
                "SELECT MAX(scored_at) FROM entertainment_forecast_calibrations"
            ).fetchone()[0]
            if latest is None:
                return summarize_latest_entertainment_calibration_rows([])
            rows = conn.execute(
                """SELECT scored_at, source_snapshot, model_probability, market_probability,
                          settlement_value, brier_score, log_loss, paper_actionable
                   FROM entertainment_forecast_calibrations
                   WHERE scored_at = ?
                   ORDER BY rowid""",
                (latest,),
            ).fetchall()
    except (sqlite3.Error, OSError):
        return None
    return summarize_latest_entertainment_calibration_rows(rows)


def summarize_entertainment_paper_account(
    trades: Iterable[Any],
    initial_bankroll: float = ENTERTAINMENT_PAPER_INITIAL_BANKROLL,
    target_bankroll: float = ENTERTAINMENT_PAPER_TARGET_BANKROLL,
    settled_forecasts: Iterable[Any] | None = None,
) -> dict:
    """Summarize the separate $1,000 -> $1,100 RT/entertainment paper account.

    Only settled simulation PnL changes current equity. Pending trades are
    visible for accounting/calibration, but they do not count as realized PnL.
    Forecast calibration fields are separate from trade PnL and may remain null
    when no settled source-resolution rows exist.
    """
    trades = list(trades)
    settled_trades = [t for t in trades if bool(_get(t, "settled", False))]
    pending_trades = [t for t in trades if not bool(_get(t, "settled", False))]

    realized_pnl = sum(float(_get(t, "pnl", 0.0) or 0.0) for t in settled_trades)
    current_equity = float(initial_bankroll) + realized_pnl
    winning_trades = sum(1 for t in settled_trades if _get(t, "result") == "win")
    win_rate = (winning_trades / len(settled_trades) * 100.0) if settled_trades else 0.0

    target_delta = max(float(target_bankroll) - float(initial_bankroll), 0.0)
    progress = 100.0 if target_delta == 0 else ((current_equity - float(initial_bankroll)) / target_delta) * 100.0
    progress = min(100.0, max(0.0, progress))
    calibration = summarize_entertainment_forecast_calibration(settled_forecasts or [])

    return {
        "initial_bankroll": float(initial_bankroll),
        "target_bankroll": float(target_bankroll),
        "current_equity": round(current_equity, 2),
        "realized_pnl": round(realized_pnl, 2),
        "remaining_to_target": round(max(float(target_bankroll) - current_equity, 0.0), 2),
        "progress_to_target_pct": round(progress, 2),
        "total_trades": len(trades),
        "settled_trades": len(settled_trades),
        "pending_trades": len(pending_trades),
        "winning_trades": winning_trades,
        "win_rate": round(win_rate, 2),
        **calibration,
        "paper_only": True,
        "selective_no_forced_trade": True,
        "market_scope": "rotten_tomatoes_entertainment",
    }
