export interface BtcPrice {
  price: number
  change_24h: number
  change_7d: number
  market_cap: number
  volume_24h: number
  last_updated: string
}

export interface Microstructure {
  rsi: number
  momentum_1m: number
  momentum_5m: number
  momentum_15m: number
  vwap_deviation: number
  sma_crossover: number
  volatility: number
  price: number
  source: string
}

export interface BtcWindow {
  slug: string
  market_id: string
  up_price: number
  down_price: number
  window_start: string
  window_end: string
  window_start_ts?: number | null
  window_end_ts?: number | null
  volume: number
  is_active: boolean
  is_upcoming: boolean
  time_until_end: number
  spread: number
  up_bid?: number | null
  up_ask?: number | null
  up_ask_size?: number | null
  down_bid?: number | null
  down_ask?: number | null
  down_ask_size?: number | null
  settlement_source: string
  settlement_url?: string | null
}

export interface Signal {
  market_ticker: string
  market_title: string
  platform: string
  direction: string
  model_probability: number
  market_probability: number
  edge: number
  confidence: number
  suggested_size: number
  reasoning: string
  timestamp: string
  category: string
  event_slug?: string
  btc_price: number
  btc_change_24h: number
  window_end?: string
  actionable: boolean
  no_trade_reasons: string[]
  execution_spread?: number | null
  top_ask_size?: number | null
  settlement_source: string
  settlement_url?: string | null
  model_price_source: string
  chainlink_feed_id?: string | null
  chainlink_capture_method?: string | null
  chainlink_source_url?: string | null
  chainlink_start_price?: number | null
  chainlink_end_price?: number | null
  chainlink_start_observed_at?: number | null
  chainlink_end_observed_at?: number | null
  chainlink_start_source_snapshot_path?: string | null
  chainlink_end_source_snapshot_path?: string | null
}

export interface Trade {
  id: number
  market_ticker: string
  platform: string
  event_slug?: string | null
  direction: string
  entry_price: number
  size: number
  timestamp: string
  settled: boolean
  result: string
  pnl: number | null
  closed_early?: boolean
  exit_time?: string | null
  exit_price?: number | null
  exit_reason?: string | null
  unrealized_pnl?: number | null
  last_mark_price?: number | null
  last_mark_time?: string | null
  last_risk_action?: string | null
  last_risk_reasons?: string[]
  last_risk_source_status?: string | null
  last_risk_evidence?: Record<string, unknown>
}

export interface OpenPositionRiskRow {
  trade_id: number
  market_type: string
  market_ticker: string
  event_slug?: string | null
  direction: string
  entry_price: number
  size: number
  current_exit_price?: number | null
  unrealized_pnl?: number | null
  model_probability_for_held_side?: number | null
  market_probability_for_held_side?: number | null
  action: 'hold' | 'watch' | 'reduce' | 'exit' | string
  reasons: string[]
  source_status?: string | null
  risk_evidence?: Record<string, unknown>
  live_exit_quote_bid?: number | null
  live_exit_quote_ask?: number | null
  live_exit_quote_top_bid_size?: number | null
  live_exit_quote_top_ask_size?: number | null
  live_exit_quote_source?: string | null
  live_exit_quote_error?: string | null
  settlement_source_known?: boolean | null
  station_known?: boolean | null
  settlement_url?: string | null
  settlement_tags?: string[]
  latest_signal_id?: number | null
  latest_signal_timestamp?: string | null
  latest_signal_market_price?: number | null
  latest_signal_edge?: number | null
  latest_signal_suggested_size?: number | null
  latest_signal_model_probability_for_held_side?: number | null
  checked_at: string
  risk_scan_stale: boolean
}

export interface OpenPositionRiskSummary {
  total_open_positions: number
  action_counts: Record<string, number>
  auto_exit_enabled?: boolean
  recommendations_only?: boolean
  stale_mark_count: number
  live_exit_quote_error_count: number
  closed_market_or_stale_token_count: number
  source_status_counts: Record<string, number>
  latest_checked_at?: string | null
  exited_count?: number
}

