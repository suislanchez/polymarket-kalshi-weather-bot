from types import SimpleNamespace

from backend.core.btc_paper_account import (
    load_latest_btc_calibration_rows_from_sqlite,
    load_latest_btc_calibration_summary_from_sqlite,
    summarize_btc_paper_account,
    summarize_latest_btc_calibration_rows,
)


def trade(pnl=None, settled=False, result="pending"):
    return SimpleNamespace(pnl=pnl, settled=settled, result=result, market_type="btc")


def test_btc_paper_account_tracks_1000_to_1100_target_with_realized_pnl_only():
    summary = summarize_btc_paper_account(
        [
            trade(pnl=42.5, settled=True, result="win"),
            trade(pnl=-12.5, settled=True, result="loss"),
            trade(pnl=None, settled=False, result="pending"),
        ]
    )

    assert summary["initial_bankroll"] == 1000.0
    assert summary["target_bankroll"] == 1100.0
    assert summary["realized_pnl"] == 30.0
    assert summary["current_equity"] == 1030.0
    assert summary["remaining_to_target"] == 70.0
    assert summary["progress_to_target_pct"] == 30.0
    assert summary["total_trades"] == 3
    assert summary["settled_trades"] == 2
    assert summary["pending_trades"] == 1
    assert summary["winning_trades"] == 1
    assert summary["win_rate"] == 50.0
    assert summary["paper_only"] is True
    assert summary["selective_no_forced_trade"] is True


def test_btc_paper_account_progress_is_capped_at_target_and_never_negative():
    above_target = summarize_btc_paper_account([trade(pnl=125.0, settled=True, result="win")])
    below_start = summarize_btc_paper_account([trade(pnl=-25.0, settled=True, result="loss")])

    assert above_target["current_equity"] == 1125.0
    assert above_target["remaining_to_target"] == 0.0
    assert above_target["progress_to_target_pct"] == 100.0
    assert below_start["current_equity"] == 975.0
    assert below_start["remaining_to_target"] == 125.0
    assert below_start["progress_to_target_pct"] == 0.0


def test_btc_paper_account_reports_brier_and_log_loss_for_settled_forecasts_only():
    summary = summarize_btc_paper_account(
        [
            trade(pnl=10.0, settled=True, result="win"),
            trade(pnl=-5.0, settled=True, result="loss"),
            trade(pnl=None, settled=False, result="pending"),
        ]
    )

    assert summary["settled_forecasts"] == 0
    assert summary["brier_score"] is None
    assert summary["log_loss"] is None

    settled_with_forecasts = [
        SimpleNamespace(pnl=10.0, settled=True, result="win", model_probability=0.7, settlement_value=1.0),
        SimpleNamespace(pnl=-5.0, settled=True, result="loss", model_probability=0.2, settlement_value=0.0),
        SimpleNamespace(pnl=None, settled=False, result="pending", model_probability=0.99, settlement_value=1.0),
    ]

    scored = summarize_btc_paper_account(settled_with_forecasts)

    assert scored["settled_forecasts"] == 2
    assert scored["brier_score"] == 0.065
    assert scored["log_loss"] == 0.2899


