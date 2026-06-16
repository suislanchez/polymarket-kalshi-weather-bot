import ast
import asyncio
from pathlib import Path

from backend.api.schemas import (
    BtcCalibrationRowResponse,
    BtcCalibrationSummaryResponse,
    BtcWindowResponse,
    BotStats,
    DashboardData,
    EntertainmentCalibrationSummaryResponse,
    EventResponse,
    OpenPositionRiskRowResponse,
    OpenPositionRiskSummaryResponse,
    PolymarketWeatherSourceStateResponse,
    PolymarketWeatherSourceStateSummaryResponse,
    SignalReviewBlockerResponse,
    SignalReviewItemResponse,
    SignalReviewQueueResponse,
    WeatherCalibrationRowResponse,
    WeatherCalibrationSummaryResponse,
    WeatherBotCalibrationRowResponse,
    WeatherSignalReviewCandidateResponse,
)


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def test_fastapi_route_module_reuses_dependency_light_schema_models_without_duplicate_classes():
    """Keep /api/dashboard contracts in backend.api.schemas, not route-local copies."""
    main_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "main.py"
    tree = ast.parse(main_path.read_text())
    route_local_classes = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }

    duplicated_schema_classes = {
        "BtcPriceResponse",
        "BtcWindowResponse",
        "MicrostructureResponse",
        "SignalResponse",
        "TradeResponse",
        "BotStats",
        "CalibrationBucket",
        "CalibrationSummary",
        "WeatherCalibrationSummaryResponse",
        "WeatherCalibrationRowResponse",
        "WeatherBotCalibrationRowResponse",
        "WeatherSignalReviewCandidateResponse",
        "PolymarketWeatherSourceStateResponse",
        "BtcCalibrationSummaryResponse",
        "BtcCalibrationRowResponse",
        "EntertainmentCalibrationSummaryResponse",
        "WeatherForecastResponse",
        "WeatherMarketResponse",
        "WeatherSignalResponse",
        "RottenTomatoesSourceStateResponse",
        "OpenPositionRiskRowResponse",
        "DashboardData",
        "EventResponse",
    }

    assert route_local_classes.isdisjoint(duplicated_schema_classes)


def test_dashboard_weather_only_scope_disables_legacy_dashboard_sections_by_default(monkeypatch):
    """Weather-only product scope should keep dashboard/API focused on weather unless explicitly overridden."""
    from backend.api import main
    from backend.config import settings

    original_scope = getattr(settings, "ACTIVE_PRODUCT_SCOPE", None)
    original_legacy = getattr(settings, "DASHBOARD_LEGACY_SECTIONS_ENABLED", None)
    try:
        settings.ACTIVE_PRODUCT_SCOPE = "weather"
        settings.DASHBOARD_LEGACY_SECTIONS_ENABLED = False
        assert main._legacy_dashboard_sections_enabled() is False
        assert main._dashboard_legacy_note() == "Legacy BTC and RT/entertainment dashboard sections paused in weather-only scope"

        settings.DASHBOARD_LEGACY_SECTIONS_ENABLED = True
        assert main._legacy_dashboard_sections_enabled() is True
        assert main._dashboard_legacy_note() is None

        settings.DASHBOARD_LEGACY_SECTIONS_ENABLED = False
        settings.ACTIVE_PRODUCT_SCOPE = "all"
        assert main._legacy_dashboard_sections_enabled() is True
        assert main._dashboard_legacy_note() is None
    finally:
        if original_scope is not None:
            settings.ACTIVE_PRODUCT_SCOPE = original_scope
        if original_legacy is not None:
            settings.DASHBOARD_LEGACY_SECTIONS_ENABLED = original_legacy


def test_dashboard_weather_only_scope_skips_legacy_btc_rt_loaders_and_review_queue_inputs():
    """Default dashboard should not refresh paused BTC/RT panels in weather-only scope."""
    main_source = (Path(__file__).resolve().parents[1] / "backend" / "api" / "main.py").read_text()
    app_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx").read_text()
    stats_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "StatsCards.tsx").read_text()
    edge_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "EdgeDistribution.tsx").read_text()

    assert "legacy_sections_enabled = _legacy_dashboard_sections_enabled()" in main_source
    assert "btc_calibration = _load_latest_btc_calibration_summary() if legacy_sections_enabled else None" in main_source
    assert "entertainment_calibration = _load_latest_entertainment_calibration_summary() if legacy_sections_enabled else None" in main_source
    assert "btc_signals=signals if legacy_sections_enabled else []" in main_source
    assert "rt_source_states=rt_review_rows if legacy_sections_enabled else []" in main_source
    assert "legacy_dashboard_sections_enabled=legacy_sections_enabled" in main_source
    assert "legacy_dashboard_note=_dashboard_legacy_note()" in main_source

    assert "showLegacyDashboardSections" in app_source
    assert "WEATHER PAPER TERMINAL" in app_source
    assert "Weather temp paper ledger + source QA" in app_source
    assert "showLegacySections={showLegacyDashboardSections}" in app_source
    assert "showLegacySections && btc" in stats_source
    assert "showLegacySections && entertainment" in stats_source
    assert "showLegacySections && <Bar dataKey=\"BTC\"" in edge_source


def test_weather_only_stats_aggregate_uses_weather_account_not_legacy_bot_state():
    """Weather-only /api/stats aggregate fields should mirror the active $1,000 weather ledger."""
    from datetime import datetime
    from types import SimpleNamespace

    from backend.api import main

    state = SimpleNamespace(
        bankroll=12_000.0,
        total_trades=99,
        winning_trades=50,
        total_pnl=2_000.0,
        is_running=True,
        last_run=datetime(2026, 6, 1, 12),
    )
    weather_account = {
        "current_equity": 1_075.0,
        "realized_pnl": 75.0,
        "total_trades": 3,
        "winning_trades": 2,
    }

    scoped = main._aggregate_bot_stats_for_scope(
        state,
        weather_account=weather_account,
        legacy_sections_enabled=False,
    )
    legacy = main._aggregate_bot_stats_for_scope(
        state,
        weather_account=weather_account,
        legacy_sections_enabled=True,
    )

    assert scoped["bankroll"] == 1_075.0
    assert scoped["total_pnl"] == 75.0
    assert scoped["total_trades"] == 3
    assert scoped["winning_trades"] == 2
    assert scoped["win_rate"] == 2 / 3
    assert scoped["is_running"] is True
    assert scoped["last_run"] == datetime(2026, 6, 1, 12)
    assert legacy["bankroll"] == 12_000.0
    assert legacy["total_trades"] == 99


