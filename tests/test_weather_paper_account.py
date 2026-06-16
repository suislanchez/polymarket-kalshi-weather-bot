import sqlite3
from types import SimpleNamespace

from backend.core.weather_paper_account import (
    build_bot_weather_signal_calibration_rows,
    build_polymarket_weather_source_state_rows,
    build_weather_calibration_rows,
    build_weather_signal_review_candidate_rows,
    join_kalshi_weather_quotes_to_outcomes,
    load_bot_weather_signal_calibration_rows_from_sqlite,
    load_latest_weather_signal_review_candidate_rows_from_sqlite,
    load_latest_weather_bot_signal_calibration_rows_from_sqlite,
    load_latest_weather_bot_signal_calibration_summary_from_sqlite,
    load_latest_polymarket_weather_source_state_rows_from_sqlite,
    load_latest_polymarket_weather_source_state_summary_from_sqlite,
    load_latest_weather_calibration_rows_from_sqlite,
    load_latest_weather_calibration_summary_from_sqlite,
    persist_bot_weather_signal_calibration_rows_to_sqlite,
    persist_polymarket_weather_source_state_rows_to_sqlite,
    persist_weather_signal_review_candidate_rows_to_sqlite,
    resolve_kalshi_high_temp_outcome,
    should_persist_weather_signal_for_calibration,
    summarize_latest_weather_calibration_rows,
    summarize_nws_cli_source_diagnostics,
    summarize_weather_paper_account,
)


def trade(pnl=None, settled=False, result="pending", market_type="weather", size=0.0, platform="kalshi"):
    return SimpleNamespace(pnl=pnl, settled=settled, result=result, market_type=market_type, size=size, platform=platform)


def test_polymarket_weather_source_state_rows_preserve_wunderground_station_and_depth(tmp_path):
    rows = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "highest-temperature-in-seoul-on-june-1",
                "condition_id": "0xabc",
                "question": "Will the highest temperature in Seoul be 25°C or higher on June 1?",
                "outcome": "Yes",
                "token_id": "123",
                "closed": False,
                "rule_text": "This market will resolve according to Weather Underground history at https://www.wunderground.com/history/daily/kr/incheon/RKSI. Forecast for the Incheon International Airport Station. Temperatures are Celsius to one decimal on 1 Jun '26.",
                "best_bid": 0.29,
                "best_ask": 0.30,
                "gamma_price": "0.305",
                "top_ask_size": 240.5,
                "volume": 1000,
                "liquidity": 500,
            }
        ],
        captured_at="20260601T150000Z",
        source_snapshot="/tmp/weather-summary.json",
    )

    assert rows == [
        {
            "captured_at": "20260601T150000Z",
            "event_slug": "highest-temperature-in-seoul-on-june-1",
            "condition_id": "0xabc",
            "question": "Will the highest temperature in Seoul be 25°C or higher on June 1?",
            "outcome": "Yes",
            "target_date": "2026-06-01",
            "token_id": "123",
            "closed": False,
            "settlement_source": "wunderground",
            "settlement_station": "RKSI",
            "settlement_station_name": "Incheon International Airport",
            "settlement_source_url": "https://www.wunderground.com/history/daily/kr/incheon/RKSI",
            "settlement_units": "celsius",
            "settlement_precision": "one-decimal",
            "best_bid": 0.29,
            "best_ask": 0.30,
            "execution_spread": 0.01,
            "market_probability": 0.305,
            "top_ask_size": 240.5,
            "volume": 1000,
            "liquidity": 500,
            "source_snapshot": "/tmp/weather-summary.json",
            "source_capture_status": None,
            "source_observed_value": None,
            "source_observed_unit": None,
            "source_observed_at": None,
            "source_capture_snapshot": None,
            "station_anomaly_status": "not_checked_missing_observation",
            "station_anomaly_neighbor_count": 0,
            "station_anomaly_neighbor_values": [],
            "station_anomaly_max_delta": None,
            "paper_actionable": False,
            "notes": "source-state only; requires direct source/final outcome, independent model, CLOB depth/spread, and sizing gates before actionability",
        }
    ]

    db_path = tmp_path / "poly-weather-source.sqlite"
    with sqlite3.connect(db_path) as conn:
        assert persist_polymarket_weather_source_state_rows_to_sqlite(conn, rows) == 1
        assert persist_polymarket_weather_source_state_rows_to_sqlite(conn, rows) == 0
        stored = conn.execute(
            "SELECT settlement_source, settlement_station, settlement_source_url, target_date, paper_actionable, execution_spread, market_probability FROM polymarket_weather_source_states"
        ).fetchone()

    assert stored == ("wunderground", "RKSI", "https://www.wunderground.com/history/daily/kr/incheon/RKSI", "2026-06-01", 0, 0.01, 0.305)


def test_latest_polymarket_weather_source_state_loader_is_read_only_latest_batch_and_non_actionable(tmp_path):
    db_path = tmp_path / "poly-weather-source.sqlite"
    first_batch = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "older-shenzhen-weather",
                "condition_id": "0xold",
                "question": "Older Shenzhen weather bucket",
                "outcome": "Yes",
                "token_id": "old-token",
                "rule_text": "Resolves by Weather Underground https://www.wunderground.com/history/daily/cn/shenzhen/ZGSZ.",
                "best_bid": 0.10,
                "best_ask": 0.12,
                "top_ask_size": 12,
            }
        ],
        captured_at="20260601T150000Z",
        source_snapshot="/tmp/old-raw.json",
    )
    latest_batch = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "latest-hong-kong-weather",
                "condition_id": "0xlatest",
                "question": "Latest Hong Kong high temperature bucket",
                "outcome": "Yes",
                "token_id": "latest-token",
                "closed": False,
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 2, 2026.",
                "best_bid": 0.39,
                "best_ask": 0.40,
                "gamma_price": "0.405",
                "top_ask_size": 321.5,
                "volume": 2000,
                "liquidity": 900,
            }
        ],
        captured_at="20260601T220000Z",
        source_snapshot="/tmp/latest-raw.json",
    )
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, first_batch)
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, latest_batch)

    rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(db_path, limit=5)

    assert len(rows) == 1
    assert rows[0]["captured_at"] == "20260601T220000Z"
    assert rows[0]["event_slug"] == "latest-hong-kong-weather"
    assert rows[0]["target_date"] == "2026-06-02"
    assert rows[0]["settlement_source"] == "hko"
    assert rows[0]["best_bid"] == 0.39
    assert rows[0]["best_ask"] == 0.40
    assert rows[0]["execution_spread"] == 0.01
    assert rows[0]["market_probability"] == 0.405
    assert rows[0]["top_ask_size"] == 321.5
    assert rows[0]["source_snapshot"] == "/tmp/latest-raw.json"
    assert rows[0]["paper_actionable"] is False
    assert rows[0]["source_state_label"] == "Polymarket weather source-state only / non-actionable"


def test_latest_polymarket_weather_source_state_loader_missing_db_does_not_create_file(tmp_path):
    missing = tmp_path / "missing-poly-weather-source.sqlite"

    assert load_latest_polymarket_weather_source_state_rows_from_sqlite(missing) == []
    assert not missing.exists()


def test_latest_polymarket_weather_source_state_loader_prioritizes_anomaly_warnings_before_limit(tmp_path):
    """The dashboard sample should not hide warning rows behind benign source-state rows."""
    db_path = tmp_path / "poly-weather-source-warning.sqlite"
    latest_batch = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "aaa-hko-benign-row",
                "condition_id": "0xhko",
                "question": "Will Hong Kong be above 29°C?",
                "outcome": "Yes",
                "token_id": "hko-token",
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 10, 2026.",
                "best_bid": 0.48,
                "best_ask": 0.51,
                "gamma_price": 0.51,
            },
            {
                "venue": "polymarket",
                "slug": "zzz-warning-wunderground-row",
                "condition_id": "0xwarn",
                "question": "Will Seoul be 25°C?",
                "outcome": "Yes",
                "token_id": "warn-token",
                "rule_text": "Recorded at the Incheon Intl Airport Station on 10 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "best_bid": 0.39,
                "best_ask": 0.40,
                "gamma_price": "0.40",
                "source_capture_status": "wunderground_current_24h_high_observed",
                "source_observed_value": 80,
                "source_observed_unit": "fahrenheit",
                "source_observed_at": "2026-06-10T21:00:00+0900",
                "station_neighbor_values": [72, 73],
            },
            {
                "venue": "polymarket",
                "slug": "yyy-pass-wunderground-row",
                "condition_id": "0xpass",
                "question": "Will NYC be 70°F?",
                "outcome": "Yes",
                "token_id": "pass-token",
                "rule_text": "Recorded at the LaGuardia Airport Station on 10 Jun '26. Source: https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA. Temperatures are Fahrenheit to whole degrees.",
                "best_bid": 0.49,
                "best_ask": 0.50,
                "gamma_price": "0.50",
                "source_capture_status": "wunderground_current_24h_high_observed",
                "source_observed_value": 70,
                "source_observed_unit": "fahrenheit",
                "source_observed_at": "2026-06-10T21:00:00-0400",
                "station_neighbor_values": [69, 71],
            },
        ],
        captured_at="20260610T150000Z",
        source_snapshot="/tmp/latest-warning-raw.json",
    )
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, latest_batch)

    rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(db_path, limit=1)

    assert len(rows) == 1
    assert rows[0]["event_slug"] == "zzz-warning-wunderground-row"
    assert rows[0]["station_anomaly_status"] == "warning"
    assert rows[0]["station_anomaly_max_delta"] == 8.0
    assert rows[0]["paper_actionable"] is False


def test_latest_polymarket_weather_source_state_loader_prioritizes_partial_history_rows_before_limit(tmp_path):
    """The dashboard sample should surface Wunderground partial-history blockers."""
    db_path = tmp_path / "poly-weather-source-partial-history.sqlite"
    latest_batch = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "aaa-observed-missing-neighbors-row",
                "condition_id": "0xmissing-neighbor",
                "question": "Will London be 24°C?",
                "outcome": "Yes",
                "token_id": "missing-neighbor-token",
                "rule_text": "Recorded at the London City Airport Station on 11 Jun '26. Source: https://www.wunderground.com/history/daily/gb/london/EGLC. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 63.0,
                "source_observed_unit": "fahrenheit",
                "source_capture_snapshot": "/tmp/eglc-history-high.json",
            },
            {
                "venue": "polymarket",
                "slug": "zzz-partial-history-row",
                "condition_id": "0xpartial-history",
                "question": "Will NYC be below 24°C?",
                "outcome": "Yes",
                "token_id": "partial-history-token",
                "rule_text": "Recorded at the LaGuardia Airport Station on 11 Jun '26. Source: https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA. Temperatures are Fahrenheit to whole degrees.",
                "source_capture_status": "wunderground_history_partial_low_observed",
                "source_observed_value": 75.0,
                "source_observed_unit": "fahrenheit",
                "source_capture_snapshot": "/tmp/klga-history-low.json",
                "station_neighbor_values": [74.0, 76.0],
            },
        ],
        captured_at="20260612T011005Z",
        source_snapshot="/tmp/latest-partial-history-raw.json",
    )
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, latest_batch)

    rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(db_path, limit=1)

    assert len(rows) == 1
    assert rows[0]["event_slug"] == "zzz-partial-history-row"
    assert rows[0]["source_capture_status"] == "wunderground_history_partial_low_observed"
    assert rows[0]["station_anomaly_status"] == "pass"
    assert rows[0]["paper_actionable"] is False