export interface BotStats {
  bankroll: number
  total_trades: number
  winning_trades: number
  win_rate: number
  total_pnl: number
  is_running: boolean
  last_run: string | null
  weather_paper_account: WeatherPaperAccount
  btc_paper_account: BtcPaperAccount
  entertainment_paper_account: EntertainmentPaperAccount
}

export interface BtcPaperAccount {
  initial_bankroll: number
  target_bankroll: number
  current_equity: number
  realized_pnl: number
  remaining_to_target: number
  progress_to_target_pct: number
  total_trades: number
  settled_trades: number
  pending_trades: number
  winning_trades: number
  win_rate: number
  settled_forecasts: number
  brier_score: number | null
  log_loss: number | null
  paper_only: boolean
  selective_no_forced_trade: boolean
}

export interface EntertainmentPaperAccount extends BtcPaperAccount {
  market_scope: 'rotten_tomatoes_entertainment'
}

export interface WeatherPlatformBreakdown {
  platform: string
  total_trades: number
  settled_trades: number
  pending_trades: number
  pending_size: number
  winning_trades: number
  realized_pnl: number
}

export interface WeatherPaperAccount extends BtcPaperAccount {
  market_scope: 'weather'
  pending_size: number
  platform_breakdown: WeatherPlatformBreakdown[]
  ledger_exposure_state: 'no_trades' | 'all_settled' | 'open_positions' | string
  ledger_status_note: string
}

export interface EquityPoint {
  timestamp: string
  pnl: number
  bankroll: number
}

export interface CalibrationSummary {
  total_signals: number
  total_with_outcome: number
  accuracy: number
  avg_predicted_edge: number
  avg_actual_edge: number
  brier_score: number
}

export interface WeatherCalibrationSummary {
  latest_scored_at: string | null
  settled_forecasts: number
  brier_score: number | null
  log_loss: number | null
  paper_actionable: boolean
  market_scope: 'weather'
  calibration_kind: 'market_implied_quote_score' | string
  source_snapshot?: string | null
}

export interface WeatherCalibrationRow {
  scored_at: string
  quote_ts: string
  venue: string
  market_key: string
  outcome?: string | null
  market_probability: number
  resolved_yes: number
  resolved_value?: number | null
  brier_score?: number | null
  log_loss?: number | null
  source_url?: string | null
  source_snapshot?: string | null
  paper_actionable: boolean
  notes?: string | null
}

export interface WeatherBotCalibrationRow {
  scored_at: string
  signal_id?: number | null
  signal_ts?: string | null
  venue: string
  market_key: string
  outcome?: string | null
  model_probability: number
  market_probability?: number | null
  resolved_yes: number
  resolved_value?: number | null
  brier_score?: number | null
  log_loss?: number | null
  source_url?: string | null
  source_snapshot?: string | null
  paper_actionable: boolean
  executed: boolean
  calibration_kind: 'bot_model_signal_score' | string
  notes?: string | null
}

export interface WeatherSignalReviewCandidate {
  captured_at: string
  venue?: string | null
  market_key: string
  title?: string | null
  city?: string | null
  target_date?: string | null
  metric?: string | null
  direction?: string | null
  threshold_f?: number | null
  model_probability?: number | null
  market_probability?: number | null
  edge?: number | null
  confidence?: number | null
  suggested_size: number
  best_bid?: number | null
  best_ask?: number | null
  execution_spread?: number | null
  top_ask_size?: number | null
  settlement_source?: string | null
  settlement_station?: string | null
  settlement_source_url?: string | null
  no_trade_reasons: string[]
  source_snapshot?: string | null
  paper_actionable: boolean
  executed: boolean
  review_kind: 'weather_threshold_review_candidate' | string
  notes?: string | null
}

