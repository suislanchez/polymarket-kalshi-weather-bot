"""Weather-specific paper account and calibration helpers.

The weather sprint treats weather markets as a separate hypothetical paper
ledger: $1,000 starting bankroll with a $1,100 target.  This module is
side-effect free and reports simulation-only progress without accessing
exchange accounts or mutating bankroll state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import math
import re
import sqlite3
from os import PathLike, fspath
from typing import Any, Iterable, Mapping

from backend.core.weather_methodology import (
    evaluate_station_anomaly_diagnostic,
    parse_settlement_metadata,
    parse_weather_rule_target_date,
)

WEATHER_PAPER_INITIAL_BANKROLL = 1000.0
WEATHER_PAPER_TARGET_BANKROLL = 1100.0
WEATHER_MARKET_TYPES = {"weather", "kalshi_weather", "polymarket_weather", "temperature", "rain"}
_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


@dataclass(frozen=True)
class WeatherResolvedForecast:
    """A quote-time forecast joined to a final weather outcome.

    This is observability/calibration only. Creating one of these rows does not
    imply a trade should have been taken; no-trade gates can still reject the
    original market for source, liquidity, spread, or uncertainty reasons.
    """

    ts: str
    market_key: str
    outcome: str | None
    market_probability: float
    resolved_yes: float
    resolved_value: float | None = None
    source_url: str | None = None


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    try:
        return obj[name]
    except (KeyError, IndexError, TypeError):
        return getattr(obj, name, default)


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_sequence(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return [raw]
        return list(parsed) if isinstance(parsed, list) else [parsed]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        return list(value)
    return [value]


def _captured_at_reference_date(captured_at: str | None) -> date | None:
    """Best-effort run-date parser for snapshot timestamps like 20260604T010832Z."""
    raw = str(captured_at or "").strip()
    compact_match = re.match(r"^(\d{4})(\d{2})(\d{2})", raw)
    if compact_match:
        try:
            return date(
                int(compact_match.group(1)),
                int(compact_match.group(2)),
                int(compact_match.group(3)),
            )
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _sqlite_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def _ensure_sqlite_column(conn: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
    if column not in _sqlite_table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def resolve_kalshi_high_temp_outcome(outcome_text: str | None, resolved_high_f: float) -> bool | None:
    """Return whether a Kalshi high-temperature line resolved Yes.

    Handles the title/subtitle phrases seen in public Kalshi rows:
    ``85° or above``, ``76° or below``, and ``83° to 84°``. Ambiguous text is
    returned as ``None`` so scoring does not silently fabricate outcomes.
    """
    text = (outcome_text or "").replace("−", "-")
    compact = re.sub(r"\s+", " ", text).strip().lower()
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*°?\s*(?:to|-)\s*(\d+(?:\.\d+)?)", compact)
    if range_match:
        low, high = sorted((float(range_match.group(1)), float(range_match.group(2))))
        return low <= float(resolved_high_f) <= high

    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", compact)]
    if not numbers:
        return None

    if "below" in compact or "or lower" in compact or "under" in compact or "less than" in compact:
        return float(resolved_high_f) <= numbers[0]
    if "above" in compact or "or higher" in compact or "greater than" in compact or compact.startswith(">"):
        return float(resolved_high_f) >= numbers[0]
    return None


def summarize_weather_forecast_calibration(
    forecasts: Iterable[Any],
) -> dict[str, int | float | None]:
    """Compute Brier/log-loss for settled weather forecasts only."""
    rows = []
    for forecast in forecasts:
        probability = _get(forecast, "market_probability", _get(forecast, "probability"))
        outcome = _get(forecast, "resolved_yes", _get(forecast, "settlement_value"))
        if probability is None or outcome is None:
            continue
        p = min(max(float(probability), 1e-6), 1 - 1e-6)
        y = float(outcome)
        if y not in (0.0, 1.0):
            continue
        rows.append((p, y))

    if not rows:
        return {"settled_forecasts": 0, "brier_score": None, "log_loss": None}

    brier = sum((p - y) ** 2 for p, y in rows) / len(rows)
    log_loss = -sum(y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in rows) / len(rows)
    return {
        "settled_forecasts": len(rows),
        "brier_score": round(brier, 4),
        "log_loss": round(log_loss, 4),
    }


def _parse_kalshi_ticker_date(market_key: str | None) -> tuple[str, date] | None:
    if not market_key:
        return None
    match = re.search(r"^(KX[A-Z]+)-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})-", market_key)
    if not match:
        return None
    month = _MONTHS.get(match.group("mon"))
    if not month:
        return None
    return match.group(1), date(2000 + int(match.group("yy")), month, int(match.group("dd")))


def _resolution_lookup_key(resolution: Any) -> tuple[str, date] | None:
    notes_raw = _get(resolution, "notes")
    notes = {}
    if isinstance(notes_raw, str):
        try:
            notes = json.loads(notes_raw)
        except json.JSONDecodeError:
            notes = {}
    elif isinstance(notes_raw, Mapping):
        notes = dict(notes_raw)

    series = notes.get("series")
    report_date = notes.get("report_date") or _get(resolution, "report_date")
    if not series or not report_date:
        market_key = _get(resolution, "market_key", "")
        match = re.search(r"^(KX[A-Z]+):[^:]+:(\d{4}-\d{2}-\d{2}):high$", market_key)
        if match:
            series, report_date = match.group(1), match.group(2)
    if not series or not report_date:
        return None
    return str(series), date.fromisoformat(str(report_date))


def join_kalshi_weather_quotes_to_outcomes(
    quotes: Iterable[Any],
    resolutions: Iterable[Any],
) -> list[WeatherResolvedForecast]:
    """Join Kalshi high-temp quote rows to final NWS CLI outcomes for scoring.

    The join is intentionally conservative: only parseable Kalshi high-temp
    tickers with a final resolution row and an unambiguous Yes/No outcome are
    returned. Other rows are skipped rather than scored with guessed outcomes.
    """
    resolved_by_series_date: dict[tuple[str, date], Any] = {}
    for resolution in resolutions:
        if _get(resolution, "venue") not in (None, "kalshi"):
            continue
        key = _resolution_lookup_key(resolution)
        if key:
            resolved_by_series_date[key] = resolution

    forecasts: list[WeatherResolvedForecast] = []
    for quote in quotes:
        if _get(quote, "venue") not in (None, "kalshi"):
            continue
        market_key = str(_get(quote, "market_key", ""))
        ticker_key = _parse_kalshi_ticker_date(market_key)
        if not ticker_key:
            continue
        resolution = resolved_by_series_date.get(ticker_key)
        if resolution is None:
            continue
        probability = _get(quote, "probability")
        if probability is None:
            continue
        resolved_value = float(_get(resolution, "resolved_value"))
        outcome_text = _get(quote, "outcome") or _get(quote, "question")
        resolved_yes = resolve_kalshi_high_temp_outcome(outcome_text, resolved_value)
        if resolved_yes is None:
            continue
        forecasts.append(
            WeatherResolvedForecast(
                ts=str(_get(quote, "ts", "")),
                market_key=market_key,
                outcome=str(outcome_text) if outcome_text is not None else None,
                market_probability=float(probability),
                resolved_yes=1.0 if resolved_yes else 0.0,
                resolved_value=resolved_value,
                source_url=_get(resolution, "source_url"),
            )
        )
    return forecasts


def build_weather_calibration_rows(
    forecasts: Iterable[Any],
    source_snapshot: str | None = None,
) -> list[dict[str, Any]]:
    """Serialize settled weather forecast scores for persistence/audit tables.

    Rows produced here are explicitly calibration-only market-implied quote
    scores. They are not paper trades and must not bypass no-trade gates.
    """
    rows: list[dict[str, Any]] = []
    for forecast in forecasts:
        probability = _get(forecast, "market_probability", _get(forecast, "probability"))
        outcome = _get(forecast, "resolved_yes", _get(forecast, "settlement_value"))
        if probability is None or outcome is None:
            continue
        p = min(max(float(probability), 1e-6), 1 - 1e-6)
        y = float(outcome)
        if y not in (0.0, 1.0):
            continue
        rows.append(
            {
                "ts": str(_get(forecast, "ts", "")),
                "venue": str(_get(forecast, "venue", "kalshi") or "kalshi"),
                "market_key": str(_get(forecast, "market_key", "")),
                "outcome": _get(forecast, "outcome"),
                "market_probability": float(probability),
                "resolved_yes": y,
                "resolved_value": _get(forecast, "resolved_value"),
                "brier_score": round((p - y) ** 2, 6),
                "log_loss": round(-(y * math.log(p) + (1.0 - y) * math.log(1.0 - p)), 6),
                "source_url": _get(forecast, "source_url"),
                "source_snapshot": source_snapshot or _get(forecast, "source_snapshot"),
                "paper_actionable": False,
                "notes": "calibration-only market-implied quote score; not a paper trade or bot edge",
            }
        )
    return rows


def _kalshi_signal_outcome_text(signal: Any) -> str | None:
    """Infer a Kalshi high-temp outcome phrase from ticker + signal reasoning.

    App DB signal rows do not persist the original Kalshi subtitle, but the
    ticker and reasoning preserve enough for conservative calibration joins for
    high-temp threshold/bucket rows. Ambiguous threshold rows return ``None`` so
    the bot-model calibration layer never fabricates outcomes.
    """
    sources_raw = _get(signal, "sources")
    if isinstance(sources_raw, str):
        try:
            sources_iterable = json.loads(sources_raw)
        except json.JSONDecodeError:
            sources_iterable = [sources_raw]
    else:
        sources_iterable = sources_raw or []
    for source in sources_iterable:
        source_text = str(source)
        if source_text.startswith("kalshi_outcome_text:"):
            explicit = source_text.split(":", 1)[1].strip()
            if explicit:
                return explicit

    ticker = str(_get(signal, "market_ticker", ""))
    reasoning = str(_get(signal, "reasoning", "") or "").lower()

    bucket_match = re.search(r"-B(\d+)(?:\.5)?$", ticker)
    if bucket_match:
        low = int(bucket_match.group(1))
        return f"{low}° to {low + 1}°"

    threshold_match = re.search(r"-T(\d+)$", ticker)
    if not threshold_match:
        return None
    threshold = int(threshold_match.group(1))
    if " below " in f" {reasoning} " or " under " in f" {reasoning} " or "<" in reasoning:
        return f"{threshold}° or below"
    if " above " in f" {reasoning} " or " higher " in f" {reasoning} " or ">" in reasoning:
        return f"{threshold + 1}° or above"
    return None


def build_bot_weather_signal_calibration_rows(
    signals: Iterable[Any],
    resolutions: Iterable[Any],
    scored_at: str,
    source_snapshot: str | None = None,
) -> list[dict[str, Any]]:
    """Join bot-generated weather signal rows to final NWS outcomes.

    This is a separate calibration layer from market-implied quote scoring. It
    uses ``model_probability`` from persisted app signals and keeps every row
    non-actionable/non-executed unless the original signal explicitly says it was
    executed. The rows are for model QA only; they never create paper trades.
    """
    resolved_by_series_date: dict[tuple[str, date], Any] = {}
    for resolution in resolutions:
        if _get(resolution, "venue") not in (None, "kalshi"):
            continue
        key = _resolution_lookup_key(resolution)
        if key:
            resolved_by_series_date[key] = resolution

    rows: list[dict[str, Any]] = []
    for signal in signals:
        if _get(signal, "platform") not in (None, "kalshi"):
            continue
        if str(_get(signal, "market_type", "weather") or "").lower() not in WEATHER_MARKET_TYPES:
            continue
        market_key = str(_get(signal, "market_ticker", ""))
        ticker_key = _parse_kalshi_ticker_date(market_key)
        if not ticker_key:
            continue
        resolution = resolved_by_series_date.get(ticker_key)
        if resolution is None:
            continue
        model_probability = _get(signal, "model_probability")
        if model_probability is None:
            continue
        outcome_text = _kalshi_signal_outcome_text(signal)
        if not outcome_text:
            continue
        resolved_value = float(_get(resolution, "resolved_value"))
        resolved_yes = resolve_kalshi_high_temp_outcome(outcome_text, resolved_value)
        if resolved_yes is None:
            continue
        p = min(max(float(model_probability), 1e-6), 1 - 1e-6)
        y = 1.0 if resolved_yes else 0.0
        rows.append(
            {
                "scored_at": str(scored_at),
                "signal_id": _get(signal, "id"),
                "signal_ts": str(_get(signal, "timestamp", "")),
                "venue": "kalshi",
                "market_key": market_key,
                "outcome": outcome_text,
                "model_probability": float(model_probability),
                "market_probability": _get(signal, "market_price"),
                "resolved_yes": y,
                "resolved_value": resolved_value,
                "brier_score": round((p - y) ** 2, 6),
                "log_loss": round(-(y * math.log(p) + (1.0 - y) * math.log(1.0 - p)), 6),
                "source_url": _get(resolution, "source_url"),
                "source_snapshot": source_snapshot or _get(resolution, "source_snapshot"),
                "paper_actionable": False,
                "executed": bool(_get(signal, "executed", False)),
                "calibration_kind": "bot_model_signal_score",
                "notes": "bot-model weather signal calibration-only; not a paper trade or execution signal",
            }
        )
    return rows


def _fetch_sqlite_rows(db_path: str | PathLike[str], query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        conn = sqlite3.connect(f"file:{fspath(db_path)}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [dict(row) for row in rows]


def load_bot_weather_signal_calibration_rows_from_sqlite(
    app_db_path: str | PathLike[str],
    research_db_path: str | PathLike[str],
    scored_at: str,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Read app weather signals and research final outcomes for model scoring.

    Both databases are opened read-only with URI ``mode=ro`` so a guessed path
    cannot silently create an empty DB during cron. Missing tables or schemas
    return an empty optional calibration set.
    """
    signals = _fetch_sqlite_rows(
        app_db_path,
        """
        SELECT id, market_ticker, platform, market_type, timestamp, direction,
               model_probability, market_price, edge, suggested_size, sources,
               reasoning, executed
        FROM signals
        WHERE market_type = 'weather'
          AND platform = 'kalshi'
          AND model_probability IS NOT NULL
          AND market_price IS NOT NULL
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """,
        (max(int(limit), 0),),
    )
    if not signals:
        return []
    resolutions = _fetch_sqlite_rows(
        research_db_path,
        """
        SELECT ts, venue, market_key, outcome, resolved_value, source,
               source_snapshot, notes, resolved_yes, source_url, source_ts
        FROM outcome_resolutions
        WHERE venue = 'kalshi'
          AND resolved_value IS NOT NULL
        """,
    )
    if not resolutions:
        return []
    return build_bot_weather_signal_calibration_rows(signals, resolutions, scored_at=scored_at)