def test_latest_polymarket_weather_source_state_loader_keeps_partial_history_visible_with_warning_limit(tmp_path):
    """A warning-heavy sample should still include a partial-history row for source QA."""
    db_path = tmp_path / "poly-weather-source-warning-partial.sqlite"
    latest_batch = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "aaa-warning-row",
                "condition_id": "0xwarning-a",
                "question": "Will Seoul be 25°C?",
                "outcome": "Yes",
                "token_id": "warning-a-token",
                "rule_text": "Recorded at the Incheon Intl Airport Station on 11 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 80.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [72.0, 73.0],
            },
            {
                "venue": "polymarket",
                "slug": "aab-warning-row",
                "condition_id": "0xwarning-b",
                "question": "Will Seoul be 26°C?",
                "outcome": "Yes",
                "token_id": "warning-b-token",
                "rule_text": "Recorded at the Incheon Intl Airport Station on 11 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_low_observed",
                "source_observed_value": 81.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [72.0, 73.0],
            },
            {
                "venue": "polymarket",
                "slug": "zzz-partial-history-row",
                "condition_id": "0xpartial-history",
                "question": "Will NYC be below 24°C?",
                "outcome": "Yes",
                "token_id": "partial-history-token",
                "rule_text": "Recorded at the LaGuardia Airport Station on 11 Jun '26. Source: https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA. Temperatures are Fahrenheit to whole degrees.",
                "source_capture_status": "wunderground_history_partial_low_observed",
                "source_observed_value": 75.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [74.0, 76.0],
            },
        ],
        captured_at="20260612T011005Z",
        source_snapshot="/tmp/latest-warning-partial-history-raw.json",
    )
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, latest_batch)

    rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(db_path, limit=2)

    assert [row["event_slug"] for row in rows] == [
        "aaa-warning-row",
        "zzz-partial-history-row",
    ]
    assert rows[0]["station_anomaly_status"] == "warning"
    assert rows[1]["source_capture_status"] == "wunderground_history_partial_low_observed"
    assert all(row["paper_actionable"] is False for row in rows)


def test_latest_polymarket_weather_source_state_loader_keeps_hko_blocker_visible_with_warning_and_partial_limit(tmp_path):
    """Compact samples should include HKO missing-target blockers when warnings and partial rows compete."""
    db_path = tmp_path / "poly-weather-source-warning-partial-hko.sqlite"
    latest_batch = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "aaa-warning-row",
                "condition_id": "0xwarning-a",
                "question": "Will Seoul be 25°C?",
                "outcome": "Yes",
                "token_id": "warning-a-token",
                "rule_text": "Recorded at the Incheon Intl Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 81.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [88.0, 89.0],
            },
            {
                "venue": "polymarket",
                "slug": "aab-warning-row",
                "condition_id": "0xwarning-b",
                "question": "Will Seoul be 26°C?",
                "outcome": "Yes",
                "token_id": "warning-b-token",
                "rule_text": "Recorded at the Incheon Intl Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 82.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [88.0, 89.0],
            },
            {
                "venue": "polymarket",
                "slug": "mmm-partial-history-row",
                "condition_id": "0xpartial-history",
                "question": "Will Shenzhen be below 28°C?",
                "outcome": "Yes",
                "token_id": "partial-history-token",
                "rule_text": "Recorded at the Shenzhen Bao'an International Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/cn/shenzhen/ZGSZ. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_partial_low_observed",
                "source_observed_value": 82.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [82.0, 83.0],
            },
            {
                "venue": "polymarket",
                "slug": "zzz-hko-missing-target-row",
                "condition_id": "0xhko-missing",
                "question": "Will Hong Kong be above 29°C?",
                "outcome": "Yes",
                "token_id": "hko-token",
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 13, 2026.",
                "source_capture_status": "hko_daily_extract_missing_target_date",
                "source_observed_value": None,
                "source_observed_unit": "celsius",
                "source_capture_snapshot": "/tmp/hko-daily-extract.json",
            },
        ],
        captured_at="20260613T150203Z",
        source_snapshot="/tmp/latest-warning-partial-hko-raw.json",
    )
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, latest_batch)

    rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(db_path, limit=3)

    assert [row["event_slug"] for row in rows] == [
        "aaa-warning-row",
        "mmm-partial-history-row",
        "zzz-hko-missing-target-row",
    ]
    assert rows[0]["station_anomaly_status"] == "warning"
    assert rows[1]["source_capture_status"] == "wunderground_history_partial_low_observed"
    assert rows[2]["settlement_source"] == "hko"
    assert rows[2]["source_capture_status"] == "hko_daily_extract_missing_target_date"
    assert all(row["paper_actionable"] is False for row in rows)


def test_latest_polymarket_weather_source_state_loader_keeps_observed_representative_visible(tmp_path):
    """Compact all-category samples should not hide benign observed rows behind blockers."""
    db_path = tmp_path / "poly-weather-source-representative-categories.sqlite"
    latest_batch = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "aaa-warning-row",
                "condition_id": "0xwarning-a",
                "question": "Will Seoul be 25°C?",
                "outcome": "Yes",
                "token_id": "warning-a-token",
                "rule_text": "Recorded at the Incheon Intl Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 81.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [88.0, 89.0],
            },
            {
                "venue": "polymarket",
                "slug": "aab-warning-row",
                "condition_id": "0xwarning-b",
                "question": "Will Seoul be 26°C?",
                "outcome": "Yes",
                "token_id": "warning-b-token",
                "rule_text": "Recorded at the Incheon Intl Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 82.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [88.0, 89.0],
            },
            {
                "venue": "polymarket",
                "slug": "mmm-partial-history-row",
                "condition_id": "0xpartial-history",
                "question": "Will Shenzhen be below 28°C?",
                "outcome": "Yes",
                "token_id": "partial-history-token",
                "rule_text": "Recorded at the Shenzhen Bao'an International Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/cn/shenzhen/ZGSZ. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_partial_low_observed",
                "source_observed_value": 82.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [82.0, 83.0],
            },
            {
                "venue": "polymarket",
                "slug": "zzz-hko-missing-target-row",
                "condition_id": "0xhko-missing",
                "question": "Will Hong Kong be above 29°C?",
                "outcome": "Yes",
                "token_id": "hko-token",
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 13, 2026.",
                "source_capture_status": "hko_daily_extract_missing_target_date",
                "source_observed_value": None,
                "source_observed_unit": "celsius",
                "source_capture_snapshot": "/tmp/hko-daily-extract.json",
            },
            {
                "venue": "polymarket",
                "slug": "yyy-observed-pass-row",
                "condition_id": "0xobserved-pass",
                "question": "Will London be 24°C?",
                "outcome": "Yes",
                "token_id": "observed-token",
                "rule_text": "Recorded at the London City Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/gb/london/EGLC. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 63.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [62.0, 64.0],
            },
            {
                "venue": "polymarket",
                "slug": "xxx-source-only-row",
                "condition_id": "0xsource-only",
                "question": "Will Shenzhen be below 28°C?",
                "outcome": "Yes",
                "token_id": "source-only-token",
                "rule_text": "Recorded at the Shenzhen Bao'an International Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/cn/shenzhen/ZGSZ. Temperatures are Celsius to whole degrees.",
            },
        ],
        captured_at="20260614T010645Z",
        source_snapshot="/tmp/latest-representative-source-state-raw.json",
    )
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, latest_batch)

    rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(db_path, limit=5)

    sample_slugs = {row["event_slug"] for row in rows}
    assert "yyy-observed-pass-row" in sample_slugs
    assert "xxx-source-only-row" in sample_slugs
    assert any(row["station_anomaly_status"] == "warning" for row in rows)
    assert any(str(row["source_capture_status"]).startswith("wunderground_history_partial") for row in rows)
    assert any(row["settlement_source"] == "hko" for row in rows)
    assert all(row["paper_actionable"] is False for row in rows)


def test_latest_polymarket_weather_source_state_loader_filters_by_operator_category(tmp_path):
    """Backend/API drilldown should load rows for a requested source-state category."""
    db_path = tmp_path / "poly-weather-source-category-drilldown.sqlite"
    rows = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "latest-seoul-warning-weather",
                "condition_id": "0xwarning",
                "question": "Will Seoul be 25°C?",
                "outcome": "Yes",
                "token_id": "warning-token",
                "rule_text": "Recorded at the Incheon Intl Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 81.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [88.0, 89.0],
            },
            {
                "venue": "polymarket",
                "slug": "latest-nyc-partial-weather",
                "condition_id": "0xpartial",
                "question": "Will NYC be below 24°C?",
                "outcome": "Yes",
                "token_id": "partial-token",
                "rule_text": "Recorded at the LaGuardia Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA. Temperatures are Fahrenheit to whole degrees.",
                "source_capture_status": "wunderground_history_partial_low_observed",
                "source_observed_value": 75.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [74.0, 76.0],
            },
            {
                "venue": "polymarket",
                "slug": "latest-hko-missing-weather",
                "condition_id": "0xhko",
                "question": "Will Hong Kong be above 29°C?",
                "outcome": "Yes",
                "token_id": "hko-token",
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 13, 2026.",
                "source_capture_status": "hko_daily_extract_missing_target_date",
                "source_observed_value": None,
                "source_observed_unit": "celsius",
            },
            {
                "venue": "polymarket",
                "slug": "latest-london-observed-weather",
                "condition_id": "0xobserved",
                "question": "Will London be 24°C?",
                "outcome": "Yes",
                "token_id": "observed-token",
                "rule_text": "Recorded at the London City Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/gb/london/EGLC. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 63.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [62.0, 64.0],
            },
            {
                "venue": "polymarket",
                "slug": "latest-source-only-weather",
                "condition_id": "0xsource-only",
                "question": "Will Shenzhen be below 28°C?",
                "outcome": "Yes",
                "token_id": "source-only-token",
                "rule_text": "Recorded at the Shenzhen Bao'an International Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/cn/shenzhen/ZGSZ. Temperatures are Celsius to whole degrees.",
            },
        ],
        captured_at="20260614T010645Z",
        source_snapshot="/tmp/category-drilldown-raw.json",
    )
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, rows)

    observed_rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(
        db_path,
        limit=5,
        category="obs",
    )

    assert [row["event_slug"] for row in observed_rows] == ["latest-london-observed-weather"]
    assert observed_rows[0]["station_anomaly_status"] == "pass"
    assert observed_rows[0]["paper_actionable"] is False


