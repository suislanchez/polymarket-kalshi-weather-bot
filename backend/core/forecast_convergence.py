"""
forecast_convergence.py — Forecast convergence timing signal for weather edge trading.

Insight: A forecast that has stopped moving is more reliable than one still shifting.
Instead of asking "what will the temperature be?", ask "has the forecast stabilized?"

Enter when the 24h forecast delta is small (< CONVERGENCE_THRESHOLD_F).
Halve position size when the forecast is still shifting.

Usage:
    from backend.core.forecast_convergence import compute_convergence_score, record_forecast_run

Data requirements:
    - At least 2 forecast runs for the same (city, target_date) separated by ~24h
    - The weather_signals scanner records a run each time it fetches GFS data
    - Stored in: data/forecast_run_history.json
      Schema: {"city:date": [[unix_ts, value_f], ...]}  (oldest first)

Integration:
    In _build_signals_sync(), after computing ensemble_mean, call record_forecast_run()
    then compute_convergence_score() and multiply suggested_size by confidence_multiplier.
"""

import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Optional

# ─── CONFIG ─────────────────────────────────────────────────────────────────────

CONVERGENCE_THRESHOLD_F = 1.0   # °F — shift below this = forecast has stabilized
WINDOW_24H_SECONDS = 86400      # 24h in seconds
WINDOW_TOLERANCE_SECONDS = 7200 # ±2h tolerance when hunting for the 24h-ago entry
MAX_HISTORY_ENTRIES = 400       # enough 5-min changed runs to preserve 24h±2h history

_HISTORY_PATH = os.path.abspath(
    os.environ.get(
        "WEATHER_EDGE_FORECAST_HISTORY_PATH",
        os.path.join(os.path.dirname(__file__), "../../data/forecast_run_history.json"),
    )
)

logger = logging.getLogger(__name__)
_HISTORY_LOCK = threading.RLock()


# ─── CORE SIGNAL ────────────────────────────────────────────────────────────────

def compute_convergence_score(
    forecast_series: list[tuple[datetime, float]],
) -> dict:
    """
    Compute forecast convergence for a single (city, target_date) pair.

    Args:
        forecast_series: list of (model_run_time, predicted_high_F) for the SAME
                         target date and city, sorted oldest → newest.
                         At least 2 entries required for a meaningful score.

    Returns:
        {
          "shift_24h": float,            # abs delta between newest and 24h-ago forecast
          "converged": bool,             # shift_24h < CONVERGENCE_THRESHOLD_F
          "confidence_multiplier": float, # 1.0 if converged, 0.5 if not, 0.75 if no 24h pair
          "runs_available": int,         # number of entries in the series
          "comparison_age_hours": float, # actual age gap used (may differ from 24h)
          "newest_value_f": float,
          "reference_value_f": Optional[float],
          "note": str,
        }
    """
    if not forecast_series:
        return _no_data_result("empty series")

    # Sort ascending by time just in case caller didn't
    sorted_series = sorted(forecast_series, key=lambda x: x[0])
    n = len(sorted_series)

    if n == 1:
        return _no_data_result("only 1 run — need 2+ for convergence", runs_available=1)

    newest_time, newest_val = sorted_series[-1]

    # Find the best reference point: entry closest to 24h before newest
    target_ref_time = newest_time.timestamp() - WINDOW_24H_SECONDS
    best_ref = None
    best_diff = float("inf")

    for run_time, val in sorted_series[:-1]:
        age_diff = abs(run_time.timestamp() - target_ref_time)
        if age_diff < best_diff:
            best_diff = age_diff
            best_ref = (run_time, val)

    # If the closest reference is more than (24h + tolerance) away, note it but still use it
    ref_time, ref_val = best_ref
    actual_gap_h = (newest_time.timestamp() - ref_time.timestamp()) / 3600.0
    within_window = abs(actual_gap_h - 24.0) <= (WINDOW_TOLERANCE_SECONDS / 3600.0)

    shift = abs(newest_val - ref_val)
    converged = shift < CONVERGENCE_THRESHOLD_F

    if not within_window:
        return {
            "shift_24h": None,
            "converged": None,
            "confidence_multiplier": 0.75,
            "runs_available": n,
            "comparison_age_hours": round(actual_gap_h, 1),
            "newest_value_f": round(newest_val, 1),
            "reference_value_f": round(ref_val, 1),
            "note": (
                f"no 24h convergence reference: closest run was {actual_gap_h:.1f}h ago "
                f"(requires 24h±{WINDOW_TOLERANCE_SECONDS / 3600.0:.0f}h)"
            ),
        }
    else:
        confidence_multiplier = 1.0 if converged else 0.5
        note = (
            f"24h shift={shift:.2f}°F (threshold={CONVERGENCE_THRESHOLD_F}°F) → "
            f"{'CONVERGED ✓' if converged else 'SHIFTING ✗'}"
        )

    return {
        "shift_24h": round(shift, 2),
        "converged": converged,
        "confidence_multiplier": confidence_multiplier,
        "runs_available": n,
        "comparison_age_hours": round(actual_gap_h, 1),
        "newest_value_f": round(newest_val, 1),
        "reference_value_f": round(ref_val, 1),
        "note": note,
    }


