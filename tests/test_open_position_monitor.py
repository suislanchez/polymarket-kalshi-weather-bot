from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from datetime import datetime

from backend.core.open_position_monitor import OpenPositionRiskSummary, run_open_position_risk_scan
from backend.core.position_risk import ExitRecommendation, RiskAction
from backend.core.weather_exit_quotes import WeatherExitQuote
from backend.models.database import Base, BotState, Signal, Trade


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'open_position_monitor.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _recommendation(action=RiskAction.WATCH, exit_price=0.10, exit_pnl=-77.78):
    return ExitRecommendation(
        action=action,
        reasons=["model probability below exit threshold"] if action == RiskAction.EXIT else ["source/model evidence incomplete"],
        exit_price=exit_price,
        exit_pnl=exit_pnl,
        unrealized_pnl=exit_pnl,
        model_probability_for_held_side=0.05,
        market_probability_for_held_side=exit_price,
        source_status="fresh",
        evidence={"source_confidence": "final", "station_known": True},
    )


def _add_trade(db, market_type="weather", settled=False, closed_early=False):
    trade = Trade(
        market_ticker=f"{market_type}-market",
        platform="polymarket",
        event_slug=f"{market_type}-event",
        market_type=market_type,
        direction="yes" if market_type != "btc" else "up",
        entry_price=0.45,
        size=100.0,
        settled=settled,
        closed_early=closed_early,
        result="pending" if not settled else "win",
    )
    db.add(trade)
    db.commit()
    return trade


def test_monitor_updates_mark_to_market_without_exiting_when_auto_exit_disabled(tmp_path):
    db = _session(tmp_path)
    trade = _add_trade(db, market_type="weather")

    summary = run_open_position_risk_scan(
        db,
        analyzers={"weather": lambda trade: _recommendation(action=RiskAction.EXIT)},
        auto_exit_enabled=False,
    )

    db.refresh(trade)
    assert isinstance(summary, OpenPositionRiskSummary)
    assert summary.total_open_positions == 1
    assert summary.action_counts["exit"] == 1
    assert summary.exited_count == 0
    assert trade.closed_early is False
    assert trade.settled is False
    assert trade.last_risk_action == "exit"
    assert trade.last_mark_price == 0.10
    assert trade.unrealized_pnl == -77.78
    assert trade.last_risk_source_status == "fresh"
    assert trade.last_risk_evidence == {"source_confidence": "final", "station_known": True}


def test_monitor_summary_rows_preserve_risk_source_status_and_evidence(tmp_path):
    db = _session(tmp_path)
    _add_trade(db, market_type="weather")

    summary = run_open_position_risk_scan(
        db,
        analyzers={"weather": lambda trade: _recommendation(action=RiskAction.WATCH)},
        auto_exit_enabled=False,
    )

    assert summary.rows[0]["source_status"] == "fresh"
    assert summary.rows[0]["risk_evidence"] == {"source_confidence": "final", "station_known": True}

def test_monitor_executes_eligible_paper_exit_only_when_auto_exit_enabled(tmp_path):
    db = _session(tmp_path)
    state = BotState(bankroll=1000.0, total_pnl=0.0)
    trade = _add_trade(db, market_type="weather")
    db.add(state)
    db.commit()

    summary = run_open_position_risk_scan(
        db,
        analyzers={"weather": lambda trade: _recommendation(action=RiskAction.EXIT)},
        auto_exit_enabled=True,
    )

    db.refresh(trade)
    assert summary.exited_count == 1
    assert trade.closed_early is True
    assert trade.result == "exited"
    assert trade.pnl == -77.78
    assert state.bankroll == 922.22


def test_monitor_routes_by_market_type_and_skips_closed_trades(tmp_path):
    db = _session(tmp_path)
    _add_trade(db, market_type="weather")
    _add_trade(db, market_type="btc")
    _add_trade(db, market_type="weather", settled=True)
    calls = []

    def analyzer(trade):
        calls.append((trade.market_type, trade.market_ticker))
        return _recommendation(action=RiskAction.WATCH, exit_price=0.20, exit_pnl=-55.56)

    summary = run_open_position_risk_scan(
        db,
        analyzers={"weather": analyzer, "btc": analyzer},
        auto_exit_enabled=False,
    )

    assert summary.total_open_positions == 2
    assert sorted(market_type for market_type, _ in calls) == ["btc", "weather"]
    assert summary.action_counts["watch"] == 2


