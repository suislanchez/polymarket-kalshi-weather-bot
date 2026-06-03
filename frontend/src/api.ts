import axios from 'axios'
import type { DashboardData, Signal, Trade, BotStats, BtcPrice, BtcWindow, WeatherForecast, WeatherSignal, WeatherStatus, KalshiMarket, PolyMarket } from './types'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8765'

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

export async function fetchWeatherStatus(): Promise<WeatherStatus> {
  const { data } = await api.get<WeatherStatus>('/weather/status')
  return data
}

export async function fetchKalshiMarkets(): Promise<{ markets: KalshiMarket[], count: number, traded_today_count: number }> {
  const { data } = await api.get('/kalshi/markets')
  return data
}

export async function fetchPolyMarkets(): Promise<{ markets: PolyMarket[], count: number }> {
  const { data } = await api.get('/polymarket/markets')
  return data
}

export async function fetchLiveData(): Promise<import('./types').LiveData> {
  const { data } = await axios.get(`${API_BASE}/api/data`)
  return data
}

export interface SettingsData {
  simulation_mode: boolean
  kalshi_configured: boolean
  kalshi_key_id: string
  initial_bankroll: number
  weather_min_edge_threshold: number
  weather_max_trade_size: number
}

export async function fetchSettings(): Promise<SettingsData> {
  const { data } = await api.get<SettingsData>('/settings')
  return data
}

export async function updateSettings(payload: Record<string, any>): Promise<{ ok: boolean; kalshi_configured: boolean; simulation_mode: boolean }> {
  const { data } = await api.post('/settings', payload)
  return data
}

export async function testKalshiConnection(): Promise<{ ok: boolean; balance?: any; error?: string }> {
  const { data } = await api.post('/settings/test-connection')
  return data
}
