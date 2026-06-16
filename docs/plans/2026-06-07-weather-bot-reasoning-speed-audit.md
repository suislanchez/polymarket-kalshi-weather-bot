# Weather Bot Reasoning + Speed Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the last 2–3 days of weak/outlier-masked weather paper-trade results into a reproducible audit pipeline, tighter weather reasoning gates, calibrated probabilities, and faster scans/reports.

**Architecture:** Separate the work into four layers: (1) read-only audit/reporting over the existing SQLite ledger, (2) calibration/probability shrinkage before edge/sizing, (3) stricter venue/source/execution gates before paper execution, and (4) scan/runtime caching + concurrency. Keep all changes simulation-only and preserve filtered signals for research visibility.

**Tech Stack:** Python 3, FastAPI backend, SQLite via `sqlite3`/SQLAlchemy, pytest, existing modules under `backend/core`, `backend/data`, and scripts under `scripts/`.

---

## Current Evidence To Preserve In The Audit

From the local `tradingbot.db` check on 2026-06-07:

- Strict last ~72h: 6 weather paper trades, 4 settled, 2 pending, 1W/3L, realized PnL `-$143.75`, win rate `25.0%`.
- Since Jun 4 midnight: 12 trades, 10 settled, 2 pending, 3W/7L, realized PnL `+$2,306.98`.
- One outlier dominates: Polymarket NYC low Jun 4 NO @ 2.7¢ won for `+$2,702.78`.
- Excluding that outlier, since Jun 4 becomes `-$395.80` with 2W/7L.
- All weather so far: 22 trades, 20 settled, 4W/16L, total PnL `+$1,716.55`; excluding the outlier, `-$986.23`.
- Kalshi is underperforming: 1W/10L, `-$665.43` all-time; last checked recent Kalshi trades in the Jun 4 window were 0W/2L.
- Latest weather signal batch: 146 signals, 3 `[ACTIONABLE]`, 143 `[FILTERED]`, 0 executed.

This plan must make those claims reproducible from the DB instead of relying on one-off terminal SQL.

---

## File Structure

### Create

- `backend/core/weather_audit.py` — pure functions for loading/aggregating weather trades/signals, outlier-adjusted metrics, venue splits, false-positive taxonomy, and report DTOs.
- `scripts/weather_audit_report.py` — CLI wrapper that reads `tradingbot.db`, prints markdown/JSON, and can write `docs/cron-context/weather-latest.md`.
- `tests/test_weather_audit.py` — temp-SQLite tests for 48h/72h windows, outlier exclusion, venue splits, pending handling, and latest signal batch interpretation.
- `backend/core/weather_calibration.py` — probability shrinkage/calibration primitives based on threshold distance, ensemble spread, venue/station sample count, and Brier/log-loss quality.
- `tests/test_weather_calibration.py` — tests that stop 31-member unanimity near a threshold from becoming fake 95% certainty.
- `backend/core/weather_scan_runtime.py` — per-scan caches and concurrency helpers for forecast/provider fetches.
- `tests/test_weather_scan_runtime.py` — tests that repeated same city/date markets fetch forecast data once and signal generation is bounded-concurrent.
- `scripts/benchmark_weather_scan.py` — lightweight scan benchmark that reports market count, forecast fetch count, signal count, elapsed seconds, and per-market latency.

### Modify

- `backend/core/weather_signals.py` — apply calibrated probabilities, use per-scan forecast cache, pass richer gate inputs, and preserve action/filter reasons.
- `backend/core/weather_methodology.py` — extend `WeatherGateInput` and `evaluate_weather_trade_gate` with dynamic threshold buffers, platform/venue controls, and minimum calibration sample gates.
- `backend/config.py` — add explicit weather audit/calibration/runtime settings with conservative defaults.
- `backend/core/scheduler.py` — add a final paper-execution guard so `[ACTIONABLE]` is necessary but not sufficient when venue/sample gates disable paper execution.
- `backend/api/main.py` / `backend/api/schemas.py` — expose audit summary through a read-only endpoint only after the CLI/module is working.
- `docs/cron-context/weather-latest.md` — generated report target, not hand-written.

---

## Success Metrics

1. **Reasoning quality**
   - No more uncalibrated `95%` probabilities solely because a 31-member ensemble is unanimous.
   - Report always separates headline PnL from ex-outlier PnL.
   - Kalshi can be forced into `MONITOR`/non-executed paper mode until venue-specific settled evidence improves.
   - Every paper execution has explicit gate evidence: settlement source, station, line-level book, threshold buffer, calibration sample status, venue enablement.

2. **Speed**
   - One scan fetches each `(provider, city, target_date)` forecast once, not once per market line.
   - Weather scan benchmark prints p50/p95 per-market signal time.
   - Target: latest local benchmark under 20 seconds for normal active market set, or at minimum 2x faster than current baseline.

3. **Reporting**
   - `python scripts/weather_audit_report.py --db tradingbot.db --window-hours 72 --format markdown` reproduces the trade summary without needing the API server.
   - If the API is offline, Slack/cron reports still work from SQLite fallback.

---

## Task 1: Reproducible Weather Paper-Trade Audit

**Files:**
- Create: `backend/core/weather_audit.py`
- Create: `scripts/weather_audit_report.py`
- Create: `tests/test_weather_audit.py`
- Generated/Write target: `docs/cron-context/weather-latest.md`

- [x] **Step 1: Write failing tests for windowed audit aggregation**

Create `tests/test_weather_audit.py` with a temp SQLite fixture and explicit sample rows that reproduce the outlier-masked scenario.