def test_latest_polymarket_weather_source_state_loader_filters_by_open_closed_state(tmp_path):
    """Drilldown should support open-only samples so closed rows do not dominate operator review."""
    db_path = tmp_path / "poly-weather-source-market-state-drilldown.sqlite"
    rows = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "open-seoul-weather",
                "condition_id": "0xopen",
                "question": "Will Seoul be 25°C?",
                "outcome": "Yes",
                "token_id": "open-token",
                "closed": False,
                "rule_text": "Recorded at the Incheon Intl Airport Station on 14 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 79.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [88.0, 88.0],
            },
            {
                "venue": "polymarket",
                "slug": "closed-hong-kong-weather",
                "condition_id": "0xclosed",
                "question": "Will Hong Kong be above 29°C?",
                "outcome": "Yes",
                "token_id": "closed-token",
                "closed": True,
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 13, 2026.",
                "source_capture_status": "hko_daily_extract_missing_target_date",
                "source_observed_value": None,
                "source_observed_unit": "celsius",
            },
        ],
        captured_at="20260614T150205Z",
        source_snapshot="/tmp/market-state-drilldown-raw.json",
    )
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, rows)

    open_rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(
        db_path,
        limit=10,
        market_state="open",
    )
    closed_rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(
        db_path,
        limit=10,
        market_state="closed",
    )
    all_rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(
        db_path,
        limit=10,
        category="all",
        market_state="all",
    )
    invalid_rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(
        db_path,
        limit=10,
        market_state="stale",
    )

    assert [row["event_slug"] for row in open_rows] == ["open-seoul-weather"]
    assert open_rows[0]["closed"] is False
    assert open_rows[0]["paper_actionable"] is False
    assert [row["event_slug"] for row in closed_rows] == ["closed-hong-kong-weather"]
    assert closed_rows[0]["closed"] is True
    assert {row["event_slug"] for row in all_rows} == {"open-seoul-weather", "closed-hong-kong-weather"}
    assert invalid_rows == []


def test_latest_polymarket_weather_source_state_summary_counts_latest_batch_coverage(tmp_path):
    missing = tmp_path / "missing-poly-weather-source-summary.sqlite"
    assert load_latest_polymarket_weather_source_state_summary_from_sqlite(missing) is None
    assert not missing.exists()

    db_path = tmp_path / "poly-weather-source-summary.sqlite"
    old_rows = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "old-weather",
                "condition_id": "0xold",
                "question": "Older weather bucket",
                "outcome": "Yes",
                "token_id": "old-token",
                "rule_text": "Resolves by Weather Underground https://www.wunderground.com/history/daily/cn/shenzhen/ZGSZ.",
                "best_bid": 0.10,
                "best_ask": 0.12,
                "top_ask_size": 9,
            }
        ],
        captured_at="20260601T150000Z",
        source_snapshot="/tmp/old-raw.json",
    )
    latest_rows = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "latest-seoul-weather",
                "condition_id": "0xseoul-bucket",
                "question": "Will Seoul be 25°C?",
                "outcome": "Yes",
                "token_id": "yes-token",
                "closed": False,
                "rule_text": "Recorded at the Incheon Intl Airport Station on 2 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "best_bid": 0.39,
                "best_ask": 0.40,
                "gamma_price": "0.40",
                "top_ask_size": 321.5,
            },
            {
                "venue": "polymarket",
                "slug": "latest-seoul-weather",
                "condition_id": "0xseoul-bucket",
                "question": "Will Seoul be 25°C?",
                "outcome": "No",
                "token_id": "no-token",
                "closed": True,
                "rule_text": "Recorded at the Incheon Intl Airport Station on 2 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "best_bid": None,
                "best_ask": None,
                "gamma_price": "0.60",
                "top_ask_size": None,
            },
            {
                "venue": "polymarket",
                "slug": "latest-hong-kong-weather",
                "condition_id": "0xhko",
                "question": "Will Hong Kong be above 29°C?",
                "outcome": "Yes",
                "token_id": "hko-token",
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 2, 2026.",
                "best_bid": 0.48,
                "best_ask": 0.51,
                "gamma_price": 0.51,
                "top_ask_size": 50,
                "source_capture_status": "history_no_data_recorded",
                "source_observed_value": None,
                "source_observed_unit": "celsius",
                "source_observed_at": None,
                "source_capture_snapshot": "/tmp/hko-source.html",
            },
        ],
        captured_at="20260602T150000Z",
        source_snapshot="/tmp/latest-raw.json",
    )
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, old_rows)
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, latest_rows)

    summary = load_latest_polymarket_weather_source_state_summary_from_sqlite(db_path)

    assert summary == {
        "latest_captured_at": "20260602T150000Z",
        "source_state_rows": 3,
        "unique_events": 2,
        "unique_conditions": 2,
        "unique_stations": 1,
        "target_date_rows": 3,
        "unique_target_dates": 1,
        "wunderground_rows": 2,
        "hko_rows": 1,
        "hko_observed_value_rows": 0,
        "hko_missing_target_date_rows": 0,
        "hko_error_rows": 0,
        "direct_source_url_rows": 3,
        "unique_source_urls": 2,
        "line_book_rows": 2,
        "open_rows": 2,
        "open_line_book_rows": 2,
        "open_top_ask_size_rows": 2,
        "closed_line_book_rows": 0,
        "category_warning_rows": 0,
        "category_partial_rows": 0,
        "category_hko_rows": 0,
        "category_observed_rows": 0,
        "category_source_only_rows": 3,
        "open_category_warning_rows": 0,
        "open_category_partial_rows": 0,
        "open_category_hko_rows": 0,
        "open_category_observed_rows": 0,
        "open_category_source_only_rows": 2,
        "closed_category_warning_rows": 0,
        "closed_category_partial_rows": 0,
        "closed_category_hko_rows": 0,
        "closed_category_observed_rows": 0,
        "closed_category_source_only_rows": 1,
        "market_probability_rows": 3,
        "yes_market_probability_rows": 2,
        "no_market_probability_rows": 1,
        "complete_binary_condition_pairs": 1,
        "incomplete_binary_condition_pairs": 1,
        "yes_market_probability_mass_event_count": 2,
        "yes_market_probability_mass_min": 0.4,
        "yes_market_probability_mass_max": 0.51,
        "yes_market_probability_mass_sanity_passed_count": 0,
        "yes_market_probability_mass_blocked_count": 2,
        "top_ask_size_rows": 2,
        "closed_rows": 1,
        "source_capture_attempted_rows": 1,
        "source_capture_unique_urls": 1,
        "source_capture_missing_rows": 2,
        "source_capture_missing_unique_urls": 1,
        "source_capture_no_data_rows": 1,
        "source_capture_observed_value_rows": 0,
        "source_capture_error_rows": 0,
        "history_capture_rows": 0,
        "history_observed_value_rows": 0,
        "history_partial_rows": 0,
        "history_complete_rows": 0,
        "history_unique_source_urls": 0,
        "history_partial_unique_source_urls": 0,
        "history_partial_unique_stations": 0,
        "station_anomaly_checked_rows": 0,
        "station_anomaly_neighbor_evidence_rows": 0,
        "station_anomaly_neighbor_evidence_max_count": 0,
        "station_anomaly_not_checked_rows": 3,
        "station_anomaly_missing_observation_rows": 3,
        "station_anomaly_missing_neighbors_rows": 0,
        "station_anomaly_warning_rows": 0,
        "station_anomaly_warning_unique_events": 0,
        "station_anomaly_warning_unique_stations": 0,
        "station_anomaly_warning_unique_source_urls": 0,
        "station_anomaly_warning_max_delta": None,
        "station_anomaly_passed_rows": 0,
        "station_anomaly_max_delta": None,
        "paper_actionable": False,
        "market_scope": "weather",
        "source_snapshot": "/tmp/latest-raw.json",
        "source_state_label": "Polymarket weather source-state only / non-actionable",
    }

    rows = load_latest_polymarket_weather_source_state_rows_from_sqlite(db_path, limit=5)
    hko_row = next(row for row in rows if row["condition_id"] == "0xhko")
    assert hko_row["source_capture_status"] == "history_no_data_recorded"
    assert hko_row["source_observed_unit"] == "celsius"
    assert hko_row["source_capture_snapshot"] == "/tmp/hko-source.html"


def test_polymarket_weather_source_state_summary_counts_category_by_market_state(tmp_path):
    """Source-state summaries should expose open/closed category counts for drilldown chips."""
    rows = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "open-warning-seoul-weather",
                "condition_id": "0xopen-warning",
                "question": "Will Seoul be 25°C?",
                "outcome": "Yes",
                "token_id": "open-warning-token",
                "closed": False,
                "rule_text": "Recorded at the Incheon Intl Airport Station on 14 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 79.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [88.0, 89.0],
            },
            {
                "venue": "polymarket",
                "slug": "closed-warning-seoul-weather",
                "condition_id": "0xclosed-warning",
                "question": "Will Seoul be 25°C?",
                "outcome": "Yes",
                "token_id": "closed-warning-token",
                "closed": True,
                "rule_text": "Recorded at the Incheon Intl Airport Station on 14 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 79.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [88.0, 89.0],
            },
            {
                "venue": "polymarket",
                "slug": "open-hko-weather",
                "condition_id": "0xopen-hko",
                "question": "Will Hong Kong be above 32°C?",
                "outcome": "Yes",
                "token_id": "open-hko-token",
                "closed": False,
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 14, 2026.",
                "source_capture_status": "hko_daily_extract_missing_target_date",
            },
            {
                "venue": "polymarket",
                "slug": "closed-observed-london-weather",
                "condition_id": "0xclosed-observed",
                "question": "Will London be 24°C?",
                "outcome": "Yes",
                "token_id": "closed-observed-token",
                "closed": True,
                "rule_text": "Recorded at the London City Airport Station on 14 Jun '26. Source: https://www.wunderground.com/history/daily/gb/london/EGLC. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_low_observed",
                "source_observed_value": 59.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [60.0, 58.0],
            },
        ],
        captured_at="20260615T010441Z",
        source_snapshot="/tmp/latest-raw.json",
    )
    db_path = tmp_path / "poly-weather-source-state-cross-counts.sqlite"
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, rows)

    summary = load_latest_polymarket_weather_source_state_summary_from_sqlite(db_path)

    assert summary is not None
    assert summary["category_warning_rows"] == 2
    assert summary["category_hko_rows"] == 1
    assert summary["category_observed_rows"] == 1
    assert summary["open_rows"] == 2
    assert summary["closed_rows"] == 2
    assert summary["open_category_warning_rows"] == 1
    assert summary["open_category_hko_rows"] == 1
    assert summary["open_category_observed_rows"] == 0
    assert summary["open_category_source_only_rows"] == 0
    assert summary["closed_category_warning_rows"] == 1
    assert summary["closed_category_hko_rows"] == 0
    assert summary["closed_category_observed_rows"] == 1
    assert summary["closed_category_source_only_rows"] == 0
    assert summary["paper_actionable"] is False


