import axios from 'axios'
import type { KalshiMarket, LiveData } from './types'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8765'

const api = axios.create({
  baseURL: `${API_BASE}/api`,
})

export async function runScan(): Promise<{ weather_signals: number; weather_actionable: number }> {
  const { data } = await api.post('/run-scan')
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

export async function fetchKalshiMarkets(): Promise<{ markets: KalshiMarket[], count: number, traded_today_count: number }> {
  const { data } = await api.get('/kalshi/markets')
  return data
}

export async function fetchLiveData(): Promise<LiveData> {
  const { data } = await axios.get(`${API_BASE}/api/data`)
  return data
}

export interface SettingsData {
  simulation_mode: boolean
  kalshi_configured: boolean
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