def test_latest_btc_calibration_summary_uses_latest_batch_and_counts_pending_rows(tmp_path):
    rows = [
        {
            "ts": "20260528T090219Z",
            "model_probability": 0.54,
            "resolved_yes": 1,
            "brier_score": 0.2116,
            "log_loss": 0.6162,
            "status": "resolved_for_calibration",
            "chainlink_start_price": 73200.0,
            "chainlink_end_price": 73210.0,
            "chainlink_start_observed_at": 1779958800,
            "chainlink_end_observed_at": 1779959100,
            "chainlink_start_source_snapshot_path": "/tmp/old-start.json",
            "chainlink_end_source_snapshot_path": "/tmp/old-end.json",
        },
        {
            "ts": "20260528T190102Z",
            "event_slug": "btc-updown-5m-1779994502",
            "model_probability": None,
            "signal_yes_bid": 0.49,
            "signal_yes_ask": 0.51,
            "signal_top_ask_size": 100.0,
            "resolved_yes": None,
            "brier_score": None,
            "log_loss": None,
            "status": "non_actionable_pending_outcome_and_boundary_values",
            "chainlink_start_price": None,
            "chainlink_end_price": None,
            "chainlink_start_observed_at": None,
            "chainlink_end_observed_at": None,
            "chainlink_start_source_snapshot_path": "/tmp/current-raw.json",
            "chainlink_end_source_snapshot_path": "/tmp/current-raw.json",
        },
        {
            "ts": "20260528T190102Z",
            "event_slug": "btc-updown-5m-1779994802",
            "model_probability": 0.51,
            "signal_yes_bid": 0.40,
            "signal_yes_ask": 0.43,
            "signal_top_ask_size": 12.5,
            "resolved_yes": None,
            "brier_score": None,
            "log_loss": None,
            "status": "non_actionable_pending_outcome_and_boundary_values",
            "chainlink_start_price": 73100.0,
            "chainlink_end_price": None,
            "chainlink_start_observed_at": 1779994800,
            "chainlink_end_observed_at": None,
            "chainlink_start_source_snapshot_path": "/tmp/current-start.json",
            "chainlink_end_source_snapshot_path": "/tmp/current-end.json",
        },
    ]

    summary = summarize_latest_btc_calibration_rows(rows)

    assert summary["latest_scored_at"] == "20260528T190102Z"
    assert summary["market_scope"] == "btc"
    assert summary["calibration_kind"] == "chainlink_boundary_outcome_score"
    assert summary["scoring_rows"] == 2
    assert summary["pending_scoring_rows"] == 2
    assert summary["settled_forecasts"] == 0
    assert summary["brier_score"] is None
    assert summary["exact_boundary_rows"] == 0
    assert summary["partial_boundary_rows"] == 1
    assert summary["line_book_rows"] == 2
    assert summary["top_ask_size_rows"] == 2
    assert summary["model_probability_rows"] == 1
    assert summary["exchange_spot_model_rows"] == 0
    assert summary["source_mismatch_rows"] == 0
    assert summary["chainlink_auth_blocked_rows"] == 0
    assert summary["unique_window_count"] == 2
    assert summary["active_window_count"] == 1
    assert summary["upcoming_window_count"] == 0
    assert summary["expired_window_count"] == 1
    assert summary["min_seconds_to_window_end"] == -60
    assert summary["max_seconds_to_window_end"] == 240
    assert summary["max_execution_spread"] == 0.03
    assert summary["min_signal_top_ask_size"] == 12.5
    assert summary["paper_actionable"] is False
    assert summary["source_snapshot"] == "/tmp/current-raw.json"

    missing_path = tmp_path / "missing.sqlite"
    assert load_latest_btc_calibration_summary_from_sqlite(missing_path) is None
    assert missing_path.exists() is False

    import sqlite3

    db_path = tmp_path / "btc.sqlite"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE btc_outcome_scoring_v1(ts TEXT, model_probability REAL, resolved_yes INTEGER, brier_score REAL, log_loss REAL, status TEXT, chainlink_start_price REAL, chainlink_end_price REAL, chainlink_start_observed_at INTEGER, chainlink_end_observed_at INTEGER, chainlink_start_source_snapshot_path TEXT, chainlink_end_source_snapshot_path TEXT)")
    con.executemany(
        "INSERT INTO btc_outcome_scoring_v1 VALUES (:ts, :model_probability, :resolved_yes, :brier_score, :log_loss, :status, :chainlink_start_price, :chainlink_end_price, :chainlink_start_observed_at, :chainlink_end_observed_at, :chainlink_start_source_snapshot_path, :chainlink_end_source_snapshot_path)",
        rows,
    )
    con.commit()
    con.close()

    loaded = load_latest_btc_calibration_summary_from_sqlite(db_path)
    assert loaded["latest_scored_at"] == "20260528T190102Z"
    assert loaded["scoring_rows"] == 2
    assert loaded["settled_forecasts"] == 0