export interface PolymarketWeatherSourceState {
  captured_at: string
  event_slug?: string | null
  condition_id: string
  question?: string | null
  outcome?: string | null
  target_date?: string | null
  token_id?: string | null
  closed: boolean
  settlement_source?: string | null
  settlement_station?: string | null
  settlement_station_name?: string | null
  settlement_source_url?: string | null
  settlement_units?: string | null
  settlement_precision?: string | null
  best_bid?: number | null
  best_ask?: number | null
  execution_spread?: number | null
  market_probability?: number | null
  top_ask_size?: number | null
  volume?: number | null
  liquidity?: number | null
  source_snapshot?: string | null
  source_capture_status?: string | null
  source_observed_value?: number | null
  source_observed_unit?: string | null
  source_observed_at?: string | null
  source_capture_snapshot?: string | null
  station_anomaly_status?: string | null
  station_anomaly_neighbor_count?: number | null
  station_anomaly_neighbor_values?: number[] | null
  station_anomaly_max_delta?: number | null
  paper_actionable: boolean
  source_state_label: 'Polymarket weather source-state only / non-actionable' | string
  notes?: string | null
}

export interface PolymarketWeatherSourceStateSummary {
  latest_captured_at: string | null
  source_state_rows: number
  unique_events: number
  unique_conditions: number
  unique_stations: number
  target_date_rows: number
  unique_target_dates: number
  wunderground_rows: number
  hko_rows: number
  hko_observed_value_rows: number
  hko_missing_target_date_rows: number
  hko_error_rows: number
  direct_source_url_rows: number
  unique_source_urls: number
  line_book_rows: number
  open_rows: number
  open_line_book_rows: number
  open_top_ask_size_rows: number
  closed_line_book_rows: number
  category_warning_rows: number
  category_partial_rows: number
  category_hko_rows: number
  category_observed_rows: number
  category_source_only_rows: number
  open_category_warning_rows: number
  open_category_partial_rows: number
  open_category_hko_rows: number
  open_category_observed_rows: number
  open_category_source_only_rows: number
  closed_category_warning_rows: number
  closed_category_partial_rows: number
  closed_category_hko_rows: number
  closed_category_observed_rows: number
  closed_category_source_only_rows: number
  market_probability_rows: number
  yes_market_probability_rows: number
  no_market_probability_rows: number
  complete_binary_condition_pairs: number
  incomplete_binary_condition_pairs: number
  yes_market_probability_mass_event_count: number
  yes_market_probability_mass_min?: number | null
  yes_market_probability_mass_max?: number | null
  yes_market_probability_mass_sanity_passed_count: number
  yes_market_probability_mass_blocked_count: number
  top_ask_size_rows: number
  closed_rows: number
  source_capture_attempted_rows: number
  source_capture_unique_urls: number
  source_capture_missing_rows: number
  source_capture_missing_unique_urls: number
  source_capture_no_data_rows: number
  source_capture_observed_value_rows: number
  source_capture_error_rows: number
  history_capture_rows: number
  history_observed_value_rows: number
  history_partial_rows: number
  history_complete_rows: number
  history_unique_source_urls: number
  history_partial_unique_source_urls: number
  history_partial_unique_stations: number
  station_anomaly_checked_rows: number
  station_anomaly_neighbor_evidence_rows: number
  station_anomaly_neighbor_evidence_max_count: number
  station_anomaly_not_checked_rows: number
  station_anomaly_missing_observation_rows: number
  station_anomaly_missing_neighbors_rows: number
  station_anomaly_warning_rows: number
  station_anomaly_warning_unique_events: number
  station_anomaly_warning_unique_stations: number
  station_anomaly_warning_unique_source_urls: number
  station_anomaly_warning_max_delta?: number | null
  station_anomaly_passed_rows: number
  station_anomaly_max_delta?: number | null
  paper_actionable: boolean
  market_scope: 'weather' | string
  source_snapshot?: string | null
  source_state_label: 'Polymarket weather source-state only / non-actionable' | string
}

