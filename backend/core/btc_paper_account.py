"""BTC-specific paper account summary helpers.

The BTC sprint treats the BTC bot as a separate hypothetical paper ledger:
$1,000 starting bankroll with a $1,100 target.  This module is intentionally
side-effect free so API/dashboard code can report progress without mutating the
main bot state or implying live execution.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from os import PathLike, fspath
from typing import Iterable, Mapping, Any

BTC_PAPER_INITIAL_BANKROLL = 1000.0
BTC_PAPER_TARGET_BANKROLL = 1100.0


def _get_value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def summarize_btc_paper_account(
    trades: Iterable[Any],
    initial_bankroll: float = BTC_PAPER_INITIAL_BANKROLL,
    target_bankroll: float = BTC_PAPER_TARGET_BANKROLL,
) -> dict[str, float | int | bool | None]:
    """Summarize a simulation-only BTC account.

    Only settled trade PnL changes current equity. Pending trades are counted
    for risk visibility but do not move realized PnL until settlement.
    """
    trade_list = list(trades)
    settled = [t for t in trade_list if bool(_get_value(t, "settled", False))]
    pending = [t for t in trade_list if not bool(_get_value(t, "settled", False))]

    realized_pnl = sum(float(_get_value(t, "pnl", 0.0) or 0.0) for t in settled)
    current_equity = initial_bankroll + realized_pnl
    winning_trades = sum(1 for t in settled if _get_value(t, "result") == "win")
    settled_count = len(settled)
    target_span = max(target_bankroll - initial_bankroll, 0.0)

    forecast_scores: list[tuple[float, float]] = []
    for trade in settled:
        probability = _get_value(trade, "model_probability")
        outcome = _get_value(trade, "settlement_value")
        if probability is None or outcome is None:
            continue
        try:
            p = min(1.0, max(0.0, float(probability)))
            actual = 1.0 if float(outcome) >= 0.5 else 0.0
        except (TypeError, ValueError):
            continue
        brier = (p - actual) ** 2
        clipped_p = min(1.0 - 1e-15, max(1e-15, p))
        log_loss = -(actual * math.log(clipped_p) + (1.0 - actual) * math.log(1.0 - clipped_p))
        forecast_scores.append((brier, log_loss))

    if target_span > 0:
        raw_progress = ((current_equity - initial_bankroll) / target_span) * 100.0
        progress_to_target_pct = min(100.0, max(0.0, raw_progress))
    else:
        progress_to_target_pct = 100.0

    return {
        "initial_bankroll": round(initial_bankroll, 2),
        "target_bankroll": round(target_bankroll, 2),
        "current_equity": round(current_equity, 2),
        "realized_pnl": round(realized_pnl, 2),
        "remaining_to_target": round(max(target_bankroll - current_equity, 0.0), 2),
        "progress_to_target_pct": round(progress_to_target_pct, 2),
        "total_trades": len(trade_list),
        "settled_trades": settled_count,
        "pending_trades": len(pending),
        "winning_trades": winning_trades,
        "win_rate": round((winning_trades / settled_count * 100.0), 2) if settled_count else 0.0,
        "settled_forecasts": len(forecast_scores),
        "brier_score": round(sum(score[0] for score in forecast_scores) / len(forecast_scores), 4) if forecast_scores else None,
        "log_loss": round(sum(score[1] for score in forecast_scores) / len(forecast_scores), 4) if forecast_scores else None,
        "paper_only": True,
        "selective_no_forced_trade": True,
    }


def _as_float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_present(value: Any) -> bool:
    return value is not None and value != ""


def _has_exact_chainlink_boundary(row: Any) -> bool:
    has_start = all(
        _is_present(_get_value(row, field))
        for field in (
            "chainlink_start_price",
            "chainlink_start_observed_at",
            "chainlink_start_source_snapshot_path",
        )
    )
    has_end = all(
        _is_present(_get_value(row, field))
        for field in (
            "chainlink_end_price",
            "chainlink_end_observed_at",
            "chainlink_end_source_snapshot_path",
        )
    )
    return has_start and has_end


def _derive_btc_boundary_outcome(row: Any) -> tuple[int | None, str | None]:
    """Derive row-level Yes/No outcome from exact Chainlink start/end prices.

    This is read-only calibration derivation. It does not mutate the DB and does
    not make any row paper-actionable; it only lets dashboard/API loaders score
    already-captured exact boundary rows if the persistence layer has not yet
    filled ``resolved_yes`` / ``final_outcome``.
    """
    if not _has_exact_chainlink_boundary(row):
        return None, None
    start_price = _as_float_or_none(_get_value(row, "chainlink_start_price"))
    end_price = _as_float_or_none(_get_value(row, "chainlink_end_price"))
    if start_price is None or end_price is None:
        return None, None
    final_outcome = "Up" if end_price > start_price else "Down"
    direction = str(_get_value(row, "direction", "") or "").lower()
    if direction == "up":
        resolved_yes = 1 if final_outcome == "Up" else 0
    elif direction == "down":
        resolved_yes = 1 if final_outcome == "Down" else 0
    else:
        return None, final_outcome
    return resolved_yes, final_outcome


def _score_btc_probability(probability: Any, resolved_yes: Any) -> tuple[float | None, float | None]:
    p = _as_float_or_none(probability)
    if p is None or resolved_yes is None:
        return None, None
    try:
        actual = 1.0 if float(resolved_yes) >= 0.5 else 0.0
    except (TypeError, ValueError):
        return None, None
    p = min(1.0, max(0.0, p))
    brier = (p - actual) ** 2
    clipped_p = min(1.0 - 1e-15, max(1e-15, p))
    log_loss = -(actual * math.log(clipped_p) + (1.0 - actual) * math.log(1.0 - clipped_p))
    return brier, log_loss


def _parse_btc_scored_at(ts: Any) -> int | None:
    try:
        text = str(ts or "")
        if not text:
            return None
        if text.endswith("Z") and "T" in text and "-" not in text:
            parsed = datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except (TypeError, ValueError):
        return None


def _parse_btc_window_start_ts(row: Any) -> int | None:
    for field in ("window_start_ts", "chainlink_start_report_boundary_ts"):
        value = _get_value(row, field)
        try:
            if value is not None and value != "":
                return int(value)
        except (TypeError, ValueError):
            pass
    slug = str(_get_value(row, "event_slug", "") or "")
    if slug.startswith("btc-updown-5m-"):
        try:
            return int(slug.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            return None
    return None


def _btc_window_state_counts(rows: Iterable[Any], scored_at: Any) -> dict[str, int | None]:
    scored_at_ts = _parse_btc_scored_at(scored_at)
    starts = sorted({start for row in rows if (start := _parse_btc_window_start_ts(row)) is not None})
    if scored_at_ts is None or not starts:
        return {
            "unique_window_count": len(starts),
            "active_window_count": 0,
            "upcoming_window_count": 0,
            "expired_window_count": 0,
            "min_seconds_to_window_end": None,
            "max_seconds_to_window_end": None,
        }
    seconds_to_end = [start + 300 - scored_at_ts for start in starts]
    return {
        "unique_window_count": len(starts),
        "active_window_count": sum(1 for start in starts if start <= scored_at_ts < start + 300),
        "upcoming_window_count": sum(1 for start in starts if scored_at_ts < start),
        "expired_window_count": sum(1 for start in starts if scored_at_ts >= start + 300),
        "min_seconds_to_window_end": min(seconds_to_end),
        "max_seconds_to_window_end": max(seconds_to_end),
    }


def summarize_latest_btc_calibration_rows(rows: Iterable[Any]) -> dict[str, float | int | str | bool | None]:
    """Summarize the newest BTC quote→Chainlink-boundary→outcome scoring batch.

    This is calibration/audit observability only. Rows in
    ``btc_outcome_scoring_v1`` are append-only scoring scaffolds and must remain
    separate from BTC paper trades. Brier/log-loss are reported only for rows
    with an actual resolved outcome and persisted score; pending boundary or
    outcome rows are counted but never converted into paper actionability.
    """
    row_list = list(rows)
    if not row_list:
        return {
            "latest_scored_at": None,
            "scoring_rows": 0,
            "pending_scoring_rows": 0,
            "settled_forecasts": 0,
            "brier_score": None,
            "log_loss": None,
            "exact_boundary_rows": 0,
            "partial_boundary_rows": 0,
            "line_book_rows": 0,
            "top_ask_size_rows": 0,
            "model_probability_rows": 0,
            "exchange_spot_model_rows": 0,
            "source_mismatch_rows": 0,
            "chainlink_auth_blocked_rows": 0,
            "unique_window_count": 0,
            "active_window_count": 0,
            "upcoming_window_count": 0,
            "expired_window_count": 0,
            "min_seconds_to_window_end": None,
            "max_seconds_to_window_end": None,
            "max_execution_spread": None,
            "min_signal_top_ask_size": None,
            "paper_actionable": False,
            "market_scope": "btc",
            "calibration_kind": "chainlink_boundary_outcome_score",
            "source_snapshot": None,
            "report_request_rows": 0,
            "auth_required_report_requests": 0,
        }

    latest_ts = max(str(_get_value(row, "ts", "")) for row in row_list)
    latest_rows = [row for row in row_list if str(_get_value(row, "ts", "")) == latest_ts]

    scored_rows = []
    pending_rows = 0
    exact_boundary_rows = 0
    partial_boundary_rows = 0
    source_snapshot = None
    line_book_rows = 0
    top_ask_sizes: list[float] = []
    execution_spreads: list[float] = []
    model_probability_rows = 0
    exchange_spot_model_rows = 0
    source_mismatch_rows = 0
    chainlink_auth_blocked_rows = 0

    for row in latest_rows:
        resolved = _get_value(row, "resolved_yes")
        final_outcome = _get_value(row, "final_outcome")
        if resolved is None or final_outcome is None:
            derived_resolved, derived_outcome = _derive_btc_boundary_outcome(row)
            resolved = resolved if resolved is not None else derived_resolved
            final_outcome = final_outcome if final_outcome is not None else derived_outcome

        brier = _as_float_or_none(_get_value(row, "brier_score"))
        log_loss = _as_float_or_none(_get_value(row, "log_loss"))
        if (brier is None or log_loss is None) and resolved is not None:
            brier, log_loss = _score_btc_probability(_get_value(row, "model_probability"), resolved)
        if brier is not None and log_loss is not None and resolved is not None:
            scored_rows.append((brier, log_loss))
        else:
            pending_rows += 1

        has_start = all(
            _is_present(_get_value(row, field))
            for field in (
                "chainlink_start_price",
                "chainlink_start_observed_at",
                "chainlink_start_source_snapshot_path",
            )
        )
        has_end = all(
            _is_present(_get_value(row, field))
            for field in (
                "chainlink_end_price",
                "chainlink_end_observed_at",
                "chainlink_end_source_snapshot_path",
            )
        )
        if has_start and has_end:
            exact_boundary_rows += 1
        elif has_start or has_end:
            partial_boundary_rows += 1

        if source_snapshot is None:
            source_snapshot = _get_value(row, "chainlink_start_source_snapshot_path") or _get_value(
                row, "chainlink_end_source_snapshot_path"
            )

        execution_spread = _execution_spread_from_bid_ask(
            _get_value(row, "signal_yes_bid"),
            _get_value(row, "signal_yes_ask"),
        )
        if execution_spread is not None:
            line_book_rows += 1
            execution_spreads.append(execution_spread)
        top_ask_size = _as_float_or_none(_get_value(row, "signal_top_ask_size"))
        if top_ask_size is not None:
            top_ask_sizes.append(top_ask_size)
        if _get_value(row, "model_probability") is not None:
            model_probability_rows += 1
        model_price_source = str(_get_value(row, "model_price_source", "") or "").lower()
        if "spot" in model_price_source or "coinbase" in model_price_source:
            exchange_spot_model_rows += 1
            source_mismatch_rows += 1
        if _get_value(row, "chainlink_start_report_requires_authentication") or _get_value(
            row, "chainlink_end_report_requires_authentication"
        ):
            chainlink_auth_blocked_rows += 1

    window_counts = _btc_window_state_counts(latest_rows, latest_ts)

    return {
        "latest_scored_at": latest_ts,
        "scoring_rows": len(latest_rows),
        "pending_scoring_rows": pending_rows,
        "settled_forecasts": len(scored_rows),
        "brier_score": round(sum(score[0] for score in scored_rows) / len(scored_rows), 4) if scored_rows else None,
        "log_loss": round(sum(score[1] for score in scored_rows) / len(scored_rows), 4) if scored_rows else None,
        "exact_boundary_rows": exact_boundary_rows,
        "partial_boundary_rows": partial_boundary_rows,
        "line_book_rows": line_book_rows,
        "top_ask_size_rows": len(top_ask_sizes),
        "model_probability_rows": model_probability_rows,
        "exchange_spot_model_rows": exchange_spot_model_rows,
        "source_mismatch_rows": source_mismatch_rows,
        "chainlink_auth_blocked_rows": chainlink_auth_blocked_rows,
        "unique_window_count": window_counts["unique_window_count"],
        "active_window_count": window_counts["active_window_count"],
        "upcoming_window_count": window_counts["upcoming_window_count"],
        "expired_window_count": window_counts["expired_window_count"],
        "min_seconds_to_window_end": window_counts["min_seconds_to_window_end"],
        "max_seconds_to_window_end": window_counts["max_seconds_to_window_end"],
        "max_execution_spread": round(max(execution_spreads), 6) if execution_spreads else None,
        "min_signal_top_ask_size": round(min(top_ask_sizes), 4) if top_ask_sizes else None,
        "paper_actionable": False,
        "market_scope": "btc",
        "calibration_kind": "chainlink_boundary_outcome_score",
        "source_snapshot": source_snapshot,
        "report_request_rows": int(_get_value(latest_rows[0], "report_request_rows", 0) or 0),
        "auth_required_report_requests": int(_get_value(latest_rows[0], "auth_required_report_requests", 0) or 0),
    }


def _execution_spread_from_bid_ask(bid: Any, ask: Any) -> float | None:
    bid_value = _as_float_or_none(bid)
    ask_value = _as_float_or_none(ask)
    if bid_value is None or ask_value is None:
        return None
    return round(ask_value - bid_value, 6)


def _btc_calibration_row_detail(row: Mapping[str, Any]) -> dict[str, Any]:
    execution_spread = _execution_spread_from_bid_ask(
        _get_value(row, "signal_yes_bid"),
        _get_value(row, "signal_yes_ask"),
    )
    has_start = all(
        _is_present(_get_value(row, field))
        for field in (
            "chainlink_start_price",
            "chainlink_start_observed_at",
            "chainlink_start_source_snapshot_path",
        )
    )
    has_end = all(
        _is_present(_get_value(row, field))
        for field in (
            "chainlink_end_price",
            "chainlink_end_observed_at",
            "chainlink_end_source_snapshot_path",
        )
    )
    exact_boundary_available = has_start and has_end
    resolved_yes = _get_value(row, "resolved_yes")
    final_outcome = _get_value(row, "final_outcome")
    if resolved_yes is None or final_outcome is None:
        derived_resolved_yes, derived_final_outcome = _derive_btc_boundary_outcome(row)
        resolved_yes = resolved_yes if resolved_yes is not None else derived_resolved_yes
        final_outcome = final_outcome if final_outcome is not None else derived_final_outcome
    brier_score = _as_float_or_none(_get_value(row, "brier_score"))
    log_loss = _as_float_or_none(_get_value(row, "log_loss"))
    if (brier_score is None or log_loss is None) and resolved_yes is not None:
        brier_score, log_loss = _score_btc_probability(_get_value(row, "model_probability"), resolved_yes)
    no_trade_reasons: list[str] = []
    if not exact_boundary_available:
        no_trade_reasons.append("missing exact Chainlink boundary values")
    if _get_value(row, "model_probability") is None:
        no_trade_reasons.append("missing independent BTC model probability")
    if resolved_yes is None:
        no_trade_reasons.append("pending resolved Up/Down outcome")
    if _get_value(row, "model_price_source") and str(_get_value(row, "model_price_source")).startswith("coinbase"):
        no_trade_reasons.append("model source is exchange spot context, not Chainlink settlement source")
    if _get_value(row, "chainlink_start_report_requires_authentication") or _get_value(
        row, "chainlink_end_report_requires_authentication"
    ):
        no_trade_reasons.append("Chainlink report requests require authentication")

    return {
        "ts": _get_value(row, "ts"),
        "quote_ts": _get_value(row, "quote_ts"),
        "event_slug": _get_value(row, "event_slug"),
        "market_key": _get_value(row, "market_key"),
        "direction": _get_value(row, "direction"),
        "model_probability": _as_float_or_none(_get_value(row, "model_probability")),
        "model_price_source": _get_value(row, "model_price_source"),
        "signal_yes_bid": _as_float_or_none(_get_value(row, "signal_yes_bid")),
        "signal_yes_ask": _as_float_or_none(_get_value(row, "signal_yes_ask")),
        "execution_spread": execution_spread,
        "signal_top_ask_size": _as_float_or_none(_get_value(row, "signal_top_ask_size")),
        "signal_probability": _as_float_or_none(_get_value(row, "signal_probability")),
        "chainlink_feed_id": _get_value(row, "chainlink_feed_id"),
        "chainlink_capture_method": _get_value(row, "chainlink_capture_method"),
        "chainlink_source_url": _get_value(row, "chainlink_source_url"),
        "chainlink_start_price": _as_float_or_none(_get_value(row, "chainlink_start_price")),
        "chainlink_end_price": _as_float_or_none(_get_value(row, "chainlink_end_price")),
        "chainlink_start_observed_at": _get_value(row, "chainlink_start_observed_at"),
        "chainlink_end_observed_at": _get_value(row, "chainlink_end_observed_at"),
        "chainlink_start_source_snapshot_path": _get_value(row, "chainlink_start_source_snapshot_path"),
        "chainlink_end_source_snapshot_path": _get_value(row, "chainlink_end_source_snapshot_path"),
        "chainlink_start_report_request_url": _get_value(row, "chainlink_start_report_request_url"),
        "chainlink_end_report_request_url": _get_value(row, "chainlink_end_report_request_url"),
        "chainlink_start_report_boundary_ts": _get_value(row, "chainlink_start_report_boundary_ts"),
        "chainlink_end_report_boundary_ts": _get_value(row, "chainlink_end_report_boundary_ts"),
        "chainlink_start_report_status": _get_value(row, "chainlink_start_report_status"),
        "chainlink_end_report_status": _get_value(row, "chainlink_end_report_status"),
        "chainlink_start_report_requires_authentication": bool(
            _get_value(row, "chainlink_start_report_requires_authentication", False)
        ),
        "chainlink_end_report_requires_authentication": bool(
            _get_value(row, "chainlink_end_report_requires_authentication", False)
        ),
        "exact_boundary_available": exact_boundary_available,
        "partial_boundary_available": (has_start or has_end) and not exact_boundary_available,
        "resolved_yes": resolved_yes,
        "final_outcome": final_outcome,
        "brier_score": round(brier_score, 4) if brier_score is not None else None,
        "log_loss": round(log_loss, 4) if log_loss is not None else None,
        "clv": _as_float_or_none(_get_value(row, "clv")),
        "status": _get_value(row, "status"),
        "notes": _get_value(row, "notes"),
        "no_trade_reasons": no_trade_reasons,
        "paper_actionable": False,
    }


def _connect_readonly_sqlite(db_path: str | PathLike[str]) -> sqlite3.Connection:
    """Open an existing SQLite DB read-only without creating missing files."""
    return sqlite3.connect(f"file:{fspath(db_path)}?mode=ro", uri=True)


def _table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(con: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except sqlite3.Error:
        return set()


def load_latest_btc_calibration_rows_from_sqlite(
    db_path: str | PathLike[str],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Read newest BTC scoring detail rows from research SQLite.

    These rows are calibration/review diagnostics only. They intentionally keep
    ``paper_actionable`` false and surface missing Chainlink/model/outcome gates
    instead of implying edge or PnL.
    """
    try:
        con = _connect_readonly_sqlite(db_path)
        con.row_factory = sqlite3.Row
        try:
            latest_row = con.execute("SELECT max(ts) AS latest_ts FROM btc_outcome_scoring_v1").fetchone()
            latest_ts = latest_row["latest_ts"] if latest_row else None
            if not latest_ts:
                return []
            scoring_columns = _table_columns(con, "btc_outcome_scoring_v1")
            signal_top_ask_size_expr = (
                "s.signal_top_ask_size AS signal_top_ask_size"
                if "signal_top_ask_size" in scoring_columns
                else "NULL AS signal_top_ask_size"
            )
            if _table_exists(con, "btc_chainlink_report_request_v1"):
                rows = con.execute(
                    f"""
                    SELECT s.ts, s.quote_ts, s.event_slug, s.market_key, s.direction,
                           s.model_probability, s.model_price_source,
                           s.signal_yes_bid, s.signal_yes_ask, s.signal_probability,
                           {signal_top_ask_size_expr},
                           s.chainlink_feed_id, s.chainlink_capture_method, s.chainlink_source_url,
                           s.chainlink_start_price, s.chainlink_end_price,
                           s.chainlink_start_observed_at, s.chainlink_end_observed_at,
                           s.chainlink_start_source_snapshot_path, s.chainlink_end_source_snapshot_path,
                           start_req.request_url AS chainlink_start_report_request_url,
                           end_req.request_url AS chainlink_end_report_request_url,
                           start_req.boundary_ts AS chainlink_start_report_boundary_ts,
                           end_req.boundary_ts AS chainlink_end_report_boundary_ts,
                           start_req.status AS chainlink_start_report_status,
                           end_req.status AS chainlink_end_report_status,
                           start_req.requires_authentication AS chainlink_start_report_requires_authentication,
                           end_req.requires_authentication AS chainlink_end_report_requires_authentication,
                           s.resolved_yes, s.final_outcome, s.brier_score, s.log_loss, s.clv,
                           s.status, s.notes
                    FROM btc_outcome_scoring_v1 s
                    LEFT JOIN btc_chainlink_report_request_v1 start_req
                      ON start_req.ts = s.ts AND start_req.event_slug = s.event_slug AND start_req.boundary = 'start'
                    LEFT JOIN btc_chainlink_report_request_v1 end_req
                      ON end_req.ts = s.ts AND end_req.event_slug = s.event_slug AND end_req.boundary = 'end'
                    WHERE s.ts=?
                    ORDER BY s.event_slug, s.direction
                    LIMIT ?
                    """,
                    (latest_ts, max(0, int(limit))),
                ).fetchall()
            else:
                signal_top_ask_size_expr = signal_top_ask_size_expr.replace("s.", "")
                rows = con.execute(
                    f"""
                    SELECT ts, quote_ts, event_slug, market_key, direction,
                           model_probability, model_price_source,
                           signal_yes_bid, signal_yes_ask, signal_probability,
                           {signal_top_ask_size_expr},
                           chainlink_feed_id, chainlink_capture_method, chainlink_source_url,
                           chainlink_start_price, chainlink_end_price,
                           chainlink_start_observed_at, chainlink_end_observed_at,
                           chainlink_start_source_snapshot_path, chainlink_end_source_snapshot_path,
                           NULL AS chainlink_start_report_request_url,
                           NULL AS chainlink_end_report_request_url,
                           NULL AS chainlink_start_report_boundary_ts,
                           NULL AS chainlink_end_report_boundary_ts,
                           NULL AS chainlink_start_report_status,
                           NULL AS chainlink_end_report_status,
                           0 AS chainlink_start_report_requires_authentication,
                           0 AS chainlink_end_report_requires_authentication,
                           resolved_yes, final_outcome, brier_score, log_loss, clv,
                           status, notes
                    FROM btc_outcome_scoring_v1
                    WHERE ts=?
                    ORDER BY event_slug, direction
                    LIMIT ?
                    """,
                    (latest_ts, max(0, int(limit))),
                ).fetchall()
            return [_btc_calibration_row_detail(dict(row)) for row in rows]
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        return []


