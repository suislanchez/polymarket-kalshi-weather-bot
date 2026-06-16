from types import SimpleNamespace

from backend.core.signal_review import summarize_signal_review_queue


def test_signal_review_queue_prioritizes_failed_gates_across_verticals():
    btc_signal = SimpleNamespace(
        market=SimpleNamespace(market_id="btc-updown-5m-1", slug="btc-updown-5m-1"),
        market_title="BTC Up or Down",
        passes_threshold=False,
        no_trade_reasons=["model price source coinbase is not Chainlink settlement source"],
        edge=0.12,
        execution_spread=0.01,
        top_ask_size=120.0,
        settlement_source="Chainlink BTC/USD",
        settlement_url="https://data.chain.link/streams/btc-usd",
        model_price_source="coinbase",
        model_probability=0.58,
        market_probability=0.49,
        category="crypto",
    )
    weather_signal = SimpleNamespace(
        market_id="KXHIGHNY-26MAY24-T59",
        city_name="New York",
        passes_threshold=False,
        no_trade_reasons=["missing settlement source/station", "threshold distance below buffer"],
        edge=0.09,
        execution_spread=0.02,
        top_ask_size=8.0,
        platform="kalshi",
    )
    rt_state = {
        "event_slug": "passenger-rotten-tomatoes-score",
        "title": "Passenger",
        "paper_actionable": False,
        "no_trade_reason": "source state only; requires current market quote, threshold, CLOB depth, and gate evaluation",
        "hours_since_source_refresh": 2.5,
    }

    summary = summarize_signal_review_queue(
        btc_signals=[btc_signal],
        weather_signals=[weather_signal],
        rt_source_states=[rt_state],
        limit=10,
    )

    assert summary["total_blocked"] == 3
    assert summary["blocked_by_vertical"] == {"btc": 1, "weather": 1, "rt_entertainment": 1}
    assert summary["blocked_by_source"] == {"btc_signal": 1, "weather_signal": 1, "rt_source_state": 1}
    assert summary["top_blockers"][0]["reason"] == "missing settlement source/station"
    assert summary["items"][0]["vertical"] == "weather"
    assert summary["items"][0]["market_key"] == "KXHIGHNY-26MAY24-T59"
    assert summary["items"][0]["review_priority"] == 5
    assert summary["items"][1]["vertical"] == "btc"
    assert summary["items"][1]["review_priority"] == 4
    assert summary["items"][1]["settlement_source"] == "Chainlink BTC/USD"
    assert summary["items"][1]["settlement_url"] == "https://data.chain.link/streams/btc-usd"
    assert summary["items"][1]["model_price_source"] == "coinbase"
    assert summary["items"][1]["model_probability"] == 0.58
    assert summary["items"][1]["market_probability"] == 0.49
    assert summary["items"][2]["vertical"] == "rt_entertainment"
    assert summary["items"][2]["review_priority"] == 3
    assert "current market quote" in summary["items"][2]["primary_blocker"]


def test_signal_review_queue_skips_actionable_or_clean_rows():
    actionable = SimpleNamespace(
        market=SimpleNamespace(market_id="btc-ok", slug="btc-ok"),
        passes_threshold=True,
        no_trade_reasons=[],
        edge=0.2,
    )
    clean_rt = {"title": "Clean", "paper_actionable": True, "no_trade_reason": ""}

    summary = summarize_signal_review_queue(
        btc_signals=[actionable],
        weather_signals=[],
        rt_source_states=[clean_rt],
    )

    assert summary["total_blocked"] == 0
    assert summary["top_blockers"] == []
    assert summary["items"] == []


def test_signal_review_queue_uses_nested_weather_market_identity():
    market = SimpleNamespace(market_id="KXHIGHNY-26MAY25-T72", city_name="New York")
    weather_signal = SimpleNamespace(
        market=market,
        passes_threshold=False,
        no_trade_reasons=["missing exact settlement source/station"],
        edge=0.0,
        execution_spread=0.02,
        top_ask_size=25.0,
    )

    summary = summarize_signal_review_queue(weather_signals=[weather_signal])

    assert summary["total_blocked"] == 1
    assert summary["items"][0]["market_key"] == "KXHIGHNY-26MAY25-T72"
    assert summary["items"][0]["title"] == "New York — KXHIGHNY-26MAY25-T72"