def test_polymarket_weather_source_state_summary_counts_wunderground_history_statuses(tmp_path):
    rows = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "latest-london-weather",
                "condition_id": "0xlondon-high",
                "question": "Will London be 24°C?",
                "outcome": "Yes",
                "token_id": "history-high-token",
                "rule_text": "Recorded at the London City Airport Station on 11 Jun '26. Source: https://www.wunderground.com/history/daily/gb/london/EGLC. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 63.0,
                "source_observed_unit": "fahrenheit",
                "source_capture_snapshot": "/tmp/eglc-history-high.json",
            },
            {
                "venue": "polymarket",
                "slug": "latest-nyc-weather",
                "condition_id": "0xnyc-low",
                "question": "Will NYC be 24°C?",
                "outcome": "Yes",
                "token_id": "history-partial-token",
                "rule_text": "Recorded at the LaGuardia Airport Station on 11 Jun '26. Source: https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA. Temperatures are Fahrenheit to whole degrees.",
                "source_capture_status": "wunderground_history_partial_low_observed",
                "source_observed_value": 75.0,
                "source_observed_unit": "fahrenheit",
                "source_capture_snapshot": "/tmp/klga-history-low.json",
            },
            {
                "venue": "polymarket",
                "slug": "latest-seoul-weather",
                "condition_id": "0xseoul-error",
                "question": "Will Seoul be 24°C?",
                "outcome": "Yes",
                "token_id": "history-error-token",
                "rule_text": "Recorded at the Incheon Intl Airport Station on 11 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_parse_error",
                "source_observed_value": None,
                "source_observed_unit": "fahrenheit",
                "source_capture_snapshot": "/tmp/rksi-history-error.json",
            },
        ],
        captured_at="20260612T011005Z",
        source_snapshot="/tmp/latest-raw.json",
    )
    db_path = tmp_path / "poly-weather-history-summary.sqlite"
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, rows)

    summary = load_latest_polymarket_weather_source_state_summary_from_sqlite(db_path)

    assert summary is not None
    assert summary["history_capture_rows"] == 3
    assert summary["history_observed_value_rows"] == 2
    assert summary["history_partial_rows"] == 1
    assert summary["history_complete_rows"] == 1
    assert summary["history_unique_source_urls"] == 3
    assert summary["history_partial_unique_source_urls"] == 1
    assert summary["history_partial_unique_stations"] == 1
    assert summary["source_capture_error_rows"] == 1
    assert summary["paper_actionable"] is False


def test_polymarket_weather_source_state_summary_counts_operator_sample_categories(tmp_path):
    rows = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "latest-seoul-warning-weather",
                "condition_id": "0xwarning",
                "question": "Will Seoul be 25°C?",
                "outcome": "Yes",
                "token_id": "warning-token",
                "rule_text": "Recorded at the Incheon Intl Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 81.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [88.0, 89.0],
            },
            {
                "venue": "polymarket",
                "slug": "latest-nyc-partial-weather",
                "condition_id": "0xpartial",
                "question": "Will NYC be below 24°C?",
                "outcome": "Yes",
                "token_id": "partial-token",
                "rule_text": "Recorded at the LaGuardia Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA. Temperatures are Fahrenheit to whole degrees.",
                "source_capture_status": "wunderground_history_partial_low_observed",
                "source_observed_value": 75.0,
                "source_observed_unit": "fahrenheit",
                "station_neighbor_values": [74.0, 76.0],
            },
            {
                "venue": "polymarket",
                "slug": "latest-hko-missing-weather",
                "condition_id": "0xhko",
                "question": "Will Hong Kong be above 29°C?",
                "outcome": "Yes",
                "token_id": "hko-token",
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 13, 2026.",
                "source_capture_status": "hko_daily_extract_missing_target_date",
                "source_observed_value": None,
                "source_observed_unit": "celsius",
            },
            {
                "venue": "polymarket",
                "slug": "latest-london-observed-weather",
                "condition_id": "0xobserved",
                "question": "Will London be 24°C?",
                "outcome": "Yes",
                "token_id": "observed-token",
                "rule_text": "Recorded at the London City Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/gb/london/EGLC. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "wunderground_history_high_observed",
                "source_observed_value": 63.0,
                "source_observed_unit": "fahrenheit",
            },
            {
                "venue": "polymarket",
                "slug": "latest-source-only-weather",
                "condition_id": "0xsource-only",
                "question": "Will Shenzhen be below 28°C?",
                "outcome": "Yes",
                "token_id": "source-only-token",
                "rule_text": "Recorded at the Shenzhen Bao'an International Airport Station on 13 Jun '26. Source: https://www.wunderground.com/history/daily/cn/shenzhen/ZGSZ. Temperatures are Celsius to whole degrees.",
            },
        ],
        captured_at="20260613T180000Z",
        source_snapshot="/tmp/operator-category-raw.json",
    )
    db_path = tmp_path / "poly-weather-category-summary.sqlite"
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, rows)

    summary = load_latest_polymarket_weather_source_state_summary_from_sqlite(db_path)

    assert summary is not None
    assert summary["category_warning_rows"] == 1
    assert summary["category_partial_rows"] == 1
    assert summary["category_hko_rows"] == 1
    assert summary["category_observed_rows"] == 1
    assert summary["category_source_only_rows"] == 1
    assert summary["paper_actionable"] is False


def test_polymarket_weather_source_state_summary_counts_hko_capture_statuses(tmp_path):
    rows = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "highest-temperature-in-hong-kong-on-june-12-2026",
                "condition_id": "0xhko-observed",
                "question": "Will Hong Kong be 29°C or above?",
                "outcome": "Yes",
                "token_id": "hko-observed-token",
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 12, 2026.",
                "source_capture_status": "hko_daily_extract_observed",
                "source_observed_value": 29.4,
                "source_observed_unit": "celsius",
                "source_capture_snapshot": "/tmp/hko-observed.json",
            },
            {
                "venue": "polymarket",
                "slug": "lowest-temperature-in-hong-kong-on-june-12-2026",
                "condition_id": "0xhko-missing",
                "question": "Will Hong Kong be 25°C or below?",
                "outcome": "Yes",
                "token_id": "hko-missing-token",
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 12, 2026.",
                "source_capture_status": "hko_daily_extract_missing_target_date",
                "source_observed_value": None,
                "source_observed_unit": "celsius",
                "source_capture_snapshot": "/tmp/hko-missing.json",
            },
            {
                "venue": "polymarket",
                "slug": "highest-temperature-in-hong-kong-on-june-13-2026",
                "condition_id": "0xhko-error",
                "question": "Will Hong Kong be 30°C or above?",
                "outcome": "Yes",
                "token_id": "hko-error-token",
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 13, 2026.",
                "source_capture_status": "hko_daily_extract_parse_error",
                "source_observed_value": None,
                "source_observed_unit": "celsius",
                "source_capture_snapshot": "/tmp/hko-error.json",
            },
        ],
        captured_at="20260612T180000Z",
        source_snapshot="/tmp/hko-raw.json",
    )
    db_path = tmp_path / "poly-weather-hko-summary.sqlite"
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, rows)

    summary = load_latest_polymarket_weather_source_state_summary_from_sqlite(db_path)

    assert summary is not None
    assert summary["hko_rows"] == 3
    assert summary["hko_observed_value_rows"] == 1
    assert summary["hko_missing_target_date_rows"] == 1
    assert summary["hko_error_rows"] == 1
    assert summary["source_capture_error_rows"] == 1
    assert summary["paper_actionable"] is False


def test_polymarket_weather_source_state_summary_treats_missing_anomaly_schema_as_not_checked(tmp_path):
    """Old snapshot rows without anomaly columns must not look checked/passed."""
    db_path = tmp_path / "poly-weather-old-schema.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE polymarket_weather_source_states (
                captured_at TEXT NOT NULL,
                event_slug TEXT,
                condition_id TEXT NOT NULL,
                outcome TEXT,
                settlement_source TEXT,
                settlement_station TEXT,
                settlement_source_url TEXT,
                best_bid REAL,
                best_ask REAL,
                top_ask_size REAL,
                closed INTEGER NOT NULL DEFAULT 0,
                source_snapshot TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO polymarket_weather_source_states (
                captured_at, event_slug, condition_id, outcome, settlement_source,
                settlement_station, settlement_source_url, best_bid, best_ask,
                top_ask_size, closed, source_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "20260607T010226Z",
                    "highest-temperature-in-seoul-on-june-7-2026",
                    "0xold-yes",
                    "Yes",
                    "wunderground",
                    "RKSI",
                    "https://www.wunderground.com/history/daily/kr/incheon/RKSI",
                    0.95,
                    0.98,
                    40.0,
                    1,
                    "/tmp/old-raw.json",
                ),
                (
                    "20260607T010226Z",
                    "highest-temperature-in-seoul-on-june-7-2026",
                    "0xold-no",
                    "No",
                    "wunderground",
                    "RKSI",
                    "https://www.wunderground.com/history/daily/kr/incheon/RKSI",
                    None,
                    None,
                    None,
                    1,
                    "/tmp/old-raw.json",
                ),
            ],
        )

    summary = load_latest_polymarket_weather_source_state_summary_from_sqlite(db_path)
    assert summary is not None

    assert summary["station_anomaly_checked_rows"] == 0
    assert summary["station_anomaly_not_checked_rows"] == 2
    assert summary["station_anomaly_missing_observation_rows"] == 2
    assert summary["station_anomaly_missing_neighbors_rows"] == 0
    assert summary["station_anomaly_warning_rows"] == 0
    assert summary["station_anomaly_passed_rows"] == 0