def test_dashboard_weather_only_scope_filters_recent_trades_and_equity_to_weather(tmp_path):
    """Weather-only dashboard trade/equity panels should not surface paused BTC/RT trades."""
    from datetime import datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.api import main
    from backend.models.database import Base, Trade

    engine = create_engine(
        f"sqlite:///{tmp_path / 'dashboard_scope.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        db.add_all([
            Trade(
                market_ticker="wx-settled",
                platform="polymarket",
                market_type="weather",
                direction="yes",
                entry_price=0.40,
                size=50.0,
                timestamp=datetime(2026, 6, 1, 8),
                settled=True,
                result="win",
                pnl=75.0,
            ),
            Trade(
                market_ticker="wx-pending",
                platform="kalshi",
                market_type="polymarket_weather",
                direction="yes",
                entry_price=0.30,
                size=25.0,
                timestamp=datetime(2026, 6, 1, 9),
                settled=False,
                result="pending",
            ),
            Trade(
                market_ticker="btc-legacy",
                platform="polymarket",
                market_type="btc",
                direction="up",
                entry_price=0.50,
                size=100.0,
                timestamp=datetime(2026, 6, 1, 10),
                settled=True,
                result="win",
                pnl=100.0,
            ),
            Trade(
                market_ticker="rt-legacy",
                platform="polymarket",
                market_type="entertainment",
                direction="yes",
                entry_price=0.60,
                size=100.0,
                timestamp=datetime(2026, 6, 1, 11),
                settled=True,
                result="loss",
                pnl=-100.0,
            ),
        ])
        db.commit()

        scoped_recent = main._query_dashboard_recent_trades(db, legacy_sections_enabled=False, limit=10)
        scoped_equity = main._query_dashboard_equity_trades(db, legacy_sections_enabled=False)
        legacy_recent = main._query_dashboard_recent_trades(db, legacy_sections_enabled=True, limit=10)

        assert [trade.market_ticker for trade in scoped_recent] == ["wx-pending", "wx-settled"]
        assert [trade.market_ticker for trade in scoped_equity] == ["wx-settled"]
        assert [trade.market_ticker for trade in legacy_recent][:2] == ["rt-legacy", "btc-legacy"]
    finally:
        db.close()


def test_dashboard_weather_only_scope_filters_open_position_risk_to_weather(tmp_path):
    """Weather-only Cash-out Risk should not leak paused BTC/RT open positions."""
    from datetime import datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.api import main
    from backend.models.database import Base, Trade

    engine = create_engine(
        f"sqlite:///{tmp_path / 'open_risk_scope.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        db.add_all([
            Trade(
                market_ticker="wx-open",
                platform="polymarket",
                market_type="weather",
                direction="yes",
                entry_price=0.40,
                size=50.0,
                timestamp=datetime(2026, 6, 1, 8),
                settled=False,
                closed_early=False,
                result="pending",
            ),
            Trade(
                market_ticker="kalshi-wx-open",
                platform="kalshi",
                market_type="kalshi_weather",
                direction="yes",
                entry_price=0.30,
                size=25.0,
                timestamp=datetime(2026, 6, 1, 9),
                settled=False,
                closed_early=False,
                result="pending",
            ),
            Trade(
                market_ticker="btc-open-legacy",
                platform="polymarket",
                market_type="btc",
                direction="up",
                entry_price=0.50,
                size=100.0,
                timestamp=datetime(2026, 6, 1, 10),
                settled=False,
                closed_early=False,
                result="pending",
            ),
            Trade(
                market_ticker="rt-open-legacy",
                platform="polymarket",
                market_type="entertainment",
                direction="yes",
                entry_price=0.60,
                size=100.0,
                timestamp=datetime(2026, 6, 1, 11),
                settled=False,
                closed_early=False,
                result="pending",
            ),
            Trade(
                market_ticker="wx-closed-early",
                platform="kalshi",
                market_type="weather",
                direction="yes",
                entry_price=0.65,
                size=20.0,
                timestamp=datetime(2026, 6, 1, 12),
                settled=False,
                closed_early=True,
                result="exited",
            ),
        ])
        db.commit()

        scoped = main._query_open_position_risk_trades(db, legacy_sections_enabled=False, limit=10)
        legacy = main._query_open_position_risk_trades(db, legacy_sections_enabled=True, limit=10)

        assert [trade.market_ticker for trade in scoped] == ["kalshi-wx-open", "wx-open"]
        assert [trade.market_ticker for trade in legacy] == [
            "rt-open-legacy",
            "btc-open-legacy",
            "kalshi-wx-open",
            "wx-open",
        ]
    finally:
        db.close()


def test_stats_cards_uses_weather_account_for_primary_header_when_legacy_hidden():
    """The top Bank/P&L/Win/Trades header should mirror the active weather ledger, not legacy BotState."""
    stats_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "StatsCards.tsx").read_text()

    assert "const primaryAccount = showLegacySections ? null : weather" in stats_source
    assert "const primaryBankroll = primaryAccount?.current_equity ?? stats.bankroll" in stats_source
    assert "const primaryPnl = primaryAccount?.realized_pnl ?? stats.total_pnl" in stats_source
    assert "const primaryTrades = primaryAccount?.total_trades ?? stats.total_trades" in stats_source
    assert "const primaryWinningTrades = primaryAccount?.winning_trades ?? stats.winning_trades" in stats_source


def test_stats_cards_weather_paper_chip_surfaces_remaining_target_and_settlement_counts():
    """After settlement repairs, the weather chip should show drawdown/remaining target and settled/open counts."""
    stats_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "StatsCards.tsx").read_text()
    types_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "types.ts").read_text()
    app_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx").read_text()

    assert "weather.remaining_to_target.toFixed(0)" in stats_source
    assert "weather.settled_trades" in stats_source
    assert "weather.pending_trades" in stats_source
    assert "weather.pending_size" in stats_source
    assert "weather.ledger_exposure_state" in stats_source
    assert "weather.ledger_status_note" in stats_source
    assert "weather.platform_breakdown" in stats_source
    assert "weatherPlatformBreakdown" in stats_source
    assert "Venue split uses settled PnL only" in stats_source
    assert "Remaining to target and settled/open paper weather trade counts" in stats_source
    assert "export interface WeatherPlatformBreakdown" in types_source
    assert "platform_breakdown: WeatherPlatformBreakdown[]" in types_source
    assert "pending_size: number" in types_source
    assert "ledger_exposure_state: 'no_trades' | 'all_settled' | 'open_positions' | string" in types_source
    assert "ledger_status_note: string" in types_source
    assert "platform_breakdown: []" in app_source
    assert "ledger_exposure_state: 'no_trades' as const" in app_source
    assert "ledger_status_note: 'No weather paper trades; selective/no-forced-trade mode is preserved.'" in app_source


