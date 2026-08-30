"""Dependency-light API response schemas used by tests and FastAPI routes.

Keep these models free of database/ORM imports so serialization behavior can be
verified in cron and CI environments even when optional runtime dependencies
such as SQLAlchemy are unavailable.
"""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict


class BtcPriceResponse(BaseModel):
    price: float
    change_24h: float
    change_7d: float
    market_cap: float
    volume_24h: float
    last_updated: datetime


class BtcWindowResponse(BaseModel):
    slug: str
    market_id: str
    up_price: float
    down_price: float
    window_start: datetime
    window_end: datetime
    window_start_ts: Optional[int] = None
    window_end_ts: Optional[int] = None
    volume: float
    is_active: bool
    is_upcoming: bool
    time_until_end: float
    spread: float
    up_bid: Optional[float] = None
    up_ask: Optional[float] = None
    up_ask_size: Optional[float] = None
    down_bid: Optional[float] = None
    down_ask: Optional[float] = None
    down_ask_size: Optional[float] = None
    up_midpoint: Optional[float] = None
    down_midpoint: Optional[float] = None
    up_last_price: Optional[float] = None
    down_last_price: Optional[float] = None
    recent_trades_count: int = 0
    settlement_source: str = "unknown"
    settlement_url: Optional[str] = None


class MicrostructureResponse(BaseModel):
    rsi: float = 50.0
    momentum_1m: float = 0.0
    momentum_5m: float = 0.0
    momentum_15m: float = 0.0
    vwap_deviation: float = 0.0
    sma_crossover: float = 0.0
    volatility: float = 0.0
    price: float = 0.0
    source: str = "unknown"


class SignalResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    market_ticker: str
    market_title: str
    platform: str
    direction: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    suggested_size: float
    reasoning: str
    timestamp: datetime
    category: str = "crypto"
    event_slug: Optional[str] = None
    btc_price: float = 0.0
    btc_change_24h: float = 0.0
    window_end: Optional[datetime] = None
    actionable: bool = False
    no_trade_reasons: List[str] = []
    execution_spread: Optional[float] = None
    top_ask_size: Optional[float] = None
    settlement_source: str = "unknown"
    settlement_url: Optional[str] = None
    model_price_source: str = "unknown"
    chainlink_feed_id: Optional[str] = None
    chainlink_capture_method: Optional[str] = None
    chainlink_source_url: Optional[str] = None
    chainlink_start_price: Optional[float] = None
    chainlink_end_price: Optional[float] = None
    chainlink_start_observed_at: Optional[int] = None
    chainlink_end_observed_at: Optional[int] = None
    chainlink_start_source_snapshot_path: Optional[str] = None
    chainlink_end_source_snapshot_path: Optional[str] = None


class TradeResponse(BaseModel):
    id: int
    market_ticker: str
    platform: str
    event_slug: Optional[str] = None
    direction: str
    entry_price: float
    size: float
    timestamp: datetime
    settled: bool
    result: str
    pnl: Optional[float]
    closed_early: bool = False
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    unrealized_pnl: Optional[float] = None
    last_mark_price: Optional[float] = None
    last_mark_time: Optional[datetime] = None
    last_risk_action: Optional[str] = None
    last_risk_reasons: List[str] = []
    last_risk_source_status: Optional[str] = None
    last_risk_evidence: dict[str, Any] = {}


class OpenPositionRiskRowResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    trade_id: int
    market_type: str
    market_ticker: str
    event_slug: Optional[str] = None
    direction: str
    entry_price: float
    size: float
    current_exit_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    model_probability_for_held_side: Optional[float] = None
    market_probability_for_held_side: Optional[float] = None
    action: str
    reasons: List[str] = []
    source_status: Optional[str] = None
    risk_evidence: dict[str, Any] = {}
    live_exit_quote_bid: Optional[float] = None
    live_exit_quote_ask: Optional[float] = None
    live_exit_quote_top_bid_size: Optional[float] = None
    live_exit_quote_top_ask_size: Optional[float] = None
    live_exit_quote_source: Optional[str] = None
    live_exit_quote_error: Optional[str] = None
    settlement_source_known: Optional[bool] = None
    station_known: Optional[bool] = None
    settlement_url: Optional[str] = None
    settlement_tags: List[str] = []
    latest_signal_id: Optional[int] = None
    latest_signal_timestamp: Optional[str] = None
    latest_signal_market_price: Optional[float] = None
    latest_signal_edge: Optional[float] = None
    latest_signal_suggested_size: Optional[float] = None
    latest_signal_model_probability_for_held_side: Optional[float] = None
    checked_at: datetime
    risk_scan_stale: bool = False


class OpenPositionRiskSummaryResponse(BaseModel):
    total_open_positions: int = 0
    action_counts: dict = {}
    auto_exit_enabled: bool = False
    recommendations_only: bool = True
    stale_mark_count: int = 0
    latest_checked_at: Optional[datetime] = None
    exited_count: int = 0
    live_exit_quote_error_count: int = 0
    closed_market_or_stale_token_count: int = 0
    source_status_counts: dict[str, int] = {}


class BotStats(BaseModel):
    bankroll: float
    total_trades: int
    winning_trades: int
    win_rate: float
    total_pnl: float
    is_running: bool
    last_run: Optional[datetime]
    weather_paper_account: dict
    btc_paper_account: dict
    entertainment_paper_account: dict


class CalibrationBucket(BaseModel):
    bucket: str
    predicted_avg: float
    actual_rate: float
    count: int


class CalibrationSummary(BaseModel):
    total_signals: int
    total_with_outcome: int
    accuracy: float
    avg_predicted_edge: float
    avg_actual_edge: float
    brier_score: float


class WeatherCalibrationSummaryResponse(BaseModel):
    latest_scored_at: Optional[str] = None
    settled_forecasts: int = 0
    brier_score: Optional[float] = None
    log_loss: Optional[float] = None
    paper_actionable: bool = False
    market_scope: str = "weather"
    calibration_kind: str = "market_implied_quote_score"
    source_snapshot: Optional[str] = None


class WeatherCalibrationRowResponse(BaseModel):
    scored_at: str
    quote_ts: str
    venue: str
    market_key: str
    outcome: Optional[str] = None
    market_probability: float
    resolved_yes: float
    resolved_value: Optional[float] = None
    brier_score: Optional[float] = None
    log_loss: Optional[float] = None
    source_url: Optional[str] = None
    source_snapshot: Optional[str] = None
    paper_actionable: bool = False
    notes: Optional[str] = None


class WeatherBotCalibrationRowResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    scored_at: str
    signal_id: Optional[int] = None
    signal_ts: Optional[str] = None
    venue: str
    market_key: str
    outcome: Optional[str] = None
    model_probability: float
    market_probability: Optional[float] = None
    resolved_yes: float
    resolved_value: Optional[float] = None
    brier_score: Optional[float] = None
    log_loss: Optional[float] = None
    source_url: Optional[str] = None
    source_snapshot: Optional[str] = None
    paper_actionable: bool = False
    executed: bool = False
    calibration_kind: str = "bot_model_signal_score"
    notes: Optional[str] = None


class WeatherSignalReviewCandidateResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    captured_at: str
    venue: Optional[str] = None
    market_key: str
    title: Optional[str] = None
    city: Optional[str] = None
    target_date: Optional[str] = None
    metric: Optional[str] = None
    direction: Optional[str] = None
    threshold_f: Optional[float] = None
    model_probability: Optional[float] = None
    market_probability: Optional[float] = None
    edge: Optional[float] = None
    confidence: Optional[float] = None
    suggested_size: float = 0.0
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    execution_spread: Optional[float] = None
    top_ask_size: Optional[float] = None
    settlement_source: Optional[str] = None
    settlement_station: Optional[str] = None
    settlement_source_url: Optional[str] = None
    no_trade_reasons: List[str] = []
    source_snapshot: Optional[str] = None
    paper_actionable: bool = False
    executed: bool = False
    review_kind: str = "weather_threshold_review_candidate"
    notes: Optional[str] = None