def test_polymarket_weather_source_state_rows_preserve_station_anomaly_diagnostics(tmp_path):
    rows = build_polymarket_weather_source_state_rows(
        [
            {
                "venue": "polymarket",
                "slug": "latest-london-weather",
                "condition_id": "0xlondon-pass",
                "question": "Will London be 24°C?",
                "outcome": "Yes",
                "token_id": "yes-token",
                "rule_text": "Recorded at the London City Airport Station on 2 Jun '26. Source: https://www.wunderground.com/history/daily/gb/london/EGLC. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "observed_value",
                "source_observed_value": 24.0,
                "source_observed_unit": "celsius",
                "station_neighbor_values": [23.4, 25.1],
            },
            {
                "venue": "polymarket",
                "slug": "latest-seoul-weather",
                "condition_id": "0xseoul-warn",
                "question": "Will Seoul be 28°C?",
                "outcome": "Yes",
                "token_id": "warn-token",
                "rule_text": "Recorded at the Incheon Intl Airport Station on 2 Jun '26. Source: https://www.wunderground.com/history/daily/kr/incheon/RKSI. Temperatures are Celsius to whole degrees.",
                "source_capture_status": "observed_value",
                "source_observed_value": 42.0,
                "source_observed_unit": "celsius",
                "neighbor_observed_values": [29.5, 30.0],
            },
            {
                "venue": "polymarket",
                "slug": "latest-hong-kong-weather",
                "condition_id": "0xhko-missing",
                "question": "Will Hong Kong be 29°C?",
                "outcome": "Yes",
                "token_id": "missing-token",
                "rule_text": "This market uses the Hong Kong Observatory Daily Extract at https://www.hko.gov.hk/en/cis/dailyExtract.htm. Temperatures are Celsius to one decimal on June 2, 2026.",
                "source_capture_status": "http_200_unparsed",
                "source_observed_value": None,
                "source_observed_unit": "celsius",
            },
        ],
        captured_at="20260602T150000Z",
        source_snapshot="/tmp/latest-raw.json",
    )

    by_condition = {row["condition_id"]: row for row in rows}
    assert by_condition["0xlondon-pass"]["station_anomaly_status"] == "pass"
    assert by_condition["0xlondon-pass"]["station_anomaly_neighbor_count"] == 2
    assert by_condition["0xlondon-pass"]["station_anomaly_max_delta"] == 1.1
    assert by_condition["0xlondon-pass"]["station_anomaly_neighbor_values"] == [23.4, 25.1]
    assert by_condition["0xseoul-warn"]["station_anomaly_status"] == "warning"
    assert by_condition["0xseoul-warn"]["station_anomaly_neighbor_count"] == 2
    assert by_condition["0xseoul-warn"]["station_anomaly_max_delta"] == 12.5
    assert by_condition["0xseoul-warn"]["station_anomaly_neighbor_values"] == [29.5, 30.0]
    assert by_condition["0xhko-missing"]["station_anomaly_status"] == "not_checked_missing_observation"
    assert by_condition["0xhko-missing"]["station_anomaly_neighbor_values"] == []

    db_path = tmp_path / "poly-weather-anomaly.sqlite"
    with sqlite3.connect(db_path) as conn:
        persist_polymarket_weather_source_state_rows_to_sqlite(conn, rows)

    summary = load_latest_polymarket_weather_source_state_summary_from_sqlite(db_path)
    assert summary is not None
    assert summary["station_anomaly_checked_rows"] == 2
    assert summary["station_anomaly_neighbor_evidence_rows"] == 2
    assert summary["station_anomaly_neighbor_evidence_max_count"] == 2
    assert summary["station_anomaly_warning_rows"] == 1
    assert summary["station_anomaly_warning_unique_events"] == 1
    assert summary["station_anomaly_warning_unique_stations"] == 1
    assert summary["station_anomaly_warning_unique_source_urls"] == 1
    assert summary["station_anomaly_warning_max_delta"] == 12.5
    assert summary["station_anomaly_not_checked_rows"] == 1
    assert summary["station_anomaly_missing_observation_rows"] == 1
    assert summary["station_anomaly_missing_neighbors_rows"] == 0

    loaded = load_latest_polymarket_weather_source_state_rows_from_sqlite(db_path, limit=10)
    warning_row = next(row for row in loaded if row["condition_id"] == "0xseoul-warn")
    assert warning_row["station_anomaly_status"] == "warning"
    assert warning_row["station_anomaly_neighbor_count"] == 2
    assert warning_row["station_anomaly_max_delta"] == 12.5
    assert warning_row["station_anomaly_neighbor_values"] == [29.5, 30.0]


def test_nws_cli_source_diagnostics_surface_pagination_and_final_found_flags(): 
    diagnostics = summarize_nws_cli_source_diagnostics(
        {
            "KNYC": {
                "product_scan_limit": 24,
                "target_dates": ["2026-05-27", "2026-05-28"],
                "parsed_reports": [
                    {
                        "product_id": "prelim",
                        "is_final": False,
                        "preliminary_reason": "preliminary valid-today product",
                    },
                    {
                        "product_id": "prior-final",
                        "is_final": True,
                        "preliminary_reason": None,
                    },
                ],
                "final_by_date": {
                    "2026-05-27": {"product_id": "prior-final"},
                    "2026-05-28": None,
                },
            }
        }
    )

    assert diagnostics == {
        "KNYC": {
            "products_fetched": 2,
            "product_scan_limit": 24,
            "target_dates": ["2026-05-27", "2026-05-28"],
            "final_found_by_date": {"2026-05-27": True, "2026-05-28": False},
            "all_targets_final_found": False,
            "missing_final_target_dates": ["2026-05-28"],
            "rejected_preliminary_count": 1,
            "rejected_non_final_count": 1,
            "latest_final_product_id_by_date": {"2026-05-27": "prior-final", "2026-05-28": None},
        }
    }


def test_weather_paper_account_tracks_separate_1000_to_1100_ledger_with_realized_pnl_only():
    summary = summarize_weather_paper_account(
        [
            trade(pnl=18.75, settled=True, result="win", size=50.0, platform="kalshi"),
            trade(pnl=-8.75, settled=True, result="loss", size=40.0, platform="polymarket"),
            trade(pnl=None, settled=False, result="pending", size=75.0, platform="polymarket"),
        ]
    )

    assert summary["initial_bankroll"] == 1000.0
    assert summary["target_bankroll"] == 1100.0
    assert summary["realized_pnl"] == 10.0
    assert summary["current_equity"] == 1010.0
    assert summary["remaining_to_target"] == 90.0
    assert summary["progress_to_target_pct"] == 10.0
    assert summary["total_trades"] == 3
    assert summary["settled_trades"] == 2
    assert summary["pending_trades"] == 1
    assert summary["pending_size"] == 75.0
    assert summary["winning_trades"] == 1
    assert summary["win_rate"] == 50.0
    assert summary["ledger_exposure_state"] == "open_positions"
    assert "1 open/pending" in str(summary["ledger_status_note"])
    assert "$75.00 pending size" in str(summary["ledger_status_note"])
    assert summary["platform_breakdown"] == [
        {
            "platform": "kalshi",
            "total_trades": 1,
            "settled_trades": 1,
            "pending_trades": 0,
            "pending_size": 0.0,
            "winning_trades": 1,
            "realized_pnl": 18.75,
        },
        {
            "platform": "polymarket",
            "total_trades": 2,
            "settled_trades": 1,
            "pending_trades": 1,
            "pending_size": 75.0,
            "winning_trades": 0,
            "realized_pnl": -8.75,
        },
    ]
    assert summary["paper_only"] is True
    assert summary["selective_no_forced_trade"] is True
    assert summary["market_scope"] == "weather"


def test_weather_paper_account_exposure_state_distinguishes_all_settled_from_no_trades():
    all_settled = summarize_weather_paper_account([
        trade(pnl=-25.0, settled=True, result="loss", size=50.0),
        trade(pnl=10.0, settled=True, result="win", size=25.0),
    ])
    no_trades = summarize_weather_paper_account([])

    assert all_settled["pending_size"] == 0.0
    assert all_settled["ledger_exposure_state"] == "all_settled"
    assert all_settled["ledger_status_note"] == "All 2 weather paper trades are settled; current equity is settled realized PnL only."
    assert no_trades["pending_size"] == 0.0
    assert no_trades["ledger_exposure_state"] == "no_trades"
    assert "No weather paper trades" in str(no_trades["ledger_status_note"])


def test_weather_paper_account_progress_is_bounded_for_no_forced_trade_reporting():
    above_target = summarize_weather_paper_account([trade(pnl=150.0, settled=True, result="win")])
    below_start = summarize_weather_paper_account([trade(pnl=-50.0, settled=True, result="loss")])

    assert above_target["current_equity"] == 1150.0
    assert above_target["remaining_to_target"] == 0.0
    assert above_target["progress_to_target_pct"] == 100.0
    assert below_start["current_equity"] == 950.0
    assert below_start["remaining_to_target"] == 150.0
    assert below_start["progress_to_target_pct"] == 0.0


def test_blocked_weather_signal_still_persists_for_model_calibration_visibility():
    signal = SimpleNamespace(
        model_probability=0.72,
        market_probability=0.55,
        edge=0.0,
        suggested_size=0.0,
        no_trade_reasons=["missing settlement source/station"],
    )

    assert should_persist_weather_signal_for_calibration(signal) is True

    missing_model_probability = SimpleNamespace(model_probability=None, market_probability=0.55)
    assert should_persist_weather_signal_for_calibration(missing_model_probability) is False


def test_threshold_passing_weather_review_candidates_are_forced_non_actionable(tmp_path):
    market = SimpleNamespace(
        platform="kalshi",
        market_id="KXHIGHLAX-26JUN01-T75",
        title="Will the high in Los Angeles be 76° or above on Jun 1?",
        city_key="los_angeles",
        city_name="Los Angeles",
        target_date="2026-06-01",
        metric="high",
        direction="above",
        threshold_f=75.0,
        best_bid=0.72,
        best_ask=0.75,
        top_ask_size=111.0,
        volume=2500,
        settlement_source="NWS CLI",
        settlement_station="KLAX",
        settlement_source_url="https://api.weather.gov/products/types/CLI/locations/LAX",
    )
    signal = SimpleNamespace(
        market=market,
        model_probability=0.95,
        market_probability=0.75,
        edge=0.20,
        direction="yes",
        confidence=0.88,
        suggested_size=25.0,
        no_trade_reasons=[],
        execution_spread=0.03,
        top_ask_size=111.0,
        composite_score=0.81,
        score_components={"spread_quality": 0.85},
        sources=["open_meteo_ensemble_31m", "settlement:NWS CLI:KLAX"],
        reasoning="[ACTIONABLE] threshold-passing review candidate",
    )

    rows = build_weather_signal_review_candidate_rows([signal], captured_at="20260601T010000Z")

    assert rows == [
        {
            "captured_at": "20260601T010000Z",
            "venue": "kalshi",
            "market_key": "KXHIGHLAX-26JUN01-T75",
            "title": "Will the high in Los Angeles be 76° or above on Jun 1?",
            "city": "los_angeles",
            "target_date": "2026-06-01",
            "metric": "high",
            "direction": "yes",
            "threshold_f": 75.0,
            "model_probability": 0.95,
            "market_probability": 0.75,
            "edge": 0.20,
            "confidence": 0.88,
            "suggested_size": 0.0,
            "best_bid": 0.72,
            "best_ask": 0.75,
            "execution_spread": 0.03,
            "top_ask_size": 111.0,
            "settlement_source": "NWS CLI",
            "settlement_station": "KLAX",
            "settlement_source_url": "https://api.weather.gov/products/types/CLI/locations/LAX",
            "no_trade_reasons": ["review-only candidate; not paper-actionable until independently revalidated"],
            "source_snapshot": None,
            "paper_actionable": False,
            "executed": False,
            "notes": "[ACTIONABLE] threshold-passing review candidate",
        }
    ]

    db_path = tmp_path / "review.sqlite"
    with sqlite3.connect(db_path) as conn:
        assert persist_weather_signal_review_candidate_rows_to_sqlite(conn, rows) == 1
        assert persist_weather_signal_review_candidate_rows_to_sqlite(conn, rows) == 0
        stored = conn.execute(
            "SELECT paper_actionable, executed, suggested_size, no_trade_reasons FROM weather_signal_review_candidates"
        ).fetchone()

    assert stored[0] == 0
    assert stored[1] == 0
    assert stored[2] == 0.0
    assert "review-only candidate" in stored[3]