def load_latest_btc_calibration_summary_from_sqlite(
    db_path: str | PathLike[str],
) -> dict[str, float | int | str | bool | None] | None:
    """Read the newest BTC scoring batch from research SQLite, if present.

    Missing files/tables/schema are treated as absent optional telemetry so the
    dashboard never weakens no-trade gates or fails because cron has not created
    BTC scoring rows yet.
    """
    try:
        con = _connect_readonly_sqlite(db_path)
        con.row_factory = sqlite3.Row
        try:
            latest_row = con.execute("SELECT max(ts) AS latest_ts FROM btc_outcome_scoring_v1").fetchone()
            latest_ts = latest_row["latest_ts"] if latest_row else None
            if not latest_ts:
                return None
            scoring_columns = _table_columns(con, "btc_outcome_scoring_v1")
            signal_yes_bid_expr = "signal_yes_bid" if "signal_yes_bid" in scoring_columns else "NULL AS signal_yes_bid"
            signal_yes_ask_expr = "signal_yes_ask" if "signal_yes_ask" in scoring_columns else "NULL AS signal_yes_ask"
            signal_top_ask_size_expr = (
                "signal_top_ask_size" if "signal_top_ask_size" in scoring_columns else "NULL AS signal_top_ask_size"
            )
            model_price_source_expr = (
                "model_price_source" if "model_price_source" in scoring_columns else "NULL AS model_price_source"
            )
            event_slug_expr = "event_slug" if "event_slug" in scoring_columns else "NULL AS event_slug"
            rows = con.execute(
                f"""
                SELECT ts, {event_slug_expr}, model_probability, {model_price_source_expr}, resolved_yes, brier_score, log_loss, status,
                       {signal_yes_bid_expr}, {signal_yes_ask_expr}, {signal_top_ask_size_expr},
                       chainlink_start_price, chainlink_end_price,
                       chainlink_start_observed_at, chainlink_end_observed_at,
                       chainlink_start_source_snapshot_path, chainlink_end_source_snapshot_path
                FROM btc_outcome_scoring_v1
                WHERE ts=?
                """,
                (latest_ts,),
            ).fetchall()
            row_dicts = [dict(row) for row in rows]
            if row_dicts and _table_exists(con, "btc_chainlink_report_request_v1"):
                request_row = con.execute(
                    """
                    SELECT count(*) AS report_request_rows,
                           sum(CASE WHEN requires_authentication THEN 1 ELSE 0 END) AS auth_required_report_requests
                    FROM btc_chainlink_report_request_v1
                    WHERE ts=?
                    """,
                    (latest_ts,),
                ).fetchone()
                if request_row:
                    row_dicts[0]["report_request_rows"] = int(request_row["report_request_rows"] or 0)
                    row_dicts[0]["auth_required_report_requests"] = int(
                        request_row["auth_required_report_requests"] or 0
                    )
                auth_by_slug = {
                    str(row["event_slug"]): bool(row["auth_required"])
                    for row in con.execute(
                        """
                        SELECT event_slug,
                               max(CASE WHEN requires_authentication THEN 1 ELSE 0 END) AS auth_required
                        FROM btc_chainlink_report_request_v1
                        WHERE ts=?
                        GROUP BY event_slug
                        """,
                        (latest_ts,),
                    ).fetchall()
                }
                for row_dict in row_dicts:
                    event_slug = str(row_dict.get("event_slug") or "")
                    if event_slug and auth_by_slug.get(event_slug):
                        row_dict["chainlink_start_report_requires_authentication"] = True
                        row_dict["chainlink_end_report_requires_authentication"] = True
                if not any(
                    row_dict.get("chainlink_start_report_requires_authentication")
                    or row_dict.get("chainlink_end_report_requires_authentication")
                    for row_dict in row_dicts
                ) and row_dicts and int(row_dicts[0].get("auth_required_report_requests") or 0) > 0:
                    # Older test/fixture schemas lacked event_slug on scoring rows.
                    # Preserve the summary-level blocker without requiring a brittle join key.
                    row_dicts[0]["chainlink_start_report_requires_authentication"] = True
                    row_dicts[0]["chainlink_end_report_requires_authentication"] = True
            return summarize_latest_btc_calibration_rows(row_dicts)
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        return None