def test_weather_only_api_copy_does_not_default_to_btc_branding():
    """Default API metadata should match the active weather-only product scope."""
    import asyncio

    from backend.api import main

    payload = asyncio.run(main.root())

    assert main.app.title == "Weather Paper Trading Dashboard"
    assert payload["message"] == "Weather Paper Trading Dashboard API v3.0"
    assert (main.__doc__ or "").startswith("FastAPI backend for weather paper-trading dashboard")


def test_open_position_risk_row_schema_is_dependency_light_and_serializable():
    row = OpenPositionRiskRowResponse(
        trade_id=7,
        market_type="weather",
        market_ticker="weather-denver-70-71",
        event_slug="denver-weather",
        direction="yes",
        entry_price=0.45,
        size=100.0,
        current_exit_price=0.10,
        unrealized_pnl=-77.78,
        model_probability_for_held_side=0.05,
        market_probability_for_held_side=0.10,
        action="exit",
        reasons=["model probability below exit threshold"],
        source_status="fresh",
        checked_at="2026-06-01T12:00:00Z",
    )

    payload = _model_dump(row)
    assert payload["trade_id"] == 7
    assert payload["action"] == "exit"
    assert payload["unrealized_pnl"] == -77.78


def test_event_response_schema_remains_dependency_light_for_route_event_payloads():
    event = EventResponse(
        timestamp="2026-05-29T13:00:00Z",
        type="paper-scan",
        message="simulation-only scan completed",
        data={"actionable": 0},
    )

    payload = _model_dump(event)

    assert payload["type"] == "paper-scan"
    assert payload["data"] == {"actionable": 0}


def test_dashboard_loads_complete_btc_calibration_batch_before_display_limiting():
    """Keep all 8 Up/Down BTC windows visible in audit rows, not just five."""
    main_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "main.py"
    source = main_path.read_text()

    assert "_load_latest_btc_calibration_rows(limit=16)" in source


def test_btc_calibration_summary_schema_preserves_window_state_counts():
    summary = BtcCalibrationSummaryResponse(
        latest_scored_at="2026-06-03T19:00:00Z",
        scoring_rows=16,
        unique_window_count=8,
        active_window_count=1,
        upcoming_window_count=7,
        expired_window_count=0,
        min_seconds_to_window_end=300,
        max_seconds_to_window_end=2400,
    )

    payload = _model_dump(summary)

    assert payload["unique_window_count"] == 8
    assert payload["active_window_count"] == 1
    assert payload["upcoming_window_count"] == 7
    assert payload["expired_window_count"] == 0
    assert payload["min_seconds_to_window_end"] == 300
    assert payload["max_seconds_to_window_end"] == 2400


def test_frontend_btc_calibration_contract_renders_window_state_counts():
    app_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx").read_text()
    types_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "types.ts").read_text()

    assert "unique_window_count" in types_source
    assert "active_window_count" in types_source
    assert "upcoming_window_count" in types_source
    assert "expired_window_count" in types_source
    assert "windows {summary.unique_window_count}" in app_source
    assert "active {summary.active_window_count}" in app_source


def test_dashboard_feeds_weather_review_candidates_into_signal_review_queue():
    """Weather REV rows should count in the blocked queue, not only WX Cal."""
    main_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "main.py"
    source = main_path.read_text()

    assert "weather_review_candidates=weather_signal_review_candidates" in source


def test_dashboard_feeds_polymarket_weather_source_states_into_signal_review_queue():
    source = (Path(__file__).resolve().parents[1] / "backend" / "api" / "main.py").read_text()

    assert "weather_source_states=polymarket_weather_source_states" in source


def test_polymarket_weather_source_states_endpoint_accepts_category_and_market_state_drilldown(monkeypatch):
    """Operator API should let tooling request category/open-state source-state samples."""
    from backend.api import main

    captured = {}

    def fake_source_state_loader(limit=5, category=None, market_state=None):
        captured["limit"] = limit
        captured["category"] = category
        captured["market_state"] = market_state
        return [
            PolymarketWeatherSourceStateResponse(
                captured_at="20260614T150205Z",
                event_slug="latest-london-observed-weather",
                condition_id="0xobserved",
                question="Will London be 24°C?",
                outcome="Yes",
                closed=False,
                paper_actionable=False,
                source_state_label="Polymarket weather source-state only / non-actionable",
            )
        ]

    monkeypatch.setattr(main, "_load_latest_polymarket_weather_source_states", fake_source_state_loader)

    rows = asyncio.run(main.get_polymarket_weather_source_states(category="obs", market_state="open", limit=7))

    assert captured == {"limit": 7, "category": "obs", "market_state": "open"}
    assert rows[0].event_slug == "latest-london-observed-weather"
    assert rows[0].closed is False
    assert rows[0].paper_actionable is False


def test_frontend_polymarket_weather_source_summary_renders_neighbor_evidence():
    app_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx").read_text()
    types_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "types.ts").read_text()

    assert "station_anomaly_neighbor_evidence_rows" in types_source
    assert "station_anomaly_neighbor_evidence_max_count" in types_source
    assert "history_capture_rows" in types_source
    assert "history_observed_value_rows" in types_source
    assert "history_partial_rows" in types_source
    assert "history_complete_rows" in types_source
    assert "history_unique_source_urls" in types_source
    assert "history_partial_unique_source_urls" in types_source
    assert "history_partial_unique_stations" in types_source
    assert "hko_observed_value_rows" in types_source
    assert "hko_missing_target_date_rows" in types_source
    assert "hko_error_rows" in types_source
    assert "open_rows" in types_source
    assert "open_line_book_rows" in types_source
    assert "open_top_ask_size_rows" in types_source
    assert "closed_line_book_rows" in types_source
    assert "category_warning_rows" in types_source
    assert "category_partial_rows" in types_source
    assert "category_hko_rows" in types_source
    assert "category_observed_rows" in types_source
    assert "category_source_only_rows" in types_source
    assert "open_category_warning_rows" in types_source
    assert "open_category_hko_rows" in types_source
    assert "closed_category_warning_rows" in types_source
    assert "closed_category_observed_rows" in types_source
    assert "anom neigh" in app_source
    assert "station_anomaly_neighbor_evidence_max_count" in app_source
    assert "hist" in app_source
    assert "history_partial_rows" in app_source
    assert "hist complete" in app_source
    assert "partial src" in app_source
    assert "hko obs" in app_source
    assert "hko miss" in app_source
    assert "open rows" in app_source
    assert "open books" in app_source
    assert "open depth" in app_source
    assert "closed books" in app_source
    assert "sourceStateBatchCategoryCounts" in app_source
    assert "sourceStateBatchCategoryCountsByMarketState" in app_source
    assert "sourceStateFilterCountsByMarketState" in app_source
    assert "sourceStateFilterCountsForActiveMarketState" in app_source
    assert "sourceStateMarketStateCounts" in app_source
    assert "category_warning_rows" in app_source
    assert "sourceStateFilterCountsForActiveMarketState[filter]}/{sourceStateBatchCategoryCountsForActiveMarketState[filter]}" in app_source
    assert "sourceStateMarketStateCounts[filter]" in app_source