def persist_bot_weather_signal_calibration_rows_to_sqlite(
    conn: sqlite3.Connection,
    rows: Iterable[Mapping[str, Any]],
) -> int:
    """Persist bot-model weather calibration rows in a dedicated table.

    This table is append-only by scored batch + signal identity and is separate
    from market-implied quote calibration and paper trades.  Even if an input row
    was generated from a methodology-actionable candidate, persistence here is
    forced to calibration-only/non-executed so downstream dashboards cannot
    confuse model scoring evidence with paper-ledger execution.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS weather_bot_signal_calibrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scored_at TEXT NOT NULL,
            signal_id INTEGER,
            signal_ts TEXT,
            venue TEXT NOT NULL,
            market_key TEXT NOT NULL,
            outcome TEXT,
            model_probability REAL NOT NULL,
            market_probability REAL,
            resolved_yes REAL NOT NULL,
            resolved_value REAL,
            brier_score REAL NOT NULL,
            log_loss REAL NOT NULL,
            source_url TEXT,
            source_snapshot TEXT,
            paper_actionable INTEGER NOT NULL DEFAULT 0,
            executed INTEGER NOT NULL DEFAULT 0,
            calibration_kind TEXT NOT NULL,
            notes TEXT,
            UNIQUE(scored_at, signal_id, market_key, outcome)
        )
        """
    )
    inserted = 0
    for row in rows:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO weather_bot_signal_calibrations (
                scored_at, signal_id, signal_ts, venue, market_key, outcome,
                model_probability, market_probability, resolved_yes,
                resolved_value, brier_score, log_loss, source_url,
                source_snapshot, paper_actionable, executed,
                calibration_kind, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(_get(row, "scored_at", "")),
                _get(row, "signal_id"),
                str(_get(row, "signal_ts", "")),
                str(_get(row, "venue", "kalshi") or "kalshi"),
                str(_get(row, "market_key", "")),
                _get(row, "outcome"),
                float(_get(row, "model_probability")),
                _get(row, "market_probability"),
                float(_get(row, "resolved_yes")),
                _get(row, "resolved_value"),
                float(_get(row, "brier_score")),
                float(_get(row, "log_loss")),
                _get(row, "source_url"),
                _get(row, "source_snapshot"),
                0,
                0,
                str(_get(row, "calibration_kind", "bot_model_signal_score") or "bot_model_signal_score"),
                _get(row, "notes"),
            ),
        )
        inserted += cursor.rowcount if cursor.rowcount else 0
    return inserted


def summarize_latest_weather_calibration_rows(
    rows: Iterable[Any],
) -> dict[str, int | float | str | bool | None]:
    """Summarize the newest persisted weather calibration batch.

    The research SQLite table is append-only by ``scored_at``. Dashboard/API
    consumers should show the latest batch as calibration observability, not as
    paper-trade PnL or bot alpha. Older batches are ignored here to avoid mixing
    duplicate quote scores across repeated cron scoring runs.
    """
    row_list = list(rows)
    if not row_list:
        return {
            "latest_scored_at": None,
            "settled_forecasts": 0,
            "brier_score": None,
            "log_loss": None,
            "paper_actionable": False,
            "market_scope": "weather",
            "calibration_kind": "market_implied_quote_score",
            "source_snapshot": None,
        }

    latest_scored_at = max(str(_get(row, "scored_at", "")) for row in row_list)
    latest_rows = [row for row in row_list if str(_get(row, "scored_at", "")) == latest_scored_at]
    brier_values = [float(_get(row, "brier_score")) for row in latest_rows if _get(row, "brier_score") is not None]
    log_loss_values = [float(_get(row, "log_loss")) for row in latest_rows if _get(row, "log_loss") is not None]
    source_snapshot = next((_get(row, "source_snapshot") for row in latest_rows if _get(row, "source_snapshot")), None)

    return {
        "latest_scored_at": latest_scored_at,
        "settled_forecasts": len(latest_rows),
        "brier_score": round(sum(brier_values) / len(brier_values), 4) if brier_values else None,
        "log_loss": round(sum(log_loss_values) / len(log_loss_values), 4) if log_loss_values else None,
        "paper_actionable": False,
        "market_scope": "weather",
        "calibration_kind": "market_implied_quote_score",
        "source_snapshot": source_snapshot,
    }