def test_default_weather_risk_analyzer_uses_latest_signal_evidence_without_auto_exit(tmp_path):
    db = _session(tmp_path)
    trade = _add_trade(db, market_type="weather")
    latest_signal = Signal(
        market_ticker=trade.market_ticker,
        platform="kalshi",
        market_type="weather",
        timestamp=datetime(2026, 6, 3, 20, 1, 0),
        direction="yes",
        model_probability=0.08,
        market_price=0.32,
        edge=0.0,
        confidence=0.7,
        kelly_fraction=0.0,
        suggested_size=0.0,
        sources=[
            "settlement:nws_cli:KNYC",
            "settlement_url:https://forecast.weather.gov/product.php?site=OKX&product=CLI&issuedby=NYC",
        ],
        reasoning="[FILTERED] missing executable exit quote; final source not captured",
        executed=False,
    )
    db.add(latest_signal)
    db.commit()

    summary = run_open_position_risk_scan(db, auto_exit_enabled=False)

    db.refresh(trade)
    row = summary.rows[0]
    assert summary.total_open_positions == 1
    assert summary.exited_count == 0
    assert trade.closed_early is False
    assert trade.last_risk_action == "watch"
    assert trade.last_risk_source_status == "latest_weather_signal_quote_not_executable"
    assert trade.last_risk_evidence["latest_signal_id"] == latest_signal.id
    assert trade.last_risk_evidence["settlement_source_known"] is True
    assert trade.last_risk_evidence["station_known"] is True
    assert trade.last_risk_evidence["settlement_url"].startswith("https://forecast.weather.gov/")
    assert row["source_status"] == "latest_weather_signal_quote_not_executable"
    assert row["settlement_source_known"] is True
    assert row["station_known"] is True
    assert row["settlement_url"].startswith("https://forecast.weather.gov/")
    assert row["settlement_tags"] == ["settlement:nws_cli:KNYC"]
    assert row["latest_signal_id"] == latest_signal.id
    assert row["latest_signal_timestamp"] == "2026-06-03T20:01:00"
    assert row["latest_signal_market_price"] == 0.32
    assert row["latest_signal_edge"] == 0.0
    assert row["latest_signal_suggested_size"] == 0.0
    assert row["latest_signal_model_probability_for_held_side"] == 0.08
    assert row["model_probability_for_held_side"] == 0.08
    assert "missing executable exit price" in row["reasons"]


def test_weather_risk_scan_uses_live_exit_quote_provider_without_auto_exit(tmp_path):
    db = _session(tmp_path)
    trade = _add_trade(db, market_type="weather")
    trade.platform = "kalshi"
    trade.direction = "yes"
    trade.entry_price = 0.45
    trade.size = 100.0
    latest_signal = Signal(
        market_ticker=trade.market_ticker,
        platform="kalshi",
        market_type="weather",
        timestamp=datetime(2026, 6, 4, 6, 2, 0),
        direction="yes",
        model_probability=0.08,
        market_price=0.32,
        edge=0.0,
        confidence=0.7,
        kelly_fraction=0.0,
        suggested_size=0.0,
        sources=[
            "settlement:nws_cli:KMDW",
            "settlement_url:https://forecast.weather.gov/product.php?site=LOT&product=CLI&issuedby=MDW",
        ],
        reasoning="[FILTERED] thesis deteriorated; live quote should be recommendations-only",
        executed=False,
    )
    db.add(latest_signal)
    db.commit()

    def quote_provider(seen_trade):
        assert seen_trade.id == trade.id
        return WeatherExitQuote(
            platform="kalshi",
            market_ticker=trade.market_ticker,
            held_side="yes",
            held_side_bid=0.22,
            held_side_ask=0.24,
            top_bid_size=30.0,
            top_ask_size=50.0,
            source_status="live_weather_exit_quote",
            evidence={"quote_source": "fake_public_orderbook"},
        )

    summary = run_open_position_risk_scan(
        db,
        auto_exit_enabled=False,
        weather_quote_provider=quote_provider,
    )

    db.refresh(trade)
    row = summary.rows[0]
    assert summary.exited_count == 0
    assert trade.closed_early is False
    assert trade.last_risk_action == "exit"
    assert trade.last_mark_price == 0.22
    assert trade.unrealized_pnl == -51.11
    assert trade.last_risk_source_status == "live_weather_exit_quote"
    assert trade.last_risk_evidence["quote_source"] == "fake_public_orderbook"
    assert row["current_exit_price"] == 0.22
    assert row["live_exit_quote_bid"] == 0.22
    assert row["live_exit_quote_ask"] == 0.24
    assert row["live_exit_quote_top_bid_size"] == 30.0
    assert row["live_exit_quote_top_ask_size"] == 50.0
    assert row["live_exit_quote_source"] == "fake_public_orderbook"
    assert row["market_probability_for_held_side"] == 0.22
    assert "model probability below exit threshold" in row["reasons"]