def test_latest_weather_signal_review_candidate_rows_load_latest_batch_read_only(tmp_path):
    db_path = tmp_path / "review.sqlite"
    base_row = {
        "captured_at": "20260601T000000Z",
        "venue": "kalshi",
        "market_key": "KXHIGHCHI-26JUN01-T70",
        "title": "Chicago high temp 70F or below",
        "city": "chi",
        "target_date": "2026-06-01",
        "metric": "high_temp",
        "direction": "below",
        "threshold_f": 70.0,
        "model_probability": 0.55,
        "market_probability": 0.51,
        "edge": 0.04,
        "confidence": 0.5,
        "suggested_size": 999.0,
        "best_bid": 0.49,
        "best_ask": 0.51,
        "execution_spread": 0.02,
        "top_ask_size": 10.0,
        "settlement_source": "NWS CLI",
        "settlement_station": "KMDW",
        "settlement_source_url": "https://api.weather.gov/products/types/CLI/locations/MDW",
        "no_trade_reasons": ["old row"],
        "source_snapshot": "/tmp/old.json",
        "paper_actionable": True,
        "executed": True,
        "notes": "old candidate",
    }
    latest_small_edge = {
        **base_row,
        "captured_at": "20260601T010923Z",
        "market_key": "KXHIGHCHI-26JUN01-T71",
        "edge": 0.07,
        "no_trade_reasons": ["small edge"],
    }
    latest_big_edge = {
        **base_row,
        "captured_at": "20260601T010923Z",
        "market_key": "KXHIGHCHI-26JUN01-T72",
        "edge": 0.63,
        "no_trade_reasons": ["review-only candidate; not paper-actionable until independently revalidated"],
    }

    with sqlite3.connect(db_path) as conn:
        assert persist_weather_signal_review_candidate_rows_to_sqlite(conn, [base_row, latest_small_edge, latest_big_edge]) == 3
        conn.execute("UPDATE weather_signal_review_candidates SET paper_actionable=1, executed=1, suggested_size=25 WHERE market_key='KXHIGHCHI-26JUN01-T72'")
        conn.commit()

    rows = load_latest_weather_signal_review_candidate_rows_from_sqlite(db_path, limit=1)

    assert len(rows) == 1
    assert rows[0]["captured_at"] == "20260601T010923Z"
    assert rows[0]["market_key"] == "KXHIGHCHI-26JUN01-T72"
    assert rows[0]["edge"] == 0.63
    assert rows[0]["paper_actionable"] is False
    assert rows[0]["executed"] is False
    assert rows[0]["suggested_size"] == 0.0
    assert rows[0]["no_trade_reasons"] == ["review-only candidate; not paper-actionable until independently revalidated"]

    missing_path = tmp_path / "missing.sqlite"
    assert load_latest_weather_signal_review_candidate_rows_from_sqlite(missing_path) == []
    assert not missing_path.exists()


def test_resolve_kalshi_high_temp_outcome_handles_thresholds_and_buckets():
    assert resolve_kalshi_high_temp_outcome("85° or above", 85) is True
    assert resolve_kalshi_high_temp_outcome("85° or above", 84) is False
    assert resolve_kalshi_high_temp_outcome("76° or below", 76) is True
    assert resolve_kalshi_high_temp_outcome("83° to 84°", 84) is True
    assert resolve_kalshi_high_temp_outcome("83° to 84°", 85) is False
    assert resolve_kalshi_high_temp_outcome("Yes", 84) is None


def test_join_kalshi_weather_quotes_to_outcomes_scores_only_parseable_final_rows():
    quotes = [
        {
            "ts": "20260525T150130Z",
            "venue": "kalshi",
            "market_key": "KXHIGHNY-26MAY26-T77",
            "outcome": "76° or below",
            "probability": 0.07,
        },
        {
            "ts": "20260525T150130Z",
            "venue": "kalshi",
            "market_key": "KXHIGHNY-26MAY26-B79.5",
            "outcome": "79° to 80°",
            "probability": 0.42,
        },
        {
            "ts": "20260525T150130Z",
            "venue": "polymarket",
            "market_key": "ignored",
            "outcome": "Yes",
            "probability": 0.5,
        },
    ]
    resolutions = [
        {
            "venue": "kalshi",
            "market_key": "KXHIGHNY:KNYC:2026-05-26:high",
            "resolved_value": "79",
            "source_url": "https://api.weather.gov/products/example",
            "notes": '{"series":"KXHIGHNY","report_date":"2026-05-26"}',
        }
    ]

    forecasts = join_kalshi_weather_quotes_to_outcomes(quotes, resolutions)
    summary = summarize_weather_paper_account([], settled_forecasts=forecasts)

    assert [row.resolved_yes for row in forecasts] == [0.0, 1.0]
    assert forecasts[0].resolved_value == 79.0
    assert forecasts[0].source_url == "https://api.weather.gov/products/example"
    assert summary["total_trades"] == 0
    assert summary["current_equity"] == 1000.0
    assert summary["settled_forecasts"] == 2
    assert summary["brier_score"] == 0.1707
    assert summary["log_loss"] == 0.47


def test_summarize_latest_weather_calibration_rows_uses_latest_scored_at_without_touching_paper_trades():
    rows = [
        {
            "scored_at": "20260527T150102Z",
            "quote_ts": "20260525T150130Z",
            "venue": "kalshi",
            "market_key": "KXHIGHNY-26MAY26-T77",
            "outcome": "76° or below",
            "market_probability": 0.07,
            "resolved_yes": 0.0,
            "resolved_value": 79.0,
            "brier_score": 0.0049,
            "log_loss": 0.072571,
            "source_url": "https://api.weather.gov/products/old",
            "source_snapshot": "/tmp/old-weather-raw.json",
            "paper_actionable": False,
            "notes": "old calibration run",
        },
        {
            "scored_at": "20260528T011314Z",
            "quote_ts": "20260527T150102Z",
            "venue": "kalshi",
            "market_key": "KXHIGHNY-26MAY28-T75",
            "outcome": "75° or below",
            "market_probability": 0.61,
            "resolved_yes": 1.0,
            "resolved_value": 75.0,
            "brier_score": 0.1521,
            "log_loss": 0.494296,
            "source_url": "https://api.weather.gov/products/latest-a",
            "source_snapshot": "/tmp/latest-weather-raw.json",
            "paper_actionable": False,
            "notes": "calibration-only market-implied quote score; not a paper trade or bot edge",
        },
        {
            "scored_at": "20260528T011314Z",
            "quote_ts": "20260527T150102Z",
            "venue": "kalshi",
            "market_key": "KXHIGHNY-26MAY28-B78.5",
            "outcome": "78° to 79°",
            "market_probability": 0.12,
            "resolved_yes": 0.0,
            "resolved_value": 75.0,
            "brier_score": 0.0144,
            "log_loss": 0.127833,
            "source_url": "https://api.weather.gov/products/latest-b",
            "source_snapshot": "/tmp/latest-weather-raw.json",
            "paper_actionable": False,
            "notes": "calibration-only market-implied quote score; not a paper trade or bot edge",
        },
    ]

    summary = summarize_latest_weather_calibration_rows(rows)

    assert summary == {
        "latest_scored_at": "20260528T011314Z",
        "settled_forecasts": 2,
        "brier_score": 0.0833,
        "log_loss": 0.3111,
        "paper_actionable": False,
        "market_scope": "weather",
        "calibration_kind": "market_implied_quote_score",
        "source_snapshot": "/tmp/latest-weather-raw.json",
    }
    account = summarize_weather_paper_account([], settled_forecasts=[])
    assert account["current_equity"] == 1000.0
    assert account["total_trades"] == 0


