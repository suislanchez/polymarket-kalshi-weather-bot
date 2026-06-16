from datetime import datetime, timedelta
from types import SimpleNamespace
import sqlite3

from backend.core.entertainment_paper_account import (
    load_latest_entertainment_calibration_summary_from_sqlite,
    summarize_entertainment_paper_account,
)
from backend.core.entertainment_signals import (
    EntertainmentSignalGateInput,
    evaluate_entertainment_signal_gate,
    parse_box_office_bucket,
    parse_the_numbers_weekend_box_office_grosses,
    parse_rotten_tomatoes_source_snapshot,
    persist_rotten_tomatoes_source_snapshot,
    score_entertainment_binary_forecast,
    load_latest_rotten_tomatoes_market_rows,
    summarize_box_office_bucket_sets,
    summarize_latest_rotten_tomatoes_source_states,
    summarize_rotten_tomatoes_market_coverage,
    summarize_rotten_tomatoes_market_candidates,
    resolve_box_office_bucket_outcome,
)


def trade(pnl=None, settled=False, result="pending"):
    return SimpleNamespace(pnl=pnl, settled=settled, result=result, market_type="entertainment")


class FakeSnapshot:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeDb:
    def __init__(self):
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_entertainment_paper_account_is_separate_1000_to_1100_ledger():
    summary = summarize_entertainment_paper_account(
        [
            trade(pnl=18.0, settled=True, result="win"),
            trade(pnl=-3.0, settled=True, result="loss"),
            trade(pnl=None, settled=False, result="pending"),
        ]
    )

    assert summary["market_scope"] == "rotten_tomatoes_entertainment"
    assert summary["initial_bankroll"] == 1000.0
    assert summary["target_bankroll"] == 1100.0
    assert summary["current_equity"] == 1015.0
    assert summary["realized_pnl"] == 15.0
    assert summary["remaining_to_target"] == 85.0
    assert summary["progress_to_target_pct"] == 15.0
    assert summary["total_trades"] == 3
    assert summary["settled_trades"] == 2
    assert summary["pending_trades"] == 1
    assert summary["winning_trades"] == 1
    assert summary["win_rate"] == 50.0
    assert summary["paper_only"] is True
    assert summary["selective_no_forced_trade"] is True


def test_entertainment_paper_account_reports_settled_forecast_calibration_separately_from_trades():
    summary = summarize_entertainment_paper_account(
        [],
        settled_forecasts=[
            SimpleNamespace(model_probability=0.80, settlement_value=1),
            SimpleNamespace(model_probability=0.30, settlement_value=0),
        ],
    )

    assert summary["current_equity"] == 1000.0
    assert summary["total_trades"] == 0
    assert summary["settled_forecasts"] == 2
    assert summary["brier_score"] == 0.065
    assert summary["log_loss"] == 0.2899
    assert summary["paper_only"] is True
    assert summary["selective_no_forced_trade"] is True