def test_latest_btc_calibration_summary_derives_scores_from_exact_boundaries():
    rows = [
        {
            "ts": "20260531T190000Z",
            "direction": "up",
            "model_probability": 0.7,
            "resolved_yes": None,
            "brier_score": None,
            "log_loss": None,
            "chainlink_start_price": 73000.0,
            "chainlink_end_price": 73010.0,
            "chainlink_start_observed_at": 1780254000,
            "chainlink_end_observed_at": 1780254300,
            "chainlink_start_source_snapshot_path": "/tmp/start.json",
            "chainlink_end_source_snapshot_path": "/tmp/end.json",
        },
        {
            "ts": "20260531T190000Z",
            "direction": "down",
            "model_probability": 0.7,
            "resolved_yes": None,
            "brier_score": None,
            "log_loss": None,
            "chainlink_start_price": 73000.0,
            "chainlink_end_price": 73010.0,
            "chainlink_start_observed_at": 1780254000,
            "chainlink_end_observed_at": 1780254300,
            "chainlink_start_source_snapshot_path": "/tmp/start.json",
            "chainlink_end_source_snapshot_path": "/tmp/end.json",
        },
    ]

    summary = summarize_latest_btc_calibration_rows(rows)

    assert summary["pending_scoring_rows"] == 0
    assert summary["settled_forecasts"] == 2
    assert summary["exact_boundary_rows"] == 2
    assert summary["brier_score"] == 0.29
    assert summary["log_loss"] == 0.7803