def test_load_latest_weather_calibration_summary_from_sqlite_uses_latest_batch_and_tolerates_missing_tables(tmp_path):
    missing_path = tmp_path / "missing.sqlite"
    assert load_latest_weather_calibration_summary_from_sqlite(missing_path) is None
    assert not missing_path.exists()

    empty_db = tmp_path / "empty.sqlite"
    sqlite3.connect(empty_db).close()
    assert load_latest_weather_calibration_summary_from_sqlite(empty_db) is None

    db_path = tmp_path / "weather.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE weather_forecast_calibrations (
                scored_at TEXT,
                quote_ts TEXT,
                venue TEXT,
                market_key TEXT,
                outcome TEXT,
                market_probability REAL,
                resolved_yes REAL,
                resolved_value REAL,
                brier_score REAL,
                log_loss REAL,
                source_url TEXT,
                source_snapshot TEXT,
                paper_actionable INTEGER,
                notes TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO weather_forecast_calibrations (
                scored_at, quote_ts, venue, market_key, outcome,
                market_probability, resolved_yes, resolved_value,
                brier_score, log_loss, source_url, source_snapshot,
                paper_actionable, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "20260527T150102Z",
                    "20260525T150130Z",
                    "kalshi",
                    "KXHIGHNY-26MAY26-T77",
                    "76° or below",
                    0.07,
                    0.0,
                    79.0,
                    0.0049,
                    0.072571,
                    "https://api.weather.gov/products/old",
                    "/tmp/old-weather-raw.json",
                    0,
                    "old batch",
                ),
                (
                    "20260528T011314Z",
                    "20260527T150102Z",
                    "kalshi",
                    "KXHIGHNY-26MAY28-T75",
                    "75° or below",
                    0.61,
                    1.0,
                    75.0,
                    0.1521,
                    0.494296,
                    "https://api.weather.gov/products/latest-a",
                    "/tmp/latest-weather-raw.json",
                    0,
                    "latest batch",
                ),
                (
                    "20260528T011314Z",
                    "20260527T150102Z",
                    "kalshi",
                    "KXHIGHNY-26MAY28-B78.5",
                    "78° to 79°",
                    0.12,
                    0.0,
                    75.0,
                    0.0144,
                    0.127833,
                    "https://api.weather.gov/products/latest-b",
                    "/tmp/latest-weather-raw.json",
                    0,
                    "latest batch",
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    summary = load_latest_weather_calibration_summary_from_sqlite(db_path)

    assert summary == {
        "latest_scored_at": "20260528T011314Z",
        "settled_forecasts": 2,
        "brier_score": 0.0833,
        "log_loss": 0.3111,
        "paper_actionable": False,
        "market_scope": "weather",
        "calibration_kind": "market_implied_quote_score",
        "source_snapshot": "/tmp/latest-weather-raw.json",
    }


def test_load_latest_weather_calibration_rows_from_sqlite_returns_latest_batch_audit_rows(tmp_path):
    missing_path = tmp_path / "missing.sqlite"
    assert load_latest_weather_calibration_rows_from_sqlite(missing_path) == []
    assert not missing_path.exists()

    db_path = tmp_path / "weather-calibration.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE weather_forecast_calibrations (
                scored_at TEXT,
                quote_ts TEXT,
                venue TEXT,
                market_key TEXT,
                outcome TEXT,
                market_probability REAL,
                resolved_yes REAL,
                resolved_value REAL,
                brier_score REAL,
                log_loss REAL,
                source_url TEXT,
                source_snapshot TEXT,
                paper_actionable INTEGER,
                notes TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO weather_forecast_calibrations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("20260527T150102Z", "20260527T010000Z", "kalshi", "KXHIGHNY-old", "80° or above", 0.8, 1.0, 81.0, 0.04, 0.223, "old-url", "old-snapshot", 0, "old batch"),
                ("20260528T011314Z", "20260528T010000Z", "kalshi", "KXHIGHNY-new-low-error", "80° or above", 0.9, 1.0, 81.0, 0.01, 0.105, "new-url-1", "new-snapshot", 0, "latest batch"),
                ("20260528T011314Z", "20260528T010500Z", "kalshi", "KXHIGHNY-new-high-error", "85° or above", 0.95, 0.0, 81.0, 0.9025, 2.996, "new-url-2", "new-snapshot", 0, "latest batch"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    rows = load_latest_weather_calibration_rows_from_sqlite(db_path, limit=1)

    assert rows == [
        {
            "scored_at": "20260528T011314Z",
            "quote_ts": "20260528T010500Z",
            "venue": "kalshi",
            "market_key": "KXHIGHNY-new-high-error",
            "outcome": "85° or above",
            "market_probability": 0.95,
            "resolved_yes": 0.0,
            "resolved_value": 81.0,
            "brier_score": 0.9025,
            "log_loss": 2.996,
            "source_url": "new-url-2",
            "source_snapshot": "new-snapshot",
            "paper_actionable": False,
            "notes": "latest batch",
        }
    ]


def test_build_weather_calibration_rows_adds_score_fields_for_persistence_without_trade_side_effects():
    forecasts = [
        SimpleNamespace(
            ts="20260525T150130Z",
            market_key="KXHIGHNY-26MAY26-T77",
            outcome="76° or below",
            market_probability=0.07,
            resolved_yes=0.0,
            resolved_value=79.0,
            source_url="https://api.weather.gov/products/example",
        ),
        SimpleNamespace(
            ts="20260525T150130Z",
            market_key="KXHIGHNY-26MAY26-B79.5",
            outcome="79° to 80°",
            market_probability=0.42,
            resolved_yes=1.0,
            resolved_value=79.0,
            source_url="https://api.weather.gov/products/example",
        ),
    ]

    rows = build_weather_calibration_rows(forecasts, source_snapshot="/tmp/weather-raw.json")

    assert rows == [
        {
            "ts": "20260525T150130Z",
            "venue": "kalshi",
            "market_key": "KXHIGHNY-26MAY26-T77",
            "outcome": "76° or below",
            "market_probability": 0.07,
            "resolved_yes": 0.0,
            "resolved_value": 79.0,
            "brier_score": 0.0049,
            "log_loss": 0.072571,
            "source_url": "https://api.weather.gov/products/example",
            "source_snapshot": "/tmp/weather-raw.json",
            "paper_actionable": False,
            "notes": "calibration-only market-implied quote score; not a paper trade or bot edge",
        },
        {
            "ts": "20260525T150130Z",
            "venue": "kalshi",
            "market_key": "KXHIGHNY-26MAY26-B79.5",
            "outcome": "79° to 80°",
            "market_probability": 0.42,
            "resolved_yes": 1.0,
            "resolved_value": 79.0,
            "brier_score": 0.3364,
            "log_loss": 0.867501,
            "source_url": "https://api.weather.gov/products/example",
            "source_snapshot": "/tmp/weather-raw.json",
            "paper_actionable": False,
            "notes": "calibration-only market-implied quote score; not a paper trade or bot edge",
        },
    ]


def test_persist_bot_weather_signal_calibration_rows_to_sqlite_is_append_only_and_non_actionable(tmp_path):
    db_path = tmp_path / "research.sqlite"
    conn = sqlite3.connect(db_path)
    rows = [
        {
            "scored_at": "20260531T010000Z",
            "signal_id": 10,
            "signal_ts": "2026-05-30 18:04:00",
            "venue": "kalshi",
            "market_key": "KXHIGHCHI-26MAY31-T74",
            "outcome": "74° or below",
            "model_probability": 0.78,
            "market_probability": 0.62,
            "resolved_yes": 1.0,
            "resolved_value": 73.0,
            "brier_score": 0.0484,
            "log_loss": 0.248461,
            "source_url": "https://api.weather.gov/products/chicago-final",
            "source_snapshot": "/tmp/weather-raw.json",
            "paper_actionable": True,
            "executed": True,
            "calibration_kind": "bot_model_signal_score",
            "notes": "candidate row must be persisted as calibration-only",
        }
    ]
    try:
        inserted_once = persist_bot_weather_signal_calibration_rows_to_sqlite(conn, rows)
        inserted_twice = persist_bot_weather_signal_calibration_rows_to_sqlite(conn, rows)
        stored = conn.execute(
            """
            SELECT scored_at, signal_id, market_key, model_probability,
                   market_probability, paper_actionable, executed,
                   calibration_kind, notes
            FROM weather_bot_signal_calibrations
            """
        ).fetchall()
    finally:
        conn.close()

    assert inserted_once == 1
    assert inserted_twice == 0
    assert stored == [
        (
            "20260531T010000Z",
            10,
            "KXHIGHCHI-26MAY31-T74",
            0.78,
            0.62,
            0,
            0,
            "bot_model_signal_score",
            "candidate row must be persisted as calibration-only",
        )
    ]


def test_load_latest_weather_bot_signal_calibration_summary_from_sqlite_uses_latest_batch_and_is_read_only(tmp_path):
    missing_path = tmp_path / "missing-bot-calibration.sqlite"
    assert load_latest_weather_bot_signal_calibration_summary_from_sqlite(missing_path) is None
    assert not missing_path.exists()

    empty_db = tmp_path / "empty.sqlite"
    sqlite3.connect(empty_db).close()
    assert load_latest_weather_bot_signal_calibration_summary_from_sqlite(empty_db) is None

    db_path = tmp_path / "weather-bot-calibration.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        rows = [
            {
                "scored_at": "20260531T000000Z",
                "signal_id": 1,
                "signal_ts": "2026-05-30 17:00:00",
                "venue": "kalshi",
                "market_key": "KXHIGHCHI-26MAY30-T74",
                "outcome": "74° or below",
                "model_probability": 0.75,
                "market_probability": 0.55,
                "resolved_yes": 1.0,
                "resolved_value": 73.0,
                "brier_score": 0.0625,
                "log_loss": 0.287682,
                "source_url": "https://api.weather.gov/products/old",
                "source_snapshot": "/tmp/old-weather-raw.json",
                "paper_actionable": True,
                "executed": True,
                "calibration_kind": "bot_model_signal_score",
                "notes": "old bot batch",
            },
            {
                "scored_at": "20260531T010247Z",
                "signal_id": 2,
                "signal_ts": "2026-05-30 18:00:00",
                "venue": "kalshi",
                "market_key": "KXHIGHCHI-26MAY31-T74",
                "outcome": "74° or below",
                "model_probability": 0.80,
                "market_probability": 0.60,
                "resolved_yes": 1.0,
                "resolved_value": 73.0,
                "brier_score": 0.04,
                "log_loss": 0.223144,
                "source_url": "https://api.weather.gov/products/latest-a",
                "source_snapshot": "/tmp/latest-weather-raw.json",
                "paper_actionable": True,
                "executed": True,
                "calibration_kind": "bot_model_signal_score",
                "notes": "latest bot batch a",
            },
            {
                "scored_at": "20260531T010247Z",
                "signal_id": 3,
                "signal_ts": "2026-05-30 18:01:00",
                "venue": "kalshi",
                "market_key": "KXHIGHCHI-26MAY31-T76",
                "outcome": "76° or above",
                "model_probability": 0.20,
                "market_probability": 0.40,
                "resolved_yes": 0.0,
                "resolved_value": 73.0,
                "brier_score": 0.04,
                "log_loss": 0.223144,
                "source_url": "https://api.weather.gov/products/latest-b",
                "source_snapshot": "/tmp/latest-weather-raw.json",
                "paper_actionable": True,
                "executed": True,
                "calibration_kind": "bot_model_signal_score",
                "notes": "latest bot batch b",
            },
        ]
        persist_bot_weather_signal_calibration_rows_to_sqlite(conn, rows)
        conn.commit()
    finally:
        conn.close()

    summary = load_latest_weather_bot_signal_calibration_summary_from_sqlite(db_path)

    assert summary == {
        "latest_scored_at": "20260531T010247Z",
        "settled_forecasts": 2,
        "brier_score": 0.04,
        "log_loss": 0.2231,
        "paper_actionable": False,
        "market_scope": "weather",
        "calibration_kind": "bot_model_signal_score",
        "source_snapshot": "/tmp/latest-weather-raw.json",
    }


def test_load_latest_weather_bot_signal_calibration_rows_from_sqlite_returns_highest_error_latest_batch(tmp_path):
    missing_path = tmp_path / "missing-bot-calibration-rows.sqlite"
    assert load_latest_weather_bot_signal_calibration_rows_from_sqlite(missing_path) == []
    assert not missing_path.exists()

    db_path = tmp_path / "weather-bot-calibration-rows.sqlite"
    conn = sqlite3.connect(db_path)
    rows = [
        {
            "scored_at": "20260531T000000Z",
            "signal_id": 1,
            "signal_ts": "2026-05-30 17:00:00",
            "venue": "kalshi",
            "market_key": "KXHIGHCHI-26MAY30-T74",
            "outcome": "74° or below",
            "model_probability": 0.75,
            "market_probability": 0.55,
            "resolved_yes": 1.0,
            "resolved_value": 73.0,
            "brier_score": 0.0625,
            "log_loss": 0.287682,
            "source_url": "https://api.weather.gov/products/old",
            "source_snapshot": "/tmp/old-weather-raw.json",
            "paper_actionable": True,
            "executed": True,
            "calibration_kind": "bot_model_signal_score",
            "notes": "old bot batch",
        },
        {
            "scored_at": "20260531T010247Z",
            "signal_id": 2,
            "signal_ts": "2026-05-30 18:00:00",
            "venue": "kalshi",
            "market_key": "KXHIGHCHI-26MAY31-T74",
            "outcome": "74° or below",
            "model_probability": 0.80,
            "market_probability": 0.60,
            "resolved_yes": 1.0,
            "resolved_value": 73.0,
            "brier_score": 0.04,
            "log_loss": 0.223144,
            "source_url": "https://api.weather.gov/products/latest-a",
            "source_snapshot": "/tmp/latest-weather-raw.json",
            "paper_actionable": True,
            "executed": True,
            "calibration_kind": "bot_model_signal_score",
            "notes": "latest bot batch low error",
        },
        {
            "scored_at": "20260531T010247Z",
            "signal_id": 3,
            "signal_ts": "2026-05-30 18:01:00",
            "venue": "kalshi",
            "market_key": "KXHIGHCHI-26MAY31-T76",
            "outcome": "76° or above",
            "model_probability": 0.95,
            "market_probability": 0.40,
            "resolved_yes": 0.0,
            "resolved_value": 73.0,
            "brier_score": 0.9025,
            "log_loss": 2.995732,
            "source_url": "https://api.weather.gov/products/latest-b",
            "source_snapshot": "/tmp/latest-weather-raw.json",
            "paper_actionable": True,
            "executed": True,
            "calibration_kind": "bot_model_signal_score",
            "notes": "latest bot batch high error",
        },
    ]
    try:
        persist_bot_weather_signal_calibration_rows_to_sqlite(conn, rows)
        conn.commit()
    finally:
        conn.close()

    latest_rows = load_latest_weather_bot_signal_calibration_rows_from_sqlite(db_path, limit=1)

    assert latest_rows == [
        {
            "scored_at": "20260531T010247Z",
            "signal_id": 3,
            "signal_ts": "2026-05-30 18:01:00",
            "venue": "kalshi",
            "market_key": "KXHIGHCHI-26MAY31-T76",
            "outcome": "76° or above",
            "model_probability": 0.95,
            "market_probability": 0.40,
            "resolved_yes": 0.0,
            "resolved_value": 73.0,
            "brier_score": 0.9025,
            "log_loss": 2.995732,
            "source_url": "https://api.weather.gov/products/latest-b",
            "source_snapshot": "/tmp/latest-weather-raw.json",
            "paper_actionable": False,
            "executed": False,
            "calibration_kind": "bot_model_signal_score",
            "notes": "latest bot batch high error",
        }
    ]


def test_build_bot_weather_signal_calibration_rows_scores_model_probability_separately_from_market_implied_rows():
    signals = [
        {
            "id": 1,
            "timestamp": "2026-05-29 15:09:58",
            "platform": "kalshi",
            "market_type": "weather",
            "market_ticker": "KXHIGHDEN-26MAY29-B79.5",
            "direction": "no",
            "model_probability": 0.16,
            "market_price": 0.34,
            "edge": 0.0,
            "suggested_size": 0.0,
            "executed": 0,
            "sources": '["open_meteo_ensemble_31m", "settlement:nws_cli:KDEN"]',
            "reasoning": "[FILTERED] Denver high bucket 80F on 2026-05-29 | Ensemble: 79.8F +/- 2.1F",
        },
        {
            "id": 2,
            "timestamp": "2026-05-29 15:09:59",
            "platform": "kalshi",
            "market_type": "weather",
            "market_ticker": "KXHIGHDEN-26MAY29-T79",
            "direction": "no",
            "model_probability": 0.23,
            "market_price": 0.29,
            "edge": 0.0,
            "suggested_size": 0.0,
            "executed": 0,
            "sources": '["open_meteo_ensemble_31m", "settlement:nws_cli:KDEN"]',
            "reasoning": "[FILTERED] Denver high below 79F on 2026-05-29 | Ensemble: 79.8F +/- 2.1F",
        },
    ]
    resolutions = [
        {
            "venue": "kalshi",
            "market_key": "KXHIGHDEN:KDEN:2026-05-29:high",
            "resolved_value": "64",
            "source_url": "https://api.weather.gov/products/denver-final",
            "source_snapshot": "/tmp/weather-raw.json",
            "notes": '{"series":"KXHIGHDEN","report_date":"2026-05-29"}',
        }
    ]

    rows = build_bot_weather_signal_calibration_rows(
        signals,
        resolutions,
        scored_at="20260530T010142Z",
        source_snapshot="/tmp/weather-public-raw.json",
    )

    assert rows == [
        {
            "scored_at": "20260530T010142Z",
            "signal_id": 1,
            "signal_ts": "2026-05-29 15:09:58",
            "venue": "kalshi",
            "market_key": "KXHIGHDEN-26MAY29-B79.5",
            "outcome": "79° to 80°",
            "model_probability": 0.16,
            "market_probability": 0.34,
            "resolved_yes": 0.0,
            "resolved_value": 64.0,
            "brier_score": 0.0256,
            "log_loss": 0.174353,
            "source_url": "https://api.weather.gov/products/denver-final",
            "source_snapshot": "/tmp/weather-public-raw.json",
            "paper_actionable": False,
            "executed": False,
            "calibration_kind": "bot_model_signal_score",
            "notes": "bot-model weather signal calibration-only; not a paper trade or execution signal",
        },
        {
            "scored_at": "20260530T010142Z",
            "signal_id": 2,
            "signal_ts": "2026-05-29 15:09:59",
            "venue": "kalshi",
            "market_key": "KXHIGHDEN-26MAY29-T79",
            "outcome": "79° or below",
            "model_probability": 0.23,
            "market_probability": 0.29,
            "resolved_yes": 1.0,
            "resolved_value": 64.0,
            "brier_score": 0.5929,
            "log_loss": 1.469676,
            "source_url": "https://api.weather.gov/products/denver-final",
            "source_snapshot": "/tmp/weather-public-raw.json",
            "paper_actionable": False,
            "executed": False,
            "calibration_kind": "bot_model_signal_score",
            "notes": "bot-model weather signal calibration-only; not a paper trade or execution signal",
        },
    ]


def test_build_bot_weather_signal_calibration_rows_prefers_explicit_kalshi_outcome_text_from_sources():
    signals = [
        SimpleNamespace(
            id=8,
            market_ticker="KXHIGHDEN-26MAY29-T79",
            platform="kalshi",
            market_type="weather",
            timestamp="2026-05-29 15:09:59",
            direction="yes",
            model_probability=0.23,
            market_price=0.29,
            reasoning="[FILTERED] Denver high below 79F reconstructed text would be wrong",
            sources=[
                "open_meteo_ensemble_31m",
                "kalshi_outcome_text:79° or above",
                "settlement:nws_cli:KDEN",
            ],
            executed=False,
        )
    ]
    resolutions = [
        {
            "venue": "kalshi",
            "market_key": "KXHIGHDEN:KDEN:2026-05-29:high",
            "resolved_value": "64",
            "source_url": "https://api.weather.gov/products/denver-final",
            "notes": '{"series":"KXHIGHDEN","report_date":"2026-05-29"}',
        }
    ]

    rows = build_bot_weather_signal_calibration_rows(
        signals,
        resolutions,
        scored_at="20260530T030000Z",
        source_snapshot="/tmp/weather-raw.json",
    )

    assert len(rows) == 1
    assert rows[0]["outcome"] == "79° or above"
    assert rows[0]["resolved_yes"] == 0.0
    assert rows[0]["brier_score"] == 0.0529
    assert rows[0]["paper_actionable"] is False


def test_load_bot_weather_signal_calibration_rows_from_sqlite_joins_app_signals_to_research_outcomes(tmp_path):
    app_db = tmp_path / "app.sqlite"
    research_db = tmp_path / "research.sqlite"
    conn = sqlite3.connect(app_db)
    try:
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
                suggested_size REAL,
                sources TEXT,
                reasoning TEXT,
                executed INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO signals VALUES (
                7, 'KXHIGHDEN-26MAY29-B79.5', 'kalshi', 'weather',
                '2026-05-29 15:09:58', 'no', 0.16, 0.34, 0.0, 0.0,
                '["open_meteo_ensemble_31m", "settlement:nws_cli:KDEN"]',
                '[FILTERED] Denver high bucket 80F on 2026-05-29', 0
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    conn = sqlite3.connect(research_db)
    try:
        conn.execute(
            """
            CREATE TABLE outcome_resolutions (
                id INTEGER PRIMARY KEY,
                ts TEXT,
                venue TEXT,
                market_key TEXT,
                outcome TEXT,
                resolved_value REAL,
                source TEXT,
                source_snapshot TEXT,
                notes TEXT,
                resolved_yes REAL,
                source_url TEXT,
                source_ts TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO outcome_resolutions (
                ts, venue, market_key, outcome, resolved_value, source,
                source_snapshot, notes, resolved_yes, source_url, source_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "20260530T010142Z", "kalshi", "KXHIGHDEN:KDEN:2026-05-29:high",
                "high", 64.0, "nws_cli", "/tmp/weather-raw.json",
                '{"series":"KXHIGHDEN","report_date":"2026-05-29"}', None,
                "https://api.weather.gov/products/denver-final", "2026-05-29T12:32:00Z"
            ),
        )
        conn.commit()
    finally:
        conn.close()

    rows = load_bot_weather_signal_calibration_rows_from_sqlite(
        app_db,
        research_db,
        scored_at="20260530T010142Z",
    )

    assert len(rows) == 1
    assert rows[0]["calibration_kind"] == "bot_model_signal_score"
    assert rows[0]["signal_id"] == 7
    assert rows[0]["resolved_yes"] == 0.0
    assert rows[0]["paper_actionable"] is False