class PolymarketWeatherSourceStateResponse(BaseModel):
    captured_at: str
    event_slug: Optional[str] = None
    condition_id: str
    question: Optional[str] = None
    outcome: Optional[str] = None
    target_date: Optional[str] = None
    token_id: Optional[str] = None
    closed: bool = False
    settlement_source: Optional[str] = None
    settlement_station: Optional[str] = None
    settlement_station_name: Optional[str] = None
    settlement_source_url: Optional[str] = None
    settlement_units: Optional[str] = None
    settlement_precision: Optional[str] = None
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    execution_spread: Optional[float] = None
    market_probability: Optional[float] = None
    top_ask_size: Optional[float] = None
    volume: Optional[float] = None
    liquidity: Optional[float] = None
    source_snapshot: Optional[str] = None
    source_capture_status: Optional[str] = None
    source_observed_value: Optional[float] = None
    source_observed_unit: Optional[str] = None
    source_observed_at: Optional[str] = None
    source_capture_snapshot: Optional[str] = None
    station_anomaly_status: Optional[str] = None
    station_anomaly_neighbor_count: Optional[int] = None
    station_anomaly_neighbor_values: List[float] = []
    station_anomaly_max_delta: Optional[float] = None
    paper_actionable: bool = False
    source_state_label: str = "Polymarket weather source-state only / non-actionable"
    notes: Optional[str] = None


class PolymarketWeatherSourceStateSummaryResponse(BaseModel):
    latest_captured_at: Optional[str] = None
    source_state_rows: int = 0
    unique_events: int = 0
    unique_conditions: int = 0
    unique_stations: int = 0
    target_date_rows: int = 0
    unique_target_dates: int = 0
    wunderground_rows: int = 0
    hko_rows: int = 0
    hko_observed_value_rows: int = 0
    hko_missing_target_date_rows: int = 0
    hko_error_rows: int = 0
    direct_source_url_rows: int = 0
    unique_source_urls: int = 0
    line_book_rows: int = 0
    open_rows: int = 0
    open_line_book_rows: int = 0
    open_top_ask_size_rows: int = 0
    closed_line_book_rows: int = 0
    category_warning_rows: int = 0
    category_partial_rows: int = 0
    category_hko_rows: int = 0
    category_observed_rows: int = 0
    category_source_only_rows: int = 0
    open_category_warning_rows: int = 0
    open_category_partial_rows: int = 0
    open_category_hko_rows: int = 0
    open_category_observed_rows: int = 0
    open_category_source_only_rows: int = 0
    closed_category_warning_rows: int = 0
    closed_category_partial_rows: int = 0
    closed_category_hko_rows: int = 0
    closed_category_observed_rows: int = 0
    closed_category_source_only_rows: int = 0
    market_probability_rows: int = 0
    yes_market_probability_rows: int = 0
    no_market_probability_rows: int = 0
    complete_binary_condition_pairs: int = 0
    incomplete_binary_condition_pairs: int = 0
    yes_market_probability_mass_event_count: int = 0
    yes_market_probability_mass_min: Optional[float] = None
    yes_market_probability_mass_max: Optional[float] = None
    yes_market_probability_mass_sanity_passed_count: int = 0
    yes_market_probability_mass_blocked_count: int = 0
    top_ask_size_rows: int = 0
    closed_rows: int = 0
    source_capture_attempted_rows: int = 0
    source_capture_unique_urls: int = 0
    source_capture_missing_rows: int = 0
    source_capture_missing_unique_urls: int = 0
    source_capture_no_data_rows: int = 0
    source_capture_observed_value_rows: int = 0
    source_capture_error_rows: int = 0
    history_capture_rows: int = 0
    history_observed_value_rows: int = 0
    history_partial_rows: int = 0
    history_complete_rows: int = 0
    history_unique_source_urls: int = 0
    history_partial_unique_source_urls: int = 0
    history_partial_unique_stations: int = 0
    station_anomaly_checked_rows: int = 0
    station_anomaly_neighbor_evidence_rows: int = 0
    station_anomaly_neighbor_evidence_max_count: int = 0
    station_anomaly_not_checked_rows: int = 0
    station_anomaly_missing_observation_rows: int = 0
    station_anomaly_missing_neighbors_rows: int = 0
    station_anomaly_warning_rows: int = 0
    station_anomaly_warning_unique_events: int = 0
    station_anomaly_warning_unique_stations: int = 0
    station_anomaly_warning_unique_source_urls: int = 0
    station_anomaly_warning_max_delta: Optional[float] = None
    station_anomaly_passed_rows: int = 0
    station_anomaly_max_delta: Optional[float] = None
    paper_actionable: bool = False
    market_scope: str = "weather"
    source_snapshot: Optional[str] = None
    source_state_label: str = "Polymarket weather source-state only / non-actionable"


class BtcCalibrationSummaryResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    latest_scored_at: Optional[str] = None
    scoring_rows: int = 0
    pending_scoring_rows: int = 0
    settled_forecasts: int = 0
    brier_score: Optional[float] = None
    log_loss: Optional[float] = None
    exact_boundary_rows: int = 0
    partial_boundary_rows: int = 0
    line_book_rows: int = 0
    top_ask_size_rows: int = 0
    model_probability_rows: int = 0
    exchange_spot_model_rows: int = 0
    source_mismatch_rows: int = 0
    chainlink_auth_blocked_rows: int = 0
    unique_window_count: int = 0
    active_window_count: int = 0
    upcoming_window_count: int = 0
    expired_window_count: int = 0
    min_seconds_to_window_end: Optional[int] = None
    max_seconds_to_window_end: Optional[int] = None
    max_execution_spread: Optional[float] = None
    min_signal_top_ask_size: Optional[float] = None
    report_request_rows: int = 0
    auth_required_report_requests: int = 0
    paper_actionable: bool = False
    market_scope: str = "btc"
    calibration_kind: str = "chainlink_boundary_outcome_score"
    source_snapshot: Optional[str] = None


class BtcCalibrationRowResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    ts: str
    quote_ts: Optional[str] = None
    event_slug: str
    market_key: str
    direction: Optional[str] = None
    model_probability: Optional[float] = None
    model_price_source: Optional[str] = None
    signal_yes_bid: Optional[float] = None
    signal_yes_ask: Optional[float] = None
    execution_spread: Optional[float] = None
    signal_top_ask_size: Optional[float] = None
    signal_probability: Optional[float] = None
    chainlink_feed_id: Optional[str] = None
    chainlink_capture_method: Optional[str] = None
    chainlink_source_url: Optional[str] = None
    chainlink_start_price: Optional[float] = None
    chainlink_end_price: Optional[float] = None
    chainlink_start_observed_at: Optional[int] = None
    chainlink_end_observed_at: Optional[int] = None
    chainlink_start_source_snapshot_path: Optional[str] = None
    chainlink_end_source_snapshot_path: Optional[str] = None
    chainlink_start_report_request_url: Optional[str] = None
    chainlink_end_report_request_url: Optional[str] = None
    chainlink_start_report_boundary_ts: Optional[int] = None
    chainlink_end_report_boundary_ts: Optional[int] = None
    chainlink_start_report_status: Optional[str] = None
    chainlink_end_report_status: Optional[str] = None
    chainlink_start_report_requires_authentication: bool = False
    chainlink_end_report_requires_authentication: bool = False
    exact_boundary_available: bool = False
    partial_boundary_available: bool = False
    resolved_yes: Optional[int] = None
    final_outcome: Optional[str] = None
    brier_score: Optional[float] = None
    log_loss: Optional[float] = None
    clv: Optional[float] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    no_trade_reasons: List[str] = []
    paper_actionable: bool = False


