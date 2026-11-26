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
  actionable: boolean
  platform?: string
}

export interface WeatherMarket {
  slug: string
  market_id: string
  platform: string
  title: string
  city_key: string
  city_name: string
  target_date: string
  threshold_f: number
  metric: 'high' | 'low'
  direction: 'above' | 'below'
  yes_price: number
  no_price: number
  volume: number
  pred_mean?: number | null
  pred_std?: number | null
}

export interface H2HMeeting {
  date: string
  home: string
  away: string
  score: string
}

export interface FormMatch {
  date: string
  opponent: string
  score: string
  both_scored: boolean
}

export interface FootballFixture {
  id: string
  date: string
  home_team: string
  away_team: string
  home_avg_gf: number
  away_avg_gf: number
  h2h_count: number
  h2h_total_avg: number
  h2h_meetings: H2HMeeting[]
  home_form: FormMatch[]
  away_form: FormMatch[]
  home_form_status: 'good' | 'bad' | 'neutral'
  away_form_status: 'good' | 'bad' | 'neutral'
  kalshi?: {
    ticker: string
    over_price: number
    under_price: number
    title: string
  }
  bet_signal: boolean
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
  weather_markets: WeatherMarket[]
  football_fixtures: FootballFixture[]
}
