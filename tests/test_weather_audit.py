import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from backend.core.weather_audit import (
    aggregate_trades,
    build_weather_audit,
    connect_sqlite,
    derive_city_label,
    detect_largest_outlier,
    load_all_weather_trades,
    load_weather_account_state,
    load_weather_trades,
    summarize_latest_signal_batch,
    summarize_probability_calibration,
    summarize_probability_calibration_by_platform,
    trade_win_probability,
)
from scripts.weather_audit_report import render_markdown


def _init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """
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
            edge_at_entry REAL,
            closed_early INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
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
        """
    )
    return conn


def _insert_trade_rows(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO trades (
            id, platform, event_slug, market_type, direction, entry_price, size,
            timestamp, settled, settlement_time, result, pnl
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def test_weather_audit_separates_headline_from_outlier(tmp_path):
    conn = _init_db(tmp_path / "audit.db")
    rows = [
        (1, "polymarket", "nyc-outlier", "weather", "no", 0.027, 75.0, "2026-06-04 11:03:55", 1, "2026-06-05 05:30:52", "win", 2702.78),
        (2, "polymarket", "london-loss", "weather", "yes", 0.050, 75.0, "2026-06-04 14:56:27", 1, "2026-06-05 00:04:58", "loss", -75.0),
        (3, "polymarket", "london-win", "weather", "no", 0.480, 75.0, "2026-06-05 02:00:50", 1, "2026-06-06 00:02:23", "win", 81.25),
        (4, "polymarket", "shanghai-loss", "weather", "yes", 0.089, 75.0, "2026-06-05 12:19:57", 1, "2026-06-05 16:48:23", "loss", -75.0),
        (5, "polymarket", "seoul-pending", "weather", "yes", 0.120, 75.0, "2026-06-06 02:33:38", 0, None, "pending", None),
        (6, "kalshi", "old-loss", "weather", "yes", 0.300, 75.0, "2026-06-01 02:33:38", 1, "2026-06-02 02:33:38", "loss", -75.0),
    ]
    _insert_trade_rows(conn, rows)

    trades = load_weather_trades(conn, since="2026-06-04 00:00:00")
    summary = aggregate_trades(trades)
    outlier = detect_largest_outlier(trades)

    assert summary.total == 5
    assert summary.settled == 4
    assert summary.pending == 1
    assert summary.wins == 2
    assert summary.losses == 2
    assert summary.realized_pnl == 2634.03
    assert outlier is not None
    assert outlier.event_slug == "nyc-outlier"
    assert outlier.pnl == 2702.78
    assert summary.outlier_event_slug == "nyc-outlier"
    assert summary.ex_outlier_pnl == -68.75


def test_weather_audit_includes_weather_market_type_variants_and_platform_split(tmp_path):
    conn = _init_db(tmp_path / "variants.db")
    rows = [
        (1, "polymarket", "pm-loss", "polymarket_weather", "yes", 0.40, 50.0, "2026-06-07 10:00:00", 1, "2026-06-07 18:00:00", "loss", -50.0),
        (2, "kalshi", "kalshi-win", "kalshi_weather", "no", 0.25, 50.0, "2026-06-07 11:00:00", 1, "2026-06-07 18:00:00", "win", 150.0),
        (3, "kalshi", "kalshi-pending", "temperature", "yes", 0.50, 25.0, "2026-06-07 12:00:00", 0, None, "pending", None),
        (4, "polymarket", "btc-ignore", "btc", "yes", 0.50, 25.0, "2026-06-07 12:00:00", 1, "2026-06-07 18:00:00", "loss", -25.0),
    ]
    _insert_trade_rows(conn, rows)

    report = build_weather_audit(
        conn,
        now=datetime(2026, 6, 7, 13, 0, 0),
        window_hours=72,
    )

    assert report.strict_window.total == 3
    assert report.strict_window.realized_pnl == 100.0
    assert set(report.by_platform) == {"polymarket", "kalshi"}
    assert report.by_platform["polymarket"].total == 1
    assert report.by_platform["polymarket"].realized_pnl == -50.0
    assert report.by_platform["kalshi"].total == 2
    assert report.by_platform["kalshi"].pending == 1
    assert report.by_platform["kalshi"].realized_pnl == 150.0
    assert report.account_state.total_trades == 3
    assert report.account_state.realized_pnl == 100.0
    assert report.account_state.equity_before_pending_marks == 1100.0
    assert report.account_state.remaining_to_target == 0.0
    assert report.account_state.progress_pct == 100.0


def test_weather_audit_supports_48h_window_and_excludes_future_rows(tmp_path):
    conn = _init_db(tmp_path / "window.db")
    rows = [
        (1, "polymarket", "before-48h", "weather", "yes", 0.40, 50.0, "2026-06-05 12:59:59", 1, "2026-06-05 18:00:00", "loss", -50.0),
        (2, "polymarket", "inside-48h", "weather", "yes", 0.40, 50.0, "2026-06-05 13:00:00", 1, "2026-06-05 18:00:00", "win", 75.0),
        (3, "kalshi", "future-row", "weather", "no", 0.25, 50.0, "2026-06-07 13:00:01", 1, "2026-06-07 18:00:00", "win", 150.0),
    ]
    _insert_trade_rows(conn, rows)

    report = build_weather_audit(
        conn,
        now=datetime(2026, 6, 7, 13, 0, 0),
        window_hours=48,
    )

    assert report.strict_window.total == 1
    assert report.strict_window.realized_pnl == 75.0
    assert report.strict_window.outlier_event_slug == "inside-48h"


def test_connect_sqlite_is_read_only_and_does_not_create_missing_db(tmp_path):
    path = tmp_path / "readonly.db"
    conn = _init_db(path)
    conn.close()

    readonly = connect_sqlite(path)
    with pytest.raises(sqlite3.OperationalError):
        readonly.execute("CREATE TABLE should_not_write (id INTEGER)")
    readonly.close()

    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        connect_sqlite(missing)
    assert not missing.exists()


def test_settled_rows_missing_pnl_are_not_counted_as_pending(tmp_path):
    conn = _init_db(tmp_path / "missing-pnl.db")
    rows = [
        (1, "polymarket", "settled-missing-pnl", "weather", "yes", 0.40, 50.0, "2026-06-07 10:00:00", 1, "2026-06-07 18:00:00", "win", None),
        (2, "polymarket", "pending", "weather", "yes", 0.40, 50.0, "2026-06-07 11:00:00", 0, None, "pending", None),
    ]
    _insert_trade_rows(conn, rows)

    summary = aggregate_trades(load_weather_trades(conn, since="2026-06-07 00:00:00"))

    assert summary.settled == 1
    assert summary.pending == 1
    assert summary.wins == 1
    assert summary.realized_pnl == 0.0


def test_weather_account_state_uses_separate_1000_to_1100_paper_ledger(tmp_path):
    conn = _init_db(tmp_path / "account.db")
    rows = [
        (1, "polymarket", "pm-win", "weather", "yes", 0.25, 75.0, "2026-06-01 10:00:00", 1, "2026-06-02 10:00:00", "win", 225.0, 0),
        (2, "kalshi", "kalshi-loss", "weather", "yes", 0.50, 50.0, "2026-06-02 10:00:00", 1, "2026-06-03 10:00:00", "loss", -50.0, 0),
        (3, "polymarket", "pm-pending", "weather", "no", 0.20, 40.0, "2026-06-03 10:00:00", 0, None, "pending", None, 0),
        (4, "kalshi", "kalshi-exited", "weather", "no", 0.60, 60.0, "2026-06-04 10:00:00", 0, "2026-06-04 12:00:00", "exited", -12.5, 1),
        (5, "polymarket", "btc-ignore", "btc", "yes", 0.50, 50.0, "2026-06-04 10:00:00", 1, "2026-06-04 11:00:00", "win", 50.0, 0),
    ]
    conn.executemany(
        """
        INSERT INTO trades (
            id, platform, event_slug, market_type, direction, entry_price, size,
            timestamp, settled, settlement_time, result, pnl, closed_early
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()

    account = load_weather_account_state(conn)

    assert account.initial_bankroll == 1000.0
    assert account.target_bankroll == 1100.0
    assert account.total_trades == 4
    assert account.settled_trades == 2
    assert account.pending_trades == 1
    assert account.closed_early_trades == 1
    assert account.pending_size == 40.0
    assert account.realized_pnl == 162.5
    assert account.equity_before_pending_marks == 1162.5
    assert account.remaining_to_target == 0.0
    assert account.progress_pct == 100.0


def test_weather_audit_markdown_reports_account_progress(tmp_path):
    conn = _init_db(tmp_path / "markdown.db")
    conn.execute(
        """
        INSERT INTO trades (
            id, platform, event_slug, market_type, direction, entry_price, size,
            timestamp, settled, settlement_time, result, pnl, closed_early
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (1, "polymarket", "pm-win", "weather", "yes", 0.25, 50.0, "2026-06-07 10:00:00", 1, "2026-06-08 10:00:00", "win", 75.0, 0),
    )
    conn.commit()
    report = build_weather_audit(conn, now=datetime(2026, 6, 8, 12, 0, 0), window_hours=72)

    markdown = render_markdown(report)

    assert "## Weather paper account" in markdown
    assert "Equity before pending marks: `$1075.00`" in markdown
    assert "Target: `$1100.00`" in markdown
    assert "Progress: `75.0%`" in markdown
    assert "Simulation-only" in markdown


def test_latest_signal_batch_counts_actionable_filtered_and_executed(tmp_path):
    conn = _init_db(tmp_path / "signals.db")
    rows = [
        (10, "m1", "polymarket", "weather", "2026-06-07 15:19:44", "yes", 0.95, 0.02, 0.93, 0.9, 0.01, 75.0, "[]", "[ACTIONABLE] NYC low above 65F", 0),
        (11, "m2", "kalshi", "weather", "2026-06-07 15:19:45", "no", 0.05, 0.33, 0.28, 0.9, 0.01, 75.0, "[]", "[ACTIONABLE] LA high above 73F", 0),
        (12, "m3", "kalshi", "weather", "2026-06-07 15:19:46", "yes", 0.05, 0.04, 0.01, 0.9, 0.0, 15.0, "[]", "[FILTERED] thin book", 0),
        (13, "m4", "polymarket", "weather", "2026-06-07 15:18:59", "yes", 0.60, 0.55, 0.05, 0.4, 0.0, 0.0, "[]", "[FILTERED] stale batch", 1),
        (14, "m5", "polymarket", "btc", "2026-06-07 15:19:47", "yes", 0.60, 0.55, 0.05, 0.4, 0.0, 0.0, "[]", "[ACTIONABLE] ignore non-weather", 1),
    ]
    conn.executemany("INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()

    batch = summarize_latest_signal_batch(conn)

    assert batch.minute == "2026-06-07 15:19"
    assert batch.total == 3
    assert batch.actionable == 2
    assert batch.filtered == 1
    assert batch.positive_size == 3
    assert batch.executed == 0


def test_latest_signal_batch_includes_rows_across_minute_boundary(tmp_path):
    conn = _init_db(tmp_path / "signals-boundary.db")
    rows = [
        (10, "m1", "polymarket", "weather", "2026-06-07 15:20:00", "yes", 0.95, 0.02, 0.93, 0.9, 0.01, 75.0, "[]", "[ACTIONABLE] latest row", 0),
        (11, "m2", "kalshi", "weather", "2026-06-07 15:19:59", "no", 0.05, 0.33, 0.28, 0.9, 0.01, 75.0, "[]", "[FILTERED] same scan previous minute", 1),
        (12, "m3", "kalshi", "weather", "2026-06-07 15:19:40", "yes", 0.05, 0.04, 0.01, 0.9, 0.0, 15.0, "[]", "[FILTERED] older scan", 0),
    ]
    conn.executemany("INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()

    batch = summarize_latest_signal_batch(conn)

    assert batch.minute == "2026-06-07 15:20"
    assert batch.total == 2
    assert batch.actionable == 1
    assert batch.filtered == 1
    assert batch.positive_size == 2
    assert batch.executed == 1


def _insert_calibration_rows(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO trades (
            id, platform, event_slug, market_ticker, market_type, direction,
            entry_price, size, timestamp, settled, settlement_time, result, pnl,
            model_probability
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def test_derive_city_label_from_polymarket_slug_and_kalshi_ticker():
    assert derive_city_label("highest-temperature-in-seoul-on-june-6-2026", "2440776", "polymarket") == "seoul"
    assert derive_city_label("lowest-temperature-in-nyc-on-june-5-2026", "2425070", "polymarket") == "nyc"
    assert derive_city_label("KXHIGHLAX-26JUN16-B73", "KXHIGHLAX-26JUN16-B73", "kalshi") == "lax"
    assert derive_city_label(None, "KXLOWMDW-26JUN16-T55", "kalshi") == "mdw"
    # Kalshi low-temp series carries a KXLOWT prefix; the station, not the T, wins.
    assert derive_city_label("KXLOWTDEN-26JUN04-T51", "KXLOWTDEN-26JUN04-T51", "kalshi") == "den"
    assert derive_city_label("something-unparseable", "weird-ticker", "polymarket") == "unknown"


def test_trade_win_probability_orients_to_held_side():
    yes_trade = trade_win_probability("yes", 0.9)
    no_trade = trade_win_probability("no", 0.2)
    up_trade = trade_win_probability("up", 0.7)
    down_trade = trade_win_probability("down", 0.3)
    assert yes_trade == 0.9
    assert no_trade == 0.8  # held NO side wins with prob 1 - model_yes
    assert up_trade == 0.7
    assert down_trade == 0.7
    assert trade_win_probability("yes", None) is None


def test_probability_calibration_brier_and_bins(tmp_path):
    conn = _init_db(tmp_path / "calib.db")
    rows = [
        # (id, platform, event_slug, market_ticker, market_type, direction,
        #  entry, size, timestamp, settled, settlement_time, result, pnl, model_prob)
        (1, "polymarket", "a", "a", "weather", "yes", 0.5, 75.0, "2026-06-04 10:00:00", 1, "2026-06-05 10:00:00", "win", 75.0, 0.9),
        (2, "polymarket", "b", "b", "weather", "yes", 0.5, 75.0, "2026-06-04 11:00:00", 1, "2026-06-05 11:00:00", "loss", -75.0, 0.8),
        (3, "polymarket", "c", "c", "weather", "no", 0.5, 75.0, "2026-06-04 12:00:00", 1, "2026-06-05 12:00:00", "win", 75.0, 0.2),
        (4, "polymarket", "d", "d", "weather", "yes", 0.5, 75.0, "2026-06-04 13:00:00", 0, None, "pending", None, 0.6),  # skipped
        (5, "polymarket", "e", "e", "weather", "yes", 0.5, 75.0, "2026-06-04 14:00:00", 1, "2026-06-05 14:00:00", "win", 75.0, None),  # skipped (no prob)
    ]
    _insert_calibration_rows(conn, rows)

    trades = load_all_weather_trades(conn)
    calib = summarize_probability_calibration(trades)

    # Held-side win probs: 0.9 (win), 0.8 (loss), 0.8 (win)
    # Brier = ((0.9-1)^2 + (0.8-0)^2 + (0.8-1)^2) / 3 = (0.01 + 0.64 + 0.04)/3
    assert calib.sample_size == 3
    assert calib.brier_score == pytest.approx(0.23, abs=1e-6)
    assert calib.mean_predicted_win_prob == pytest.approx((0.9 + 0.8 + 0.8) / 3, abs=1e-6)
    assert calib.empirical_win_rate == pytest.approx(2 / 3, abs=1e-6)
    assert sum(b.count for b in calib.bins) == 3


def test_build_weather_audit_includes_all_time_windows_city_and_calibration(tmp_path):
    conn = _init_db(tmp_path / "extended.db")
    rows = [
        (1, "polymarket", "highest-temperature-in-seoul-on-june-6-2026", "2440776", "weather", "yes", 0.12, 75.0, "2026-06-06 02:00:00", 1, "2026-06-06 20:00:00", "win", 550.0, 0.7),
        (2, "kalshi", "KXHIGHLAX-26JUN16-B73", "KXHIGHLAX-26JUN16-B73", "weather", "yes", 0.5, 75.0, "2026-06-15 10:00:00", 1, "2026-06-16 06:00:00", "loss", -75.0, 0.55),
        (3, "kalshi", "KXHIGHLAX-26JUN10-B70", "KXHIGHLAX-26JUN10-B70", "weather", "no", 0.5, 75.0, "2026-06-01 10:00:00", 1, "2026-06-02 06:00:00", "loss", -75.0, 0.4),
    ]
    _insert_calibration_rows(conn, rows)

    report = build_weather_audit(conn, now=datetime(2026, 6, 16, 12, 0, 0), window_hours=72)

    assert report.all_time.total == 3
    assert set(report.trailing_windows) == {"72h", "7d", "14d"}
    # Only the Jun 15 LAX trade is within 72h of Jun 16 12:00.
    assert report.trailing_windows["72h"].total == 1
    # 14d back is Jun 2 12:00, so the Jun 1 trade falls outside it (Jun 6 + Jun 15 remain).
    assert report.trailing_windows["14d"].total == 2
    assert report.all_time.total == 3
    assert "seoul" in report.by_city
    assert "lax" in report.by_city
    assert report.by_city["lax"].total == 2
    assert report.calibration.sample_size == 3


def test_weather_audit_reports_probability_calibration_by_platform(tmp_path):
    conn = _init_db(tmp_path / "venue-calibration.db")
    rows = [
        # Polymarket: two accurate high-confidence held-side forecasts.
        (1, "polymarket", "pm-a", "pm-a", "weather", "yes", 0.5, 75.0, "2026-06-04 10:00:00", 1, "2026-06-05 10:00:00", "win", 75.0, 0.9),
        (2, "polymarket", "pm-b", "pm-b", "weather", "no", 0.5, 75.0, "2026-06-04 11:00:00", 1, "2026-06-05 11:00:00", "win", 75.0, 0.1),
        # Kalshi: two overconfident losers.
        (3, "kalshi", "kx-a", "kx-a", "weather", "yes", 0.5, 75.0, "2026-06-04 12:00:00", 1, "2026-06-05 12:00:00", "loss", -75.0, 0.9),
        (4, "kalshi", "kx-b", "kx-b", "weather", "no", 0.5, 75.0, "2026-06-04 13:00:00", 1, "2026-06-05 13:00:00", "loss", -75.0, 0.1),
    ]
    _insert_calibration_rows(conn, rows)

    trades = load_all_weather_trades(conn)
    by_platform = summarize_probability_calibration_by_platform(trades)
    report = build_weather_audit(conn, now=datetime(2026, 6, 6, 12, 0, 0), window_hours=72)
    markdown = render_markdown(report)

    assert set(by_platform) == {"polymarket", "kalshi"}
    assert by_platform["polymarket"].sample_size == 2
    assert by_platform["polymarket"].brier_score == pytest.approx(0.01, abs=1e-6)
    assert by_platform["kalshi"].sample_size == 2
    assert by_platform["kalshi"].brier_score == pytest.approx(0.81, abs=1e-6)
    assert report.calibration_by_platform["kalshi"].empirical_win_rate == 0.0
    assert "## Probability calibration by venue" in markdown
    assert "**kalshi:** sample `2`; Brier `0.8100`" in markdown
    assert "**polymarket:** sample `2`; Brier `0.0100`" in markdown


def test_extended_report_renders_and_is_json_serializable(tmp_path):
    import json

    from backend.core.weather_audit import dataclass_to_dict

    conn = _init_db(tmp_path / "render.db")
    rows = [
        (1, "polymarket", "highest-temperature-in-seoul-on-june-6-2026", "2440776", "weather", "yes", 0.12, 75.0, "2026-06-06 02:00:00", 1, "2026-06-06 20:00:00", "win", 550.0, 0.7),
    ]
    _insert_calibration_rows(conn, rows)
    report = build_weather_audit(conn, now=datetime(2026, 6, 16, 12, 0, 0), window_hours=72)

    markdown = render_markdown(report)
    assert "## All-time performance" in markdown
    assert "## Trailing windows" in markdown
    assert "## By city" in markdown
    assert "## Probability calibration" in markdown

    payload = json.loads(json.dumps(report, default=dataclass_to_dict))
    assert "all_time" in payload
    assert "trailing_windows" in payload
    assert "by_city" in payload
    assert "calibration" in payload