class EntertainmentCalibrationSummaryResponse(BaseModel):
    latest_scored_at: Optional[str] = None
    scoring_rows: int = 0
    pending_scoring_rows: int = 0
    settled_forecasts: int = 0
    brier_score: Optional[float] = None
    log_loss: Optional[float] = None
    paper_actionable: bool = False
    market_scope: str = "rotten_tomatoes_entertainment"
    calibration_kind: str = "rt_entertainment_outcome_score"
    source_snapshot: Optional[str] = None


class WeatherForecastResponse(BaseModel):
    city_key: str
    city_name: str
    target_date: str
    mean_high: float
    std_high: float
    mean_low: float
    std_low: float
    num_members: int
    ensemble_agreement: float


class WeatherMarketResponse(BaseModel):
    slug: str
    market_id: str
    platform: str = "polymarket"
    title: str
    city_key: str
    city_name: str
    target_date: str
    threshold_f: float
    metric: str
    direction: str
    yes_price: float
    no_price: float
    volume: float
    yes_midpoint: Optional[float] = None
    yes_last_price: Optional[float] = None
    recent_trades_count: int = 0


class WeatherDivergenceResponse(BaseModel):
    city_key: str
    target_date: str
    metric: str
    direction: str
    threshold_f: float

    polymarket_market_id: str
    kalshi_market_id: str
    polymarket_yes_price: float
    kalshi_yes_price: float
    probability_gap: float

    buy_yes_venue: str
    sell_yes_venue: str
    min_volume: float


class WeatherSignalResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    market_id: str
    city_key: str
    city_name: str
    target_date: str
    threshold_f: float
    metric: str
    direction: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    suggested_size: float
    reasoning: str
    ensemble_mean: float
    ensemble_std: float
    ensemble_members: int
    actionable: bool = False
    no_trade_reasons: List[str] = []
    execution_spread: Optional[float] = None
    top_ask_size: Optional[float] = None
    bucket_set_probability_mass: Optional[float] = None
    bucket_set_sanity_passed: bool = False
    bucket_set_size: int = 0


class RottenTomatoesSourceStateResponse(BaseModel):
    title: Optional[str] = None
    event_slug: Optional[str] = None
    source_url: Optional[str] = None
    source_method: Optional[str] = None
    captured_at: Optional[str] = None
    hours_since_source_refresh: Optional[float] = None
    tomatometer_score: Optional[int] = None
    review_count: Optional[int] = None
    previous_captured_at: Optional[str] = None
    previous_tomatometer_score: Optional[int] = None
    previous_review_count: Optional[int] = None
    score_delta: Optional[int] = None
    review_count_delta: Optional[int] = None
    hours_since_previous_source: Optional[float] = None
    direct_source_status: str = "unknown"
    timing_risk_label: Optional[str] = None
    cutoff_time: Optional[str] = None
    source_state_label: str = "source-state: unknown"
    paper_actionable: bool = False
    no_trade_reason: str = "source state only"
    no_trade_reasons: List[str] = []


class SignalReviewBlockerResponse(BaseModel):
    reason: str
    count: int


class SignalReviewItemResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    vertical: str
    market_key: str
    title: str
    primary_blocker: str
    no_trade_reasons: List[str] = []
    review_priority: int
    source_kind: Optional[str] = None
    edge: Optional[float] = None
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    threshold: Optional[float] = None
    box_office_lower_m: Optional[float] = None
    box_office_upper_m: Optional[float] = None
    box_office_bucket_label: Optional[str] = None
    box_office_bucket_type: Optional[str] = None
    box_office_bucket_set_size: Optional[int] = None
    box_office_bucket_set_probability_mass: Optional[float] = None
    box_office_bucket_set_sanity_passed: Optional[bool] = None
    box_office_resolved_yes_count: Optional[int] = None
    box_office_resolved_winner_label: Optional[str] = None
    market_closed: Optional[bool] = None
    execution_spread: Optional[float] = None
    top_ask_size: Optional[float] = None
    hours_since_source_refresh: Optional[float] = None
    settlement_source: Optional[str] = None
    settlement_url: Optional[str] = None
    settlement_station: Optional[str] = None
    settlement_station_name: Optional[str] = None
    settlement_units: Optional[str] = None
    settlement_precision: Optional[str] = None
    source_capture_status: Optional[str] = None
    source_observed_value: Optional[float] = None
    source_observed_unit: Optional[str] = None
    source_observed_at: Optional[str] = None
    source_capture_snapshot: Optional[str] = None
    station_anomaly_status: Optional[str] = None
    station_anomaly_neighbor_count: Optional[int] = None
    station_anomaly_max_delta: Optional[float] = None
    model_price_source: Optional[str] = None
    chainlink_feed_id: Optional[str] = None
    chainlink_capture_method: Optional[str] = None
    chainlink_source_url: Optional[str] = None
    chainlink_start_price: Optional[float] = None
    chainlink_end_price: Optional[float] = None
    chainlink_start_observed_at: Optional[int] = None
    chainlink_end_observed_at: Optional[int] = None
    chainlink_start_source_snapshot_path: Optional[str] = None
    chainlink_end_source_snapshot_path: Optional[str] = None
    source_url: Optional[str] = None
    source_method: Optional[str] = None
    direct_source_status: Optional[str] = None
    tomatometer_score: Optional[int] = None
    review_count: Optional[int] = None
    previous_captured_at: Optional[str] = None
    previous_tomatometer_score: Optional[int] = None
    previous_review_count: Optional[int] = None
    score_delta: Optional[int] = None
    review_count_delta: Optional[int] = None
    hours_since_previous_source: Optional[float] = None
    captured_at: Optional[str] = None
    cutoff_time: Optional[str] = None
    timing_risk_label: Optional[str] = None
    source_state_label: Optional[str] = None
    model_probability: Optional[float] = None
    market_probability: Optional[float] = None


class SignalReviewQueueResponse(BaseModel):
    total_blocked: int = 0
    blocked_by_vertical: dict = {}
    blocked_by_source: dict = {}
    top_blockers: List[SignalReviewBlockerResponse] = []
    items: List[SignalReviewItemResponse] = []


class EventResponse(BaseModel):
    timestamp: str
    type: str
    message: str
    data: dict = {}


class DashboardData(BaseModel):
    # Active dashboard scope. Weather-only is the current product direction;
    # set DASHBOARD_LEGACY_SECTIONS_ENABLED=true to temporarily surface legacy
    # BTC/RT dashboard panels without re-enabling trading.
    active_product_scope: str = "weather"
    legacy_dashboard_sections_enabled: bool = False
    legacy_dashboard_note: Optional[str] = None

    stats: BotStats
    btc_price: Optional[BtcPriceResponse]
    microstructure: Optional[MicrostructureResponse] = None
    windows: List[BtcWindowResponse]
    active_signals: List[SignalResponse]
    recent_trades: List[TradeResponse]
    equity_curve: List[dict]
    calibration: Optional[CalibrationSummary] = None
    weather_calibration: Optional[WeatherCalibrationSummaryResponse] = None
    weather_bot_calibration: Optional[WeatherCalibrationSummaryResponse] = None
    weather_calibration_rows: List[WeatherCalibrationRowResponse] = []
    weather_bot_calibration_rows: List[WeatherBotCalibrationRowResponse] = []
    weather_signal_review_candidates: List[WeatherSignalReviewCandidateResponse] = []
    polymarket_weather_source_states: List[PolymarketWeatherSourceStateResponse] = []
    polymarket_weather_source_state_summary: Optional[PolymarketWeatherSourceStateSummaryResponse] = None
    btc_calibration: Optional[BtcCalibrationSummaryResponse] = None
    btc_calibration_rows: List[BtcCalibrationRowResponse] = []
    entertainment_calibration: Optional[EntertainmentCalibrationSummaryResponse] = None
    weather_signals: List[WeatherSignalResponse] = []
    weather_divergences: List[WeatherDivergenceResponse] = []
    weather_forecasts: List[WeatherForecastResponse] = []
    rotten_tomatoes_source_states: List[RottenTomatoesSourceStateResponse] = []
    signal_review_queue: SignalReviewQueueResponse = SignalReviewQueueResponse()
    open_position_risk_rows: List[OpenPositionRiskRowResponse] = []
    open_position_risk_summary: OpenPositionRiskSummaryResponse = OpenPositionRiskSummaryResponse()