def test_load_latest_entertainment_calibration_summary_from_sqlite_uses_latest_batch_and_tolerates_missing_tables(tmp_path):
    db_path = tmp_path / "research.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE entertainment_forecast_calibrations (
                scored_at TEXT,
                source_snapshot TEXT,
                model_probability REAL,
                market_probability REAL,
                settlement_value REAL,
                brier_score REAL,
                log_loss REAL,
                paper_actionable INTEGER
            )"""
        )
        conn.executemany(
            "INSERT INTO entertainment_forecast_calibrations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("20260528T210150Z", "/tmp/old.json", 0.80, 0.77, 1.0, 0.04, 0.2231, 0),
                ("20260529T050150Z", "/tmp/latest.json", 0.30, 0.33, 0.0, 0.09, 0.3567, 0),
                ("20260529T050150Z", "/tmp/latest.json", None, 0.20, 1.0, None, None, 0),
            ],
        )

    summary = load_latest_entertainment_calibration_summary_from_sqlite(str(db_path))

    assert summary["latest_scored_at"] == "20260529T050150Z"
    assert summary["scoring_rows"] == 2
    assert summary["pending_scoring_rows"] == 1
    assert summary["settled_forecasts"] == 1
    assert summary["brier_score"] == 0.09
    assert summary["log_loss"] == 0.3567
    assert summary["source_snapshot"] == "/tmp/latest.json"
    assert summary["paper_actionable"] is False
    assert summary["market_scope"] == "rotten_tomatoes_entertainment"
    assert summary["calibration_kind"] == "rt_entertainment_outcome_score"

    missing_table_db = tmp_path / "missing.sqlite"
    with sqlite3.connect(missing_table_db):
        pass
    assert load_latest_entertainment_calibration_summary_from_sqlite(str(missing_table_db)) is None


def test_load_latest_entertainment_calibration_summary_missing_db_is_read_only(tmp_path):
    missing_db = tmp_path / "does-not-exist.sqlite"

    assert load_latest_entertainment_calibration_summary_from_sqlite(str(missing_db)) is None
    assert not missing_db.exists()


def test_entertainment_gate_blocks_market_only_or_stale_source_signals():
    result = evaluate_entertainment_signal_gate(
        EntertainmentSignalGateInput(
            market_question='Will "Example" score at least 80 on Rotten Tomatoes?',
            market_probability=0.55,
            model_probability=0.70,
            best_bid=0.50,
            best_ask=0.62,
            top_ask_size=10.0,
            direct_source_status="fallback_only",
            source_score=84,
            review_count=12,
            threshold=80,
            hours_since_source_refresh=30,
        )
    )

    assert result.actionable is False
    assert result.edge == 0.15
    assert result.spread == 0.12
    assert result.top_ask_size == 10.0
    assert "source-state: fallback_only" in result.source_state_label
    assert "top_ask=10" in result.market_state_label
    assert any("not fresh" in reason for reason in result.reasons)
    assert any("review count" in reason for reason in result.reasons)
    assert any("spread" in reason for reason in result.reasons)


def test_entertainment_gate_allows_fresh_deep_high_edge_paper_candidate():
    result = evaluate_entertainment_signal_gate(
        EntertainmentSignalGateInput(
            market_question='Will "Example" score at least 80 on Rotten Tomatoes?',
            market_probability=0.55,
            model_probability=0.68,
            best_bid=0.54,
            best_ask=0.58,
            top_ask_size=80.0,
            direct_source_status="fresh",
            source_score=84,
            review_count=65,
            threshold=80,
            hours_since_source_refresh=2,
        )
    )

    assert result.actionable is True
    assert result.reasons == []
    assert result.edge == 0.13
    assert result.spread == 0.04
    assert "source-state: fresh" in result.source_state_label
    assert "market-state: open" in result.market_state_label


def test_entertainment_binary_forecast_scores_brier_and_log_loss_without_side_effects():
    score = score_entertainment_binary_forecast(
        market_question='Will "Example" score at least 65 on Rotten Tomatoes?',
        forecast_probability=0.7,
        resolved_yes=True,
        direct_source_status="fresh",
        source_score=68,
        review_count=84,
    )

    assert score.brier_score == 0.09
    assert score.log_loss == 0.356675
    assert score.source_state_label == "source-state: fresh; score=68; reviews=84"


def test_entertainment_binary_forecast_rejects_invalid_probability():
    try:
        score_entertainment_binary_forecast(
            market_question='Will "Example" score at least 65 on Rotten Tomatoes?',
            forecast_probability=1.2,
            resolved_yes=True,
            direct_source_status="fresh",
        )
    except ValueError as exc:
        assert "between 0 and 1" in str(exc)
    else:
        raise AssertionError("invalid forecast probability should raise ValueError")


def test_parse_rotten_tomatoes_source_snapshot_extracts_score_reviews_and_timing_risk():
    parsed = parse_rotten_tomatoes_source_snapshot(
        "Watchlist Tomatometer Popcornmeter\n\n95% Tomatometer 59 Reviews",
        title="I Love Boosters",
    )

    assert parsed.title == "I Love Boosters"
    assert parsed.tomatometer_score == 95
    assert parsed.review_count == 59
    assert parsed.direct_source_status == "fresh"
    assert parsed.timing_risk_label == "medium timing risk: review wave still small"


def test_parse_rotten_tomatoes_source_snapshot_extracts_embedded_critics_score_json():
    parsed = parse_rotten_tomatoes_source_snapshot(
        '"audienceScore":{"reviewCount":25,"score":"80"},'
        '"criticsScore":{"averageRating":"7.40","ratingCount":91,'
        '"reviewCount":91,"score":"92","scorePercent":"92%","title":"Tomatometer"}',
        title="I Love Boosters",
    )

    assert parsed.title == "I Love Boosters"
    assert parsed.tomatometer_score == 92
    assert parsed.review_count == 91
    assert parsed.direct_source_status == "fresh"
    assert parsed.timing_risk_label == "lower timing risk: review count above gate"


def test_persist_rotten_tomatoes_source_snapshot_records_source_state_without_real_db():
    fake_db = FakeDb()
    parsed = parse_rotten_tomatoes_source_snapshot(
        "Watchlist Tomatometer Popcornmeter\n\n62% Tomatometer 149 Reviews",
        title="Star Wars: The Mandalorian and Grogu",
    )

    captured_at = datetime(2026, 5, 23, 21, 2, 17)
    saved = persist_rotten_tomatoes_source_snapshot(
        parsed,
        source_url="https://www.rottentomatoes.com/m/star_wars_the_mandalorian_and_grogu",
        source_method="public-web-extract",
        cutoff_time="2026-05-25T10:00:00-04:00",
        event_slug="star-wars-the-mandalorian-and-grogu-rotten-tomatoes-score",
        captured_at=captured_at,
        db_factory=lambda: fake_db,
        snapshot_cls=FakeSnapshot,
    )

    assert saved is True
    assert fake_db.committed is True
    assert fake_db.closed is True
    assert len(fake_db.added) == 1
    snapshot = fake_db.added[0]
    assert snapshot.title == "Star Wars: The Mandalorian and Grogu"
    assert snapshot.event_slug == "star-wars-the-mandalorian-and-grogu-rotten-tomatoes-score"
    assert snapshot.captured_at == captured_at
    assert snapshot.source_url == "https://www.rottentomatoes.com/m/star_wars_the_mandalorian_and_grogu"
    assert snapshot.source_method == "public-web-extract"
    assert snapshot.tomatometer_score == 62
    assert snapshot.review_count == 149
    assert snapshot.direct_source_status == "fresh"
    assert snapshot.timing_risk_label == "lower timing risk: review count above gate"
    assert snapshot.cutoff_time == "2026-05-25T10:00:00-04:00"


def test_parse_rotten_tomatoes_source_snapshot_blocks_review_count_without_score():
    parsed = parse_rotten_tomatoes_source_snapshot(
        "Watchlist Tomatometer Popcornmeter\n\nTomatometer 1 Reviews Popcornmeter 0 Verified Ratings",
        title="Passenger",
    )

    assert parsed.tomatometer_score is None
    assert parsed.review_count == 1
    assert parsed.direct_source_status == "no_displayed_score"
    assert parsed.timing_risk_label == "high timing risk: below 30 reviews"


def test_latest_rt_source_state_summary_dedupes_by_event_and_preserves_no_trade_context():
    now = datetime(2026, 5, 22, 21, 30)
    rows = [
        SimpleNamespace(
            captured_at=now - timedelta(hours=3),
            title="Star Wars: The Mandalorian and Grogu",
            event_slug="star-wars-the-mandalorian-and-grogu-rotten-tomatoes-score",
            source_url="https://www.rottentomatoes.com/m/star_wars_the_mandalorian_and_grogu",
            source_method="public-web-extract",
            tomatometer_score=62,
            review_count=149,
            direct_source_status="fresh",
            timing_risk_label="lower timing risk: review count above gate",
            cutoff_time="2026-05-25T10:00:00-04:00",
        ),
        SimpleNamespace(
            captured_at=now,
            title="Star Wars: The Mandalorian and Grogu",
            event_slug="star-wars-the-mandalorian-and-grogu-rotten-tomatoes-score",
            source_url="https://www.rottentomatoes.com/m/star_wars_the_mandalorian_and_grogu",
            source_method="embedded-criticsScore-json",
            tomatometer_score=64,
            review_count=207,
            direct_source_status="fresh",
            timing_risk_label="lower timing risk: review count above gate",
            cutoff_time="2026-05-25T10:00:00-04:00",
        ),
        SimpleNamespace(
            captured_at=now - timedelta(minutes=20),
            title="Passenger",
            event_slug="passenger-rotten-tomatoes-score",
            source_url="https://www.rottentomatoes.com/m/passenger_2026",
            source_method="embedded-criticsScore-json",
            tomatometer_score=43,
            review_count=49,
            direct_source_status="fresh",
            timing_risk_label="medium timing risk: review wave still small",
            cutoff_time="2026-05-25T10:00:00-04:00",
        ),
    ]

    summary = summarize_latest_rotten_tomatoes_source_states(rows, limit=5)

    assert len(summary) == 2
    assert summary[0]["event_slug"] == "star-wars-the-mandalorian-and-grogu-rotten-tomatoes-score"
    assert summary[0]["tomatometer_score"] == 64
    assert summary[0]["review_count"] == 207
    assert summary[0]["previous_tomatometer_score"] == 62
    assert summary[0]["previous_review_count"] == 149
    assert summary[0]["score_delta"] == 2
    assert summary[0]["review_count_delta"] == 58
    assert summary[0]["hours_since_previous_source"] == 3.0
    assert summary[0]["source_state_label"] == "source-state: fresh; score=64; reviews=207; score_delta=+2; reviews_delta=+58"
    assert summary[0]["source_method"] == "embedded-criticsScore-json"
    assert summary[1]["event_slug"] == "passenger-rotten-tomatoes-score"
    assert summary[1]["paper_actionable"] is False
    assert "source state only" in summary[1]["no_trade_reason"]
    assert any("source state only" in reason for reason in summary[1]["no_trade_reasons"])
    assert "review count/timing risk gate blocks action" in summary[1]["no_trade_reasons"]


def test_infer_rotten_tomatoes_source_url_covers_active_rt_slug_patterns():
    from backend.core.entertainment_signals import infer_rotten_tomatoes_source_url

    assert infer_rotten_tomatoes_source_url("backrooms-rotten-tomatoes-score") == "https://www.rottentomatoes.com/m/backrooms"
    assert infer_rotten_tomatoes_source_url("pressure-rotten-tomatoes-score") == "https://www.rottentomatoes.com/m/pressure_2026"
    assert infer_rotten_tomatoes_source_url("scary-movie-rotten-tomatoes-score") == "https://www.rottentomatoes.com/m/scary_movie_2026"
    assert infer_rotten_tomatoes_source_url("the-death-of-robin-hood-rotten-tomatoes-score") == "https://www.rottentomatoes.com/m/the_death_of_robin_hood"
    assert infer_rotten_tomatoes_source_url("the-last-viking-rotten-tomatoes-score") == "https://www.rottentomatoes.com/m/the_last_viking"
    assert infer_rotten_tomatoes_source_url("the-breadwinner-rotten-tomatoes-score") == "https://www.rottentomatoes.com/m/the_breadwinner_2026"
    assert infer_rotten_tomatoes_source_url("supergirl-rotten-tomatoes-score") == "https://www.rottentomatoes.com/m/supergirl_2026"


def test_rt_market_candidate_summary_exposes_inferred_source_url_when_direct_source_missing():
    market_rows = [
        {
            "event_slug": "backrooms-rotten-tomatoes-score",
            "question": 'Will "Backrooms" score at least 60 on the Rotten Tomatoes Tomatometer?',
            "threshold": 60.0,
            "probability": 0.80,
            "yes_bid": 0.69,
            "yes_ask": 0.98,
            "top_ask_size": 50.0,
            "market_closed": False,
            "source_state": None,
        }
    ]

    candidates = summarize_rotten_tomatoes_market_candidates(market_rows)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["source_url"] == "https://www.rottentomatoes.com/m/backrooms"
    assert candidate["direct_source_status"] == "missing"
    assert "no direct RT source snapshot for inferred source URL" in candidate["no_trade_reasons"]
    assert candidate["market_type"] == "rotten_tomatoes"
    assert candidate["paper_actionable"] is False


def test_box_office_candidate_summary_uses_final_source_blockers_not_rt_source_blockers():
    market_rows = [
        {
            "event_slug": "backrooms-opening-weekend-box-office",
            "question": 'Will "Backrooms" Opening Weekend Box Office be greater than 61m?',
            "probability": 0.84,
            "yes_bid": 0.82,
            "yes_ask": 0.86,
            "top_ask_size": 4998.83,
            "market_closed": False,
            "source_state": None,
            "rules": "This market will resolve based on The Numbers final domestic opening weekend chart.",
        }
    ]

    candidates = summarize_rotten_tomatoes_market_candidates(market_rows)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["market_type"] == "box_office"
    assert candidate["box_office_lower_m"] == 61.0
    assert candidate["box_office_upper_m"] is None
    assert candidate["box_office_bucket_label"] == ">$61M"
    assert candidate["box_office_bucket_type"] == "above"
    assert candidate["direct_source_status"] == "missing_final_box_office_source"
    assert candidate["source_method"] == "final-box-office-source-required"
    assert candidate["source_url"] == "https://www.the-numbers.com/weekend-box-office-chart"
    assert "missing direct final box-office source snapshot" in candidate["no_trade_reasons"]
    assert "no direct RT source snapshot for inferred source URL" not in candidate["no_trade_reasons"]
    assert "source-state snapshot is current-state evidence, not an independent calibrated forecast" not in candidate["no_trade_reasons"]
    assert "box-office market requires calibrated distribution plus final-source watcher" in candidate["no_trade_reasons"]
    assert candidate["paper_actionable"] is False


def test_box_office_candidate_summary_flags_bucket_probability_mass_outside_sanity_band():
    candidates = summarize_rotten_tomatoes_market_candidates([
        {
            "event_slug": "masters-opening-weekend-box-office",
            "question": 'Will "Masters" Opening Weekend Box Office be less than 27m?',
            "probability": 0.20,
            "yes_bid": 0.18,
            "yes_ask": 0.22,
            "top_ask_size": 50.0,
        },
        {
            "event_slug": "masters-opening-weekend-box-office",
            "question": 'Will "Masters" Opening Weekend Box Office be between 27m and 30m?',
            "probability": 0.30,
            "yes_bid": 0.28,
            "yes_ask": 0.32,
            "top_ask_size": 50.0,
        },
        {
            "event_slug": "masters-opening-weekend-box-office",
            "question": 'Will "Masters" Opening Weekend Box Office be greater than 30m?',
            "probability": 0.90,
            "yes_bid": 0.88,
            "yes_ask": 0.92,
            "top_ask_size": 50.0,
        },
    ])

    assert len(candidates) == 3
    assert candidates[0]["box_office_bucket_set_probability_mass"] == 1.4
    assert candidates[0]["box_office_bucket_set_sanity_passed"] is False
    assert "box-office bucket-set probability mass outside 0.95-1.05 sanity band" in candidates[0]["no_trade_reasons"]
    assert all(candidate["paper_actionable"] is False for candidate in candidates)


def test_rt_entertainment_market_coverage_summary_counts_source_depth_and_bucket_blockers():
    rows = [
        {
            "event_slug": "scary-movie-rotten-tomatoes-score",
            "market_type": "rotten_tomatoes",
            "yes_bid": 0.08,
            "yes_ask": 0.11,
            "top_ask_size": 60.0,
            "source_state": {"direct_source_status": "no_displayed_score", "review_count": 0},
            "no_trade_reasons": ["direct source status no_displayed_score is not fresh"],
            "paper_actionable": False,
        },
        {
            "event_slug": "masters-opening-weekend-box-office",
            "market_type": "box_office",
            "yes_bid": 0.16,
            "yes_ask": 0.23,
            "top_ask_size": 6.49,
            "box_office_bucket_set_size": 5,
            "box_office_bucket_set_probability_mass": 1.09,
            "box_office_bucket_set_sanity_passed": False,
            "no_trade_reasons": ["box-office bucket-set probability mass outside 0.95-1.05 sanity band"],
            "paper_actionable": False,
        },
    ]

    summary = summarize_rotten_tomatoes_market_coverage(rows)

    assert summary == {
        "total_rows": 2,
        "rotten_tomatoes_rows": 1,
        "box_office_rows": 1,
        "unique_event_count": 2,
        "direct_source_rows": 1,
        "fresh_rt_source_rows": 0,
        "no_score_rt_rows": 1,
        "line_book_rows": 2,
        "top_ask_size_rows": 2,
        "box_office_bucket_rows": 1,
        "box_office_mass_outside_sanity_rows": 1,
        "paper_actionable_rows": 0,
    }


def test_box_office_candidate_summary_preserves_final_source_capture_without_missing_source_blocker():
    candidates = summarize_rotten_tomatoes_market_candidates([
        {
            "event_slug": "backrooms-opening-weekend-box-office",
            "question": 'Will "Backrooms" Opening Weekend Box Office be greater than 79m?',
            "probability": 0.96,
            "yes_bid": 0.944,
            "yes_ask": 0.96,
            "top_ask_size": 732.78,
            "market_closed": False,
            "source_state": {
                "source_url": "https://www.the-numbers.com/weekend-box-office-chart",
                "source_method": "the-numbers-weekend-chart",
                "direct_source_status": "final_source_captured",
                "domestic_weekend_gross_m": 81.456,
            },
            "box_office_actual_gross_m": 81.456,
            "box_office_resolved_yes": True,
        }
    ])

    candidate = candidates[0]
    assert candidate["box_office_actual_gross_m"] == 81.456
    assert candidate["box_office_resolved_yes"] is True
    assert candidate["box_office_bucket_set_size"] == 1
    assert candidate["box_office_bucket_set_sanity_passed"] is True
    assert candidate["box_office_resolved_yes_count"] == 1
    assert candidate["box_office_resolved_winner_label"] == ">$79M"
    assert "missing direct final box-office source snapshot" not in candidate["no_trade_reasons"]
    assert "missing score/threshold source data" not in candidate["no_trade_reasons"]
    assert "review count below timing-risk gate" not in candidate["no_trade_reasons"]
    assert "box-office final source captured for calibration only; platform settlement still required" in candidate["no_trade_reasons"]
    assert candidate["paper_actionable"] is False


def test_parse_box_office_bucket_parses_ranges_and_tails():
    assert parse_box_office_bucket('Will "Backrooms" Opening Weekend Box Office be between 73m and 79m?') == {
        "box_office_lower_m": 73.0,
        "box_office_upper_m": 79.0,
        "box_office_bucket_label": "$73M–$79M",
        "box_office_bucket_type": "range",
    }
    assert parse_box_office_bucket('Will "The Breadwinner" Opening Weekend Box Office be less than 4m?')["box_office_bucket_label"] == "<$4M"
    assert parse_box_office_bucket('Will "Backrooms" Opening Weekend Box Office be greater than 79m?')["box_office_bucket_label"] == ">$79M"
    assert parse_box_office_bucket('Will "Scary Movie" Opening Weekend Box Office be at least 52m?') == {
        "box_office_lower_m": 52.0,
        "box_office_upper_m": None,
        "box_office_bucket_label": "≥$52M",
        "box_office_bucket_type": "at_least",
    }


def test_the_numbers_box_office_parser_and_bucket_resolution_are_calibration_only():
    chart = """
    | Rank | Prev | Title | Gross | Theaters |
    | --- | --- | --- | --- | --- |
    | 1 | (new) | Backrooms | $81,456,295 | 3,442 |
    | 5 | (new) | The Breadwinner | $7,500,000 | 3,252 |
    """

    grosses = parse_the_numbers_weekend_box_office_grosses(chart)

    assert grosses["backrooms"]["domestic_weekend_gross"] == 81456295.0
    assert grosses["backrooms"]["domestic_weekend_gross_m"] == 81.456
    assert grosses["the breadwinner"]["domestic_weekend_gross_m"] == 7.5

    backrooms_tail = resolve_box_office_bucket_outcome(
        'Will "Backrooms" Opening Weekend Box Office be greater than 79m?',
        grosses["backrooms"]["domestic_weekend_gross_m"],
    )
    backrooms_range = resolve_box_office_bucket_outcome(
        'Will "Backrooms" Opening Weekend Box Office be between 73m and 79m?',
        grosses["backrooms"]["domestic_weekend_gross_m"],
    )
    breadwinner_tail = resolve_box_office_bucket_outcome(
        'Will "The Breadwinner" Opening Weekend Box Office be greater than 7m?',
        grosses["the breadwinner"]["domestic_weekend_gross_m"],
    )

    assert backrooms_tail["resolved_yes"] is True
    assert backrooms_range["resolved_yes"] is False
    assert breadwinner_tail["resolved_yes"] is True


def test_rt_market_candidate_summary_joins_source_state_to_current_clob_rows_without_actionability():
    market_rows = [
        {
            "event_slug": "passenger-rotten-tomatoes-score",
            "question": 'Will "Passenger" score at least 50 on the Rotten Tomatoes Tomatometer?',
            "threshold": 50.0,
            "probability": 0.001,
            "yes_bid": None,
            "yes_ask": 0.001,
            "top_ask_size": 150.0,
            "market_closed": False,
            "source_state": {"tomatometer_score": 45, "review_count": 66, "direct_source_status": "fresh"},
        }
    ]
    source_summaries = [
        {
            "event_slug": "passenger-rotten-tomatoes-score",
            "title": "Passenger",
            "source_url": "https://www.rottentomatoes.com/m/passenger_2026",
            "source_method": "direct-rt-html",
            "captured_at": "2026-05-26T05:01:13+00:00",
            "hours_since_source_refresh": 0.5,
            "tomatometer_score": 45,
            "review_count": 66,
            "previous_tomatometer_score": 45,
            "previous_review_count": 65,
            "score_delta": 0,
            "review_count_delta": 1,
            "hours_since_previous_source": 8.0,
            "direct_source_status": "fresh",
            "timing_risk_label": "medium timing risk: review wave still small",
            "cutoff_time": "2026-05-26T10:00:00-04:00",
        }
    ]

    candidates = summarize_rotten_tomatoes_market_candidates(
        market_rows,
        source_summaries=source_summaries,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["event_slug"] == "passenger-rotten-tomatoes-score"
    assert candidate["title"] == 'Will "Passenger" score at least 50 on the Rotten Tomatoes Tomatometer?'
    assert candidate["paper_actionable"] is False
    assert candidate["best_bid"] is None
    assert candidate["best_ask"] == 0.001
    assert candidate["threshold"] == 50.0
    assert candidate["top_ask_size"] == 150.0
    assert candidate["tomatometer_score"] == 45
    assert candidate["review_count"] == 66
    assert candidate["review_count_delta"] == 1
    assert candidate["source_url"] == "https://www.rottentomatoes.com/m/passenger_2026"
    assert candidate["source_method"] == "direct-rt-html"
    assert candidate["captured_at"] == "2026-05-26T05:01:13+00:00"
    assert candidate["cutoff_time"] == "2026-05-26T10:00:00-04:00"
    assert "missing model probability" in candidate["no_trade_reasons"]
    assert "missing line-level bid/ask" in candidate["no_trade_reasons"]
    assert "source-state snapshot is current-state evidence, not an independent calibrated forecast" in candidate["no_trade_reasons"]


def test_rt_market_candidate_summary_preserves_runner_previous_source_timestamp_alias():
    market_rows = [
        {
            "event_slug": "pressure-rotten-tomatoes-score",
            "question": 'Will "Pressure" score at least 80 on the Rotten Tomatoes Tomatometer?',
            "threshold": 80.0,
            "probability": 0.90,
            "yes_bid": 0.88,
            "yes_ask": 0.95,
            "top_ask_size": 50.0,
            "market_closed": False,
            "source_state": {
                "tomatometer_score": 87,
                "review_count": 85,
                "direct_source_status": "fresh",
                "captured_at": "20260602T210149Z",
                "previous_source_captured_at": "2026-06-02 05:03:30",
                "previous_tomatometer_score": 88,
                "previous_review_count": 82,
                "score_delta": -1,
                "review_count_delta": 3,
                "hours_since_previous_source": 15.972,
            },
        }
    ]

    candidates = summarize_rotten_tomatoes_market_candidates(market_rows)

    assert candidates[0]["previous_captured_at"] == "2026-06-02 05:03:30"
    assert candidates[0]["previous_tomatometer_score"] == 88
    assert candidates[0]["previous_review_count"] == 82
    assert candidates[0]["score_delta"] == -1
    assert candidates[0]["review_count_delta"] == 3
    assert candidates[0]["hours_since_previous_source"] == 15.972


def test_latest_rt_market_rows_loader_reads_newest_public_summary(tmp_path):
    older = tmp_path / "20260525T210122Z-rt-entertainment-public-summary.json"
    newer = tmp_path / "20260526T210159Z-rt-entertainment-public-summary.json"
    older.write_text('{"ts":"old","active_rows":[{"event_slug":"old"}]}', encoding="utf-8")
    newer.write_text(
        '{"ts":"new","active_rows":[{"event_slug":"new","yes_ask":0.99}, null]}',
        encoding="utf-8",
    )

    rows, path, ts = load_latest_rotten_tomatoes_market_rows(snapshot_dir=tmp_path)

    assert ts == "new"
    assert path == str(newer)
    assert rows == [{"event_slug": "new", "yes_ask": 0.99}]


def test_build_rotten_tomatoes_review_rows_keeps_all_public_summary_rows_visible():
    from backend.core.entertainment_signals import build_rotten_tomatoes_review_rows

    market_rows = [
        {
            "event_slug": "backrooms-rotten-tomatoes-score",
            "question": f'Will "Backrooms" score at least {threshold} on the Rotten Tomatoes Tomatometer?',
            "threshold": float(threshold),
            "probability": 0.8,
            "yes_bid": 0.7,
            "yes_ask": 0.9,
            "top_ask_size": 50.0,
            "market_closed": False,
        }
        for threshold in range(50, 80)
    ]
    source_summaries = [
        {
            "event_slug": "backrooms-rotten-tomatoes-score",
            "title": "Backrooms",
            "source_url": "https://www.rottentomatoes.com/m/backrooms",
            "direct_source_status": "fresh",
            "tomatometer_score": 90,
            "review_count": 174,
            "captured_at": "2026-05-30T21:00:44+00:00",
        },
        {
            "event_slug": "pressure-rotten-tomatoes-score",
            "title": "Pressure",
            "source_url": "https://www.rottentomatoes.com/m/pressure_2026",
            "direct_source_status": "fresh",
            "tomatometer_score": 86,
            "review_count": 70,
            "captured_at": "2026-05-30T21:00:44+00:00",
        },
    ]

    rows = build_rotten_tomatoes_review_rows(market_rows, source_summaries)

    assert len(rows) == 31
    assert sum(1 for row in rows if row.get("event_slug") == "backrooms-rotten-tomatoes-score") == 30
    assert any(row.get("event_slug") == "pressure-rotten-tomatoes-score" for row in rows)

    assert all(row.get("paper_actionable") is False for row in rows)


def test_box_office_bucket_set_summary_requires_exactly_one_resolved_winner_before_calibration():
    rows = [
        {
            "event_slug": "backrooms-opening-weekend-box-office",
            "question": 'Will "Backrooms" Opening Weekend Box Office be less than 73m?',
            "probability": 0.01,
            "yes_bid": 0.001,
            "yes_ask": 0.004,
            "top_ask_size": 100,
            "box_office_actual_gross_m": 81.456,
            "box_office_resolved_yes": False,
        },
        {
            "event_slug": "backrooms-opening-weekend-box-office",
            "question": 'Will "Backrooms" Opening Weekend Box Office be between 73m and 79m?',
            "probability": 0.02,
            "yes_bid": 0.018,
            "yes_ask": 0.052,
            "top_ask_size": 15,
            "box_office_actual_gross_m": 81.456,
            "box_office_resolved_yes": False,
        },
        {
            "event_slug": "backrooms-opening-weekend-box-office",
            "question": 'Will "Backrooms" Opening Weekend Box Office be greater than 79m?',
            "probability": 0.97,
            "yes_bid": 0.972,
            "yes_ask": 0.993,
            "top_ask_size": 1350,
            "box_office_actual_gross_m": 81.456,
            "box_office_resolved_yes": True,
        },
        {
            "event_slug": "ambiguous-opening-weekend-box-office",
            "question": 'Will "Ambiguous" Opening Weekend Box Office be greater than 10m?',
            "probability": 0.6,
            "yes_bid": 0.55,
            "yes_ask": 0.65,
            "top_ask_size": 10,
            "box_office_actual_gross_m": 12.0,
            "box_office_resolved_yes": True,
        },
        {
            "event_slug": "ambiguous-opening-weekend-box-office",
            "question": 'Will "Ambiguous" Opening Weekend Box Office be greater than 11m?',
            "probability": 0.7,
            "yes_bid": 0.66,
            "yes_ask": 0.75,
            "top_ask_size": 8,
            "box_office_actual_gross_m": 12.0,
            "box_office_resolved_yes": True,
        },
    ]

    summaries = summarize_box_office_bucket_sets(rows)

    backrooms = summaries["backrooms-opening-weekend-box-office"]
    assert backrooms["bucket_set_size"] == 3
    assert backrooms["resolved_yes_count"] == 1
    assert backrooms["bucket_set_sanity_passed"] is True
    assert backrooms["resolved_winner_label"] == ">$79M"
    assert backrooms["paper_actionable"] is False
    assert "exactly-one-winner sanity passed" in backrooms["diagnostics"]

    ambiguous = summaries["ambiguous-opening-weekend-box-office"]
    assert ambiguous["resolved_yes_count"] == 2
    assert ambiguous["bucket_set_sanity_passed"] is False
    assert ambiguous["paper_actionable"] is False
    assert "expected exactly one resolved Yes bucket; found 2" in ambiguous["diagnostics"]