def test_signal_review_queue_includes_weather_review_only_candidates():
    review_candidate = {
        "market_key": "KXHIGHCHI-26JUN01-T72",
        "title": "Chicago high temp below 72F",
        "city": "Chicago",
        "paper_actionable": False,
        "executed": False,
        "suggested_size": 0.0,
        "no_trade_reasons": ["review-only candidate; not paper-actionable until independently revalidated"],
        "edge": 0.63,
        "best_bid": 0.29,
        "best_ask": 0.32,
        "execution_spread": 0.03,
        "top_ask_size": 208.09,
        "settlement_source": "NWS CLI",
        "settlement_source_url": "https://api.weather.gov/products/types/CLI/locations/MDW",
        "model_probability": 0.95,
        "market_probability": 0.32,
        "captured_at": "20260601T010923Z",
    }

    summary = summarize_signal_review_queue(weather_review_candidates=[review_candidate], limit=10)

    assert summary["total_blocked"] == 1
    assert summary["blocked_by_vertical"] == {"weather": 1}
    assert summary["blocked_by_source"] == {"weather_review_candidate": 1}
    item = summary["items"][0]
    assert item["vertical"] == "weather"
    assert item["market_key"] == "KXHIGHCHI-26JUN01-T72"
    assert item["title"] == "Chicago — KXHIGHCHI-26JUN01-T72"
    assert item["primary_blocker"] == "review-only candidate; not paper-actionable until independently revalidated"
    assert item["edge"] == 0.63
    assert item["execution_spread"] == 0.03
    assert item["top_ask_size"] == 208.09
    assert item["settlement_source"] == "NWS CLI"
    assert item["settlement_url"] == "https://api.weather.gov/products/types/CLI/locations/MDW"
    assert item["model_probability"] == 0.95
    assert item["market_probability"] == 0.32


def test_signal_review_queue_includes_polymarket_weather_source_states_as_source_only_blockers():
    source_state = {
        "captured_at": "20260602T010604Z",
        "event_slug": "highest-temperature-in-seoul-on-june-2",
        "condition_id": "pm-seoul-jun2-28c",
        "question": "Will the high temperature in Seoul be 28°C or higher on June 2?",
        "outcome": "Yes",
        "closed": False,
        "settlement_source": "Wunderground",
        "settlement_station": "RKSI",
        "settlement_station_name": "Seoul Incheon International Airport",
        "settlement_source_url": "https://www.wunderground.com/history/daily/kr/seoul/RKSI",
        "settlement_units": "C",
        "settlement_precision": "whole_degree_celsius",
        "source_capture_status": "history_no_data_recorded",
        "source_observed_value": None,
        "source_observed_unit": "celsius",
        "source_observed_at": None,
        "source_capture_snapshot": "/tmp/seoul-rksi-source.html",
        "best_bid": 0.47,
        "best_ask": 0.48,
        "execution_spread": 0.01,
        "top_ask_size": 383.81,
        "paper_actionable": False,
        "source_state_label": "Polymarket weather source-state only / non-actionable",
    }

    summary = summarize_signal_review_queue(weather_source_states=[source_state], limit=10)

    assert summary["total_blocked"] == 1
    assert summary["blocked_by_vertical"] == {"weather": 1}
    assert summary["blocked_by_source"] == {"polymarket_weather_source_state": 1}
    item = summary["items"][0]
    assert item["market_key"] == "pm-seoul-jun2-28c"
    assert item["title"] == "Will the high temperature in Seoul be 28°C or higher on June 2?"
    assert item["primary_blocker"] == "Polymarket weather source-state only / non-actionable"
    assert item["settlement_source"] == "Wunderground"
    assert item["settlement_url"] == "https://www.wunderground.com/history/daily/kr/seoul/RKSI"
    assert item["settlement_station"] == "RKSI"
    assert item["settlement_station_name"] == "Seoul Incheon International Airport"
    assert item["settlement_units"] == "C"
    assert item["settlement_precision"] == "whole_degree_celsius"
    assert item["source_capture_status"] == "history_no_data_recorded"
    assert item["source_observed_unit"] == "celsius"
    assert item["source_capture_snapshot"] == "/tmp/seoul-rksi-source.html"
    assert item["best_bid"] == 0.47
    assert item["best_ask"] == 0.48
    assert item["execution_spread"] == 0.01
    assert item["top_ask_size"] == 383.81
    assert item["market_closed"] is False
    assert item["source_state_label"] == "Polymarket weather source-state only / non-actionable"


