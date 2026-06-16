from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_types_include_open_position_risk_dashboard_contract():
    source = (ROOT / "frontend" / "src" / "types.ts").read_text()

    assert "export interface OpenPositionRiskRow" in source
    assert "risk_scan_stale: boolean" in source
    assert "risk_evidence?: Record<string, unknown>" in source
    assert "live_exit_quote_bid?: number | null" in source
    assert "live_exit_quote_ask?: number | null" in source
    assert "live_exit_quote_top_bid_size?: number | null" in source
    assert "live_exit_quote_top_ask_size?: number | null" in source
    assert "live_exit_quote_source?: string | null" in source
    assert "live_exit_quote_error?: string | null" in source
    assert "settlement_source_known?: boolean | null" in source
    assert "station_known?: boolean | null" in source
    assert "settlement_url?: string | null" in source
    assert "settlement_tags?: string[]" in source
    assert "latest_signal_id?: number | null" in source
    assert "latest_signal_timestamp?: string | null" in source
    assert "latest_signal_market_price?: number | null" in source
    assert "latest_signal_edge?: number | null" in source
    assert "latest_signal_suggested_size?: number | null" in source
    assert "latest_signal_model_probability_for_held_side?: number | null" in source
    assert "open_position_risk_rows: OpenPositionRiskRow[]" in source
    assert "open_position_risk_summary: OpenPositionRiskSummary" in source
    assert "stale_mark_count: number" in source
    assert "live_exit_quote_error_count: number" in source
    assert "closed_market_or_stale_token_count: number" in source
    assert "source_status_counts: Record<string, number>" in source
    assert "latest_checked_at?: string | null" in source


def test_frontend_renders_open_position_risk_panel_from_dashboard_payload():
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text()

    assert "OpenPositionRiskPanel" in app
    assert "dashboard.open_position_risk_rows" in app
    assert "Cash-out Risk" in app
    assert "stale marks" in app
    assert "quote errors" in app
    assert "closed/stale tokens" in app
    assert "riskSourceLabels" in app
    assert "summary.source_status_counts" in app
    assert "src {row.source_status}" in app
    assert "live bid" in app
    assert "ask " in app
    assert "depth" in app
    assert "quote err" in app
    assert "source mapped" in app
    assert "station mapped" in app
    assert "sig mkt" in app
    assert "sig edge" in app


def test_frontend_renders_polymarket_weather_source_capture_contract():
    types = (ROOT / "frontend" / "src" / "types.ts").read_text()
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text()

    assert "source_capture_status?: string | null" in types
    assert "source_observed_value?: number | null" in types
    assert "source_capture_attempted_rows: number" in types
    assert "source_capture_unique_urls: number" in types
    assert "source_capture_missing_rows: number" in types
    assert "source_capture_missing_unique_urls: number" in types
    assert "source_capture_observed_value_rows: number" in types
    assert "history_complete_rows: number" in types
    assert "history_unique_source_urls: number" in types
    assert "history_partial_unique_source_urls: number" in types
    assert "history_partial_unique_stations: number" in types
    assert "hko_observed_value_rows: number" in types
    assert "hko_missing_target_date_rows: number" in types
    assert "hko_error_rows: number" in types
    assert "station_anomaly_status?: string | null" in types
    assert "station_anomaly_neighbor_values?: number[] | null" in types
    assert "station_anomaly_checked_rows: number" in types
    assert "station_anomaly_warning_rows: number" in types
    assert "station_anomaly_not_checked_rows: number" in types
    assert "src cap" in app
    assert "src urls" in app
    assert "src miss" in app
    assert "hist complete" in app
    assert "partial src" in app
    assert "hko obs" in app
    assert "hko miss" in app
    assert "anom" in app
    assert "warn" in app
    assert "source_capture_attempted_rows" in app
    assert "src {row.source_capture_status}" in app
    assert "anom {row.station_anomaly_status}" in app
    assert "neigh {row.station_anomaly_neighbor_values" in app
    assert "obs {row.source_observed_value}" in app


def test_frontend_renders_all_polymarket_weather_source_sample_rows():
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text()

    assert "visiblePolymarketSourceStates.map(row =>" in app
    assert "sourceStateFilter === 'all'" in app
    assert "polymarketSourceStates.slice(0, 3).map" not in app


def test_frontend_polymarket_weather_source_rows_have_status_badges():
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text()

    assert "function sourceStateBadge" in app
    assert "sourceStateBadge(row)" in app
    assert "label: 'WARN'" in app
    assert "label: 'PART'" in app
    assert "label: 'HKO'" in app
    assert "label: 'OBS'" in app


def test_frontend_polymarket_weather_source_sample_has_operator_filters():
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text()
    types = (ROOT / "frontend" / "src" / "types.ts").read_text()

    assert "type SourceStateFilter = 'all' | 'warn' | 'part' | 'hko' | 'obs' | 'src'" in app
    assert "const [sourceStateFilter, setSourceStateFilter]" in app
    assert "sourceStateFilterOptions.map" in app
    assert "Poly WX filters" in app
    assert "visiblePolymarketSourceStates.length" in app
    assert "category_warning_rows: number" in types
    assert "category_partial_rows: number" in types
    assert "category_hko_rows: number" in types
    assert "category_observed_rows: number" in types
    assert "category_source_only_rows: number" in types
    assert "open_category_warning_rows: number" in types
    assert "open_category_hko_rows: number" in types
    assert "closed_category_warning_rows: number" in types
    assert "closed_category_observed_rows: number" in types
    assert "sourceStateBatchCategoryCounts" in app
    assert "sourceStateBatchCategoryCountsByMarketState" in app
    assert "sourceStateFilterCountsByMarketState" in app
    assert "sourceStateBatchCategoryCountsForActiveMarketState" in app
    assert "sourceStateFilterCountsForActiveMarketState[filter]}/{sourceStateBatchCategoryCountsForActiveMarketState[filter]}" in app


def test_frontend_polymarket_weather_source_filters_fetch_backend_drilldown():
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text()
    api = (ROOT / "frontend" / "src" / "api.ts").read_text()

    assert "fetchPolymarketWeatherSourceStates" in api
    assert "fetchPolymarketWeatherSourceStates" in app
    assert "type SourceStateMarketStateFilter = 'all' | 'open' | 'closed'" in app
    assert "const [sourceStateMarketStateFilter, setSourceStateMarketStateFilter]" in app
    assert "sourceStateMarketStateFilterOptions.map" in app
    assert "Poly WX market-state filters" in app
    assert "queryKey: ['polymarket-weather-source-states', sourceStateFilter, sourceStateMarketStateFilter]" in app
    assert "fetchPolymarketWeatherSourceStates({" in app
    assert "sourceStateDrilldownRows" in app
    assert "sourceStateMarketStateCounts" in app
    assert "sourceStateMarketStateCounts[filter]" in app
    assert "open/closed drilldown" in app


def test_frontend_polymarket_weather_source_filters_sync_url_state():
    """Operator drilldown filters should be shareable without growing dashboard payloads."""
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text()

    assert "polyWxCategory" in app
    assert "polyWxMarketState" in app
    assert "readSourceStateFilterFromUrl" in app
    assert "readSourceStateMarketStateFilterFromUrl" in app
    assert "useState<SourceStateFilter>(() => readSourceStateFilterFromUrl())" in app
    assert "useState<SourceStateMarketStateFilter>(() => readSourceStateMarketStateFilterFromUrl())" in app
    assert "syncSourceStateUrlFilters(sourceStateFilter, sourceStateMarketStateFilter)" in app
    assert "window.history.replaceState" in app