def _no_data_result(reason: str, runs_available: int = 0) -> dict:
    return {
        "shift_24h": None,
        "converged": None,
        "confidence_multiplier": 0.75,   # partial — can't confirm or deny
        "runs_available": runs_available,
        "comparison_age_hours": None,
        "newest_value_f": None,
        "reference_value_f": None,
        "note": f"no convergence data: {reason}",
    }


# ─── HISTORY STORE ──────────────────────────────────────────────────────────────

def _quarantine_corrupt_history(path: str) -> None:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantine_path = f"{path}.corrupt-{suffix}"
    try:
        os.replace(path, quarantine_path)
        logger.warning("Quarantined corrupt forecast history at %s", quarantine_path)
    except OSError as exc:
        logger.warning("Failed to quarantine corrupt forecast history %s: %s", path, exc)


def _history_key(city: str, target_date_str: str) -> str:
    return f"{str(city).strip().lower()}:{target_date_str}"


def _sanitize_runs(raw_runs: object) -> list[list[float]]:
    if not isinstance(raw_runs, list):
        return []
    cleaned: list[list[float]] = []
    for raw in raw_runs:
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            continue
        try:
            ts = float(raw[0])
            value = float(raw[1])
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        cleaned.append([ts, value])
    return cleaned[-MAX_HISTORY_ENTRIES:]


