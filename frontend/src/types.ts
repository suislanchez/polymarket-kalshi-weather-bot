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
  volume: number
  is_active: boolean
  is_upcoming: boolean
  time_until_end: number
  spread: number
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
}

export interface BotStats {
  bankroll: number
  total_trades: number
  winning_trades: number
  win_rate: number
  total_pnl: number
  is_running: boolean
  last_run: string | null
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
  signal_source?: string
  metar_note?: string
  observation_source?: string
  station_id?: string
  observed_at?: string
  fetched_at?: string
  signal_at?: string
  observation_latency_seconds?: number
  signal_latency_seconds?: number
  threshold_state?: string
  fusion_lock_state?: string
  fusion_trade_allowed?: boolean
  fusion_authority_source?: string
  fusion_watch_sources?: string[]
  fusion_rejected_sources?: string[]
  fusion_conflicts?: string[]
  fusion_skip_reason?: string
  raw_hash?: string
  source_url?: string
  actionable: boolean
  platform?: string
}

export interface WeatherStatus {
  enabled: boolean
  fast_loop_interval_seconds: number
  next_fast_scan_in_seconds: number | null
  cache_age_seconds: number | null
  last_observation_age_seconds: number | null
  last_observation?: {
    source: string
    station_id: string
    observed_at: string
    fetched_at: string
    temp_f: number
    raw_hash: string
  } | null
  last_change?: Record<string, unknown> | null
}

export interface KalshiPosition {
  ticker: string
  contracts: number
  value: number
  cost: number
  unrealized_pnl: number
  realized_pnl: number
  side: string
  payout_if_win: number
  placed_ts: string
}

export interface KalshiData {
  balance: number
  portfolio_value: number
  total: number
  positions: KalshiPosition[]
  resting_orders: any[]
  last_live_trade_ts: string
  error: string | null
}

export interface PolyPosition {
  market: string
  title: string
  outcome: string
  token_id: string
  size: number
  avg_price: number
  current_price: number
  pnl: number
  coldmath: boolean
  new_trade: boolean
  placed_ts: string
  garbage: boolean
  unattributed: boolean
}

export interface PolyData {
  balance: number
  position_value: number
  total: number
  positions: PolyPosition[]
  last_live_trade_ts: string
  dry_run_warning: boolean
  error: string | null
}

export interface LifetimeData {
  lifetime_pnl: number
  kalshi_lifetime_pnl: number
  poly_lifetime_pnl: number
  total_deposited: number
  kalshi_deposited: number
  poly_deposited: number
  current_total: number
  today_spent: number
  error?: string | null
}

export interface MetarV2Signal {
  ts: string
  city: string
  icao: string
  condition_id: string
  question: string
  threshold_type: string
  threshold_raw: string
  v1: number
  v2: number | null
  side: string
  raw_temp_f: number
  peak_temp_f: number
  confidence: number
  raw_price: number
  microprice: number | null
  spread: number
  depth: number
  order_imbalance: number | null
  info_velocity: number
  ev_gross: number
  ev_net: number
  breakeven_q: number
  filtered_prob: number
  uncertainty: number
  flagged_informed: boolean
  recommend: boolean
  dry_run: boolean
}

export interface SystemStatus {
  services: { label: string; running: boolean }[]
  socks_up: boolean
}

export interface LiveData {
  ts: string
  kalshi: KalshiData
  polymarket: PolyData
  lifetime: LifetimeData
  metar_lines: string[]
  metar_poly_lines: string[]
  metar_v2_signals: MetarV2Signal[]
  weather_signals: WeatherSignal[]
  weather_forecasts: WeatherForecast[]
  system: SystemStatus
}

export interface KalshiMarket {
  condition_id: string
  city: string
  question: string
  side: string
  threshold_raw: string
  current_temp_f: number | null
  peak_temp_f: number | null
  confidence: number | null
  raw_price: number | null
  filtered_prob: number | null
  ev_net: number | null
  ev_gross: number | null
  uncertainty: number | null
  recommend: boolean
  flagged_informed: boolean
  dry_run: boolean
  is_traded: boolean
  status: 'bet_placed' | 'watching_hot' | 'watching' | 'flagged' | 'neutral'
  trigger: string
  roi_pct: number | null
  v1: number | null
  v2: number | null
  ts: string
}

export interface PolyMarket {
  condition_id: string
  city: string
  question: string
  side: string
  price: number | null
  bet_usd: number | null
  metar_temp_f: number | null
  threshold: string
  score: number | null
  score_desc: string | null
  dry_run: boolean
  order_success: boolean
  order_id: string
  ts: string
  status: 'holding' | 'bet_placed' | 'scanned' | 'dry_run'
  roi_pct: number | null
  current_price: number | null
  current_pnl: number | null
  position_size: number | null
  trigger: string
}

export interface DashboardData {
  stats: BotStats
  btc_price: BtcPrice | null
  microstructure: Microstructure | null
  windows: BtcWindow[]
  active_signals: Signal[]
  recent_trades: Trade[]
  equity_curve: EquityPoint[]
  calibration: CalibrationSummary | null
  weather_signals: WeatherSignal[]
  weather_forecasts: WeatherForecast[]
}