def test_load_latest_btc_calibration_rows_derives_outcome_fields_from_exact_boundaries(tmp_path):
    import sqlite3

    db_path = tmp_path / "btc-derived.sqlite"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        CREATE TABLE btc_outcome_scoring_v1(
            ts TEXT, quote_ts TEXT, event_slug TEXT, market_key TEXT, direction TEXT,
            model_probability REAL, model_price_source TEXT, signal_yes_bid REAL,
            signal_yes_ask REAL, signal_probability REAL, chainlink_feed_id TEXT,
            chainlink_capture_method TEXT, chainlink_source_url TEXT,
            chainlink_start_price REAL, chainlink_end_price REAL,
            chainlink_start_observed_at INTEGER, chainlink_end_observed_at INTEGER,
            chainlink_start_source_snapshot_path TEXT,
            chainlink_end_source_snapshot_path TEXT, resolved_yes INTEGER,
            final_outcome TEXT, brier_score REAL, log_loss REAL, clv REAL,
            status TEXT, notes TEXT
        )
        """
    )
    con.execute(
        """
        INSERT INTO btc_outcome_scoring_v1 VALUES(
            '20260531T190000Z', '20260531T190000Z', 'btc-updown-5m-1780254000',
            'btc-updown-5m-1780254000::Up', 'up', 0.7, 'chainlink_stream_snapshot',
            0.69, 0.71, 0.70, 'feed', 'chainlink_data_streams_rest',
            'https://data.chain.link/streams/btc-usd', 73000.0, 73010.0,
            1780254000, 1780254300, '/tmp/start.json', '/tmp/end.json',
            NULL, NULL, NULL, NULL, NULL, 'pending_derivation', 'exact boundaries present'
        )
        """
    )
    con.commit()
    con.close()

    rows = load_latest_btc_calibration_rows_from_sqlite(db_path, limit=5)

    assert rows[0]["resolved_yes"] == 1
    assert rows[0]["final_outcome"] == "Up"
    assert rows[0]["brier_score"] == 0.09
    assert rows[0]["log_loss"] == 0.3567
    assert rows[0]["exact_boundary_available"] is True
    assert "pending resolved Up/Down outcome" not in rows[0]["no_trade_reasons"]
    assert rows[0]["paper_actionable"] is False


def test_load_latest_btc_calibration_rows_from_sqlite_returns_latest_batch_detail_rows(tmp_path):
    import sqlite3

    db_path = tmp_path / "btc-detail.sqlite"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        CREATE TABLE btc_outcome_scoring_v1(
            ts TEXT, quote_ts TEXT, event_slug TEXT, market_key TEXT, direction TEXT,
            model_probability REAL, model_price_source TEXT, signal_yes_bid REAL,
            signal_yes_ask REAL, signal_probability REAL, chainlink_feed_id TEXT,
            chainlink_capture_method TEXT, chainlink_source_url TEXT,
            chainlink_start_price REAL, chainlink_end_price REAL,
            chainlink_start_observed_at INTEGER, chainlink_end_observed_at INTEGER,
            chainlink_start_source_snapshot_path TEXT,
            chainlink_end_source_snapshot_path TEXT, resolved_yes INTEGER,
            final_outcome TEXT, brier_score REAL, log_loss REAL, clv REAL,
            status TEXT, notes TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE btc_chainlink_report_request_v1(
            ts TEXT, event_slug TEXT, market_id TEXT, boundary TEXT,
            boundary_ts INTEGER, feed_id TEXT, request_url TEXT,
            requires_authentication INTEGER, status TEXT, source_url TEXT,
            source_snapshot_path TEXT, notes TEXT
        )
        """
    )
    con.executemany(
        """
        INSERT INTO btc_outcome_scoring_v1 VALUES(
            :ts, :quote_ts, :event_slug, :market_key, :direction,
            :model_probability, :model_price_source, :signal_yes_bid,
            :signal_yes_ask, :signal_probability, :chainlink_feed_id,
            :chainlink_capture_method, :chainlink_source_url,
            :chainlink_start_price, :chainlink_end_price,
            :chainlink_start_observed_at, :chainlink_end_observed_at,
            :chainlink_start_source_snapshot_path,
            :chainlink_end_source_snapshot_path, :resolved_yes,
            :final_outcome, :brier_score, :log_loss, :clv, :status, :notes
        )
        """,
        [
            {
                "ts": "20260528T090219Z",
                "quote_ts": "20260528T090219Z",
                "event_slug": "btc-updown-5m-old",
                "market_key": "btc-updown-5m-old::Up",
                "direction": "up",
                "model_probability": 0.52,
                "model_price_source": "coinbase_spot_context",
                "signal_yes_bid": 0.49,
                "signal_yes_ask": 0.51,
                "signal_probability": 0.5,
                "chainlink_feed_id": "feed",
                "chainlink_capture_method": "chainlink_data_streams_rest",
                "chainlink_source_url": "https://data.chain.link/streams/btc-usd",
                "chainlink_start_price": 73000.0,
                "chainlink_end_price": 73010.0,
                "chainlink_start_observed_at": 1779958800,
                "chainlink_end_observed_at": 1779959100,
                "chainlink_start_source_snapshot_path": "/tmp/old-start.json",
                "chainlink_end_source_snapshot_path": "/tmp/old-end.json",
                "resolved_yes": 1,
                "final_outcome": "Up",
                "brier_score": 0.2304,
                "log_loss": 0.6539,
                "clv": None,
                "status": "resolved_for_calibration",
                "notes": "old batch",
            },
            {
                "ts": "20260528T190820Z",
                "quote_ts": "20260528T190820Z",
                "event_slug": "btc-updown-5m-1779995100",
                "market_key": "btc-updown-5m-1779995100::Up",
                "direction": "up",
                "model_probability": None,
                "model_price_source": "coinbase_spot_context",
                "signal_yes_bid": 0.61,
                "signal_yes_ask": 0.62,
                "signal_probability": 0.62,
                "chainlink_feed_id": "feed",
                "chainlink_capture_method": "chainlink_data_streams_rest",
                "chainlink_source_url": "https://data.chain.link/streams/btc-usd",
                "chainlink_start_price": None,
                "chainlink_end_price": None,
                "chainlink_start_observed_at": None,
                "chainlink_end_observed_at": None,
                "chainlink_start_source_snapshot_path": "/tmp/current-raw.json",
                "chainlink_end_source_snapshot_path": "/tmp/current-raw.json",
                "resolved_yes": None,
                "final_outcome": None,
                "brier_score": None,
                "log_loss": None,
                "clv": None,
                "status": "non_actionable_pending_outcome_and_boundary_values",
                "notes": "current batch pending exact boundary values",
            },
        ],
    )
    con.executemany(
        """
        INSERT INTO btc_chainlink_report_request_v1 VALUES(
            :ts, :event_slug, :market_id, :boundary, :boundary_ts, :feed_id,
            :request_url, :requires_authentication, :status, :source_url,
            :source_snapshot_path, :notes
        )
        """,
        [
            {
                "ts": "20260528T190820Z",
                "event_slug": "btc-updown-5m-1779995100",
                "market_id": "123",
                "boundary": "start",
                "boundary_ts": 1779995100,
                "feed_id": "feed",
                "request_url": "https://api.dataengine.chain.link/api/v1/reports?feedID=feed&timestamp=1779995100",
                "requires_authentication": 1,
                "status": "auth_required_not_fetched",
                "source_url": "https://data.chain.link/streams/btc-usd",
                "source_snapshot_path": None,
                "notes": "request metadata only",
            },
            {
                "ts": "20260528T190820Z",
                "event_slug": "btc-updown-5m-1779995100",
                "market_id": "123",
                "boundary": "end",
                "boundary_ts": 1779995400,
                "feed_id": "feed",
                "request_url": "https://api.dataengine.chain.link/api/v1/reports?feedID=feed&timestamp=1779995400",
                "requires_authentication": 1,
                "status": "auth_required_not_fetched",
                "source_url": "https://data.chain.link/streams/btc-usd",
                "source_snapshot_path": None,
                "notes": "request metadata only",
            },
        ],
    )
    con.commit()
    con.close()

    rows = load_latest_btc_calibration_rows_from_sqlite(db_path, limit=5)

    assert len(rows) == 1
    assert rows[0]["ts"] == "20260528T190820Z"
    assert rows[0]["event_slug"] == "btc-updown-5m-1779995100"
    assert rows[0]["signal_yes_ask"] == 0.62
    assert rows[0]["execution_spread"] == 0.01
    assert rows[0]["chainlink_start_report_request_url"].endswith("timestamp=1779995100")
    assert rows[0]["chainlink_end_report_request_url"].endswith("timestamp=1779995400")
    assert rows[0]["chainlink_start_report_boundary_ts"] == 1779995100
    assert rows[0]["chainlink_end_report_boundary_ts"] == 1779995400
    assert rows[0]["chainlink_start_report_status"] == "auth_required_not_fetched"
    assert rows[0]["chainlink_end_report_status"] == "auth_required_not_fetched"
    assert rows[0]["chainlink_start_report_requires_authentication"] is True
    assert rows[0]["chainlink_end_report_requires_authentication"] is True
    assert rows[0]["exact_boundary_available"] is False
    assert rows[0]["paper_actionable"] is False
    assert "missing exact Chainlink boundary values" in rows[0]["no_trade_reasons"]
    assert "Chainlink report requests require authentication" in rows[0]["no_trade_reasons"]

    missing_path = tmp_path / "missing-detail.sqlite"
    assert load_latest_btc_calibration_rows_from_sqlite(missing_path) == []
    assert missing_path.exists() is False