```python
import sqlite3
from pathlib import Path

from backend.core.weather_audit import (
    aggregate_trades,
    build_weather_audit,
    detect_largest_outlier,
    load_weather_trades,
    summarize_latest_signal_batch,
)


def _init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY,
            signal_id INTEGER,
            market_ticker TEXT,
            platform TEXT,
            event_slug TEXT,
            market_type TEXT,
            direction TEXT,
            entry_price REAL,
            size REAL,
            timestamp TEXT,
            settled INTEGER,
            settlement_time TEXT,
            settlement_value REAL,
            result TEXT,
            pnl REAL,
            model_probability REAL,
            market_price_at_entry REAL,
            edge_at_entry REAL
        )
    """)
    conn.execute("""
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY,
            market_ticker TEXT,
            platform TEXT,
            market_type TEXT,
            timestamp TEXT,
            direction TEXT,
            model_probability REAL,
            market_price REAL,
            edge REAL,
            confidence REAL,
            kelly_fraction REAL,
            suggested_size REAL,
            sources TEXT,
            reasoning TEXT,
            executed INTEGER
        )
    """)
    return conn


def test_weather_audit_separates_headline_from_outlier(tmp_path):
    conn = _init_db(tmp_path / "audit.db")
    rows = [
        (1, "polymarket", "nyc-outlier", "weather", "no", 0.027, 75.0, "2026-06-04 11:03:55", 1, "2026-06-05 05:30:52", "win", 2702.78),
        (2, "polymarket", "london-loss", "weather", "yes", 0.050, 75.0, "2026-06-04 14:56:27", 1, "2026-06-05 00:04:58", "loss", -75.0),
        (3, "polymarket", "london-win", "weather", "no", 0.480, 75.0, "2026-06-05 02:00:50", 1, "2026-06-06 00:02:23", "win", 81.25),
        (4, "polymarket", "shanghai-loss", "weather", "yes", 0.089, 75.0, "2026-06-05 12:19:57", 1, "2026-06-05 16:48:23", "loss", -75.0),
        (5, "polymarket", "seoul-pending", "weather", "yes", 0.120, 75.0, "2026-06-06 02:33:38", 0, None, "pending", None),
    ]
    conn.executemany("""
        INSERT INTO trades (
            id, platform, event_slug, market_type, direction, entry_price, size,
            timestamp, settled, settlement_time, result, pnl
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

    trades = load_weather_trades(conn, since="2026-06-04 00:00:00")
    summary = aggregate_trades(trades)
    outlier = detect_largest_outlier(trades)

    assert summary.total == 5
    assert summary.settled == 4
    assert summary.pending == 1
    assert summary.wins == 2
    assert summary.losses == 2
    assert summary.realized_pnl == 2633.03
    assert outlier.event_slug == "nyc-outlier"
    assert outlier.pnl == 2702.78
    assert summary.ex_outlier_pnl == -69.75


def test_latest_signal_batch_counts_actionable_filtered_and_executed(tmp_path):
    conn = _init_db(tmp_path / "signals.db")
    rows = [
        (10, "m1", "polymarket", "weather", "2026-06-07 15:19:44", "yes", 0.95, 0.02, 0.93, 0.9, 0.01, 75.0, "[]", "[ACTIONABLE] NYC low above 65F", 0),
        (11, "m2", "kalshi", "weather", "2026-06-07 15:19:45", "no", 0.05, 0.33, 0.28, 0.9, 0.01, 75.0, "[]", "[ACTIONABLE] LA high above 73F", 0),
        (12, "m3", "kalshi", "weather", "2026-06-07 15:19:46", "yes", 0.05, 0.04, 0.01, 0.9, 0.0, 15.0, "[]", "[FILTERED] thin book", 0),
    ]
    conn.executemany("""
        INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

    batch = summarize_latest_signal_batch(conn)

    assert batch.minute == "2026-06-07 15:19"
    assert batch.total == 3
    assert batch.actionable == 2
    assert batch.filtered == 1
    assert batch.positive_size == 3
    assert batch.executed == 0
```

- [x] **Step 2: Run tests and verify they fail**

Run:

```bash
pytest tests/test_weather_audit.py -q
```

Expected: import failure for `backend.core.weather_audit`.

- [x] **Step 3: Implement `backend/core/weather_audit.py`**

Implement pure dataclasses and functions with no network calls and no DB mutation.

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3
from typing import Iterable


@dataclass(frozen=True)
class WeatherTradeRow:
    id: int
    platform: str
    event_slug: str
    direction: str
    entry_price: float
    size: float
    timestamp: str
    settled: bool
    settlement_time: str | None
    result: str
    pnl: float | None
    model_probability: float | None = None
    market_price_at_entry: float | None = None
    edge_at_entry: float | None = None


@dataclass(frozen=True)
class WeatherTradeSummary:
    total: int
    settled: int
    pending: int
    wins: int
    losses: int
    realized_pnl: float
    win_rate: float | None
    outlier_event_slug: str | None
    outlier_pnl: float | None
    ex_outlier_pnl: float


@dataclass(frozen=True)
class SignalBatchSummary:
    minute: str | None
    total: int
    actionable: int
    filtered: int
    positive_size: int
    executed: int


@dataclass(frozen=True)
class WeatherAuditReport:
    generated_at: str
    window_hours: int
    strict_window: WeatherTradeSummary
    by_platform: dict[str, WeatherTradeSummary]
    latest_signal_batch: SignalBatchSummary


def _row_to_trade(row: sqlite3.Row) -> WeatherTradeRow:
    return WeatherTradeRow(
        id=int(row["id"]),
        platform=str(row["platform"] or "unknown"),
        event_slug=str(row["event_slug"] or row["market_ticker"] or "unknown"),
        direction=str(row["direction"] or "unknown"),
        entry_price=float(row["entry_price"] or 0.0),
        size=float(row["size"] or 0.0),
        timestamp=str(row["timestamp"]),
        settled=bool(row["settled"]),
        settlement_time=row["settlement_time"],
        result=str(row["result"] or "pending"),
        pnl=None if row["pnl"] is None else round(float(row["pnl"]), 2),
        model_probability=row["model_probability"],
        market_price_at_entry=row["market_price_at_entry"],
        edge_at_entry=row["edge_at_entry"],
    )