export interface BtcCalibrationSummary {
  latest_scored_at: string | null
  scoring_rows: number
  pending_scoring_rows: number
  settled_forecasts: number
  brier_score: number | null
  log_loss: number | null
  exact_boundary_rows: number
  partial_boundary_rows: number
  line_book_rows: number
  top_ask_size_rows: number
  model_probability_rows: number
  exchange_spot_model_rows: number
  source_mismatch_rows: number
  chainlink_auth_blocked_rows: number
  unique_window_count: number
  active_window_count: number
  upcoming_window_count: number
  expired_window_count: number
  min_seconds_to_window_end?: number | null
  max_seconds_to_window_end?: number | null
  max_execution_spread?: number | null
  min_signal_top_ask_size?: number | null
  report_request_rows: number
  auth_required_report_requests: number
  paper_actionable: boolean
  market_scope: 'btc'
  calibration_kind: 'chainlink_boundary_outcome_score' | string
  source_snapshot?: string | null
}

export interface BtcCalibrationRow {
  ts: string
  quote_ts?: string | null
  event_slug: string
  market_key: string
  direction?: string | null
  model_probability?: number | null
  model_price_source?: string | null
  signal_yes_bid?: number | null
  signal_yes_ask?: number | null
  execution_spread?: number | null
  signal_top_ask_size?: number | null
  signal_probability?: number | null
  chainlink_feed_id?: string | null
  chainlink_capture_method?: string | null
  chainlink_source_url?: string | null
  chainlink_start_price?: number | null
  chainlink_end_price?: number | null
  chainlink_start_observed_at?: number | null
  chainlink_end_observed_at?: number | null
  chainlink_start_source_snapshot_path?: string | null
  chainlink_end_source_snapshot_path?: string | null
  chainlink_start_report_request_url?: string | null
  chainlink_end_report_request_url?: string | null
  chainlink_start_report_boundary_ts?: number | null
  chainlink_end_report_boundary_ts?: number | null
  chainlink_start_report_status?: string | null
  chainlink_end_report_status?: string | null
  chainlink_start_report_requires_authentication: boolean
  chainlink_end_report_requires_authentication: boolean
  exact_boundary_available: boolean
  partial_boundary_available: boolean
  resolved_yes?: number | null
  final_outcome?: string | null
  brier_score?: number | null
  log_loss?: number | null
  clv?: number | null
  status?: string | null
  notes?: string | null
  no_trade_reasons: string[]
  paper_actionable: boolean
}

export interface EntertainmentCalibrationSummary {
  latest_scored_at: string | null
  scoring_rows: number
  pending_scoring_rows: number
  settled_forecasts: number
  brier_score: number | null
  log_loss: number | null
  paper_actionable: boolean
  market_scope: 'rotten_tomatoes_entertainment'
  calibration_kind: 'rt_entertainment_outcome_score' | string
  source_snapshot?: string | null
}

export interface WeatherForecast {
  city_key: string
  city_name: string
  target_date: string
  mean_high: number
  std_high: number
  mean_low: number
  std_low: number
  num_members: number
  ensemble_agreement: number
}

export interface WeatherSignal {
  market_id: string
  city_key: string
  city_name: string
  target_date: string
  threshold_f: number
  metric: string
  direction: string
  model_probability: number
  market_probability: number
  edge: number
  confidence: number
  suggested_size: number
  reasoning: string
  ensemble_mean: number
  ensemble_std: number
  ensemble_members: number
  actionable: boolean
  no_trade_reasons: string[]
  execution_spread?: number | null
  top_ask_size?: number | null
  bucket_set_probability_mass?: number | null
  bucket_set_sanity_passed?: boolean
  bucket_set_size?: number
  platform?: string
}

export interface RottenTomatoesSourceState {
  title?: string | null
  event_slug?: string | null
  source_url?: string | null
  source_method?: string | null
  captured_at?: string | null
  hours_since_source_refresh?: number | null
  tomatometer_score?: number | null
  review_count?: number | null
  previous_captured_at?: string | null
  previous_tomatometer_score?: number | null
  previous_review_count?: number | null
  score_delta?: number | null
  review_count_delta?: number | null
  hours_since_previous_source?: number | null
  direct_source_status: string
  timing_risk_label?: string | null
  cutoff_time?: string | null
  source_state_label: string
  paper_actionable: boolean
  no_trade_reason: string
  no_trade_reasons?: string[]
}

export interface SignalReviewBlocker {
  reason: string
  count: number
}