def test_dashboard_exposes_open_position_risk_rows_and_summary():
    main_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "main.py"
    source = main_path.read_text()

    assert '@app.get("/api/open-position-risk", response_model=List[OpenPositionRiskRowResponse])' in source
    assert "open_position_risk_rows=open_position_risk_rows" in source
    assert "open_position_risk_summary=open_position_risk_summary" in source
    assert "source_status_counts=" in source


def test_open_position_risk_schema_preserves_scan_staleness_and_summary_counts():
    row = OpenPositionRiskRowResponse(
        trade_id=7,
        market_type="weather",
        market_ticker="KXHIGHNY-26JUN03-T83",
        event_slug="nyc-high-jun-3",
        direction="yes",
        entry_price=0.45,
        size=75.0,
        action="watch",
        reasons=["risk scan has not refreshed this position yet"],
        checked_at="2026-06-03T03:01:00Z",
        risk_scan_stale=True,
        source_status="missing_live_quote",
        risk_evidence={"market_type": "weather", "station_known": False},
        live_exit_quote_bid=0.22,
        live_exit_quote_ask=0.24,
        live_exit_quote_top_bid_size=30.0,
        live_exit_quote_top_ask_size=50.0,
        live_exit_quote_source="kalshi_public_orderbook",
        live_exit_quote_error="CLOB book 404 for held YES token",
        settlement_source_known=True,
        station_known=False,
        settlement_url="https://forecast.weather.gov/product.php?site=OKX&product=CLI&issuedby=NYC",
        settlement_tags=["settlement:nws_cli:KNYC"],
        latest_signal_id=42,
        latest_signal_timestamp="2026-06-03T03:00:00",
        latest_signal_market_price=0.32,
        latest_signal_edge=-0.24,
        latest_signal_suggested_size=0.0,
        latest_signal_model_probability_for_held_side=0.61,
    )

    summary = OpenPositionRiskSummaryResponse(
        total_open_positions=1,
        action_counts={"watch": 1},
        auto_exit_enabled=False,
        recommendations_only=True,
        stale_mark_count=1,
        latest_checked_at="2026-06-03T03:01:00Z",
        exited_count=0,
        live_exit_quote_error_count=1,
        closed_market_or_stale_token_count=1,
        source_status_counts={"closed_market_or_stale_token": 1},
    )

    assert _model_dump(row)["risk_scan_stale"] is True
    assert _model_dump(row)["source_status"] == "missing_live_quote"
    assert _model_dump(row)["risk_evidence"]["station_known"] is False
    assert _model_dump(row)["live_exit_quote_bid"] == 0.22
    assert _model_dump(row)["live_exit_quote_ask"] == 0.24
    assert _model_dump(row)["live_exit_quote_top_bid_size"] == 30.0
    assert _model_dump(row)["live_exit_quote_top_ask_size"] == 50.0
    assert _model_dump(row)["live_exit_quote_source"] == "kalshi_public_orderbook"
    assert _model_dump(row)["live_exit_quote_error"] == "CLOB book 404 for held YES token"
    assert _model_dump(row)["settlement_source_known"] is True
    assert _model_dump(row)["station_known"] is False
    assert _model_dump(row)["settlement_url"].startswith("https://forecast.weather.gov/")
    assert _model_dump(row)["settlement_tags"] == ["settlement:nws_cli:KNYC"]
    assert _model_dump(row)["latest_signal_id"] == 42
    assert _model_dump(row)["latest_signal_timestamp"] == "2026-06-03T03:00:00"
    assert _model_dump(row)["latest_signal_market_price"] == 0.32
    assert _model_dump(row)["latest_signal_edge"] == -0.24
    assert _model_dump(row)["latest_signal_suggested_size"] == 0.0
    assert _model_dump(row)["latest_signal_model_probability_for_held_side"] == 0.61
    payload = _model_dump(summary)
    assert payload["stale_mark_count"] == 1
    assert payload["latest_checked_at"].isoformat().startswith("2026-06-03T03:01:00")
    assert payload["exited_count"] == 0
    assert payload["live_exit_quote_error_count"] == 1
    assert payload["closed_market_or_stale_token_count"] == 1
    assert payload["source_status_counts"] == {"closed_market_or_stale_token": 1}


def test_signal_review_item_schema_preserves_weather_source_state_diagnostics():
    item = SignalReviewItemResponse(
        vertical="weather",
        market_key="pm-seoul-jun2-28c",
        title="Will the high temperature in Seoul be 28°C or higher on June 2?",
        primary_blocker="Polymarket weather source-state only / non-actionable",
        no_trade_reasons=["Polymarket weather source-state only / non-actionable"],
        review_priority=2,
        best_bid=0.47,
        best_ask=0.48,
        execution_spread=0.01,
        top_ask_size=383.81,
        market_closed=False,
        settlement_source="Wunderground",
        settlement_url="https://www.wunderground.com/history/daily/kr/seoul/RKSI",
        settlement_station="RKSI",
        settlement_station_name="Seoul Incheon International Airport",
        settlement_units="C",
        settlement_precision="whole_degree_celsius",
        source_capture_status="history_no_data_recorded",
        source_observed_value=None,
        source_observed_unit="celsius",
        source_observed_at=None,
        source_capture_snapshot="/tmp/hko-source.html",
        station_anomaly_status="not_checked_missing_observation",
        station_anomaly_neighbor_count=0,
        station_anomaly_max_delta=None,
        source_state_label="Polymarket weather source-state only / non-actionable",
    )

    payload = _model_dump(item)

    assert payload["settlement_station"] == "RKSI"
    assert payload["settlement_station_name"] == "Seoul Incheon International Airport"
    assert payload["settlement_units"] == "C"
    assert payload["settlement_precision"] == "whole_degree_celsius"
    assert payload["source_capture_status"] == "history_no_data_recorded"
    assert payload["source_observed_unit"] == "celsius"
    assert payload["source_capture_snapshot"] == "/tmp/hko-source.html"
    assert payload["station_anomaly_status"] == "not_checked_missing_observation"
    assert payload["station_anomaly_neighbor_count"] == 0
    assert payload["station_anomaly_max_delta"] is None
    assert payload["market_closed"] is False