def connect_sqlite(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def cutoff_from_window(now: datetime, window_hours: int) -> str:
    return (now - timedelta(hours=window_hours)).strftime("%Y-%m-%d %H:%M:%S")


def load_weather_trades(conn: sqlite3.Connection, *, since: str) -> list[WeatherTradeRow]:
    rows = conn.execute(
        """
        SELECT id, market_ticker, platform, event_slug, direction, entry_price,
               size, timestamp, settled, settlement_time, result, pnl,
               model_probability, market_price_at_entry, edge_at_entry
        FROM trades
        WHERE market_type = 'weather' AND timestamp >= ?
        ORDER BY timestamp ASC, id ASC
        """,
        (since,),
    ).fetchall()
    return [_row_to_trade(row) for row in rows]


def detect_largest_outlier(trades: Iterable[WeatherTradeRow]) -> WeatherTradeRow | None:
    settled = [t for t in trades if t.settled and t.pnl is not None]
    if not settled:
        return None
    return max(settled, key=lambda t: abs(float(t.pnl or 0.0)))


def aggregate_trades(trades: Iterable[WeatherTradeRow]) -> WeatherTradeSummary:
    rows = list(trades)
    settled = [t for t in rows if t.settled]
    wins = [t for t in settled if t.result == "win"]
    losses = [t for t in settled if t.result == "loss"]
    realized = round(sum(float(t.pnl or 0.0) for t in settled), 2)
    outlier = detect_largest_outlier(rows)
    outlier_pnl = None if outlier is None or outlier.pnl is None else float(outlier.pnl)
    ex_outlier_pnl = round(realized - (outlier_pnl or 0.0), 2)
    win_rate = None if not settled else round(100.0 * len(wins) / len(settled), 1)
    return WeatherTradeSummary(
        total=len(rows),
        settled=len(settled),
        pending=len(rows) - len(settled),
        wins=len(wins),
        losses=len(losses),
        realized_pnl=realized,
        win_rate=win_rate,
        outlier_event_slug=None if outlier is None else outlier.event_slug,
        outlier_pnl=outlier_pnl,
        ex_outlier_pnl=ex_outlier_pnl,
    )


def summarize_latest_signal_batch(conn: sqlite3.Connection) -> SignalBatchSummary:
    minute = conn.execute(
        "SELECT substr(max(timestamp),1,16) FROM signals WHERE market_type='weather'"
    ).fetchone()[0]
    if minute is None:
        return SignalBatchSummary(None, 0, 0, 0, 0, 0)
    row = conn.execute(
        """
        SELECT count(*) AS total,
               sum(CASE WHEN reasoning LIKE '[ACTIONABLE]%' THEN 1 ELSE 0 END) AS actionable,
               sum(CASE WHEN reasoning LIKE '[FILTERED]%' THEN 1 ELSE 0 END) AS filtered,
               sum(CASE WHEN suggested_size > 0 THEN 1 ELSE 0 END) AS positive_size,
               sum(CASE WHEN executed = 1 THEN 1 ELSE 0 END) AS executed
        FROM signals
        WHERE market_type='weather' AND substr(timestamp,1,16)=?
        """,
        (minute,),
    ).fetchone()
    return SignalBatchSummary(
        minute=minute,
        total=int(row["total"] or 0),
        actionable=int(row["actionable"] or 0),
        filtered=int(row["filtered"] or 0),
        positive_size=int(row["positive_size"] or 0),
        executed=int(row["executed"] or 0),
    )


def build_weather_audit(conn: sqlite3.Connection, *, now: datetime, window_hours: int) -> WeatherAuditReport:
    since = cutoff_from_window(now, window_hours)
    trades = load_weather_trades(conn, since=since)
    by_platform: dict[str, list[WeatherTradeRow]] = {}
    for trade in trades:
        by_platform.setdefault(trade.platform, []).append(trade)
    return WeatherAuditReport(
        generated_at=now.isoformat(),
        window_hours=window_hours,
        strict_window=aggregate_trades(trades),
        by_platform={platform: aggregate_trades(platform_trades) for platform, platform_trades in by_platform.items()},
        latest_signal_batch=summarize_latest_signal_batch(conn),
    )
```

- [x] **Step 4: Implement the CLI wrapper**

Create `scripts/weather_audit_report.py`.

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from backend.core.weather_audit import build_weather_audit, connect_sqlite


def _summary_line(label, summary):
    win_rate = "n/a" if summary.win_rate is None else f"{summary.win_rate:.1f}%"
    return (
        f"- **{label}:** {summary.total} trades; {summary.settled} settled / "
        f"{summary.pending} pending; {summary.wins}W/{summary.losses}L; "
        f"PnL `${summary.realized_pnl:+.2f}`; win rate `{win_rate}`; "
        f"ex-largest-outlier PnL `${summary.ex_outlier_pnl:+.2f}`"
    )


def render_markdown(report) -> str:
    lines = [
        "# Weather Paper-Trade Audit",
        "",
        f"Generated: `{report.generated_at}`",
        f"Window: `{report.window_hours}h`",
        "",
        _summary_line("Strict window", report.strict_window),
    ]
    if report.strict_window.outlier_event_slug:
        lines.append(
            f"- Largest outlier: `{report.strict_window.outlier_event_slug}` "
            f"PnL `${report.strict_window.outlier_pnl:+.2f}`"
        )
    lines.append("")
    lines.append("## Venue split")
    for platform, summary in sorted(report.by_platform.items()):
        lines.append(_summary_line(platform, summary))
    batch = report.latest_signal_batch
    lines.extend([
        "",
        "## Latest signal batch",
        f"- Minute: `{batch.minute}`",
        f"- Signals: `{batch.total}` total; `{batch.actionable}` actionable; `{batch.filtered}` filtered; `{batch.executed}` executed",
        "",
        "Simulation-only: this report does not place trades or access private exchange accounts.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="tradingbot.db")
    parser.add_argument("--window-hours", type=int, default=72)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    conn = connect_sqlite(args.db)
    report = build_weather_audit(conn, now=datetime.utcnow(), window_hours=args.window_hours)
    if args.format == "json":
        payload = json.dumps(report, default=lambda obj: obj.__dict__, indent=2)
    else:
        payload = render_markdown(report)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 5: Verify audit report**

Run:

```bash
pytest tests/test_weather_audit.py -q
python scripts/weather_audit_report.py --db tradingbot.db --window-hours 72 --format markdown
python scripts/weather_audit_report.py --db tradingbot.db --window-hours 72 --format markdown --output docs/cron-context/weather-latest.md
```

Expected:
- Tests pass.
- CLI report includes strict-window PnL, ex-largest-outlier PnL, venue split, and latest signal batch counts.
- No network calls occur.

- [ ] **Step 6: Commit**

Deferred for now because the repo is already on `main` with a broad pre-existing dirty working tree; this task intentionally left changes uncommitted for review.

```bash
git add backend/core/weather_audit.py scripts/weather_audit_report.py tests/test_weather_audit.py docs/cron-context/weather-latest.md
git commit -m "feat: add reproducible weather paper audit"
```

---

## Task 2: Probability Calibration / Anti-Overconfidence Layer

**Files:**
- Create: `backend/core/weather_calibration.py`
- Create: `tests/test_weather_calibration.py`
- Modify: `backend/core/weather_signals.py:129-337`
- Modify: `backend/config.py:88-136`

- [ ] **Step 1: Write failing calibration tests**

Create `tests/test_weather_calibration.py`.

```python
from backend.core.weather_calibration import calibrate_weather_probability


def test_unanimous_ensemble_near_threshold_is_not_95_percent():
    calibrated = calibrate_weather_probability(
        raw_probability=0.95,
        threshold_distance_f=1.2,
        ensemble_std_f=1.0,
        settled_sample_count=0,
        brier_score=None,
    )
    assert calibrated <= 0.70
    assert calibrated >= 0.50


def test_far_threshold_with_good_history_can_remain_high_confidence():
    calibrated = calibrate_weather_probability(
        raw_probability=0.95,
        threshold_distance_f=8.0,
        ensemble_std_f=1.0,
        settled_sample_count=80,
        brier_score=0.12,
    )
    assert calibrated == 0.95


def test_poor_brier_score_caps_extreme_confidence():
    calibrated = calibrate_weather_probability(
        raw_probability=0.95,
        threshold_distance_f=8.0,
        ensemble_std_f=1.0,
        settled_sample_count=80,
        brier_score=0.31,
    )
    assert calibrated == 0.80


def test_low_probability_is_symmetrically_capped():
    calibrated = calibrate_weather_probability(
        raw_probability=0.05,
        threshold_distance_f=8.0,
        ensemble_std_f=1.0,
        settled_sample_count=0,
        brier_score=None,
    )
    assert calibrated == 0.25
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/test_weather_calibration.py -q
```

Expected: import failure for `backend.core.weather_calibration`.

- [ ] **Step 3: Implement `backend/core/weather_calibration.py`**

```python
from __future__ import annotations


def _cap_probability(probability: float, max_certainty: float) -> float:
    p = max(0.0, min(1.0, float(probability)))
    cap = max(0.5, min(0.99, float(max_certainty)))
    if p >= 0.5:
        return min(p, cap)
    return max(p, 1.0 - cap)


def certainty_cap_for_history(*, settled_sample_count: int, brier_score: float | None) -> float:
    if settled_sample_count < 20:
        return 0.75
    if brier_score is None:
        return 0.85
    if brier_score <= 0.16:
        return 0.95
    if brier_score <= 0.24:
        return 0.90
    return 0.80


def certainty_cap_for_threshold_distance(*, threshold_distance_f: float, ensemble_std_f: float | None) -> float:
    std = max(float(ensemble_std_f or 0.0), 0.5)
    z = abs(float(threshold_distance_f)) / std
    if z < 1.5:
        return 0.70
    if z < 2.5:
        return 0.85
    return 0.95


def calibrate_weather_probability(
    *,
    raw_probability: float,
    threshold_distance_f: float,
    ensemble_std_f: float | None,
    settled_sample_count: int,
    brier_score: float | None,
) -> float:
    history_cap = certainty_cap_for_history(
        settled_sample_count=settled_sample_count,
        brier_score=brier_score,
    )
    distance_cap = certainty_cap_for_threshold_distance(
        threshold_distance_f=threshold_distance_f,
        ensemble_std_f=ensemble_std_f,
    )
    return round(_cap_probability(raw_probability, min(history_cap, distance_cap)), 6)
```

- [ ] **Step 4: Add config knobs**

Modify `backend/config.py` after existing weather composite settings.

```python
    # Weather calibration / anti-overconfidence controls
    WEATHER_CALIBRATION_ENABLED: bool = True
    WEATHER_MIN_SETTLED_SAMPLES_FOR_EXTREME_PROB: int = 20
    WEATHER_DEFAULT_BRIER_SCORE: Optional[float] = None
    WEATHER_MAX_CERTAINTY_WITHOUT_HISTORY: float = 0.75
    WEATHER_NEAR_THRESHOLD_Z_CAP: float = 0.70
```

- [ ] **Step 5: Apply calibration in `generate_weather_signal`**

Modify `backend/core/weather_signals.py` after line 236 where `mean_val` and `std_val` are available, before edge calculation. Use an explicit default sample count until Task 3 wires venue/station history from the audit module.

```python
from backend.core.weather_calibration import calibrate_weather_probability
```

Then insert:

```python
    raw_model_yes_prob = max(0.05, min(0.95, model_yes_prob))
    if settings.WEATHER_CALIBRATION_ENABLED:
        threshold_distance_f = mean_val - market.threshold_f
        model_yes_prob = calibrate_weather_probability(
            raw_probability=raw_model_yes_prob,
            threshold_distance_f=threshold_distance_f,
            ensemble_std_f=std_val,
            settled_sample_count=0,
            brier_score=settings.WEATHER_DEFAULT_BRIER_SCORE,
        )
    else:
        model_yes_prob = raw_model_yes_prob
```

Remove the older direct clipping block at `backend/core/weather_signals.py:199-200` to avoid double-clipping.

- [ ] **Step 6: Verify calibration tests and existing signal tests**

```bash
pytest tests/test_weather_calibration.py tests/test_weather_composite_score.py tests/test_weather_signal_live_side_odds.py -q
```

Expected: pass. If existing tests expected literal `95%`, update assertions to require conservative caps when `WEATHER_CALIBRATION_ENABLED=True`.

- [ ] **Step 7: Commit**

```bash
git add backend/core/weather_calibration.py tests/test_weather_calibration.py backend/core/weather_signals.py backend/config.py
git commit -m "feat: calibrate weather probability confidence"
```

---

## Task 3: Venue/Source Gate Audit And Conservative Paper-Execution Controls

**Files:**
- Modify: `backend/core/weather_methodology.py:35-60` and `evaluate_weather_trade_gate(...)` body
- Modify: `backend/core/weather_signals.py:239-251`
- Modify: `backend/core/scheduler.py:218-364`
- Modify: `backend/config.py:88-136`
- Create: `tests/test_weather_reasoning_gates.py`

- [ ] **Step 1: Write failing tests for venue and dynamic threshold gates**

Create `tests/test_weather_reasoning_gates.py`.

```python
from datetime import date

from backend.core.weather_methodology import WeatherGateInput, evaluate_weather_trade_gate


def test_kalshi_can_be_blocked_for_paper_execution_until_calibrated():
    gate = evaluate_weather_trade_gate(
        WeatherGateInput(
            settlement_source="nws_cli",
            station_code="KLAX",
            market_probability=0.33,
            best_bid=0.31,
            best_ask=0.33,
            top_ask_size=100.0,
            ensemble_mean=69.6,
            ensemble_std=0.4,
            threshold_f=73.0,
            target_date=date(2026, 6, 7),
            platform="kalshi",
            platform_paper_execution_enabled=False,
            settled_sample_count=11,
            min_settled_samples=20,
        )
    )
    assert not gate.allowed
    assert "platform paper execution disabled" in gate.reasons
    assert "settled sample count 11 below minimum 20" in gate.reasons


def test_dynamic_threshold_buffer_scales_with_ensemble_std():
    gate = evaluate_weather_trade_gate(
        WeatherGateInput(
            settlement_source="wunderground",
            station_code="KLGA",
            market_probability=0.04,
            best_bid=0.02,
            best_ask=0.04,
            top_ask_size=50.0,
            ensemble_mean=68.2,
            ensemble_std=2.5,
            threshold_f=65.0,
            target_date=date(2026, 6, 7),
            platform="polymarket",
            platform_paper_execution_enabled=True,
            settled_sample_count=30,
            min_settled_samples=20,
        )
    )
    assert not gate.allowed
    assert any("threshold buffer" in reason for reason in gate.reasons)
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/test_weather_reasoning_gates.py -q
```

Expected: `WeatherGateInput` does not accept the new fields.

- [ ] **Step 3: Extend gate input dataclass**

Modify `backend/core/weather_methodology.py:35-51`.

```python
@dataclass(frozen=True)
class WeatherGateInput:
    settlement_source: str | None
    station_code: str | None
    market_probability: float
    best_bid: float | None
    best_ask: float | None
    top_ask_size: float | None
    ensemble_mean: float | None
    threshold_f: float | None
    target_date: date | None = None
    max_spread: float = 0.08
    min_top_ask_size: float = 10.0
    min_threshold_buffer_f: float = 3.0
    ensemble_std: float | None = None
    platform: str | None = None
    platform_paper_execution_enabled: bool = True
    settled_sample_count: int = 0
    min_settled_samples: int = 0
```

- [ ] **Step 4: Add dynamic gate checks in `evaluate_weather_trade_gate`**

Inside the existing function body, add these checks before returning.

```python
    if not gate.platform_paper_execution_enabled:
        reasons.append("platform paper execution disabled")

    if gate.settled_sample_count < gate.min_settled_samples:
        reasons.append(
            f"settled sample count {gate.settled_sample_count} below minimum {gate.min_settled_samples}"
        )

    if gate.ensemble_mean is not None and gate.threshold_f is not None:
        base_buffer = gate.min_threshold_buffer_f
        std_buffer = 1.75 * max(float(gate.ensemble_std or 0.0), 0.5)
        required_buffer = max(base_buffer, std_buffer)
        actual_buffer = abs(float(gate.ensemble_mean) - float(gate.threshold_f))
        if actual_buffer < required_buffer:
            reasons.append(
                f"threshold buffer {actual_buffer:.1f}F below required {required_buffer:.1f}F"
            )
```

Keep existing source/book/spread/depth checks intact.

- [ ] **Step 5: Add conservative config defaults**

Modify `backend/config.py`.

```python
    WEATHER_POLYMARKET_PAPER_EXECUTION_ENABLED: bool = True
    WEATHER_KALSHI_PAPER_EXECUTION_ENABLED: bool = False
    WEATHER_MIN_SETTLED_SAMPLES_BEFORE_PAPER_EXECUTION: int = 20
    WEATHER_DYNAMIC_THRESHOLD_BUFFER_ENABLED: bool = True
```

Rationale: Kalshi is showing 1W/10L all-time and should be monitor-only until the audit shows a venue-specific improvement.

- [ ] **Step 6: Pass gate fields from `weather_signals.py`**

Modify the `WeatherGateInput(...)` call in `backend/core/weather_signals.py:239-251`.

```python
            ensemble_std=std_val,
            platform=market.platform,
            platform_paper_execution_enabled=(
                settings.WEATHER_KALSHI_PAPER_EXECUTION_ENABLED
                if market.platform == "kalshi"
                else settings.WEATHER_POLYMARKET_PAPER_EXECUTION_ENABLED
            ),
            settled_sample_count=0,
            min_settled_samples=settings.WEATHER_MIN_SETTLED_SAMPLES_BEFORE_PAPER_EXECUTION,
```

This starts conservative. Task 4 can replace the hardcoded `0` with real station/venue history from the audit module.

- [ ] **Step 7: Add scheduler safety assertion**

Modify `backend/core/scheduler.py:277-323` before creating `Trade(...)`.

```python
                if getattr(signal, "no_trade_reasons", None):
                    log_event(
                        "info",
                        f"Weather paper execution blocked by gate: {signal.no_trade_reasons}",
                        {"market": signal.market.market_id, "city": getattr(signal.market, "city_name", None)},
                    )
                    continue
```

This is a final defense so a bug in `passes_threshold` cannot execute a signal carrying explicit blockers.

- [ ] **Step 8: Verify gate and scheduler tests**

```bash
pytest tests/test_weather_reasoning_gates.py tests/test_weather_scheduler_risk_controls.py tests/test_weather_gate_structured_result.py -q
```

Expected: pass. Kalshi actionable-looking rows should remain visible but non-executed unless the config is deliberately changed.

- [ ] **Step 9: Commit**

```bash
git add backend/core/weather_methodology.py backend/core/weather_signals.py backend/core/scheduler.py backend/config.py tests/test_weather_reasoning_gates.py
git commit -m "feat: tighten weather paper execution gates"
```

---

## Task 4: Wire Calibration History Into Reasoning

**Files:**
- Modify: `backend/core/weather_audit.py`
- Modify: `backend/core/weather_signals.py:129-337`
- Create/Modify: `tests/test_weather_audit.py`
- Modify: `tests/test_weather_calibration.py`

- [ ] **Step 1: Add tests for venue/station calibration lookup**

Extend `tests/test_weather_audit.py`.

```python
from backend.core.weather_audit import load_weather_calibration_summary


def test_load_weather_calibration_summary_by_platform(tmp_path):
    conn = _init_db(tmp_path / "calibration.db")
    rows = [
        (1, "kalshi", "k1", "weather", "yes", 0.10, 75.0, "2026-06-01 00:00:00", 1, "2026-06-02 00:00:00", "loss", -75.0),
        (2, "kalshi", "k2", "weather", "yes", 0.50, 75.0, "2026-06-02 00:00:00", 1, "2026-06-03 00:00:00", "win", 75.0),
        (3, "polymarket", "p1", "weather", "no", 0.25, 75.0, "2026-06-03 00:00:00", 1, "2026-06-04 00:00:00", "win", 225.0),
    ]
    conn.executemany("""
        INSERT INTO trades (
            id, platform, event_slug, market_type, direction, entry_price, size,
            timestamp, settled, settlement_time, result, pnl
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

    summary = load_weather_calibration_summary(conn)

    assert summary["kalshi"].settled_count == 2
    assert summary["kalshi"].win_rate == 50.0
    assert summary["polymarket"].settled_count == 1
```

- [ ] **Step 2: Implement calibration summary in `weather_audit.py`**

Add:

```python
@dataclass(frozen=True)
class WeatherCalibrationSummary:
    platform: str
    settled_count: int
    wins: int
    losses: int
    win_rate: float | None
    realized_pnl: float


def load_weather_calibration_summary(conn: sqlite3.Connection) -> dict[str, WeatherCalibrationSummary]:
    rows = load_weather_trades(conn, since="1970-01-01 00:00:00")
    out: dict[str, WeatherCalibrationSummary] = {}
    by_platform: dict[str, list[WeatherTradeRow]] = {}
    for trade in rows:
        if trade.settled:
            by_platform.setdefault(trade.platform, []).append(trade)
    for platform, trades in by_platform.items():
        wins = sum(1 for trade in trades if trade.result == "win")
        losses = sum(1 for trade in trades if trade.result == "loss")
        win_rate = None if not trades else round(100.0 * wins / len(trades), 1)
        realized_pnl = round(sum(float(trade.pnl or 0.0) for trade in trades), 2)
        out[platform] = WeatherCalibrationSummary(platform, len(trades), wins, losses, win_rate, realized_pnl)
    return out
```

- [ ] **Step 3: Load history once per scan**

Modify `backend/core/weather_signals.py` so `scan_for_weather_signals()` opens the DB once and builds a `platform -> summary` map before generating signals. Pass the relevant `settled_count` into `generate_weather_signal()` via an optional argument.

Signature change:

```python
async def generate_weather_signal(
    market: WeatherMarket,
    *,
    platform_settled_sample_count: int = 0,
    platform_brier_score: float | None = None,
) -> Optional[WeatherTradingSignal]:
```

In `scan_for_weather_signals()`:

```python
    platform_history = {}
    db = SessionLocal()
    try:
        raw_conn = db.connection().connection
        from backend.core.weather_audit import load_weather_calibration_summary
        platform_history = load_weather_calibration_summary(raw_conn)
    except Exception as e:
        logger.warning("Weather calibration history unavailable: %s", e)
    finally:
        db.close()
```

Then before each call:

```python
            history = platform_history.get(market.platform)
            signal = await generate_weather_signal(
                market,
                platform_settled_sample_count=0 if history is None else history.settled_count,
                platform_brier_score=None,
            )
```

- [ ] **Step 4: Use history in calibration and gates**

Replace hardcoded `settled_sample_count=0` in Task 2/3 with `platform_settled_sample_count`.

```python
        settled_sample_count=platform_settled_sample_count,
        brier_score=platform_brier_score,
```

and in gate input:

```python
            settled_sample_count=platform_settled_sample_count,
```

- [ ] **Step 5: Verify tests**

```bash
pytest tests/test_weather_audit.py tests/test_weather_calibration.py tests/test_weather_reasoning_gates.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/core/weather_audit.py backend/core/weather_signals.py tests/test_weather_audit.py tests/test_weather_calibration.py
git commit -m "feat: use weather trade history in calibration gates"
```

---

## Task 5: Weather Scan Runtime Cache + Concurrency

**Files:**
- Create: `backend/core/weather_scan_runtime.py`
- Create: `tests/test_weather_scan_runtime.py`
- Modify: `backend/core/weather_signals.py:385-445`
- Create: `scripts/benchmark_weather_scan.py`

- [ ] **Step 1: Write failing runtime-cache tests**

Create `tests/test_weather_scan_runtime.py`.

```python
import asyncio
from datetime import date

import pytest

from backend.core.weather_scan_runtime import ForecastCache, gather_bounded


@pytest.mark.asyncio
async def test_forecast_cache_fetches_each_city_date_once():
    calls = []

    async def fetcher(city_key, target_date):
        calls.append((city_key, target_date))
        return {"city": city_key, "date": str(target_date)}

    cache = ForecastCache(fetcher=fetcher)
    d = date(2026, 6, 7)
    first = await cache.get("nyc", d)
    second = await cache.get("nyc", d)
    third = await cache.get("boston", d)

    assert first == second
    assert third["city"] == "boston"
    assert calls == [("nyc", d), ("boston", d)]


@pytest.mark.asyncio
async def test_gather_bounded_preserves_order():
    async def work(value):
        await asyncio.sleep(0)
        return value * 2

    results = await gather_bounded([lambda v=v: work(v) for v in [1, 2, 3]], limit=2)

    assert results == [2, 4, 6]
```

- [ ] **Step 2: Implement runtime helpers**

Create `backend/core/weather_scan_runtime.py`.

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Awaitable, Callable, Hashable, TypeVar

T = TypeVar("T")


@dataclass
class ForecastCache:
    fetcher: Callable[[str, date], Awaitable[T]]
    _cache: dict[tuple[str, date], T] = field(default_factory=dict)

    async def get(self, city_key: str, target_date: date) -> T:
        key = (city_key, target_date)
        if key not in self._cache:
            self._cache[key] = await self.fetcher(city_key, target_date)
        return self._cache[key]

    @property
    def size(self) -> int:
        return len(self._cache)


async def gather_bounded(callables: list[Callable[[], Awaitable[T]]], *, limit: int) -> list[T]:
    semaphore = asyncio.Semaphore(limit)

    async def run(fn: Callable[[], Awaitable[T]]) -> T:
        async with semaphore:
            return await fn()

    return await asyncio.gather(*(run(fn) for fn in callables))
```

- [ ] **Step 3: Refactor `generate_weather_signal` to accept pre-fetched forecast**

Modify signature in `backend/core/weather_signals.py`:

```python
async def generate_weather_signal(
    market: WeatherMarket,
    *,
    forecast: EnsembleForecast | None = None,
    platform_settled_sample_count: int = 0,
    platform_brier_score: float | None = None,
) -> Optional[WeatherTradingSignal]:
```

Replace line 138:

```python
    forecast = forecast or await fetch_ensemble_forecast(market.city_key, market.target_date)
```

- [ ] **Step 4: Refactor `scan_for_weather_signals` to cache and run bounded-concurrent**

In `scan_for_weather_signals()` after markets are fetched:

```python
    from backend.core.weather_scan_runtime import ForecastCache, gather_bounded

    forecast_cache = ForecastCache(fetcher=fetch_ensemble_forecast)

    async def build_signal(market):
        history = platform_history.get(market.platform)
        forecast = await forecast_cache.get(market.city_key, market.target_date)
        return await generate_weather_signal(
            market,
            forecast=forecast,
            platform_settled_sample_count=0 if history is None else history.settled_count,
            platform_brier_score=None,
        )

    results = await gather_bounded(
        [lambda market=market: build_signal(market) for market in markets],
        limit=20,
    )
    signals = [signal for signal in results if signal is not None]
    logger.info("Weather forecast cache entries: %s", forecast_cache.size)
```

Remove the old sequential `for market in markets:` block at `backend/core/weather_signals.py:420-427`.

- [ ] **Step 5: Add benchmark script**

Create `scripts/benchmark_weather_scan.py`.

```python
#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import time

from backend.core.weather_signals import scan_for_weather_signals


async def main() -> int:
    started = time.perf_counter()
    signals = await scan_for_weather_signals()
    elapsed = time.perf_counter() - started
    actionable = [s for s in signals if s.passes_threshold]
    per_signal = elapsed / max(len(signals), 1)
    print(f"signals={len(signals)} actionable={len(actionable)} elapsed_seconds={elapsed:.2f} per_signal_seconds={per_signal:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 6: Verify speed helper tests and benchmark**

```bash
pytest tests/test_weather_scan_runtime.py tests/test_weather_aigefs_fallback.py -q
python scripts/benchmark_weather_scan.py
```

Expected:
- Tests pass.
- Benchmark prints elapsed seconds and signal counts.
- If the network/provider is unavailable, benchmark failure is reported directly; do not fabricate a speed number.

- [ ] **Step 7: Commit**

```bash
git add backend/core/weather_scan_runtime.py tests/test_weather_scan_runtime.py backend/core/weather_signals.py scripts/benchmark_weather_scan.py
git commit -m "perf: cache and parallelize weather signal scans"
```

---

## Task 6: Read-Only API/Slack Reporting Endpoint

**Files:**
- Modify: `backend/api/schemas.py`
- Modify: `backend/api/main.py`
- Create/Modify: `tests/test_api_response_models.py`
- Modify: `docs/cron-context/weather-latest.md` through the report script only

- [ ] **Step 1: Add schema tests for weather audit endpoint response**

Extend `tests/test_api_response_models.py` with a Pydantic validation case for the audit payload.

```python
from backend.api.schemas import WeatherAuditResponse


def test_weather_audit_response_shape():
    response = WeatherAuditResponse(
        generated_at="2026-06-07T22:15:45",
        window_hours=72,
        total=6,
        settled=4,
        pending=2,
        wins=1,
        losses=3,
        realized_pnl=-143.75,
        ex_outlier_pnl=-143.75,
        latest_signal_total=146,
        latest_signal_actionable=3,
        latest_signal_executed=0,
    )
    assert response.window_hours == 72
    assert response.realized_pnl == -143.75
```

- [ ] **Step 2: Add schema**

Modify `backend/api/schemas.py`.

```python
class WeatherAuditResponse(BaseModel):
    generated_at: str
    window_hours: int
    total: int
    settled: int
    pending: int
    wins: int
    losses: int
    realized_pnl: float
    ex_outlier_pnl: float
    latest_signal_total: int
    latest_signal_actionable: int
    latest_signal_executed: int
```

- [ ] **Step 3: Add endpoint**

Modify `backend/api/main.py` with a read-only endpoint.

```python
@app.get("/api/weather/audit", response_model=WeatherAuditResponse)
async def get_weather_audit(window_hours: int = 72):
    from datetime import datetime
    from backend.core.weather_audit import build_weather_audit

    db = SessionLocal()
    try:
        raw_conn = db.connection().connection
        report = build_weather_audit(raw_conn, now=datetime.utcnow(), window_hours=window_hours)
        summary = report.strict_window
        batch = report.latest_signal_batch
        return WeatherAuditResponse(
            generated_at=report.generated_at,
            window_hours=report.window_hours,
            total=summary.total,
            settled=summary.settled,
            pending=summary.pending,
            wins=summary.wins,
            losses=summary.losses,
            realized_pnl=summary.realized_pnl,
            ex_outlier_pnl=summary.ex_outlier_pnl,
            latest_signal_total=batch.total,
            latest_signal_actionable=batch.actionable,
            latest_signal_executed=batch.executed,
        )
    finally:
        db.close()
```

- [ ] **Step 4: Verify endpoint model tests**

```bash
pytest tests/test_api_response_models.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/api/schemas.py backend/api/main.py tests/test_api_response_models.py
git commit -m "feat: expose read-only weather audit summary"
```

---

## Task 7: End-To-End Verification And Before/After Report

**Files:**
- Read: `tradingbot.db`
- Generated: `docs/cron-context/weather-latest.md`
- No code changes unless a verification failure identifies a specific bug

- [ ] **Step 1: Run focused backend tests**

```bash
pytest \
  tests/test_weather_audit.py \
  tests/test_weather_calibration.py \
  tests/test_weather_reasoning_gates.py \
  tests/test_weather_scan_runtime.py \
  tests/test_weather_composite_score.py \
  tests/test_weather_scheduler_risk_controls.py \
  tests/test_weather_signal_live_side_odds.py \
  tests/test_api_response_models.py \
  -q
```

Expected: all pass.

- [ ] **Step 2: Run full backend test suite if focused tests pass**

```bash
pytest tests -q
```

Expected: all pass. If unrelated legacy BTC/RT tests fail, capture the exact failures and run the focused weather subset again before merging.

- [ ] **Step 3: Generate current audit report**

```bash
python scripts/weather_audit_report.py --db tradingbot.db --window-hours 72 --format markdown --output docs/cron-context/weather-latest.md
```

Expected: report includes strict 72h metrics, ex-outlier PnL, venue split, and latest signal batch counts.

- [ ] **Step 4: Benchmark scan runtime**

```bash
python scripts/benchmark_weather_scan.py
```

Expected: benchmark prints elapsed seconds. Record the output in the final implementation summary.

- [ ] **Step 5: Optional local API smoke test**

Only if starting the app is safe in the current environment:

```bash
uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
curl -sS http://127.0.0.1:8000/api/weather/audit?window_hours=72 | python -m json.tool
```

Expected: JSON matches the CLI report. Stop the server after smoke test.

- [ ] **Step 6: Final report to Kayvon**

Include:

```markdown
## Weather Bot Audit Upgrade Complete

- Tests: <exact pytest command + pass/fail>
- Audit report: <path>
- Strict 72h PnL: <value>
- Ex-outlier PnL: <value>
- Venue split: <Kalshi / Polymarket>
- Latest signal batch: <total/actionable/executed>
- Scan benchmark: <elapsed/per-signal>
- Conservative changes: <calibration caps, Kalshi monitor-only, dynamic threshold buffer>
- Remaining risk: <sample size, source settlement ambiguity, pending trades>
```

- [ ] **Step 7: Commit verification artifacts**

```bash
git add docs/cron-context/weather-latest.md
git commit -m "docs: update weather audit status"
```

---

## Implementation Order

1. Task 1 first: make the bad/mixed performance reproducible.
2. Task 2 second: reduce model overconfidence.
3. Task 3 third: prevent weak venues/gates from paper-executing.
4. Task 4 fourth: wire actual history into reasoning.
5. Task 5 fifth: speed up scans without changing decisions.
6. Task 6 sixth: expose summary read-only.
7. Task 7 last: verify and report.

Do not start by tuning thresholds blindly. The audit/report layer must land first so every later change can be judged against real paper outcomes and outlier-adjusted metrics.

---

## Plan Self-Review

- **Spec coverage:** Covers audit, reasoning quality, calibration, venue gates, speed/runtime, reporting, and verification.
- **Safety:** Paper/simulation only; no live trading or private-account order placement.
- **Known current issue addressed:** One outlier is masking losses; Kalshi venue is underperforming; latest actionable rows can exist without execution; API can be offline while DB fallback still reports.
- **No unsupported claims:** Performance targets require benchmark output before claiming improvement.
- **No BTC/RT work:** Scope stays weather-only, matching current product focus.