def test_signal_review_queue_preserves_rt_candidate_reason_lists():
    rt_candidate = {
        "event_slug": "passenger-rotten-tomatoes-score",
        "title": "Passenger >= 50 Tomatometer",
        "paper_actionable": False,
        "no_trade_reasons": [
            "review count/timing risk gate blocks action",
            "source-state snapshot is current-state evidence, not an independent calibrated forecast",
        ],
        "top_ask_size": 83.33,
        "execution_spread": 0.059,
        "best_bid": 0.001,
        "best_ask": 0.005,
        "threshold": 50,
        "box_office_lower_m": None,
        "box_office_upper_m": None,
        "box_office_bucket_label": None,
        "box_office_bucket_type": None,
        "box_office_bucket_set_size": 5,
        "box_office_bucket_set_probability_mass": 0.998,
        "box_office_bucket_set_sanity_passed": True,
        "box_office_resolved_yes_count": 1,
        "box_office_resolved_winner_label": ">$79M",
        "market_closed": False,
        "source_method": "rt_embedded_json",
        "hours_since_source_refresh": 1.5,
        "source_url": "https://www.rottentomatoes.com/m/passenger_2026",
        "direct_source_status": "fresh",
        "tomatometer_score": 44,
        "review_count": 64,
        "previous_tomatometer_score": 43,
        "previous_review_count": 56,
        "score_delta": 1,
        "review_count_delta": 8,
        "hours_since_previous_source": 24.0,
        "captured_at": "2026-05-24T21:02:34Z",
        "cutoff_time": "2026-05-25T10:00:00-04:00",
        "timing_risk_label": "medium timing risk: below 75-review gate",
        "source_state_label": "RT source-state: fresh direct score",
    }

    summary = summarize_signal_review_queue(rt_source_states=[rt_candidate])

    assert summary["total_blocked"] == 1
    item = summary["items"][0]
    assert item["vertical"] == "rt_entertainment"
    assert item["market_key"] == "passenger-rotten-tomatoes-score"
    assert item["primary_blocker"] == "review count/timing risk gate blocks action"
    assert item["no_trade_reasons"] == rt_candidate["no_trade_reasons"]
    assert item["top_ask_size"] == 83.33
    assert item["execution_spread"] == 0.059
    assert item["best_bid"] == 0.001
    assert item["best_ask"] == 0.005
    assert item["threshold"] == 50
    assert item["box_office_lower_m"] is None
    assert item["box_office_upper_m"] is None
    assert item["box_office_bucket_label"] is None
    assert item["box_office_bucket_type"] is None
    assert item["box_office_bucket_set_size"] == 5
    assert item["box_office_bucket_set_probability_mass"] == 0.998
    assert item["box_office_bucket_set_sanity_passed"] is True
    assert item["box_office_resolved_yes_count"] == 1
    assert item["box_office_resolved_winner_label"] == ">$79M"
    assert item["market_closed"] is False
    assert item["source_method"] == "rt_embedded_json"
    assert item["source_url"] == "https://www.rottentomatoes.com/m/passenger_2026"
    assert item["direct_source_status"] == "fresh"
    assert item["tomatometer_score"] == 44
    assert item["review_count"] == 64
    assert item["previous_tomatometer_score"] == 43
    assert item["previous_review_count"] == 56
    assert item["score_delta"] == 1
    assert item["review_count_delta"] == 8
    assert item["hours_since_previous_source"] == 24.0
    assert item["captured_at"] == "2026-05-24T21:02:34Z"
    assert item["cutoff_time"] == "2026-05-25T10:00:00-04:00"
    assert item["timing_risk_label"] == "medium timing risk: below 75-review gate"
    assert item["source_state_label"] == "RT source-state: fresh direct score"


def test_signal_review_queue_preserves_btc_chainlink_boundary_evidence_fields():
    btc_signal = SimpleNamespace(
        market=SimpleNamespace(market_id="btc-updown-5m-1779872700", slug="btc-updown-5m-1779872700"),
        market_title="BTC Up or Down",
        passes_threshold=False,
        no_trade_reasons=["missing Chainlink boundary source snapshot for this 5-minute window"],
        edge=0.02,
        settlement_source="Chainlink BTC/USD",
        settlement_url="https://data.chain.link/streams/btc-usd",
        model_price_source="coinbase",
        chainlink_feed_id="0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8",
        chainlink_capture_method="chainlink_data_streams_rest",
        chainlink_source_url="https://data.chain.link/streams/btc-usd",
        chainlink_start_price=107250.11,
        chainlink_end_price=107262.77,
        chainlink_start_observed_at=1779872700,
        chainlink_end_observed_at=1779873000,
        chainlink_start_source_snapshot_path="/tmp/chainlink-start.json",
        chainlink_end_source_snapshot_path="/tmp/chainlink-end.json",
    )

    summary = summarize_signal_review_queue(btc_signals=[btc_signal])
    item = summary["items"][0]

    assert item["chainlink_feed_id"] == btc_signal.chainlink_feed_id
    assert item["chainlink_capture_method"] == "chainlink_data_streams_rest"
    assert item["chainlink_source_url"] == "https://data.chain.link/streams/btc-usd"
    assert item["chainlink_start_price"] == 107250.11
    assert item["chainlink_end_price"] == 107262.77
    assert item["chainlink_start_observed_at"] == 1779872700
    assert item["chainlink_end_observed_at"] == 1779873000
    assert item["chainlink_start_source_snapshot_path"] == "/tmp/chainlink-start.json"
    assert item["chainlink_end_source_snapshot_path"] == "/tmp/chainlink-end.json"