def _normalize_weather_calibration_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["paper_actionable"] = bool(normalized.get("paper_actionable", False))
    return normalized


def _normalize_weather_bot_calibration_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["paper_actionable"] = bool(normalized.get("paper_actionable", False))
    normalized["executed"] = bool(normalized.get("executed", False))
    return normalized


def _fetch_latest_weather_calibration_rows(
    db_path: str | PathLike[str],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    try:
        conn = sqlite3.connect(f"file:{fspath(db_path)}?mode=ro", uri=True)
    except sqlite3.Error:
        return []

    conn.row_factory = sqlite3.Row
    try:
        latest = conn.execute(
            "SELECT MAX(scored_at) AS latest_scored_at FROM weather_forecast_calibrations"
        ).fetchone()
        latest_scored_at = latest["latest_scored_at"] if latest else None
        if not latest_scored_at:
            return []
        query = """
            SELECT scored_at, quote_ts, venue, market_key, outcome,
                   market_probability, resolved_yes, resolved_value,
                   brier_score, log_loss, source_url, source_snapshot,
                   paper_actionable, notes
            FROM weather_forecast_calibrations
            WHERE scored_at = ?
            ORDER BY brier_score DESC, log_loss DESC, market_key ASC
        """
        params: tuple[Any, ...]
        if limit is not None:
            query += " LIMIT ?"
            params = (latest_scored_at, max(int(limit), 0))
        else:
            params = (latest_scored_at,)
        rows = conn.execute(query, params).fetchall()
    except (sqlite3.Error, ValueError):
        return []
    finally:
        conn.close()

    return [_normalize_weather_calibration_row(dict(row)) for row in rows]


def load_latest_weather_calibration_summary_from_sqlite(
    db_path: str | PathLike[str],
) -> dict[str, int | float | str | bool | None] | None:
    """Read the newest weather calibration batch from a SQLite DB.

    This helper is intentionally dependency-light and read-only so cron/schema
    tests can validate dashboard payload behavior without importing FastAPI,
    SQLAlchemy, or route modules. Missing DB/table/schema errors are treated as
    an absent optional summary, not as a reason to break the dashboard or weaken
    no-trade gates.
    """
    rows = _fetch_latest_weather_calibration_rows(db_path)
    if not rows:
        return None
    return summarize_latest_weather_calibration_rows(rows)


def load_latest_weather_calibration_rows_from_sqlite(
    db_path: str | PathLike[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return newest weather calibration audit rows ordered by largest error.

    Rows are read-only, latest-batch only, and explicitly non-actionable. They
    are suitable for dashboard diagnostics so humans can inspect where market-
    implied weather probabilities were most wrong without mixing older repeated
    scoring batches or touching paper ledgers.
    """
    return _fetch_latest_weather_calibration_rows(db_path, limit=limit)


def load_latest_weather_bot_signal_calibration_rows_from_sqlite(
    db_path: str | PathLike[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return newest bot-model weather calibration audit rows by largest error.

    This is read-only model QA telemetry. Rows are intentionally separate from
    market-implied quote calibration and paper ledgers, and they are normalized
    as ``paper_actionable=False`` / ``executed=False`` before returning.
    Missing DB/table/schema returns an empty optional row set.
    """
    try:
        conn = sqlite3.connect(f"file:{fspath(db_path)}?mode=ro", uri=True)
    except sqlite3.Error:
        return []

    conn.row_factory = sqlite3.Row
    try:
        latest = conn.execute(
            "SELECT MAX(scored_at) AS latest_scored_at FROM weather_bot_signal_calibrations"
        ).fetchone()
        latest_scored_at = latest["latest_scored_at"] if latest else None
        if not latest_scored_at:
            return []
        query = """
            SELECT scored_at, signal_id, signal_ts, venue, market_key, outcome,
                   model_probability, market_probability, resolved_yes,
                   resolved_value, brier_score, log_loss, source_url,
                   source_snapshot, paper_actionable, executed,
                   calibration_kind, notes
            FROM weather_bot_signal_calibrations
            WHERE scored_at = ?
            ORDER BY brier_score DESC, log_loss DESC, market_key ASC, signal_id ASC
        """
        params: tuple[Any, ...]
        if limit is not None:
            query += " LIMIT ?"
            params = (latest_scored_at, max(int(limit), 0))
        else:
            params = (latest_scored_at,)
        rows = conn.execute(query, params).fetchall()
    except (sqlite3.Error, ValueError):
        return []
    finally:
        conn.close()

    return [_normalize_weather_bot_calibration_row(dict(row)) for row in rows]


def load_latest_weather_bot_signal_calibration_summary_from_sqlite(
    db_path: str | PathLike[str],
) -> dict[str, int | float | str | bool | None] | None:
    """Read newest bot-model weather calibration batch from SQLite.

    These rows score persisted bot/model probabilities against final weather
    outcomes and are intentionally separate from both market-implied quote
    calibration and the weather paper ledger. The database is opened read-only
    so missing paths/tables become absent telemetry instead of creating files or
    weakening no-trade gates.
    """
    try:
        conn = sqlite3.connect(f"file:{fspath(db_path)}?mode=ro", uri=True)
    except sqlite3.Error:
        return None

    conn.row_factory = sqlite3.Row
    try:
        latest = conn.execute(
            "SELECT MAX(scored_at) AS latest_scored_at FROM weather_bot_signal_calibrations"
        ).fetchone()
        latest_scored_at = latest["latest_scored_at"] if latest else None
        if not latest_scored_at:
            return None
        rows = conn.execute(
            """
            SELECT scored_at, brier_score, log_loss, source_snapshot
            FROM weather_bot_signal_calibrations
            WHERE scored_at = ?
            """,
            (latest_scored_at,),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    if not rows:
        return None
    brier_values = [float(row["brier_score"]) for row in rows if row["brier_score"] is not None]
    log_loss_values = [float(row["log_loss"]) for row in rows if row["log_loss"] is not None]
    source_snapshot = next((row["source_snapshot"] for row in rows if row["source_snapshot"]), None)
    return {
        "latest_scored_at": str(latest_scored_at),
        "settled_forecasts": len(rows),
        "brier_score": round(sum(brier_values) / len(brier_values), 4) if brier_values else None,
        "log_loss": round(sum(log_loss_values) / len(log_loss_values), 4) if log_loss_values else None,
        "paper_actionable": False,
        "market_scope": "weather",
        "calibration_kind": "bot_model_signal_score",
        "source_snapshot": source_snapshot,
    }


_POLYMARKET_WEATHER_SOURCE_STATE_NOTE = (
    "source-state only; requires direct source/final outcome, independent model, "
    "CLOB depth/spread, and sizing gates before actionability"
)

_POLYMARKET_SOURCE_STATE_CATEGORY_ALIASES = {
    "warn": "warning",
    "warning": "warning",
    "part": "partial",
    "partial": "partial",
    "hko": "hko",
    "obs": "observed",
    "observed": "observed",
    "src": "source_only",
    "source": "source_only",
    "source_only": "source_only",
    "source-only": "source_only",
}
_POLYMARKET_SOURCE_STATE_REPRESENTATIVE_CATEGORIES = (
    "warning",
    "partial",
    "hko",
    "observed",
    "source_only",
)

_POLYMARKET_SOURCE_STATE_MARKET_STATE_ALIASES = {
    "open": "open",
    "active": "open",
    "live": "open",
    "closed": "closed",
    "settled": "closed",
    "resolved": "closed",
}


def _normalize_polymarket_source_state_category(category: str | None) -> str | None:
    raw = str(category or "").strip().lower().replace(" ", "_")
    if not raw or raw == "all":
        return None
    return _POLYMARKET_SOURCE_STATE_CATEGORY_ALIASES.get(raw)


def _raw_filter_value(value: str | None) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _is_empty_or_all_filter(value: str | None) -> bool:
    return _raw_filter_value(value) in {"", "all"}


def _normalize_polymarket_source_state_market_state(market_state: str | None) -> str | None:
    raw = _raw_filter_value(market_state)
    if not raw or raw == "all":
        return None
    return _POLYMARKET_SOURCE_STATE_MARKET_STATE_ALIASES.get(raw)


def _polymarket_weather_source_state_operator_category(
    row: Any,
    anomaly_status: str | None = None,
) -> str:
    """Return the dashboard/source-state operator category for a row.

    The same precedence is used by newest-batch summaries, default compact
    samples, and category-specific drilldowns: warning > partial > HKO blocker >
    observed > generic source-only. This is visibility-only QA; it never upgrades
    paper actionability.
    """
    status = str(
        anomaly_status
        if anomaly_status is not None
        else (_get(row, "station_anomaly_status") or "")
    ).strip().lower()
    capture_status = str(_get(row, "source_capture_status") or "").strip().lower()
    source = str(_get(row, "settlement_source") or "").strip().lower()
    source_url = str(_get(row, "settlement_source_url") or "").strip().lower()
    if status.startswith("warning"):
        return "warning"
    if "partial" in capture_status:
        return "partial"
    if (source == "hko" or capture_status.startswith("hko_")) and "missing_target" in capture_status:
        return "hko"
    if "hko.gov.hk" in source_url or "weather.gov.hk" in source_url:
        if "missing_target" in capture_status:
            return "hko"
    if _get(row, "source_observed_value") is not None:
        return "observed"
    return "source_only"


def build_polymarket_weather_source_state_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    captured_at: str,
    source_snapshot: str | None = None,
) -> list[dict[str, Any]]:
    """Build non-actionable source-state rows for Polymarket weather markets.

    This preserves exact rule/source/station/precision plus line-level book
    context for Wunderground/HKO-style weather markets. It is observability
    only: every row is forced ``paper_actionable=False`` and must later be
    joined to direct final source evidence, model probabilities, spread/depth,
    and sizing gates before any paper action can be considered.
    """
    source_rows: list[dict[str, Any]] = []
    for row in rows:
        if str(_get(row, "venue", "")).lower() != "polymarket":
            continue
        settlement = parse_settlement_metadata(_get(row, "rule_text") or "")
        if not (settlement.source or settlement.station_code or settlement.source_url):
            continue
        best_bid = _get(row, "best_bid")
        best_ask = _get(row, "best_ask")
        market_probability = _coerce_optional_float(
            _get(row, "market_probability", _get(row, "gamma_price", _get(row, "price")))
        )
        execution_spread = None
        if best_bid is not None and best_ask is not None:
            try:
                execution_spread = round(float(best_ask) - float(best_bid), 6)
            except (TypeError, ValueError):
                execution_spread = None
        target_date = parse_weather_rule_target_date(
            " ".join(
                str(part or "")
                for part in (
                    _get(row, "event_title"),
                    _get(row, "question"),
                    _get(row, "rule_text"),
                    _get(row, "slug"),
                )
            ),
            reference_date=_captured_at_reference_date(captured_at),
        )
        source_observed_value = _coerce_optional_float(_get(row, "source_observed_value"))
        raw_neighbor_values = _coerce_optional_sequence(
            _get(row, "station_neighbor_values", _get(row, "neighbor_observed_values"))
        )
        station_anomaly_neighbor_values = [
            value
            for value in (_coerce_optional_float(item) for item in (raw_neighbor_values or []))
            if value is not None
        ]
        anomaly = evaluate_station_anomaly_diagnostic(
            source_observed_value,
            station_anomaly_neighbor_values,
        )
        station_anomaly_status = _get(row, "station_anomaly_status") or anomaly.status
        station_anomaly_neighbor_count = _coerce_optional_int(
            _get(row, "station_anomaly_neighbor_count")
        )
        if station_anomaly_neighbor_count is None:
            station_anomaly_neighbor_count = anomaly.neighbor_count
        station_anomaly_max_delta = _coerce_optional_float(_get(row, "station_anomaly_max_delta"))
        if station_anomaly_max_delta is None:
            station_anomaly_max_delta = anomaly.max_delta
        source_rows.append(
            {
                "captured_at": captured_at,
                "event_slug": _get(row, "slug"),
                "condition_id": _get(row, "condition_id"),
                "question": _get(row, "question"),
                "outcome": _get(row, "outcome"),
                "target_date": target_date.isoformat() if target_date else None,
                "token_id": _get(row, "token_id"),
                "closed": bool(_get(row, "closed", False)),
                "settlement_source": settlement.source,
                "settlement_station": settlement.station_code,
                "settlement_station_name": settlement.station_name,
                "settlement_source_url": settlement.source_url,
                "settlement_units": settlement.units,
                "settlement_precision": settlement.precision,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "execution_spread": execution_spread,
                "market_probability": market_probability,
                "top_ask_size": _get(row, "top_ask_size"),
                "volume": _get(row, "volume"),
                "liquidity": _get(row, "liquidity"),
                "source_snapshot": source_snapshot,
                "source_capture_status": _get(row, "source_capture_status"),
                "source_observed_value": source_observed_value,
                "source_observed_unit": _get(row, "source_observed_unit"),
                "source_observed_at": _get(row, "source_observed_at"),
                "source_capture_snapshot": _get(row, "source_capture_snapshot"),
                "station_anomaly_status": station_anomaly_status,
                "station_anomaly_neighbor_count": station_anomaly_neighbor_count,
                "station_anomaly_neighbor_values": station_anomaly_neighbor_values,
                "station_anomaly_max_delta": station_anomaly_max_delta,
                "paper_actionable": False,
                "notes": _POLYMARKET_WEATHER_SOURCE_STATE_NOTE,
            }
        )
    return source_rows


def persist_polymarket_weather_source_state_rows_to_sqlite(
    conn: sqlite3.Connection,
    rows: Iterable[Mapping[str, Any]],
) -> int:
    """Persist Polymarket weather source-state rows without trade effects."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS polymarket_weather_source_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            event_slug TEXT,
            condition_id TEXT NOT NULL,
            question TEXT,
            outcome TEXT,
            target_date TEXT,
            token_id TEXT,
            closed INTEGER NOT NULL DEFAULT 0,
            settlement_source TEXT,
            settlement_station TEXT,
            settlement_station_name TEXT,
            settlement_source_url TEXT,
            settlement_units TEXT,
            settlement_precision TEXT,
            best_bid REAL,
            best_ask REAL,
            execution_spread REAL,
            market_probability REAL,
            top_ask_size REAL,
            volume REAL,
            liquidity REAL,
            source_snapshot TEXT,
            source_capture_status TEXT,
            source_observed_value REAL,
            source_observed_unit TEXT,
            source_observed_at TEXT,
            source_capture_snapshot TEXT,
            station_anomaly_status TEXT,
            station_anomaly_neighbor_count INTEGER,
            station_anomaly_neighbor_values TEXT,
            station_anomaly_max_delta REAL,
            paper_actionable INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            UNIQUE(captured_at, condition_id, outcome)
        )
        """
    )
    _ensure_sqlite_column(conn, "polymarket_weather_source_states", "target_date", "TEXT")
    _ensure_sqlite_column(conn, "polymarket_weather_source_states", "market_probability", "REAL")
    _ensure_sqlite_column(conn, "polymarket_weather_source_states", "source_capture_status", "TEXT")
    _ensure_sqlite_column(conn, "polymarket_weather_source_states", "source_observed_value", "REAL")
    _ensure_sqlite_column(conn, "polymarket_weather_source_states", "source_observed_unit", "TEXT")
    _ensure_sqlite_column(conn, "polymarket_weather_source_states", "source_observed_at", "TEXT")
    _ensure_sqlite_column(conn, "polymarket_weather_source_states", "source_capture_snapshot", "TEXT")
    _ensure_sqlite_column(conn, "polymarket_weather_source_states", "station_anomaly_status", "TEXT")
    _ensure_sqlite_column(conn, "polymarket_weather_source_states", "station_anomaly_neighbor_count", "INTEGER")
    _ensure_sqlite_column(conn, "polymarket_weather_source_states", "station_anomaly_neighbor_values", "TEXT")
    _ensure_sqlite_column(conn, "polymarket_weather_source_states", "station_anomaly_max_delta", "REAL")
    inserted = 0
    for row in rows:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO polymarket_weather_source_states (
                captured_at, event_slug, condition_id, question, outcome,
                target_date, token_id, closed, settlement_source, settlement_station,
                settlement_station_name, settlement_source_url, settlement_units,
                settlement_precision, best_bid, best_ask, execution_spread,
                market_probability,
                top_ask_size, volume, liquidity, source_snapshot,
                source_capture_status, source_observed_value, source_observed_unit,
                source_observed_at, source_capture_snapshot,
                station_anomaly_status, station_anomaly_neighbor_count, station_anomaly_neighbor_values, station_anomaly_max_delta,
                paper_actionable, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("captured_at"),
                row.get("event_slug"),
                row.get("condition_id"),
                row.get("question"),
                row.get("outcome"),
                row.get("target_date"),
                row.get("token_id"),
                1 if row.get("closed") else 0,
                row.get("settlement_source"),
                row.get("settlement_station"),
                row.get("settlement_station_name"),
                row.get("settlement_source_url"),
                row.get("settlement_units"),
                row.get("settlement_precision"),
                row.get("best_bid"),
                row.get("best_ask"),
                row.get("execution_spread"),
                row.get("market_probability"),
                row.get("top_ask_size"),
                row.get("volume"),
                row.get("liquidity"),
                row.get("source_snapshot"),
                row.get("source_capture_status"),
                row.get("source_observed_value"),
                row.get("source_observed_unit"),
                row.get("source_observed_at"),
                row.get("source_capture_snapshot"),
                row.get("station_anomaly_status"),
                row.get("station_anomaly_neighbor_count"),
                json.dumps(row.get("station_anomaly_neighbor_values") or []),
                row.get("station_anomaly_max_delta"),
                0,
                row.get("notes") or _POLYMARKET_WEATHER_SOURCE_STATE_NOTE,
            ),
        )
        if conn.total_changes > before:
            inserted += 1
    conn.commit()
    return inserted


def _normalize_polymarket_weather_source_state_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["closed"] = bool(normalized.get("closed", False))
    normalized["market_probability"] = _coerce_optional_float(normalized.get("market_probability"))
    normalized["source_observed_value"] = _coerce_optional_float(normalized.get("source_observed_value"))
    normalized["station_anomaly_neighbor_count"] = _coerce_optional_int(normalized.get("station_anomaly_neighbor_count"))
    normalized["station_anomaly_neighbor_values"] = [
        value
        for value in (
            _coerce_optional_float(item)
            for item in (_coerce_optional_sequence(normalized.get("station_anomaly_neighbor_values")) or [])
        )
        if value is not None
    ]
    normalized["station_anomaly_max_delta"] = _coerce_optional_float(normalized.get("station_anomaly_max_delta"))
    if not normalized.get("station_anomaly_status"):
        normalized["station_anomaly_status"] = evaluate_station_anomaly_diagnostic(
            normalized.get("source_observed_value")
        ).status
    normalized["paper_actionable"] = False
    normalized["source_state_label"] = "Polymarket weather source-state only / non-actionable"
    if not normalized.get("notes"):
        normalized["notes"] = _POLYMARKET_WEATHER_SOURCE_STATE_NOTE
    return normalized


def load_latest_polymarket_weather_source_state_rows_from_sqlite(
    db_path: str | PathLike[str],
    limit: int = 5,
    category: str | None = None,
    market_state: str | None = None,
) -> list[dict[str, Any]]:
    """Return newest Polymarket weather source-state rows from SQLite.

    Rows preserve settlement source/station and line-level book context for the
    latest captured batch only. They are read-only dashboard/audit telemetry and
    are force-normalized as non-actionable; missing DB/table/schema returns an
    empty row set without creating a SQLite file.
    """
    try:
        conn = sqlite3.connect(f"file:{fspath(db_path)}?mode=ro", uri=True)
    except sqlite3.Error:
        return []

    conn.row_factory = sqlite3.Row
    try:
        latest = conn.execute(
            "SELECT MAX(captured_at) AS latest_captured_at FROM polymarket_weather_source_states"
        ).fetchone()
        latest_captured_at = latest["latest_captured_at"] if latest else None
        if not latest_captured_at:
            return []
        columns = _sqlite_table_columns(conn, "polymarket_weather_source_states")
        target_date_expr = "target_date" if "target_date" in columns else "NULL AS target_date"
        market_probability_expr = "market_probability" if "market_probability" in columns else "NULL AS market_probability"
        source_capture_status_expr = "source_capture_status" if "source_capture_status" in columns else "NULL AS source_capture_status"
        source_observed_value_expr = "source_observed_value" if "source_observed_value" in columns else "NULL AS source_observed_value"
        source_observed_unit_expr = "source_observed_unit" if "source_observed_unit" in columns else "NULL AS source_observed_unit"
        source_observed_at_expr = "source_observed_at" if "source_observed_at" in columns else "NULL AS source_observed_at"
        source_capture_snapshot_expr = "source_capture_snapshot" if "source_capture_snapshot" in columns else "NULL AS source_capture_snapshot"
        station_anomaly_status_expr = "station_anomaly_status" if "station_anomaly_status" in columns else "NULL AS station_anomaly_status"
        station_anomaly_neighbor_count_expr = "station_anomaly_neighbor_count" if "station_anomaly_neighbor_count" in columns else "NULL AS station_anomaly_neighbor_count"
        station_anomaly_neighbor_values_expr = "station_anomaly_neighbor_values" if "station_anomaly_neighbor_values" in columns else "NULL AS station_anomaly_neighbor_values"
        station_anomaly_max_delta_expr = "station_anomaly_max_delta" if "station_anomaly_max_delta" in columns else "NULL AS station_anomaly_max_delta"
        query = f"""
            SELECT captured_at, event_slug, condition_id, question, outcome,
                   {target_date_expr}, token_id, closed, settlement_source, settlement_station,
                   settlement_station_name, settlement_source_url,
                   settlement_units, settlement_precision, best_bid, best_ask,
                   execution_spread, {market_probability_expr}, top_ask_size, volume, liquidity,
                   source_snapshot, {source_capture_status_expr}, {source_observed_value_expr},
                   {source_observed_unit_expr}, {source_observed_at_expr}, {source_capture_snapshot_expr},
                   {station_anomaly_status_expr}, {station_anomaly_neighbor_count_expr},
                   {station_anomaly_neighbor_values_expr}, {station_anomaly_max_delta_expr},
                   paper_actionable, notes
            FROM polymarket_weather_source_states
            WHERE captured_at = ?
        """
        rows = conn.execute(query, (latest_captured_at,)).fetchall()
    except (sqlite3.Error, ValueError):
        return []
    finally:
        conn.close()

    def source_state_sample_priority(row: Mapping[str, Any]) -> int:
        status = str(row.get("station_anomaly_status") or "").strip().lower()
        capture_status = str(row.get("source_capture_status") or "").strip().lower()
        if status.startswith("warning"):
            return 0
        if capture_status.startswith("wunderground_history_partial"):
            return 1
        if status == "not_checked_missing_neighbors":
            return 2
        if status == "pass":
            return 3
        if status == "not_checked_missing_observation":
            return 4
        return 5

    def source_state_sample_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            source_state_sample_priority(row),
            bool(row.get("closed", False)),
            str(row.get("event_slug") or ""),
            str(row.get("condition_id") or ""),
            str(row.get("outcome") or ""),
        )

    normalized_rows = [_normalize_polymarket_weather_source_state_row(dict(row)) for row in rows]
    normalized_rows.sort(key=source_state_sample_sort_key)
    requested_category = _normalize_polymarket_source_state_category(category)
    if category is not None and not _is_empty_or_all_filter(category) and requested_category is None:
        return []
    requested_market_state = _normalize_polymarket_source_state_market_state(market_state)
    if market_state is not None and not _is_empty_or_all_filter(market_state) and requested_market_state is None:
        return []
    if requested_market_state == "open":
        normalized_rows = [row for row in normalized_rows if not bool(row.get("closed", False))]
    elif requested_market_state == "closed":
        normalized_rows = [row for row in normalized_rows if bool(row.get("closed", False))]
    if requested_category is not None:
        normalized_rows = [
            row
            for row in normalized_rows
            if _polymarket_weather_source_state_operator_category(row) == requested_category
        ]
    if limit is None:
        return normalized_rows
    limit_int = max(int(limit), 0)
    if limit_int == 0:
        return []
    sample: list[dict[str, Any]] = []

    def row_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            row.get("captured_at"),
            row.get("event_slug"),
            row.get("condition_id"),
            row.get("outcome"),
            row.get("token_id"),
        )

    selected_keys: set[tuple[Any, ...]] = set()

    def append_row(row: dict[str, Any]) -> bool:
        key = row_key(row)
        if key in selected_keys:
            return False
        sample.append(row)
        selected_keys.add(key)
        return True

    # Keep one row from each operator category when possible before filling the
    # compact sample by severity. This avoids warning-heavy batches hiding HKO,
    # observed, or generic source-only blockers from dashboard/API drilldown.
    for representative_category in _POLYMARKET_SOURCE_STATE_REPRESENTATIVE_CATEGORIES:
        if len(sample) >= limit_int:
            break
        representative = next(
            (
                row
                for row in normalized_rows
                if _polymarket_weather_source_state_operator_category(row) == representative_category
                and row_key(row) not in selected_keys
            ),
            None,
        )
        if representative is not None:
            append_row(representative)

    for row in normalized_rows:
        if len(sample) >= limit_int:
            break
        append_row(row)
    sample.sort(key=source_state_sample_sort_key)
    return sample