export interface SignalReviewItem {
  vertical: 'btc' | 'weather' | 'rt_entertainment' | string
  market_key: string
  title: string
  primary_blocker: string
  no_trade_reasons: string[]
  review_priority: number
  source_kind?: string | null
  edge?: number | null
  best_bid?: number | null
  best_ask?: number | null
  threshold?: number | null
  box_office_lower_m?: number | null
  box_office_upper_m?: number | null
  box_office_bucket_label?: string | null
  box_office_bucket_type?: string | null
  box_office_bucket_set_size?: number | null
  box_office_bucket_set_probability_mass?: number | null
  box_office_bucket_set_sanity_passed?: boolean | null
  box_office_resolved_yes_count?: number | null
  box_office_resolved_winner_label?: string | null
  market_closed?: boolean | null
  execution_spread?: number | null
  top_ask_size?: number | null
  hours_since_source_refresh?: number | null
  settlement_source?: string | null
  settlement_url?: string | null
  settlement_station?: string | null
  settlement_station_name?: string | null
  settlement_units?: string | null
  settlement_precision?: string | null
  source_capture_status?: string | null
  source_observed_value?: number | null
  source_observed_unit?: string | null
  source_observed_at?: string | null
  source_capture_snapshot?: string | null
  station_anomaly_status?: string | null
  station_anomaly_neighbor_count?: number | null
  station_anomaly_max_delta?: number | null
  model_price_source?: string | null
  chainlink_feed_id?: string | null
  chainlink_capture_method?: string | null
  chainlink_source_url?: string | null
  chainlink_start_price?: number | null
  chainlink_end_price?: number | null
  chainlink_start_observed_at?: number | null
  chainlink_end_observed_at?: number | null
  chainlink_start_source_snapshot_path?: string | null
  chainlink_end_source_snapshot_path?: string | null
  source_url?: string | null
  source_method?: string | null
  direct_source_status?: string | null
  tomatometer_score?: number | null
  review_count?: number | null
  previous_captured_at?: string | null
  previous_tomatometer_score?: number | null
  previous_review_count?: number | null
  score_delta?: number | null
  review_count_delta?: number | null
  hours_since_previous_source?: number | null
  captured_at?: string | null
  cutoff_time?: string | null
  timing_risk_label?: string | null
  source_state_label?: string | null
  model_probability?: number | null
  market_probability?: number | null
}

export interface SignalReviewQueue {
  total_blocked: number
  blocked_by_vertical: Record<string, number>
  blocked_by_source: Record<string, number>
  top_blockers: SignalReviewBlocker[]
  items: SignalReviewItem[]
}

export interface DashboardData {
  active_product_scope: string
  legacy_dashboard_sections_enabled: boolean
  legacy_dashboard_note: string | null
  stats: BotStats
  btc_price: BtcPrice | null
  microstructure: Microstructure | null
  windows: BtcWindow[]
  active_signals: Signal[]
  recent_trades: Trade[]
  equity_curve: EquityPoint[]
  calibration: CalibrationSummary | null
  weather_calibration: WeatherCalibrationSummary | null
  weather_bot_calibration: WeatherCalibrationSummary | null
  weather_calibration_rows: WeatherCalibrationRow[]
  weather_bot_calibration_rows: WeatherBotCalibrationRow[]
  weather_signal_review_candidates: WeatherSignalReviewCandidate[]
  polymarket_weather_source_states: PolymarketWeatherSourceState[]
  polymarket_weather_source_state_summary: PolymarketWeatherSourceStateSummary | null
  btc_calibration: BtcCalibrationSummary | null
  btc_calibration_rows: BtcCalibrationRow[]
  entertainment_calibration: EntertainmentCalibrationSummary | null
  weather_signals: WeatherSignal[]
  weather_forecasts: WeatherForecast[]
  rotten_tomatoes_source_states: RottenTomatoesSourceState[]
  signal_review_queue: SignalReviewQueue
  open_position_risk_rows: OpenPositionRiskRow[]
  open_position_risk_summary: OpenPositionRiskSummary
}
