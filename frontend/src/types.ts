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
  signal_source?: string
  metar_note?: string
  gfs_probability?: number
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

export interface LifetimeData {
  lifetime_pnl: number
  kalshi_lifetime_pnl: number
  total_deposited: number
  kalshi_deposited: number
  current_total: number
  today_spent: number
  error?: string | null
}

export interface SystemStatus {
  services: { label: string; running: boolean }[]
  weather_enabled: boolean
  kalshi_configured: boolean
  signal_cache_age_seconds: number | null
}

export interface LiveData {
  ts: string
  kalshi: KalshiData
  lifetime: LifetimeData
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
