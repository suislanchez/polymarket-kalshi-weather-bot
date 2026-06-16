from datetime import datetime, timezone
from types import SimpleNamespace

from backend.core.btc_methodology import (
    CHAINLINK_BTC_USD_FEED_ID,
    BtcChainlinkBoundarySnapshot,
    build_chainlink_boundary_report_requests,
    derive_btc_window_boundary_timestamps,
    evaluate_btc_no_trade_gate,
    persist_btc_price_snapshot,
    validate_chainlink_boundary_snapshot,
)
from backend.data.crypto import BtcMicrostructure


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


class FakeSnapshot:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_btc_window_boundary_timestamps_are_derived_from_market_window_datetimes():
    class FakeMarket:
        window_start = datetime(2026, 5, 26, 19, 10, tzinfo=timezone.utc)
        window_end = datetime(2026, 5, 26, 19, 15, tzinfo=timezone.utc)

    start_ts, end_ts = derive_btc_window_boundary_timestamps(FakeMarket())

    assert start_ts == 1779822600
    assert end_ts == 1779822900


def test_btc_window_boundary_timestamps_return_none_when_window_missing():
    class FakeMarket:
        window_start = None
        window_end = None

    assert derive_btc_window_boundary_timestamps(FakeMarket()) == (None, None)


def test_chainlink_boundary_report_requests_preserve_exact_market_boundaries_and_auth_status():
    market = SimpleNamespace(
        window_start=datetime(2026, 5, 29, 19, 10, tzinfo=timezone.utc),
        window_end=datetime(2026, 5, 29, 19, 15, tzinfo=timezone.utc),
    )

    requests = build_chainlink_boundary_report_requests(market)

    assert [request.boundary for request in requests] == ["start", "end"]
    assert [request.timestamp for request in requests] == [1780081800, 1780082100]
    assert all(request.feed_id == CHAINLINK_BTC_USD_FEED_ID for request in requests)
    assert all("/api/v1/reports?" in request.url for request in requests)
    assert all(f"feedID={CHAINLINK_BTC_USD_FEED_ID}" in request.url for request in requests)
    assert "timestamp=1780081800" in requests[0].url
    assert "timestamp=1780082100" in requests[1].url
    assert all(request.requires_authentication is True for request in requests)
    assert all(request.status == "auth_required_not_fetched" for request in requests)


def test_persist_btc_price_snapshot_records_microstructure_source():
    fake_db = FakeDb()
    micro = BtcMicrostructure(price=104321.25, source="coinbase", rsi=51.0)

    saved = persist_btc_price_snapshot(
        micro,
        db_factory=lambda: fake_db,
        snapshot_cls=FakeSnapshot,
    )

    assert saved is True
    assert fake_db.committed is True
    assert fake_db.closed is True
    assert len(fake_db.added) == 1
    snapshot = fake_db.added[0]
    assert snapshot.price == 104321.25
    assert snapshot.source == "coinbase"


def test_btc_gate_blocks_exchange_spot_model_even_with_good_clob_depth():
    gate = evaluate_btc_no_trade_gate(
        direction="up",
        settlement_source="Chainlink BTC/USD",
        model_price_source="coinbase",
        up_bid=0.50,
        up_ask=0.51,
        up_ask_size=250.0,
        down_bid=0.49,
        down_ask=0.50,
        down_ask_size=250.0,
        max_entry_price=0.55,
    )

    assert gate.actionable is False
    assert gate.entry_price == 0.51
    assert gate.spread == 0.01
    assert any("not Chainlink" in reason for reason in gate.reasons)


def test_btc_gate_requires_line_level_depth_and_spread():
    gate = evaluate_btc_no_trade_gate(
        direction="down",
        settlement_source="Chainlink BTC/USD",
        model_price_source="chainlink_stream_snapshot",
        up_bid=0.50,
        up_ask=0.51,
        up_ask_size=100.0,
        down_bid=0.47,
        down_ask=0.51,
        down_ask_size=20.0,
        max_entry_price=0.55,
        max_spread=0.02,
        min_top_ask_size=50.0,
    )

    assert gate.actionable is False
    assert any("spread" in reason for reason in gate.reasons)
    assert any("top ask size" in reason for reason in gate.reasons)


def test_btc_gate_blocks_chainlink_labeled_model_without_boundary_snapshot():
    gate = evaluate_btc_no_trade_gate(
        direction="up",
        settlement_source="Chainlink BTC/USD",
        model_price_source="chainlink_stream_snapshot",
        up_bid=0.50,
        up_ask=0.51,
        up_ask_size=250.0,
        down_bid=0.49,
        down_ask=0.50,
        down_ask_size=250.0,
        max_entry_price=0.55,
        max_spread=0.02,
        min_top_ask_size=50.0,
    )

    assert gate.actionable is False
    assert any("boundary source" in reason for reason in gate.reasons)
    assert any("observation timestamp" in reason for reason in gate.reasons)
    assert any("feed id" in reason for reason in gate.reasons)
    assert any("capture method" in reason for reason in gate.reasons)