def _load_history() -> dict:
    """Load forecast run history from disk, ignoring malformed per-key rows."""
    if not os.path.exists(_HISTORY_PATH):
        return {}
    try:
        with open(_HISTORY_PATH, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        _quarantine_corrupt_history(_HISTORY_PATH)
        return {}
    if not isinstance(data, dict):
        logger.warning("Forecast history root is %s, expected dict; ignoring", type(data).__name__)
        return {}
    cleaned: dict[str, list[list[float]]] = {}
    for key, raw_runs in data.items():
        runs = _sanitize_runs(raw_runs)
        if runs:
            cleaned[str(key)] = runs
    return cleaned


def _save_history(history: dict) -> None:
    """Persist forecast run history atomically and durably."""
    history_dir = os.path.dirname(_HISTORY_PATH)
    os.makedirs(history_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".forecast_run_history.", suffix=".tmp", dir=history_dir)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(history, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, _HISTORY_PATH)
        try:
            dir_fd = os.open(history_dir, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Directory fsync is best-effort on non-POSIX filesystems.
            pass
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def record_forecast_run(city: str, target_date_str: str, forecast_high_f: float) -> None:
    """
    Record a GFS forecast fetch for (city, target_date). Called by weather_signals
    each time it reads a fresh ensemble mean for a city/date pair.

    Args:
        city: city key (e.g. "new york", "chicago")
        target_date_str: ISO date string "YYYY-MM-DD"
        forecast_high_f: predicted high temperature in °F for that target date
    """
    key = _history_key(city, target_date_str)
    now_ts = time.time()

    with _HISTORY_LOCK:
        history = _load_history()
        runs = history.get(key, [])

        # Avoid near-duplicate entries: skip if last entry was < 2h ago with same value
        if runs:
            last_ts, last_val = runs[-1]
            if (now_ts - last_ts) < 7200 and abs(last_val - forecast_high_f) < 0.1:
                return

        runs.append([now_ts, round(forecast_high_f, 1)])

        # Trim to cap
        if len(runs) > MAX_HISTORY_ENTRIES:
            runs = runs[-MAX_HISTORY_ENTRIES:]

        history[key] = runs
        _save_history(history)


def load_forecast_series(city: str, target_date_str: str) -> list[tuple[datetime, float]]:
    """
    Load the stored forecast series for a (city, target_date) as
    [(datetime, value_f), ...] sorted oldest first.
    """
    key = _history_key(city, target_date_str)
    with _HISTORY_LOCK:
        history = _load_history()
    runs = history.get(key, [])
    result = []
    for ts, val in runs:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        result.append((dt, val))
    return sorted(result, key=lambda x: x[0])


# ─── UNIT TESTS ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import timedelta

    print("=== forecast_convergence.py unit tests ===\n")
    errors = 0

    def _make_series(*pairs):
        """Helper: list of (hours_ago, value_f) → (datetime, float) series."""
        now = datetime.now(tz=timezone.utc)
        return [(now - timedelta(hours=h), v) for h, v in reversed(pairs)]

    # Test 1: converged example from the task spec
    # [(T-48h, 72°), (T-24h, 74°), (T, 74.2°)] → shift=0.2 → converged ✓
    series1 = _make_series((48, 72.0), (24, 74.0), (0, 74.2))
    r1 = compute_convergence_score(series1)
    assert r1["converged"] is True, f"Test 1 failed: {r1}"
    assert r1["shift_24h"] == 0.2, f"Test 1 shift wrong: {r1}"
    assert r1["confidence_multiplier"] == 1.0, f"Test 1 multiplier wrong: {r1}"
    assert r1["runs_available"] == 3
    print(f"Test 1 PASS — converged example: shift={r1['shift_24h']}°F → {r1['note']}")

    # Test 2: still shifting — shift > threshold → confidence_multiplier=0.5
    # [(T-48h, 65°), (T-24h, 70°), (T, 74°)] → 24h shift=4° → not converged
    series2 = _make_series((48, 65.0), (24, 70.0), (0, 74.0))
    r2 = compute_convergence_score(series2)
    assert r2["converged"] is False, f"Test 2 failed: {r2}"
    assert r2["shift_24h"] == 4.0, f"Test 2 shift wrong: {r2}"
    assert r2["confidence_multiplier"] == 0.5, f"Test 2 multiplier wrong: {r2}"
    print(f"Test 2 PASS — shifting example: shift={r2['shift_24h']}°F → {r2['note']}")

    # Test 3: only 1 run → no data, partial multiplier
    series3 = _make_series((0, 75.0))
    r3 = compute_convergence_score(series3)
    assert r3["converged"] is None, f"Test 3 failed: {r3}"
    assert r3["confidence_multiplier"] == 0.75, f"Test 3 multiplier wrong: {r3}"
    print(f"Test 3 PASS — single run: {r3['note']}")

    # Test 4: exactly at threshold boundary (1.0°F) → not converged (strict <)
    series4 = _make_series((48, 70.0), (24, 71.0), (0, 72.0))
    r4 = compute_convergence_score(series4)
    assert r4["converged"] is False, f"Test 4 failed: {r4}"
    assert r4["shift_24h"] == 1.0
    print(f"Test 4 PASS — boundary 1.0°F: converged={r4['converged']} (strict <, so False)")

    print(f"\n{'All 4 tests passed ✓' if errors == 0 else f'{errors} test(s) FAILED'}")