def test_signal_review_queue_response_preserves_rt_timing_diagnostics(): 
    item = SignalReviewItemResponse(
        vertical="rt_entertainment",
        market_key="passenger-rotten-tomatoes-score",
        title="Passenger >= 50 Tomatometer",
        primary_blocker="review count/timing risk gate blocks action",
        no_trade_reasons=["review count/timing risk gate blocks action"],
        review_priority=2,
        best_bid=0.001,
        best_ask=0.005,
        threshold=50,
        market_closed=False,
        source_method="rt_embedded_json",
        source_url="https://www.rottentomatoes.com/m/passenger_2026",
        direct_source_status="fresh",
        tomatometer_score=44,
        review_count=64,
        previous_tomatometer_score=43,
        previous_review_count=56,
        score_delta=1,
        review_count_delta=8,
        hours_since_previous_source=24.0,
        captured_at="2026-05-24T21:02:34Z",
        cutoff_time="2026-05-25T10:00:00-04:00",
        timing_risk_label="medium timing risk: below 75-review gate",
        source_state_label="RT source-state: fresh direct score",
    )
    queue = SignalReviewQueueResponse(
        total_blocked=1,
        blocked_by_vertical={"rt_entertainment": 1},
        blocked_by_source={"rt_source_state": 1},
        top_blockers=[SignalReviewBlockerResponse(reason="review count/timing risk gate blocks action", count=1)],
        items=[item],
    )

    payload = _model_dump(queue)

    assert payload["items"][0]["captured_at"] == "2026-05-24T21:02:34Z"
    assert payload["items"][0]["best_bid"] == 0.001
    assert payload["items"][0]["best_ask"] == 0.005
    assert payload["items"][0]["threshold"] == 50
    assert payload["items"][0]["market_closed"] is False
    assert payload["items"][0]["source_method"] == "rt_embedded_json"
    assert payload["items"][0]["score_delta"] == 1
    assert payload["items"][0]["review_count_delta"] == 8
    assert payload["items"][0]["hours_since_previous_source"] == 24.0
    assert payload["items"][0]["cutoff_time"] == "2026-05-25T10:00:00-04:00"
    assert payload["items"][0]["timing_risk_label"] == "medium timing risk: below 75-review gate"
    assert payload["items"][0]["source_state_label"] == "RT source-state: fresh direct score"