def test_btc_chainlink_boundary_snapshot_preserves_feed_and_timestamp_metadata():
    snapshot = BtcChainlinkBoundarySnapshot(
        price=77370.12,
        observed_at=1779700200,
        method="chainlink_data_streams_rest",
        source_snapshot_path="/tmp/chainlink-1779700200.json",
    )

    assert snapshot.price == 77370.12
    assert snapshot.observed_at == 1779700200
    assert snapshot.feed_id == CHAINLINK_BTC_USD_FEED_ID
    assert snapshot.method == "chainlink_data_streams_rest"
    assert snapshot.source_snapshot_path == "/tmp/chainlink-1779700200.json"
    assert validate_chainlink_boundary_snapshot(snapshot, expected_observed_at=1779700200) == []


def test_btc_chainlink_boundary_validator_blocks_wrong_boundary_timestamp():
    snapshot = BtcChainlinkBoundarySnapshot(
        price=77370.12,
        observed_at=1779700201,
        method="chainlink_data_streams_rest",
        source_snapshot_path="/tmp/chainlink-1779700201.json",
    )

    reasons = validate_chainlink_boundary_snapshot(snapshot, expected_observed_at=1779700200)

    assert any("does not match expected market boundary" in reason for reason in reasons)


def test_btc_gate_blocks_boundary_prices_without_metadata():
    gate = evaluate_btc_no_trade_gate(
        direction="up",
        settlement_source="Chainlink BTC/USD",
        model_price_source="chainlink_stream_snapshot",
        up_bid=0.50,
        up_ask=0.51,
        up_ask_size=250.0,
        down_bid=0.49,
        down_ask=0.50,
        down_ask_size=250.0,
        max_entry_price=0.55,
        max_spread=0.02,
        min_top_ask_size=50.0,
        chainlink_start_price=74500.0,
        chainlink_end_price=74512.5,
    )

    assert gate.actionable is False
    assert any("observation timestamp" in reason for reason in gate.reasons)
    assert any("feed id" in reason for reason in gate.reasons)
    assert any("capture method" in reason for reason in gate.reasons)


def test_btc_gate_can_pass_for_chainlink_aligned_source_good_book_and_boundary_snapshot():
    gate = evaluate_btc_no_trade_gate(
        direction="up",
        settlement_source="Chainlink BTC/USD",
        model_price_source="chainlink_stream_snapshot",
        up_bid=0.50,
        up_ask=0.51,
        up_ask_size=250.0,
        down_bid=0.49,
        down_ask=0.50,
        down_ask_size=250.0,
        max_entry_price=0.55,
        max_spread=0.02,
        min_top_ask_size=50.0,
        chainlink_start_price=74500.0,
        chainlink_end_price=74512.5,
        chainlink_start_observed_at=1779700200,
        chainlink_end_observed_at=1779700500,
        chainlink_feed_id=CHAINLINK_BTC_USD_FEED_ID,
        chainlink_capture_method="chainlink_data_streams_rest",
        chainlink_start_source_snapshot_path="/tmp/chainlink-1779700200.json",
        chainlink_end_source_snapshot_path="/tmp/chainlink-1779700500.json",
        expected_window_start_ts=1779700200,
        expected_window_end_ts=1779700500,
    )

    assert gate.actionable is True
    assert gate.reasons == []
    assert gate.entry_price == 0.51
    assert gate.top_ask_size == 250.0


def test_btc_simulation_guard_rejects_filtered_signal():
    from backend.core.btc_methodology import validate_btc_signal_for_simulation

    class FakeSignal:
        actionable = False
        suggested_size = 0.0
        no_trade_reasons = ["model price source coinbase is not Chainlink settlement source"]

        @property
        def passes_threshold(self):
            return False

    allowed, reason = validate_btc_signal_for_simulation(FakeSignal())

    assert allowed is False
    assert "No paper BTC trade" in reason
    assert "not Chainlink" in reason


def test_btc_simulation_guard_accepts_threshold_passing_signal():
    from backend.core.btc_methodology import validate_btc_signal_for_simulation

    class FakeSignal:
        actionable = True
        suggested_size = 12.5
        no_trade_reasons = []

        @property
        def passes_threshold(self):
            return True

    allowed, reason = validate_btc_signal_for_simulation(FakeSignal())

    assert allowed is True
    assert reason == ""


def test_btc_signal_db_kwargs_preserve_market_type_and_event_slug_for_calibration():
    from backend.core.btc_signal_persistence import btc_signal_to_db_kwargs

    fake_market = SimpleNamespace(
        market_id="condition-123",
        slug="btc-updown-5m-1779959100",
    )
    fake_signal = SimpleNamespace(
        market=fake_market,
        timestamp=datetime(2026, 5, 28, 9, 5, tzinfo=timezone.utc),
        direction="up",
        model_probability=0.54,
        market_probability=0.51,
        edge=0.03,
        confidence=0.62,
        kelly_fraction=0.01,
        suggested_size=10.0,
        sources=["binance_microstructure_coinbase"],
        reasoning="filtered; source mismatch remains visible",
    )

    kwargs = btc_signal_to_db_kwargs(fake_signal)

    assert kwargs["market_ticker"] == "condition-123"
    assert kwargs["market_type"] == "btc"
    assert kwargs["event_slug"] == "btc-updown-5m-1779959100"
    assert kwargs["sources"] == ["binance_microstructure_coinbase"]
    assert kwargs["executed"] is False