# ---------------------------------------------------------------------------
# Task 13: unified paper trading read models and manual run
#
# Money and quantities cross this boundary as STRINGS. On this stack a Decimal
# inside a pydantic model already serializes to a JSON string, but a bare
# Decimal dropped into a plain dict serializes to a float and silently loses the
# precision the ledger preserved. Declaring these `str` makes the boundary
# explicit rather than dependent on where the value happens to sit.
# ---------------------------------------------------------------------------


class TradingKillSwitchResponse(BaseModel):
    """Which flag is authoritative, named so an operator cannot flip a dead one."""

    engaged: bool
    source: str


class TradingVenueStateResponse(BaseModel):
    venue: str
    simulation: bool
    execution_enabled: bool
    monitor_only: bool


class TradingArchivesResponse(BaseModel):
    """The SHAPE of the Archives binding, never its contents.

    The runtime path list begins with the database URL, and a non-sqlite URL
    passes through unchanged, so returning the paths themselves would publish
    database credentials on any deployment that is not sqlite.
    """

    root_configured: bool
    root_available: bool
    runtime_paths_contained: bool
    required_directories_present: bool


class TradingStatusResponse(BaseModel):
    execution_mode: str
    paper_only: bool
    kill_switch: TradingKillSwitchResponse
    lanes: dict[str, bool]
    venues: List[TradingVenueStateResponse]
    credentials: dict[str, bool]
    archives: TradingArchivesResponse


class UnifiedOrderResponse(BaseModel):
    """An explicit projection of unified_orders.

    Deliberately not a dump: the projection copies adapter report metadata into
    a JSON column with no key filtering, so echoing it would publish whatever a
    strategy or adapter happened to put there.
    """

    client_order_id: str
    venue: str
    status: str
    broker_order_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    filled_quantity: str
    filled_notional: str
    average_fill_price: Optional[str] = None
    occurred_at: datetime


class TradingEventResponse(BaseModel):
    aggregate_id: str
    sequence: int
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any]


class TradingPositionResponse(BaseModel):
    symbol: str
    quantity: str
    notional: str


class TradingPortfolioResponse(BaseModel):
    """Absent state is reported as absent.

    The portfolio reader returns None rather than a placeholder when it cannot
    read real account state, because a risk decision made against invented
    exposure would be written to an append-only ledger as though it were real.
    Neither equity nor cash is ever derived from the other.
    """

    available: bool
    reason: Optional[str] = None
    equity: Optional[str] = None
    cash: Optional[str] = None
    positions: List[TradingPositionResponse] = []


class PaperRunResultResponse(BaseModel):
    """One proposal's outcome. Never the domain model.

    A TradeProposal carries a free-text rationale and a caller-supplied metadata
    dict, both of which survive a successful execution in memory. Only the
    fields named here leave the process.
    """

    proposal_id: str
    strategy_id: str
    venue: str
    asset_class: str
    symbol: str
    side: str
    outcome: str
    status: Optional[str] = None
    reason_codes: List[str] = []
    rejection_reason: Optional[str] = None
    notional: Optional[str] = None


class PaperRunResponse(BaseModel):
    ran: bool
    proposals: int
    results: List[PaperRunResultResponse] = []


class TradingRefusalResponse(BaseModel):
    """A fixed reason code. Never an exception string."""

    refused: str
