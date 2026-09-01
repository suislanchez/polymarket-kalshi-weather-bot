import { useState, useEffect, Suspense, lazy } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { fetchDashboard, runScan, simulateTrade, startBot, stopBot } from './api'
import { StatsCards } from './components/StatsCards'
import { SignalsTable } from './components/SignalsTable'
import { TradesTable } from './components/TradesTable'
import { EquityChart } from './components/EquityChart'
import { Terminal } from './components/Terminal'
import { MicrostructurePanel } from './components/MicrostructurePanel'
import { CalibrationPanel } from './components/CalibrationPanel'
import { WeatherPanel } from './components/WeatherPanel'
import { EdgeDistribution } from './components/EdgeDistribution'
import { GlobeErrorBoundary } from './components/GlobeErrorBoundary'
import { formatCountdown } from './utils'
import type { BtcWindow } from './types'

const GlobeView = lazy(() => import('./components/GlobeView').then(m => ({ default: m.GlobeView })))

function LiveClock() {
  const [time, setTime] = useState(new Date())
  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])
  return (
    <span className="text-xs tabular-nums text-neutral-400">
      {time.toLocaleTimeString('en-US', { hour12: false })}
    </span>
  )
}

function WindowPill({ window: w }: { window: BtcWindow }) {
  const [countdown, setCountdown] = useState(w.time_until_end)

  useEffect(() => {
    const interval = setInterval(() => {
      setCountdown(prev => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(interval)
  }, [w.time_until_end])

  return (
    <div className={`flex items-center gap-2 px-2 py-1 border shrink-0 ${w.is_active ? 'border-amber-500/30 bg-amber-500/5' : 'border-neutral-800 bg-neutral-900/50'}`}>
      {w.is_active && <span className="text-[9px] font-bold text-amber-400 uppercase">Live</span>}
      {w.is_upcoming && <span className="text-[9px] font-medium text-blue-400 uppercase">Next</span>}
      <span className="text-[10px] tabular-nums text-green-400">{(w.up_price * 100).toFixed(0)}c</span>
      <span className="text-neutral-600 text-[10px]">/</span>
      <span className="text-[10px] tabular-nums text-red-400">{(w.down_price * 100).toFixed(0)}c</span>
      <span className="text-[10px] tabular-nums text-neutral-500">{formatCountdown(countdown)}</span>
    </div>
  )
}

function RefreshBar({ interval }: { interval: number }) {
  const [progress, setProgress] = useState(100)

  useEffect(() => {
    setProgress(100)
    const step = 100 / (interval / 1000)
    const timer = setInterval(() => {
      setProgress(p => Math.max(0, p - step))
    }, 1000)
    return () => clearInterval(timer)
  }, [interval])

  return (
    <div className="refresh-bar w-16">
      <div className="refresh-fill" style={{ width: `${progress}%` }} />
    </div>
  )
}

function App() {
  const queryClient = useQueryClient()

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
    refetchInterval: 10000,
  })

  const scanMutation = useMutation({
    mutationFn: runScan,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  const tradeMutation = useMutation({
    mutationFn: simulateTrade,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  const startMutation = useMutation({
    mutationFn: startBot,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  const stopMutation = useMutation({
    mutationFn: stopBot,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  const activeSignals = data?.active_signals ?? []
  const recentTrades = data?.recent_trades ?? []
  const btcPrice = data?.btc_price
  const micro = data?.microstructure
  const windows = data?.windows ?? []
  const weatherSignals = data?.weather_signals ?? []
  const weatherForecasts = data?.weather_forecasts ?? []

  const stats = data?.stats ?? {
    is_running: false,
    last_run: null,
    total_trades: 0,
    total_pnl: 0,
    bankroll: 10000,
    winning_trades: 0,
    win_rate: 0
  }
  const equityCurve = data?.equity_curve ?? []
  const calibration = data?.calibration ?? null

  const actionableCount = activeSignals.filter(s => s.actionable).length + weatherSignals.filter(s => s.actionable).length

  if (isLoading) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="relative w-10 h-10 mx-auto mb-4">
            <div className="absolute inset-0 border-2 border-neutral-800 rounded-full" />
            <div className="absolute inset-0 border-2 border-transparent border-t-green-500 rounded-full animate-spin" />
          </div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">Initializing</div>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="text-red-500 text-xs uppercase mb-2 tracking-wider">Connection Error</div>
          <button
            onClick={() => refetch()}
            className="px-3 py-1.5 bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs uppercase tracking-wider"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen bg-black text-neutral-200 flex flex-col overflow-hidden">
      {/* ===== HEADER ===== */}
      <motion.header
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="shrink-0 border-b border-neutral-800 px-3 py-1.5 flex items-center gap-4 relative"
      >
        <div className="scan-line" />

        <div className="flex items-center gap-2 shrink-0">
          <h1 className="text-xs font-bold text-neutral-100 uppercase tracking-widest whitespace-nowrap font-mono">
            TRADING TERMINAL
          </h1>
          <span className={`px-1.5 py-0.5 text-[9px] font-bold uppercase ${
            stats.is_running
              ? 'bg-green-500/10 text-green-500 border border-green-500/20'
              : 'bg-neutral-800 text-neutral-500 border border-neutral-700'
          }`}>
            {stats.is_running ? 'Live' : 'Idle'}
          </span>
          <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase bg-amber-500/10 text-amber-400 border border-amber-500/20">
            Sim
          </span>
        </div>

        {btcPrice && (
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-sm font-bold tabular-nums text-neutral-100">
              ${btcPrice.price.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
            <span className={`text-[10px] tabular-nums ${btcPrice.change_24h >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              {btcPrice.change_24h >= 0 ? '+' : ''}{btcPrice.change_24h.toFixed(2)}%
            </span>
          </div>
        )}

        <div className="flex-1" />

        <StatsCards stats={stats} />

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => scanMutation.mutate()}
            disabled={scanMutation.isPending}
            className="px-2.5 py-1 bg-neutral-900 border border-neutral-700 hover:border-neutral-600 text-neutral-300 text-[10px] uppercase tracking-wider transition-colors disabled:opacity-50 whitespace-nowrap"
          >
            {scanMutation.isPending ? 'Scanning...' : 'Scan'}
          </button>
          <LiveClock />
        </div>
      </motion.header>

      {/* ===== MAIN GRID ===== */}
      <div className="flex-1 min-h-0 grid grid-cols-[300px_1fr_340px] grid-rows-[1fr] gap-0">

        {/* ===== LEFT COLUMN ===== */}
        <div className="flex flex-col border-r border-neutral-800 min-h-0 overflow-hidden">
          {/* Microstructure */}
          {micro && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="shrink-0 border-b border-neutral-800 px-2 py-2"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Microstructure</span>
                <span className="text-[9px] text-neutral-600 tabular-nums">{micro.source}</span>
              </div>
              <MicrostructurePanel micro={micro} />
            </motion.div>
          )}

          {/* Equity chart */}
          <div className="border-b border-neutral-800" style={{ height: '28%', minHeight: '120px' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Equity</span>
              <span className={`text-[10px] tabular-nums ${stats.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(0)}
              </span>
            </div>
            <div className="h-[calc(100%-24px)] p-1">
              <EquityChart data={equityCurve} initialBankroll={stats.bankroll - stats.total_pnl} />
            </div>
          </div>

          {/* Calibration */}
          {calibration && calibration.total_with_outcome > 0 && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="shrink-0 border-b border-neutral-800 px-2 py-2"
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Calibration</span>
                <span className="text-[9px] text-neutral-600 tabular-nums">{calibration.total_with_outcome} settled</span>
              </div>
              <CalibrationPanel calibration={calibration} />
            </motion.div>
          )}

          {/* Terminal fills remaining */}
          <div className="flex-1 min-h-0">
            <Terminal
              isRunning={stats.is_running}
              lastRun={stats.last_run}
              stats={{ total_trades: stats.total_trades, total_pnl: stats.total_pnl }}
              onStart={() => startMutation.mutate()}
              onStop={() => stopMutation.mutate()}
              onScan={() => scanMutation.mutate()}
            />
          </div>
        </div>

        {/* ===== CENTER COLUMN ===== */}
        <div className="flex flex-col min-h-0 border-r border-neutral-800">
          {/* Globe - top 60% */}
          <div className="relative" style={{ height: '58%' }}>
            <div className="absolute inset-0">
              <GlobeErrorBoundary>
                <Suspense fallback={
                  <div className="w-full h-full flex items-center justify-center bg-black">
                    <span className="text-[10px] text-neutral-600 uppercase tracking-wider">Loading Globe...</span>
                  </div>
                }>
                  <GlobeView forecasts={weatherForecasts} signals={weatherSignals} />
                </Suspense>
              </GlobeErrorBoundary>
            </div>
            {/* Globe overlay: actionable count */}
            <div className="absolute top-2 left-2 z-10">
              <div className="px-2 py-1 bg-black/80 border border-neutral-800 text-[10px]">
                <span className="text-neutral-500 uppercase tracking-wider mr-2">Markets</span>
                <span className="text-amber-500 tabular-nums">{actionableCount} actionable</span>
              </div>
            </div>
          </div>

          {/* Bottom panels - 3 side by side */}
          <div className="flex-1 min-h-0 grid grid-cols-3 border-t border-neutral-800">
            {/* Edge Distribution */}
            <div className="border-r border-neutral-800 flex flex-col min-h-0">
              <div className="px-2 py-1 border-b border-neutral-800 shrink-0">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Edge Distribution</span>
              </div>
              <div className="flex-1 min-h-0 p-1">
                <EdgeDistribution btcSignals={activeSignals} weatherSignals={weatherSignals} />
              </div>
            </div>

            {/* BTC Windows */}
            <div className="border-r border-neutral-800 flex flex-col min-h-0">
              <div className="px-2 py-1 border-b border-neutral-800 shrink-0">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">BTC Windows</span>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto p-1 space-y-1">
                {windows.length > 0 ? (
                  windows.slice(0, 10).map(w => (
                    <WindowPill key={w.slug} window={w} />
                  ))
                ) : (
                  <div className="text-[10px] text-neutral-600 p-2">No active windows</div>
                )}
              </div>
            </div>

            {/* Weather Forecasts */}
            <div className="flex flex-col min-h-0">
              <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Weather</span>
                <span className="px-1 py-0.5 text-[8px] font-bold uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">WX</span>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto">
                <WeatherPanel forecasts={weatherForecasts} signals={weatherSignals} />
              </div>
            </div>
          </div>
        </div>

        {/* ===== RIGHT COLUMN ===== */}
        <div className="flex flex-col min-h-0 overflow-hidden">
          {/* Signals - top portion */}
          <div className="flex flex-col min-h-0" style={{ height: '50%' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Signals</span>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-amber-400 tabular-nums">{activeSignals.length} BTC</span>
                {weatherSignals.length > 0 && (
                  <span className="text-[10px] text-cyan-400 tabular-nums">{weatherSignals.length} WX</span>
                )}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0">
              <SignalsTable
                signals={activeSignals}
                weatherSignals={weatherSignals}
                onSimulateTrade={(ticker) => tradeMutation.mutate(ticker)}
                isSimulating={tradeMutation.isPending}
              />
            </div>
          </div>

          {/* Trades */}
          <div className="flex flex-col min-h-0 border-t border-neutral-800" style={{ height: '50%' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Trades</span>
              <span className="text-[10px] text-neutral-600 tabular-nums">{recentTrades.length}</span>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0">
              <TradesTable trades={recentTrades} />
            </div>
          </div>
        </div>
      </div>

      {/* ===== FOOTER ===== */}
      <footer className="shrink-0 border-t border-neutral-800 px-3 py-0.5 flex items-center justify-between">
        <span className="text-[10px] text-neutral-700 font-mono">
          Binance/Coinbase | Open-Meteo | Polymarket + Kalshi
        </span>
        <div className="flex items-center gap-3">
          <RefreshBar interval={10000} />
          <span className="text-[10px] text-neutral-700 font-mono">BTC 5-min + Weather Temp</span>
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
            <span className="text-[10px] text-neutral-600 font-mono">Connected</span>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