def test_load_latest_btc_calibration_rows_preserves_signal_top_ask_size(tmp_path):
    import sqlite3

    db_path = tmp_path / "btc-depth-detail.sqlite"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        CREATE TABLE btc_outcome_scoring_v1(
            ts TEXT, quote_ts TEXT, event_slug TEXT, market_key TEXT, direction TEXT,
            model_probability REAL, model_price_source TEXT, signal_yes_bid REAL,
            signal_yes_ask REAL, signal_top_ask_size REAL, signal_probability REAL,
            chainlink_feed_id TEXT, chainlink_capture_method TEXT, chainlink_source_url TEXT,
            chainlink_start_price REAL, chainlink_end_price REAL,
            chainlink_start_observed_at INTEGER, chainlink_end_observed_at INTEGER,
            chainlink_start_source_snapshot_path TEXT,
            chainlink_end_source_snapshot_path TEXT, resolved_yes INTEGER,
            final_outcome TEXT, brier_score REAL, log_loss REAL, clv REAL,
            status TEXT, notes TEXT
        )
        """
    )
    con.execute(
        """
        INSERT INTO btc_outcome_scoring_v1 VALUES(
            '20260601T190000Z', '20260601T190000Z', 'btc-updown-5m-1780340400',
            'btc-updown-5m-1780340400::Down', 'down', NULL, 'coinbase_spot_context',
            0.49, 0.50, 447.57, 0.50, 'feed', 'chainlink_data_streams_rest',
            'https://data.chain.link/streams/btc-usd', NULL, NULL,
            NULL, NULL, '/tmp/raw.json', '/tmp/raw.json',
            NULL, NULL, NULL, NULL, NULL, 'pending_boundary', 'current batch pending'
        )
        """
    )
    con.commit()
    con.close()

    rows = load_latest_btc_calibration_rows_from_sqlite(db_path, limit=16)
    summary = load_latest_btc_calibration_summary_from_sqlite(db_path)

    assert len(rows) == 1
    assert rows[0]["signal_yes_bid"] == 0.49
    assert rows[0]["signal_yes_ask"] == 0.50
    assert rows[0]["execution_spread"] == 0.01
    assert rows[0]["signal_top_ask_size"] == 447.57
    assert rows[0]["paper_actionable"] is False
    assert summary is not None
    assert summary["line_book_rows"] == 1
    assert summary["top_ask_size_rows"] == 1
    assert summary["model_probability_rows"] == 0
    assert summary["exchange_spot_model_rows"] == 1
    assert summary["source_mismatch_rows"] == 1
    assert summary["chainlink_auth_blocked_rows"] == 0
    assert summary["max_execution_spread"] == 0.01
    assert summary["min_signal_top_ask_size"] == 447.57


def test_latest_btc_calibration_summary_counts_auth_required_report_requests(tmp_path):
    import sqlite3

    db_path = tmp_path / "btc-summary-requests.sqlite"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE btc_outcome_scoring_v1(ts TEXT, model_probability REAL, resolved_yes INTEGER, brier_score REAL, log_loss REAL, status TEXT, chainlink_start_price REAL, chainlink_end_price REAL, chainlink_start_observed_at INTEGER, chainlink_end_observed_at INTEGER, chainlink_start_source_snapshot_path TEXT, chainlink_end_source_snapshot_path TEXT)")
    con.executemany(
        "INSERT INTO btc_outcome_scoring_v1 VALUES (:ts, :model_probability, :resolved_yes, :brier_score, :log_loss, :status, :chainlink_start_price, :chainlink_end_price, :chainlink_start_observed_at, :chainlink_end_observed_at, :chainlink_start_source_snapshot_path, :chainlink_end_source_snapshot_path)",
        [
            {
                "ts": "20260530T090249Z",
                "model_probability": None,
                "resolved_yes": None,
                "brier_score": None,
                "log_loss": None,
                "status": "non_actionable_pending_outcome_and_boundary_values",
                "chainlink_start_price": None,
                "chainlink_end_price": None,
                "chainlink_start_observed_at": None,
                "chainlink_end_observed_at": None,
                "chainlink_start_source_snapshot_path": "/tmp/raw.json",
                "chainlink_end_source_snapshot_path": "/tmp/raw.json",
            }
        ],
    )
    con.execute(
        """
        CREATE TABLE btc_chainlink_report_request_v1(
            ts TEXT, event_slug TEXT, market_id TEXT, boundary TEXT,
            boundary_ts INTEGER, feed_id TEXT, request_url TEXT,
            requires_authentication INTEGER, status TEXT, source_url TEXT,
            source_snapshot_path TEXT, notes TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO btc_chainlink_report_request_v1 VALUES (:ts, :event_slug, :market_id, :boundary, :boundary_ts, :feed_id, :request_url, :requires_authentication, :status, :source_url, :source_snapshot_path, :notes)",
        [
            {"ts": "20260530T090249Z", "event_slug": "btc-updown-5m-1", "market_id": "1", "boundary": "start", "boundary_ts": 1, "feed_id": "feed", "request_url": "https://example/start", "requires_authentication": 1, "status": "auth_required_not_fetched", "source_url": "https://data.chain.link/streams/btc-usd", "source_snapshot_path": None, "notes": "request metadata only"},
            {"ts": "20260530T090249Z", "event_slug": "btc-updown-5m-1", "market_id": "1", "boundary": "end", "boundary_ts": 2, "feed_id": "feed", "request_url": "https://example/end", "requires_authentication": 1, "status": "auth_required_not_fetched", "source_url": "https://data.chain.link/streams/btc-usd", "source_snapshot_path": None, "notes": "request metadata only"},
        ],
    )
    con.commit()
    con.close()

    loaded = load_latest_btc_calibration_summary_from_sqlite(db_path)

    assert loaded["latest_scored_at"] == "20260530T090249Z"
    assert loaded["report_request_rows"] == 2
    assert loaded["auth_required_report_requests"] == 2
    assert loaded["chainlink_auth_blocked_rows"] == 1