def test_signal_review_item_schema_accepts_btc_chainlink_boundary_evidence_fields():
    item = SignalReviewItemResponse(
        vertical="btc",
        market_key="btc-updown-5m-1779872700",
        title="BTC Up or Down",
        primary_blocker="missing Chainlink boundary source snapshot for this 5-minute window",
        no_trade_reasons=["missing Chainlink boundary source snapshot for this 5-minute window"],
        review_priority=4,
        settlement_source="Chainlink BTC/USD",
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

    payload = _model_dump(item)

    assert payload["chainlink_feed_id"].startswith("0x00039d9e")
    assert payload["chainlink_capture_method"] == "chainlink_data_streams_rest"
    assert payload["chainlink_start_price"] == 107250.11
    assert payload["chainlink_end_observed_at"] == 1779873000


def _paper_account_payload(scope=None):
    payload = {
        "initial_bankroll": 1000,
        "target_bankroll": 1100,
        "current_equity": 1000,
        "realized_pnl": 0,
        "remaining_to_target": 100,
        "progress_to_target_pct": 0,
        "total_trades": 0,
        "settled_trades": 0,
        "pending_trades": 0,
        "winning_trades": 0,
        "win_rate": 0,
        "settled_forecasts": 0,
        "brier_score": None,
        "log_loss": None,
        "paper_only": True,
        "selective_no_forced_trade": True,
    }
    if scope is not None:
        payload["market_scope"] = scope
    return payload


def test_dashboard_response_schema_is_dependency_light_and_preserves_all_paper_ledgers():
    stats = BotStats(
        bankroll=10000,
        total_trades=0,
        winning_trades=0,
        win_rate=0,
        total_pnl=0,
        is_running=False,
        last_run=None,
        btc_paper_account=_paper_account_payload(),
        weather_paper_account=_paper_account_payload("weather"),
        entertainment_paper_account=_paper_account_payload("rotten_tomatoes_entertainment"),
    )
    window = BtcWindowResponse(
        slug="btc-updown-5m-1779872700",
        market_id="btc-updown-5m-1779872700",
        up_price=0.50,
        down_price=0.50,
        window_start="2026-05-27T09:05:00Z",
        window_end="2026-05-27T09:10:00Z",
        window_start_ts=1779872700,
        window_end_ts=1779873000,
        volume=9000,
        is_active=True,
        is_upcoming=False,
        time_until_end=120,
        spread=0.01,
        up_bid=0.50,
        up_ask=0.51,
        up_ask_size=242.46,
        down_bid=0.49,
        down_ask=0.50,
        down_ask_size=1071.21,
        settlement_source="Chainlink BTC/USD",
        settlement_url="https://data.chain.link/streams/btc-usd",
    )

    dashboard = DashboardData(
        active_product_scope="weather",
        legacy_dashboard_sections_enabled=False,
        legacy_dashboard_note="Legacy BTC and RT/entertainment dashboard sections paused in weather-only scope",
        stats=stats,
        btc_price=None,
        microstructure=None,
        windows=[window],
        active_signals=[],
        recent_trades=[],
        equity_curve=[],
        calibration=None,
        weather_calibration=WeatherCalibrationSummaryResponse(
            latest_scored_at="20260528T011314Z",
            settled_forecasts=206,
            brier_score=0.0856,
            log_loss=0.2682,
            paper_actionable=False,
            market_scope="weather",
            calibration_kind="market_implied_quote_score",
            source_snapshot="/Users/kayvonai/.hermes/research/.snapshots/20260528T011314Z-weather-public-raw.json",
        ),
        weather_bot_calibration=WeatherCalibrationSummaryResponse(
            latest_scored_at="20260531T010247Z",
            settled_forecasts=104,
            brier_score=0.1835,
            log_loss=0.5879,
            paper_actionable=False,
            market_scope="weather",
            calibration_kind="bot_model_signal_score",
            source_snapshot="/Users/kayvonai/.hermes/research/.snapshots/20260531T010247Z-weather-public-raw.json",
        ),
        weather_calibration_rows=[
            WeatherCalibrationRowResponse(
                scored_at="20260528T011314Z",
                quote_ts="20260528T010500Z",
                venue="kalshi",
                market_key="KXHIGHNY-26MAY28-T85",
                outcome="85° or above",
                market_probability=0.95,
                resolved_yes=0.0,
                resolved_value=81.0,
                brier_score=0.9025,
                log_loss=2.996,
                source_url="https://api.weather.gov/products/latest",
                source_snapshot="/Users/kayvonai/.hermes/research/.snapshots/20260528T011314Z-weather-public-raw.json",
                paper_actionable=False,
                notes="calibration-only market-implied quote score; not a paper trade or bot edge",
            )
        ],
        weather_bot_calibration_rows=[
            WeatherBotCalibrationRowResponse(
                scored_at="20260531T010247Z",
                signal_id=88,
                signal_ts="2026-05-30 18:01:00",
                venue="kalshi",
                market_key="KXHIGHLAX-26MAY31-T75",
                outcome="75° or above",
                model_probability=0.91,
                market_probability=0.63,
                resolved_yes=0.0,
                resolved_value=73.0,
                brier_score=0.8281,
                log_loss=2.407946,
                source_url="https://api.weather.gov/products/latest-lax",
                source_snapshot="/Users/kayvonai/.hermes/research/.snapshots/20260531T010247Z-weather-public-raw.json",
                paper_actionable=False,
                executed=False,
                calibration_kind="bot_model_signal_score",
                notes="bot-model calibration-only / non-actionable",
            )
        ],
        weather_signal_review_candidates=[
            WeatherSignalReviewCandidateResponse(
                captured_at="20260601T010923Z",
                venue="kalshi",
                market_key="KXHIGHCHI-26JUN01-T72",
                title="Chicago high temp below 72F",
                city="chicago",
                target_date="2026-06-01",
                metric="high",
                direction="yes",
                threshold_f=72.0,
                model_probability=0.95,
                market_probability=0.32,
                edge=0.63,
                confidence=0.88,
                suggested_size=0.0,
                best_bid=0.29,
                best_ask=0.32,
                execution_spread=0.03,
                top_ask_size=208.09,
                settlement_source="NWS CLI",
                settlement_station="KMDW",
                settlement_source_url="https://api.weather.gov/products/types/CLI/locations/MDW",
                no_trade_reasons=["review-only candidate; not paper-actionable until independently revalidated"],
                source_snapshot="/Users/kayvonai/.hermes/research/.snapshots/20260601T010424Z-weather-public-raw.json",
                paper_actionable=False,
                executed=False,
                review_kind="weather_threshold_review_candidate",
                notes="review-only threshold-passing row",
            )
        ],
        polymarket_weather_source_states=[
            PolymarketWeatherSourceStateResponse(
                captured_at="20260601T220000Z",
                event_slug="highest-temperature-in-shenzhen-on-june-1",
                condition_id="0xpoly",
                question="Will Shenzhen be 25°C or below?",
                outcome="Yes",
                target_date="2026-06-01",
                token_id="poly-token",
                closed=False,
                settlement_source="wunderground",
                settlement_station="ZGSZ",
                settlement_station_name="Shenzhen Bao'an International Airport",
                settlement_source_url="https://www.wunderground.com/history/daily/cn/shenzhen/ZGSZ",
                settlement_units="celsius",
                settlement_precision="whole-degree",
                best_bid=None,
                best_ask=0.001,
                execution_spread=None,
                market_probability=0.0005,
                top_ask_size=1022.37,
                volume=14630.0,
                liquidity=2210.0,
                source_snapshot="/Users/kayvonai/.hermes/research/.snapshots/20260601T220000Z-weather-public-raw.json",
                source_capture_status="history_no_data_recorded",
                source_observed_value=None,
                source_observed_unit="celsius",
                source_observed_at=None,
                source_capture_snapshot="/Users/kayvonai/.hermes/research/.snapshots/20260601T220000Z-shenzhen-ZGSZ-source.html",
                station_anomaly_status="not_checked_missing_observation",
                station_anomaly_neighbor_count=0,
                station_anomaly_neighbor_values=[],
                station_anomaly_max_delta=None,
                paper_actionable=False,
                source_state_label="Polymarket weather source-state only / non-actionable",
                notes="source-state only; requires direct source/final outcome, independent model, CLOB depth/spread, and sizing gates before actionability",
            )
        ],
        polymarket_weather_source_state_summary=PolymarketWeatherSourceStateSummaryResponse(
            latest_captured_at="20260601T220000Z",
            source_state_rows=370,
            unique_events=12,
            unique_conditions=185,
            unique_stations=4,
            target_date_rows=370,
            unique_target_dates=2,
            wunderground_rows=340,
            hko_rows=30,
            direct_source_url_rows=370,
            unique_source_urls=12,
            line_book_rows=350,
            open_rows=350,
            open_line_book_rows=340,
            open_top_ask_size_rows=180,
            closed_line_book_rows=10,
            category_warning_rows=3,
            category_partial_rows=2,
            category_hko_rows=30,
            category_observed_rows=8,
            category_source_only_rows=327,
            market_probability_rows=370,
            yes_market_probability_rows=185,
            no_market_probability_rows=185,
            complete_binary_condition_pairs=185,
            incomplete_binary_condition_pairs=0,
            yes_market_probability_mass_event_count=12,
            yes_market_probability_mass_min=0.98,
            yes_market_probability_mass_max=1.02,
            yes_market_probability_mass_sanity_passed_count=12,
            yes_market_probability_mass_blocked_count=0,
            top_ask_size_rows=185,
            closed_rows=20,
            source_capture_attempted_rows=12,
            source_capture_unique_urls=5,
            source_capture_missing_rows=358,
            source_capture_missing_unique_urls=7,
            source_capture_no_data_rows=12,
            source_capture_observed_value_rows=0,
            source_capture_error_rows=0,
            history_capture_rows=12,
            history_observed_value_rows=8,
            history_partial_rows=2,
            history_complete_rows=6,
            history_unique_source_urls=5,
            history_partial_unique_source_urls=1,
            history_partial_unique_stations=1,
            station_anomaly_checked_rows=0,
            station_anomaly_neighbor_evidence_rows=42,
            station_anomaly_neighbor_evidence_max_count=2,
            station_anomaly_warning_rows=3,
            station_anomaly_warning_unique_events=2,
            station_anomaly_warning_unique_stations=1,
            station_anomaly_warning_unique_source_urls=1,
            station_anomaly_warning_max_delta=8.5,
            station_anomaly_not_checked_rows=370,
            station_anomaly_missing_observation_rows=370,
            station_anomaly_missing_neighbors_rows=0,
            paper_actionable=False,
            market_scope="weather",
            source_snapshot="/Users/kayvonai/.hermes/research/.snapshots/20260601T220000Z-weather-public-raw.json",
            source_state_label="Polymarket weather source-state only / non-actionable",
        ),
        btc_calibration=BtcCalibrationSummaryResponse(
            latest_scored_at="20260528T090219Z",
            scoring_rows=16,
            pending_scoring_rows=16,
            settled_forecasts=0,
            brier_score=None,
            log_loss=None,
            exact_boundary_rows=0,
            partial_boundary_rows=0,
            line_book_rows=16,
            top_ask_size_rows=16,
            max_execution_spread=0.01,
            min_signal_top_ask_size=11.35,
            report_request_rows=16,
            auth_required_report_requests=16,
            paper_actionable=False,
            market_scope="btc",
            calibration_kind="chainlink_boundary_outcome_score",
            source_snapshot="/Users/kayvonai/.hermes/research/.snapshots/20260528T090219Z-btc-public-raw.json",
        ),
        btc_calibration_rows=[
            BtcCalibrationRowResponse(
                ts="20260528T190820Z",
                quote_ts="20260528T190820Z",
                event_slug="btc-updown-5m-1779995100",
                market_key="btc-updown-5m-1779995100::Up",
                direction="up",
                model_probability=None,
                model_price_source="coinbase_spot_context",
                signal_yes_bid=0.61,
                signal_yes_ask=0.62,
                execution_spread=0.01,
                signal_probability=0.62,
                chainlink_feed_id="0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8",
                chainlink_capture_method="chainlink_data_streams_rest",
                chainlink_source_url="https://data.chain.link/streams/btc-usd",
                chainlink_start_price=None,
                chainlink_end_price=None,
                chainlink_start_observed_at=None,
                chainlink_end_observed_at=None,
                chainlink_start_source_snapshot_path="/tmp/current-raw.json",
                chainlink_end_source_snapshot_path="/tmp/current-raw.json",
                chainlink_start_report_request_url="https://api.dataengine.chain.link/api/v1/reports?feedID=feed&timestamp=1779995100",
                chainlink_end_report_request_url="https://api.dataengine.chain.link/api/v1/reports?feedID=feed&timestamp=1779995400",
                chainlink_start_report_boundary_ts=1779995100,
                chainlink_end_report_boundary_ts=1779995400,
                chainlink_start_report_status="auth_required_not_fetched",
                chainlink_end_report_status="auth_required_not_fetched",
                chainlink_start_report_requires_authentication=True,
                chainlink_end_report_requires_authentication=True,
                exact_boundary_available=False,
                partial_boundary_available=False,
                resolved_yes=None,
                final_outcome=None,
                brier_score=None,
                log_loss=None,
                clv=None,
                status="non_actionable_pending_outcome_and_boundary_values",
                no_trade_reasons=["missing exact Chainlink boundary values"],
                paper_actionable=False,
            )
        ],
        entertainment_calibration=EntertainmentCalibrationSummaryResponse(
            latest_scored_at="20260529T050150Z",
            scoring_rows=2,
            pending_scoring_rows=1,
            settled_forecasts=1,
            brier_score=0.09,
            log_loss=0.3567,
            paper_actionable=False,
            market_scope="rotten_tomatoes_entertainment",
            calibration_kind="rt_entertainment_outcome_score",
            source_snapshot="/Users/kayvonai/.hermes/research/.snapshots/20260529T050150Z-rt-entertainment-public-raw.json",
        ),
        weather_signals=[],
        weather_forecasts=[],
        rotten_tomatoes_source_states=[],
        signal_review_queue=SignalReviewQueueResponse(),
    )

    payload = _model_dump(dashboard)

    assert payload["active_product_scope"] == "weather"
    assert payload["legacy_dashboard_sections_enabled"] is False
    assert payload["legacy_dashboard_note"] == "Legacy BTC and RT/entertainment dashboard sections paused in weather-only scope"
    assert payload["stats"]["btc_paper_account"]["current_equity"] == 1000
    assert payload["stats"]["btc_paper_account"]["brier_score"] is None
    assert payload["stats"]["weather_paper_account"]["market_scope"] == "weather"
    assert payload["stats"]["entertainment_paper_account"]["market_scope"] == "rotten_tomatoes_entertainment"
    assert payload["windows"][0]["up_bid"] == 0.50
    assert payload["windows"][0]["down_ask_size"] == 1071.21
    assert payload["windows"][0]["window_start_ts"] == 1779872700
    assert payload["windows"][0]["window_end_ts"] == 1779873000
    assert payload["weather_calibration"]["settled_forecasts"] == 206
    assert payload["weather_calibration"]["paper_actionable"] is False
    assert payload["weather_calibration"]["calibration_kind"] == "market_implied_quote_score"
    assert payload["weather_bot_calibration"]["settled_forecasts"] == 104
    assert payload["weather_bot_calibration"]["paper_actionable"] is False
    assert payload["weather_bot_calibration"]["calibration_kind"] == "bot_model_signal_score"
    assert payload["weather_calibration_rows"][0]["market_key"] == "KXHIGHNY-26MAY28-T85"
    assert payload["weather_calibration_rows"][0]["paper_actionable"] is False
    assert payload["weather_bot_calibration_rows"][0]["market_key"] == "KXHIGHLAX-26MAY31-T75"
    assert payload["weather_bot_calibration_rows"][0]["model_probability"] == 0.91
    assert payload["weather_bot_calibration_rows"][0]["calibration_kind"] == "bot_model_signal_score"
    assert payload["weather_bot_calibration_rows"][0]["paper_actionable"] is False
    assert payload["weather_signal_review_candidates"][0]["market_key"] == "KXHIGHCHI-26JUN01-T72"
    assert payload["weather_signal_review_candidates"][0]["suggested_size"] == 0.0
    assert payload["weather_signal_review_candidates"][0]["paper_actionable"] is False
    assert payload["weather_signal_review_candidates"][0]["executed"] is False
    assert payload["weather_signal_review_candidates"][0]["review_kind"] == "weather_threshold_review_candidate"
    assert payload["weather_signal_review_candidates"][0]["no_trade_reasons"] == ["review-only candidate; not paper-actionable until independently revalidated"]
    assert payload["polymarket_weather_source_states"][0]["event_slug"] == "highest-temperature-in-shenzhen-on-june-1"
    assert payload["polymarket_weather_source_states"][0]["target_date"] == "2026-06-01"
    assert payload["polymarket_weather_source_states"][0]["settlement_station"] == "ZGSZ"
    assert payload["polymarket_weather_source_states"][0]["best_ask"] == 0.001
    assert payload["polymarket_weather_source_states"][0]["market_probability"] == 0.0005
    assert payload["polymarket_weather_source_states"][0]["top_ask_size"] == 1022.37
    assert payload["polymarket_weather_source_states"][0]["source_capture_status"] == "history_no_data_recorded"
    assert payload["polymarket_weather_source_states"][0]["station_anomaly_status"] == "not_checked_missing_observation"
    assert payload["polymarket_weather_source_states"][0]["station_anomaly_neighbor_count"] == 0
    assert payload["polymarket_weather_source_states"][0]["station_anomaly_neighbor_values"] == []
    assert payload["polymarket_weather_source_states"][0]["source_capture_snapshot"].endswith("shenzhen-ZGSZ-source.html")
    assert payload["polymarket_weather_source_states"][0]["paper_actionable"] is False
    assert payload["polymarket_weather_source_states"][0]["source_state_label"] == "Polymarket weather source-state only / non-actionable"
    assert payload["polymarket_weather_source_state_summary"]["source_state_rows"] == 370
    assert payload["polymarket_weather_source_state_summary"]["unique_stations"] == 4
    assert payload["polymarket_weather_source_state_summary"]["target_date_rows"] == 370
    assert payload["polymarket_weather_source_state_summary"]["unique_target_dates"] == 2
    assert payload["polymarket_weather_source_state_summary"]["direct_source_url_rows"] == 370
    assert payload["polymarket_weather_source_state_summary"]["unique_source_urls"] == 12
    assert payload["polymarket_weather_source_state_summary"]["line_book_rows"] == 350
    assert payload["polymarket_weather_source_state_summary"]["open_rows"] == 350
    assert payload["polymarket_weather_source_state_summary"]["open_line_book_rows"] == 340
    assert payload["polymarket_weather_source_state_summary"]["open_top_ask_size_rows"] == 180
    assert payload["polymarket_weather_source_state_summary"]["closed_line_book_rows"] == 10
    assert payload["polymarket_weather_source_state_summary"]["category_warning_rows"] == 3
    assert payload["polymarket_weather_source_state_summary"]["category_partial_rows"] == 2
    assert payload["polymarket_weather_source_state_summary"]["category_hko_rows"] == 30
    assert payload["polymarket_weather_source_state_summary"]["category_observed_rows"] == 8
    assert payload["polymarket_weather_source_state_summary"]["category_source_only_rows"] == 327
    assert payload["polymarket_weather_source_state_summary"]["market_probability_rows"] == 370
    assert payload["polymarket_weather_source_state_summary"]["complete_binary_condition_pairs"] == 185
    assert payload["polymarket_weather_source_state_summary"]["yes_market_probability_mass_sanity_passed_count"] == 12
    assert payload["polymarket_weather_source_state_summary"]["source_capture_attempted_rows"] == 12
    assert payload["polymarket_weather_source_state_summary"]["source_capture_unique_urls"] == 5
    assert payload["polymarket_weather_source_state_summary"]["source_capture_missing_rows"] == 358
    assert payload["polymarket_weather_source_state_summary"]["source_capture_missing_unique_urls"] == 7
    assert payload["polymarket_weather_source_state_summary"]["source_capture_no_data_rows"] == 12
    assert payload["polymarket_weather_source_state_summary"]["history_capture_rows"] == 12
    assert payload["polymarket_weather_source_state_summary"]["history_observed_value_rows"] == 8
    assert payload["polymarket_weather_source_state_summary"]["history_partial_rows"] == 2
    assert payload["polymarket_weather_source_state_summary"]["station_anomaly_not_checked_rows"] == 370
    assert payload["polymarket_weather_source_state_summary"]["station_anomaly_neighbor_evidence_rows"] == 42
    assert payload["polymarket_weather_source_state_summary"]["station_anomaly_neighbor_evidence_max_count"] == 2
    assert payload["polymarket_weather_source_state_summary"]["station_anomaly_warning_rows"] == 3
    assert payload["polymarket_weather_source_state_summary"]["station_anomaly_warning_unique_events"] == 2
    assert payload["polymarket_weather_source_state_summary"]["station_anomaly_warning_unique_stations"] == 1
    assert payload["polymarket_weather_source_state_summary"]["station_anomaly_warning_unique_source_urls"] == 1
    assert payload["polymarket_weather_source_state_summary"]["station_anomaly_warning_max_delta"] == 8.5
    assert payload["polymarket_weather_source_state_summary"]["paper_actionable"] is False
    assert payload["btc_calibration"]["scoring_rows"] == 16
    assert payload["btc_calibration"]["settled_forecasts"] == 0
    assert payload["btc_calibration"]["report_request_rows"] == 16
    assert payload["btc_calibration"]["auth_required_report_requests"] == 16
    assert payload["btc_calibration"]["line_book_rows"] == 16
    assert payload["btc_calibration"]["top_ask_size_rows"] == 16
    assert payload["btc_calibration"]["max_execution_spread"] == 0.01
    assert payload["btc_calibration"]["min_signal_top_ask_size"] == 11.35
    assert payload["btc_calibration"]["paper_actionable"] is False
    assert payload["btc_calibration"]["calibration_kind"] == "chainlink_boundary_outcome_score"
    assert payload["btc_calibration_rows"][0]["event_slug"] == "btc-updown-5m-1779995100"
    assert payload["btc_calibration_rows"][0]["execution_spread"] == 0.01
    assert payload["btc_calibration_rows"][0]["exact_boundary_available"] is False
    assert payload["btc_calibration_rows"][0]["chainlink_start_report_boundary_ts"] == 1779995100
    assert payload["btc_calibration_rows"][0]["chainlink_end_report_boundary_ts"] == 1779995400
    assert payload["btc_calibration_rows"][0]["chainlink_start_report_status"] == "auth_required_not_fetched"
    assert payload["btc_calibration_rows"][0]["chainlink_start_report_requires_authentication"] is True
    assert payload["btc_calibration_rows"][0]["paper_actionable"] is False
    assert payload["entertainment_calibration"]["scoring_rows"] == 2
    assert payload["entertainment_calibration"]["pending_scoring_rows"] == 1
    assert payload["entertainment_calibration"]["settled_forecasts"] == 1
    assert payload["entertainment_calibration"]["paper_actionable"] is False
    assert payload["entertainment_calibration"]["calibration_kind"] == "rt_entertainment_outcome_score"
    assert payload["signal_review_queue"]["total_blocked"] == 0