def load_latest_polymarket_weather_source_state_summary_from_sqlite(
    db_path: str | PathLike[str],
) -> dict[str, Any] | None:
    """Summarize newest Polymarket weather source-state batch read-only.

    The summary is coverage/audit metadata only: it reports whether the latest
    batch has source URLs, station mapping, line-level books, and closed rows,
    while force-labelling the batch non-actionable. Missing DB/table/schema
    returns ``None`` without creating a SQLite file.
    """
    try:
        conn = sqlite3.connect(f"file:{fspath(db_path)}?mode=ro", uri=True)
    except sqlite3.Error:
        return None

    conn.row_factory = sqlite3.Row
    try:
        latest = conn.execute(
            "SELECT MAX(captured_at) AS latest_captured_at FROM polymarket_weather_source_states"
        ).fetchone()
        latest_captured_at = latest["latest_captured_at"] if latest else None
        if not latest_captured_at:
            return None
        columns = _sqlite_table_columns(conn, "polymarket_weather_source_states")
        target_date_expr = "target_date" if "target_date" in columns else "NULL AS target_date"
        market_probability_expr = "market_probability" if "market_probability" in columns else "NULL AS market_probability"
        source_capture_status_expr = "source_capture_status" if "source_capture_status" in columns else "NULL AS source_capture_status"
        source_observed_value_expr = "source_observed_value" if "source_observed_value" in columns else "NULL AS source_observed_value"
        station_anomaly_status_expr = "station_anomaly_status" if "station_anomaly_status" in columns else "NULL AS station_anomaly_status"
        station_anomaly_neighbor_count_expr = "station_anomaly_neighbor_count" if "station_anomaly_neighbor_count" in columns else "NULL AS station_anomaly_neighbor_count"
        station_anomaly_max_delta_expr = "station_anomaly_max_delta" if "station_anomaly_max_delta" in columns else "NULL AS station_anomaly_max_delta"
        rows = conn.execute(
            f"""
            SELECT event_slug, condition_id, outcome, {target_date_expr}, settlement_source, settlement_station,
                   settlement_source_url, best_bid, best_ask, {market_probability_expr}, top_ask_size,
                   closed, source_snapshot, {source_capture_status_expr}, {source_observed_value_expr},
                   {station_anomaly_status_expr}, {station_anomaly_neighbor_count_expr}, {station_anomaly_max_delta_expr}
            FROM polymarket_weather_source_states
            WHERE captured_at = ?
            """,
            (latest_captured_at,),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    if not rows:
        return None

    def has_value(value: Any) -> bool:
        return value is not None and str(value).strip() != ""

    unique_events = {str(row["event_slug"]) for row in rows if has_value(row["event_slug"])}
    unique_conditions = {str(row["condition_id"]) for row in rows if has_value(row["condition_id"])}
    unique_stations = {
        str(row["settlement_station"])
        for row in rows
        if has_value(row["settlement_station"])
    }
    unique_target_dates = {
        str(row["target_date"])
        for row in rows
        if has_value(row["target_date"])
    }
    unique_source_urls = {
        str(row["settlement_source_url"])
        for row in rows
        if has_value(row["settlement_source_url"])
    }
    source_capture_unique_urls = {
        str(row["settlement_source_url"])
        for row in rows
        if has_value(row["settlement_source_url"]) and has_value(row["source_capture_status"])
    }
    source_capture_missing_urls = unique_source_urls - source_capture_unique_urls
    condition_outcomes: dict[str, set[str]] = {}
    event_yes_probability_mass: dict[str, float] = {}
    market_probability_rows = 0
    yes_market_probability_rows = 0
    no_market_probability_rows = 0
    for row in rows:
        condition_id = row["condition_id"]
        outcome = str(row["outcome"] or "").strip().lower()
        if has_value(condition_id) and outcome:
            condition_outcomes.setdefault(str(condition_id), set()).add(outcome)
        probability = _coerce_optional_float(row["market_probability"])
        if probability is None:
            continue
        market_probability_rows += 1
        if outcome == "yes":
            yes_market_probability_rows += 1
            if has_value(row["event_slug"]):
                event_yes_probability_mass[str(row["event_slug"])] = event_yes_probability_mass.get(str(row["event_slug"]), 0.0) + probability
        elif outcome == "no":
            no_market_probability_rows += 1
    complete_binary_condition_pairs = sum(1 for outcomes in condition_outcomes.values() if {"yes", "no"}.issubset(outcomes))
    incomplete_binary_condition_pairs = len(condition_outcomes) - complete_binary_condition_pairs
    yes_mass_values = [round(value, 6) for value in event_yes_probability_mass.values()]
    yes_mass_sanity_passed = sum(1 for value in yes_mass_values if 0.95 <= value <= 1.05)
    def normalized_station_anomaly_status(row: sqlite3.Row) -> str:
        status = str(row["station_anomaly_status"] or "").strip()
        if status:
            return status
        # Older source-state batches predate station-anomaly columns. Treat
        # absent/blank diagnostics as an explicit not-checked blocker instead
        # of counting them as checked/pass rows in operator summaries.
        return evaluate_station_anomaly_diagnostic(row["source_observed_value"]).status

    rows_with_anomaly_status = [(row, normalized_station_anomaly_status(row)) for row in rows]
    station_anomaly_statuses = [status for _, status in rows_with_anomaly_status]

    source_state_category_counts = {
        "warning": 0,
        "partial": 0,
        "hko": 0,
        "observed": 0,
        "source_only": 0,
    }
    open_source_state_category_counts = dict.fromkeys(source_state_category_counts, 0)
    closed_source_state_category_counts = dict.fromkeys(source_state_category_counts, 0)
    for row, anomaly_status in rows_with_anomaly_status:
        category = _polymarket_weather_source_state_operator_category(row, anomaly_status)
        source_state_category_counts[category] += 1
        if bool(row["closed"]):
            closed_source_state_category_counts[category] += 1
        else:
            open_source_state_category_counts[category] += 1

    station_anomaly_checked_rows = sum(
        1 for status in station_anomaly_statuses if not status.startswith("not_checked")
    )
    station_anomaly_not_checked_rows = sum(
        1 for status in station_anomaly_statuses if status.startswith("not_checked")
    )
    station_anomaly_missing_observation_rows = sum(
        1 for status in station_anomaly_statuses if status == "not_checked_missing_observation"
    )
    station_anomaly_missing_neighbors_rows = sum(
        1 for status in station_anomaly_statuses if status == "not_checked_missing_neighbors"
    )
    station_anomaly_warning_rows = sum(
        1 for status in station_anomaly_statuses if status.startswith("warning")
    )
    station_anomaly_passed_rows = sum(1 for status in station_anomaly_statuses if status == "pass")
    station_anomaly_warning_batch_rows = [
        row for row, status in rows_with_anomaly_status if status.startswith("warning")
    ]
    station_anomaly_warning_unique_events = {
        str(row["event_slug"])
        for row in station_anomaly_warning_batch_rows
        if has_value(row["event_slug"])
    }
    station_anomaly_warning_unique_stations = {
        str(row["settlement_station"])
        for row in station_anomaly_warning_batch_rows
        if has_value(row["settlement_station"])
    }
    station_anomaly_warning_unique_source_urls = {
        str(row["settlement_source_url"])
        for row in station_anomaly_warning_batch_rows
        if has_value(row["settlement_source_url"])
    }
    station_anomaly_warning_max_delta_values = [
        value
        for value in (
            _coerce_optional_float(row["station_anomaly_max_delta"])
            for row in station_anomaly_warning_batch_rows
        )
        if value is not None
    ]
    station_anomaly_neighbor_count_values = [
        value
        for value in (_coerce_optional_int(row["station_anomaly_neighbor_count"]) for row in rows)
        if value is not None and value > 0
    ]
    station_anomaly_max_delta_values = [
        value
        for value in (_coerce_optional_float(row["station_anomaly_max_delta"]) for row in rows)
        if value is not None
    ]
    history_capture_rows = [
        row
        for row in rows
        if str(row["source_capture_status"] or "").lower().startswith("wunderground_history")
    ]
    history_partial_rows = [
        row
        for row in history_capture_rows
        if str(row["source_capture_status"] or "").lower().startswith("wunderground_history_partial")
    ]
    history_complete_rows = [
        row
        for row in history_capture_rows
        if row["source_observed_value"] is not None
        and not str(row["source_capture_status"] or "").lower().startswith("wunderground_history_partial")
        and "error" not in str(row["source_capture_status"] or "").lower()
    ]
    history_unique_source_urls = {
        str(row["settlement_source_url"])
        for row in history_capture_rows
        if has_value(row["settlement_source_url"])
    }
    history_partial_unique_source_urls = {
        str(row["settlement_source_url"])
        for row in history_partial_rows
        if has_value(row["settlement_source_url"])
    }
    history_partial_unique_stations = {
        str(row["settlement_station"])
        for row in history_partial_rows
        if has_value(row["settlement_station"])
    }
    hko_rows = [
        row
        for row in rows
        if str(row["settlement_source"] or "").lower() == "hko"
    ]
    hko_missing_target_date_rows = [
        row
        for row in hko_rows
        if str(row["source_capture_status"] or "").lower()
        == "hko_daily_extract_missing_target_date"
    ]
    hko_error_rows = [
        row
        for row in hko_rows
        if "error" in str(row["source_capture_status"] or "").lower()
    ]
    open_rows = [row for row in rows if not bool(row["closed"])]
    closed_rows = [row for row in rows if bool(row["closed"])]

    def has_line_book(row: sqlite3.Row) -> bool:
        return row["best_bid"] is not None or row["best_ask"] is not None

    source_snapshot = next((row["source_snapshot"] for row in rows if has_value(row["source_snapshot"])), None)
    return {
        "latest_captured_at": str(latest_captured_at),
        "source_state_rows": len(rows),
        "unique_events": len(unique_events),
        "unique_conditions": len(unique_conditions),
        "unique_stations": len(unique_stations),
        "target_date_rows": sum(1 for row in rows if has_value(row["target_date"])),
        "unique_target_dates": len(unique_target_dates),
        "wunderground_rows": sum(
            1 for row in rows if str(row["settlement_source"] or "").lower() == "wunderground"
        ),
        "hko_rows": len(hko_rows),
        "hko_observed_value_rows": sum(1 for row in hko_rows if row["source_observed_value"] is not None),
        "hko_missing_target_date_rows": len(hko_missing_target_date_rows),
        "hko_error_rows": len(hko_error_rows),
        "direct_source_url_rows": sum(1 for row in rows if has_value(row["settlement_source_url"])),
        "unique_source_urls": len(unique_source_urls),
        "line_book_rows": sum(1 for row in rows if has_line_book(row)),
        "open_rows": len(open_rows),
        "open_line_book_rows": sum(1 for row in open_rows if has_line_book(row)),
        "open_top_ask_size_rows": sum(1 for row in open_rows if row["top_ask_size"] is not None),
        "closed_line_book_rows": sum(1 for row in closed_rows if has_line_book(row)),
        "category_warning_rows": source_state_category_counts["warning"],
        "category_partial_rows": source_state_category_counts["partial"],
        "category_hko_rows": source_state_category_counts["hko"],
        "category_observed_rows": source_state_category_counts["observed"],
        "category_source_only_rows": source_state_category_counts["source_only"],
        "open_category_warning_rows": open_source_state_category_counts["warning"],
        "open_category_partial_rows": open_source_state_category_counts["partial"],
        "open_category_hko_rows": open_source_state_category_counts["hko"],
        "open_category_observed_rows": open_source_state_category_counts["observed"],
        "open_category_source_only_rows": open_source_state_category_counts["source_only"],
        "closed_category_warning_rows": closed_source_state_category_counts["warning"],
        "closed_category_partial_rows": closed_source_state_category_counts["partial"],
        "closed_category_hko_rows": closed_source_state_category_counts["hko"],
        "closed_category_observed_rows": closed_source_state_category_counts["observed"],
        "closed_category_source_only_rows": closed_source_state_category_counts["source_only"],
        "market_probability_rows": market_probability_rows,
        "yes_market_probability_rows": yes_market_probability_rows,
        "no_market_probability_rows": no_market_probability_rows,
        "complete_binary_condition_pairs": complete_binary_condition_pairs,
        "incomplete_binary_condition_pairs": incomplete_binary_condition_pairs,
        "yes_market_probability_mass_event_count": len(yes_mass_values),
        "yes_market_probability_mass_min": min(yes_mass_values) if yes_mass_values else None,
        "yes_market_probability_mass_max": max(yes_mass_values) if yes_mass_values else None,
        "yes_market_probability_mass_sanity_passed_count": yes_mass_sanity_passed,
        "yes_market_probability_mass_blocked_count": len(yes_mass_values) - yes_mass_sanity_passed,
        "top_ask_size_rows": sum(1 for row in rows if row["top_ask_size"] is not None),
        "closed_rows": len(closed_rows),
        "source_capture_attempted_rows": sum(1 for row in rows if has_value(row["source_capture_status"])),
        "source_capture_unique_urls": len(source_capture_unique_urls),
        "source_capture_missing_rows": sum(
            1
            for row in rows
            if has_value(row["settlement_source_url"]) and not has_value(row["source_capture_status"])
        ),
        "source_capture_missing_unique_urls": len(source_capture_missing_urls),
        "source_capture_no_data_rows": sum(1 for row in rows if str(row["source_capture_status"] or "").lower() in {"history_no_data_recorded", "no_data", "not_available"}),
        "source_capture_observed_value_rows": sum(1 for row in rows if row["source_observed_value"] is not None),
        "source_capture_error_rows": sum(1 for row in rows if "error" in str(row["source_capture_status"] or "").lower()),
        "history_capture_rows": len(history_capture_rows),
        "history_observed_value_rows": sum(1 for row in history_capture_rows if row["source_observed_value"] is not None),
        "history_partial_rows": len(history_partial_rows),
        "history_complete_rows": len(history_complete_rows),
        "history_unique_source_urls": len(history_unique_source_urls),
        "history_partial_unique_source_urls": len(history_partial_unique_source_urls),
        "history_partial_unique_stations": len(history_partial_unique_stations),
        "station_anomaly_checked_rows": station_anomaly_checked_rows,
        "station_anomaly_neighbor_evidence_rows": len(station_anomaly_neighbor_count_values),
        "station_anomaly_neighbor_evidence_max_count": max(station_anomaly_neighbor_count_values) if station_anomaly_neighbor_count_values else 0,
        "station_anomaly_not_checked_rows": station_anomaly_not_checked_rows,
        "station_anomaly_missing_observation_rows": station_anomaly_missing_observation_rows,
        "station_anomaly_missing_neighbors_rows": station_anomaly_missing_neighbors_rows,
        "station_anomaly_warning_rows": station_anomaly_warning_rows,
        "station_anomaly_warning_unique_events": len(station_anomaly_warning_unique_events),
        "station_anomaly_warning_unique_stations": len(station_anomaly_warning_unique_stations),
        "station_anomaly_warning_unique_source_urls": len(station_anomaly_warning_unique_source_urls),
        "station_anomaly_warning_max_delta": max(station_anomaly_warning_max_delta_values) if station_anomaly_warning_max_delta_values else None,
        "station_anomaly_passed_rows": station_anomaly_passed_rows,
        "station_anomaly_max_delta": max(station_anomaly_max_delta_values) if station_anomaly_max_delta_values else None,
        "paper_actionable": False,
        "market_scope": "weather",
        "source_snapshot": source_snapshot,
        "source_state_label": "Polymarket weather source-state only / non-actionable",
    }


def summarize_nws_cli_source_diagnostics(
    reports_by_station: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Summarize final-CLI source pagination coverage by station.

    The public NWS product list can put same-day preliminary ``VALID TODAY``
    products ahead of prior-day final climate reports. Weather cron summaries
    should therefore surface how many products were fetched, how many were
    rejected as preliminary/non-final, and which target dates actually found a
    validated final report. This is source-capture QA only; it does not make a
    market paper-actionable.
    """
    diagnostics: dict[str, dict[str, Any]] = {}
    for station, report_bundle in reports_by_station.items():
        parsed_reports = list(_get(report_bundle, "parsed_reports", []) or [])
        final_by_date = _get(report_bundle, "final_by_date", {}) or {}
        target_dates = list(_get(report_bundle, "target_dates", []) or final_by_date.keys())
        final_found_by_date = {
            str(target_date): bool(_get(final_by_date, target_date))
            for target_date in target_dates
        }
        missing_final_target_dates = [
            str(target_date)
            for target_date in target_dates
            if not final_found_by_date.get(str(target_date), False)
        ]
        rejected_preliminary = sum(
            1
            for report in parsed_reports
            if str(_get(report, "preliminary_reason", "") or "").lower().startswith("preliminary")
        )
        rejected_non_final = sum(1 for report in parsed_reports if not bool(_get(report, "is_final", False)))
        diagnostics[str(station)] = {
            "products_fetched": len(parsed_reports),
            "product_scan_limit": _get(report_bundle, "product_scan_limit"),
            "target_dates": [str(target_date) for target_date in target_dates],
            "final_found_by_date": final_found_by_date,
            "all_targets_final_found": not missing_final_target_dates,
            "missing_final_target_dates": missing_final_target_dates,
            "rejected_preliminary_count": rejected_preliminary,
            "rejected_non_final_count": rejected_non_final,
            "latest_final_product_id_by_date": {
                str(target_date): _get(_get(final_by_date, target_date), "product_id")
                if _get(final_by_date, target_date)
                else None
                for target_date in target_dates
            },
        }
    return diagnostics


def should_persist_weather_signal_for_calibration(signal: Any) -> bool:
    """Return whether a weather signal is useful calibration evidence.

    No-trade gates can correctly zero out ``edge`` and sizing, but the blocked
    row may still carry a bot-generated model probability, current market
    probability, source metadata, and structured blockers. Persisting such rows
    as non-executed signals supports future calibration without creating paper
    trades or weakening safeguards.
    """
    return _get(signal, "model_probability") is not None and _get(signal, "market_probability") is not None


_WEATHER_REVIEW_ONLY_BLOCKER = "review-only candidate; not paper-actionable until independently revalidated"


def build_weather_signal_review_candidate_rows(
    signals: Iterable[Any],
    *,
    captured_at: str,
    min_abs_edge: float = 0.0,
    source_snapshot: str | None = None,
) -> list[dict[str, Any]]:
    """Build review-only rows for threshold-passing weather candidates.

    These rows are a safety/audit export, not paper-trade instructions. They
    preserve source/rule/depth/model diagnostics while forcing execution fields
    to non-actionable values so threshold-passing scans can be reviewed without
    mutating ledgers or bypassing no-trade gates.
    """
    rows: list[dict[str, Any]] = []
    for signal in signals:
        edge = float(_get(signal, "edge", 0.0) or 0.0)
        if abs(edge) < float(min_abs_edge):
            continue
        market = _get(signal, "market")
        if not market:
            continue
        reasons = list(_get(signal, "no_trade_reasons", []) or [])
        if _WEATHER_REVIEW_ONLY_BLOCKER not in reasons:
            reasons.append(_WEATHER_REVIEW_ONLY_BLOCKER)
        rows.append(
            {
                "captured_at": captured_at,
                "venue": _get(market, "platform"),
                "market_key": _get(market, "market_id"),
                "title": _get(market, "title"),
                "city": _get(market, "city_key") or _get(market, "city_name"),
                "target_date": str(_get(market, "target_date")) if _get(market, "target_date") is not None else None,
                "metric": _get(market, "metric"),
                "direction": _get(signal, "direction"),
                "threshold_f": _get(market, "threshold_f"),
                "model_probability": _get(signal, "model_probability"),
                "market_probability": _get(signal, "market_probability"),
                "edge": edge,
                "confidence": _get(signal, "confidence"),
                "suggested_size": 0.0,
                "best_bid": _get(market, "best_bid"),
                "best_ask": _get(market, "best_ask"),
                "execution_spread": _get(signal, "execution_spread"),
                "top_ask_size": _get(signal, "top_ask_size") if _get(signal, "top_ask_size") is not None else _get(market, "top_ask_size"),
                "settlement_source": _get(market, "settlement_source"),
                "settlement_station": _get(market, "settlement_station"),
                "settlement_source_url": _get(market, "settlement_source_url"),
                "no_trade_reasons": reasons,
                "source_snapshot": source_snapshot,
                "paper_actionable": False,
                "executed": False,
                "notes": _get(signal, "reasoning"),
            }
        )
    return rows


def persist_weather_signal_review_candidate_rows_to_sqlite(
    conn: sqlite3.Connection,
    rows: Iterable[Mapping[str, Any]],
) -> int:
    """Append review-only weather candidates to SQLite without ledger effects."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS weather_signal_review_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            venue TEXT,
            market_key TEXT NOT NULL,
            title TEXT,
            city TEXT,
            target_date TEXT,
            metric TEXT,
            direction TEXT,
            threshold_f REAL,
            model_probability REAL,
            market_probability REAL,
            edge REAL,
            confidence REAL,
            suggested_size REAL NOT NULL DEFAULT 0,
            best_bid REAL,
            best_ask REAL,
            execution_spread REAL,
            top_ask_size REAL,
            settlement_source TEXT,
            settlement_station TEXT,
            settlement_source_url TEXT,
            no_trade_reasons TEXT,
            source_snapshot TEXT,
            paper_actionable INTEGER NOT NULL DEFAULT 0,
            executed INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            UNIQUE(captured_at, market_key, direction)
        )
        """
    )
    inserted = 0
    for row in rows:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO weather_signal_review_candidates (
                captured_at, venue, market_key, title, city, target_date, metric,
                direction, threshold_f, model_probability, market_probability,
                edge, confidence, suggested_size, best_bid, best_ask,
                execution_spread, top_ask_size, settlement_source,
                settlement_station, settlement_source_url, no_trade_reasons,
                source_snapshot, paper_actionable, executed, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("captured_at"),
                row.get("venue"),
                row.get("market_key"),
                row.get("title"),
                row.get("city"),
                row.get("target_date"),
                row.get("metric"),
                row.get("direction"),
                row.get("threshold_f"),
                row.get("model_probability"),
                row.get("market_probability"),
                row.get("edge"),
                row.get("confidence"),
                0.0,
                row.get("best_bid"),
                row.get("best_ask"),
                row.get("execution_spread"),
                row.get("top_ask_size"),
                row.get("settlement_source"),
                row.get("settlement_station"),
                row.get("settlement_source_url"),
                json.dumps(list(row.get("no_trade_reasons") or []), sort_keys=True),
                row.get("source_snapshot"),
                0,
                0,
                row.get("notes"),
            ),
        )
        if conn.total_changes > before:
            inserted += 1
    conn.commit()
    return inserted


def _normalize_weather_signal_review_candidate_row(row: Mapping[str, Any]) -> dict[str, Any]:
    reasons_raw = row.get("no_trade_reasons")
    if isinstance(reasons_raw, str):
        try:
            reasons = json.loads(reasons_raw)
        except json.JSONDecodeError:
            reasons = [reasons_raw] if reasons_raw else []
    else:
        reasons = list(reasons_raw or [])
    if _WEATHER_REVIEW_ONLY_BLOCKER not in reasons:
        reasons.append(_WEATHER_REVIEW_ONLY_BLOCKER)

    normalized = dict(row)
    normalized["no_trade_reasons"] = reasons
    normalized["suggested_size"] = 0.0
    normalized["paper_actionable"] = False
    normalized["executed"] = False
    normalized["review_kind"] = "weather_threshold_review_candidate"
    return normalized


def load_latest_weather_signal_review_candidate_rows_from_sqlite(
    db_path: str | PathLike[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return newest weather threshold review candidates from SQLite.

    This is a read-only audit/dashboard loader. It opens the canonical research
    DB with ``mode=ro`` so missing paths are absent telemetry, not silently
    created empty databases, and it force-normalizes every row as non-actionable
    / non-executed / zero suggested size at the presentation boundary.
    """
    try:
        conn = sqlite3.connect(f"file:{fspath(db_path)}?mode=ro", uri=True)
    except sqlite3.Error:
        return []

    conn.row_factory = sqlite3.Row
    try:
        latest = conn.execute(
            "SELECT MAX(captured_at) AS latest_captured_at FROM weather_signal_review_candidates"
        ).fetchone()
        latest_captured_at = latest["latest_captured_at"] if latest else None
        if not latest_captured_at:
            return []
        query = """
            SELECT captured_at, venue, market_key, title, city, target_date,
                   metric, direction, threshold_f, model_probability,
                   market_probability, edge, confidence, suggested_size,
                   best_bid, best_ask, execution_spread, top_ask_size,
                   settlement_source, settlement_station, settlement_source_url,
                   no_trade_reasons, source_snapshot, paper_actionable, executed,
                   notes
            FROM weather_signal_review_candidates
            WHERE captured_at = ?
            ORDER BY ABS(edge) DESC, market_key ASC, direction ASC
        """
        params: tuple[Any, ...]
        if limit is not None:
            query += " LIMIT ?"
            params = (latest_captured_at, max(int(limit), 0))
        else:
            params = (latest_captured_at,)
        rows = conn.execute(query, params).fetchall()
    except (sqlite3.Error, ValueError):
        return []
    finally:
        conn.close()

    return [_normalize_weather_signal_review_candidate_row(dict(row)) for row in rows]


def _summarize_weather_platform_breakdown(trades: Iterable[Any]) -> list[dict[str, float | int | str]]:
    """Return per-venue paper-ledger diagnostics without changing account equity.

    The weather paper account is a single $1,000 -> $1,100 ledger, not separate
    bankrolls per venue.  This breakdown is therefore audit metadata only: it
    shows which venue contributed settled PnL / pending exposure while the
    top-level account summary remains the source of truth for equity.
    """
    grouped: dict[str, list[Any]] = {}
    for trade in trades:
        platform = str(_get(trade, "platform", "unknown") or "unknown").strip().lower() or "unknown"
        grouped.setdefault(platform, []).append(trade)

    breakdown: list[dict[str, float | int | str]] = []
    for platform in sorted(grouped):
        platform_trades = grouped[platform]
        settled = [t for t in platform_trades if bool(_get(t, "settled", False))]
        pending = [t for t in platform_trades if not bool(_get(t, "settled", False))]
        breakdown.append(
            {
                "platform": platform,
                "total_trades": len(platform_trades),
                "settled_trades": len(settled),
                "pending_trades": len(pending),
                "pending_size": round(sum(float(_get(t, "size", 0.0) or 0.0) for t in pending), 2),
                "winning_trades": sum(1 for t in settled if _get(t, "result") == "win"),
                "realized_pnl": round(sum(float(_get(t, "pnl", 0.0) or 0.0) for t in settled), 2),
            }
        )
    return breakdown


def summarize_weather_paper_account(
    trades: Iterable[Any],
    initial_bankroll: float = WEATHER_PAPER_INITIAL_BANKROLL,
    target_bankroll: float = WEATHER_PAPER_TARGET_BANKROLL,
    settled_forecasts: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Summarize the separate $1,000 -> $1,100 weather paper account.

    Only settled simulation PnL changes current equity. Pending trades are
    counted for calibration/risk visibility but never move realized PnL. This
    preserves selective/no-forced-trade behavior when weather gates reject all
    candidates. Forecast calibration fields are reported separately and may be
    populated even while trade counts remain zero.
    """
    trade_list = list(trades)
    settled = [t for t in trade_list if bool(_get(t, "settled", False))]
    pending = [t for t in trade_list if not bool(_get(t, "settled", False))]

    realized_pnl = sum(float(_get(t, "pnl", 0.0) or 0.0) for t in settled)
    pending_size = sum(float(_get(t, "size", 0.0) or 0.0) for t in pending)
    current_equity = float(initial_bankroll) + realized_pnl
    winning_trades = sum(1 for t in settled if _get(t, "result") == "win")
    settled_count = len(settled)
    pending_count = len(pending)

    if not trade_list:
        ledger_exposure_state = "no_trades"
        ledger_status_note = "No weather paper trades; selective/no-forced-trade mode is preserved."
    elif pending_count:
        ledger_exposure_state = "open_positions"
        ledger_status_note = (
            f"{pending_count} open/pending weather paper trade"
            f"{'s' if pending_count != 1 else ''}; ${pending_size:.2f} pending size. "
            "Current equity is settled realized PnL only."
        )
    else:
        ledger_exposure_state = "all_settled"
        ledger_status_note = (
            f"All {settled_count} weather paper trade{'s' if settled_count != 1 else ''} are settled; "
            "current equity is settled realized PnL only."
        )

    target_span = max(float(target_bankroll) - float(initial_bankroll), 0.0)
    if target_span > 0:
        raw_progress = ((current_equity - float(initial_bankroll)) / target_span) * 100.0
        progress_to_target_pct = min(100.0, max(0.0, raw_progress))
    else:
        progress_to_target_pct = 100.0

    calibration = summarize_weather_forecast_calibration(settled_forecasts or [])

    return {
        "initial_bankroll": round(float(initial_bankroll), 2),
        "target_bankroll": round(float(target_bankroll), 2),
        "current_equity": round(current_equity, 2),
        "realized_pnl": round(realized_pnl, 2),
        "remaining_to_target": round(max(float(target_bankroll) - current_equity, 0.0), 2),
        "progress_to_target_pct": round(progress_to_target_pct, 2),
        "total_trades": len(trade_list),
        "settled_trades": settled_count,
        "pending_trades": pending_count,
        "pending_size": round(pending_size, 2),
        "platform_breakdown": _summarize_weather_platform_breakdown(trade_list),
        "winning_trades": winning_trades,
        "win_rate": round((winning_trades / settled_count * 100.0), 2) if settled_count else 0.0,
        "ledger_exposure_state": ledger_exposure_state,
        "ledger_status_note": ledger_status_note,
        **calibration,
        "paper_only": True,
        "selective_no_forced_trade": True,
        "market_scope": "weather",
    }
