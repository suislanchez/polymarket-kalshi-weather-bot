export interface CityWeather {
  city: string
  lat: number
  lon: number
  high_temp: number
  low_temp: number
  ensemble_count: number
  confidence: number
  prob_above_40: number
  prob_above_50: number
  prob_above_60: number
}

export interface Signal {
  market_ticker: string
  market_title: string
  platform: string
  city: string | null
  direction: string
  model_probability: number
  market_probability: number
  edge: number
  confidence: number
  suggested_size: number
  reasoning: string
  timestamp: string
}

export interface Trade {
  id: number
  market_ticker: string
  platform: string
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

export interface DashboardData {
  stats: BotStats
  cities: CityWeather[]
  active_signals: Signal[]
  recent_trades: Trade[]
  equity_curve: EquityPoint[]
}
