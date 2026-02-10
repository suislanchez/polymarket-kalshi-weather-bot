import axios from 'axios'
import type { DashboardData, Signal, CityWeather, Trade, BotStats } from './types'

const api = axios.create({
  baseURL: 'http://localhost:8000/api',
})

export async function fetchDashboard(): Promise<DashboardData> {
  const { data } = await api.get<DashboardData>('/dashboard')
  return data
}

export async function fetchSignals(): Promise<Signal[]> {
  const { data } = await api.get<Signal[]>('/signals/actionable')
  return data
}

export async function fetchWeather(): Promise<CityWeather[]> {
  const { data } = await api.get<CityWeather[]>('/weather')
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
