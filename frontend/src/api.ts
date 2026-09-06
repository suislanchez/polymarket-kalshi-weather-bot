import axios from 'axios'
import type { DashboardData, Signal, Trade, BotStats, BtcPrice, BtcWindow, WeatherForecast, WeatherSignal, PolymarketWeatherSourceState, TradingStatus, TradingPortfolio, UnifiedOrder } from './types'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const api = axios.create({
  baseURL: `${API_BASE}/api`,
})

export async function fetchDashboard(): Promise<DashboardData> {
  const { data } = await api.get<DashboardData>('/dashboard')
  return data
}

export async function fetchSignals(): Promise<Signal[]> {
  const { data } = await api.get<Signal[]>('/signals')
  return data
}

export async function fetchBtcPrice(): Promise<BtcPrice | null> {
  const { data } = await api.get<BtcPrice | null>('/btc/price')
  return data
}

export async function fetchBtcWindows(): Promise<BtcWindow[]> {
  const { data } = await api.get<BtcWindow[]>('/btc/windows')
  return data
}

export async function fetchTrades(): Promise<Trade[]> {
  const { data } = await api.get<Trade[]>('/trades')
  return data
}

export async function fetchStats(): Promise<BotStats> {
  const { data } = await api.get<BotStats>('/stats')
  return data
}

export async function runScan(): Promise<{ total_signals: number; actionable_signals: number }> {
  const { data } = await api.post('/run-scan')
  return data
}

export async function simulateTrade(ticker: string): Promise<{ trade_id: number; size: number }> {
  const { data } = await api.post('/simulate-trade', null, {
    params: { signal_ticker: ticker }
  })
  return data
}

export async function startBot(): Promise<{ status: string; is_running: boolean }> {
  const { data } = await api.post('/bot/start')
  return data
}

export async function stopBot(): Promise<{ status: string; is_running: boolean }> {
  const { data } = await api.post('/bot/stop')
  return data
}

export async function settleTradesApi(): Promise<{ settled_count: number }> {
  const { data } = await api.post('/settle-trades')
  return data
}

export async function resetBot(): Promise<{ status: string; trades_deleted: number; new_bankroll: number }> {
  const { data } = await api.post('/bot/reset')
  return data
}

export async function fetchWeatherForecasts(): Promise<WeatherForecast[]> {
  const { data } = await api.get<WeatherForecast[]>('/weather/forecasts')
  return data
}

export async function fetchWeatherSignals(): Promise<WeatherSignal[]> {
  const { data } = await api.get<WeatherSignal[]>('/weather/signals')
  return data
}

export async function fetchPolymarketWeatherSourceStates({
  category = 'all',
  marketState = 'all',
  limit = 25,
}: {
  category?: string
  marketState?: string
  limit?: number
} = {}): Promise<PolymarketWeatherSourceState[]> {
  const { data } = await api.get<PolymarketWeatherSourceState[]>('/weather/polymarket-source-states', {
    params: {
      category,
      market_state: marketState,
      limit,
    },
  })
  return data
}

export async function fetchTradingStatus(): Promise<TradingStatus> {
  const { data } = await api.get<TradingStatus>('/trading/status')
  return data
}

export async function fetchTradingOrders(): Promise<UnifiedOrder[]> {
  const { data } = await api.get<UnifiedOrder[]>('/trading/orders')
  return data
}

export async function fetchTradingPortfolio(): Promise<TradingPortfolio> {
  const { data } = await api.get<TradingPortfolio>('/trading/portfolio')
  return data
}