def test_weather_risk_scan_surfaces_live_exit_quote_fetch_error_as_typed_row_field(tmp_path):
    db = _session(tmp_path)
    trade = _add_trade(db, market_type="weather")
    trade.platform = "polymarket"
    trade.direction = "yes"
    latest_signal = Signal(
        market_ticker=trade.market_ticker,
        platform="polymarket",
        market_type="weather",
        timestamp=datetime(2026, 6, 8, 6, 5, 0),
        direction="yes",
        model_probability=0.55,
        market_price=0.12,
        edge=0.43,
        confidence=0.7,
        kelly_fraction=0.0,
        suggested_size=0.0,
        sources=[
            "settlement:wunderground:RKSI",
            "settlement_url:https://www.wunderground.com/history/daily/kr/incheon/RKSI",
        ],
        reasoning="[FILTERED] live exit quote failed; keep recommendations-only",
        executed=False,
    )
    db.add(latest_signal)
    db.commit()

    def quote_provider(seen_trade):
        assert seen_trade.id == trade.id
        return WeatherExitQuote(
            platform="polymarket",
            market_ticker=trade.market_ticker,
            held_side="yes",
            held_side_bid=None,
            held_side_ask=None,
            top_bid_size=None,
            top_ask_size=None,
            source_status="live_weather_exit_quote_fetch_error",
            evidence={"quote_error": "CLOB book 404 for held YES token"},
        )

    summary = run_open_position_risk_scan(
        db,
        auto_exit_enabled=False,
        weather_quote_provider=quote_provider,
    )

    db.refresh(trade)
    row = summary.rows[0]
    assert summary.exited_count == 0
    assert summary.live_exit_quote_error_count == 1
    assert trade.closed_early is False
    assert trade.last_risk_source_status == "live_weather_exit_quote_fetch_error"
    assert trade.last_risk_evidence["quote_error"] == "CLOB book 404 for held YES token"
    assert row["source_status"] == "live_weather_exit_quote_fetch_error"
    assert row["live_exit_quote_bid"] is None
    assert row["live_exit_quote_error"] == "CLOB book 404 for held YES token"


def test_weather_risk_summary_counts_closed_or_stale_exit_tokens_separately(tmp_path):
    db = _session(tmp_path)
    trade = _add_trade(db, market_type="weather")
    trade.platform = "polymarket"
    trade.direction = "yes"
    latest_signal = Signal(
        market_ticker=trade.market_ticker,
        platform="polymarket",
        market_type="weather",
        timestamp=datetime(2026, 6, 8, 20, 0, 0),
        direction="yes",
        model_probability=0.55,
        market_price=0.12,
        edge=0.43,
        confidence=0.7,
        kelly_fraction=0.0,
        suggested_size=0.0,
        sources=[
            "settlement:wunderground:RKSI",
            "settlement_url:https://www.wunderground.com/history/daily/kr/incheon/RKSI",
        ],
        reasoning="[FILTERED] closed/stale held token; keep recommendations-only",
        executed=False,
    )
    db.add(latest_signal)
    db.commit()

    def quote_provider(seen_trade):
        assert seen_trade.id == trade.id
        return WeatherExitQuote(
            platform="polymarket",
            market_ticker=trade.market_ticker,
            held_side="yes",
            held_side_bid=None,
            held_side_ask=None,
            top_bid_size=None,
            top_ask_size=None,
            source_status="closed_market_or_stale_token",
            evidence={
                "quote_source": "polymarket_gamma_clob",
                "quote_error": "CLOB book 404 for held YES token",
                "gamma_closed": True,
            },
        )

    summary = run_open_position_risk_scan(
        db,
        auto_exit_enabled=False,
        weather_quote_provider=quote_provider,
    )

    db.refresh(trade)
    row = summary.rows[0]
    assert summary.exited_count == 0
    assert summary.live_exit_quote_error_count == 1
    assert summary.closed_market_or_stale_token_count == 1
    assert summary.source_status_counts == {"closed_market_or_stale_token": 1}
    assert trade.closed_early is False
    assert trade.last_risk_source_status == "closed_market_or_stale_token"
    assert row["source_status"] == "closed_market_or_stale_token"
    assert row["live_exit_quote_error"] == "CLOB book 404 for held YES token"
