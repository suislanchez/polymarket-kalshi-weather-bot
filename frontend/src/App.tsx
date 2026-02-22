import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDashboard, runScan, simulateTrade, startBot, stopBot } from './api'
import { StatsCards } from './components/StatsCards'
import { SignalsTable } from './components/SignalsTable'
import { TradesTable } from './components/TradesTable'
import { EquityChart } from './components/EquityChart'
import { Terminal } from './components/Terminal'
import { formatCountdown } from './utils'
import type { BtcWindow, Microstructure } from './types'

function WindowPill({ window: w }: { window: BtcWindow }) {
  const [countdown, setCountdown] = useState(w.time_until_end)

  useEffect(() => {
    const interval = setInterval(() => {
      setCountdown(prev => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(interval)
  }, [w.time_until_end])

  return (
    <div className={`flex items-center gap-2 px-2 py-1 border shrink-0 ${w.is_active ? 'border-amber-500/30 bg-amber-500/5' : 'border-neutral-800 bg-neutral-900'}`}>
      {w.is_active && <span className="text-[9px] font-bold text-amber-400 uppercase">Live</span>}
      {w.is_upcoming && <span className="text-[9px] font-medium text-blue-400 uppercase">Next</span>}
      <span className="text-[10px] tabular-nums text-green-400">{(w.up_price * 100).toFixed(0)}c</span>
      <span className="text-neutral-600 text-[10px]">/</span>
      <span className="text-[10px] tabular-nums text-red-400">{(w.down_price * 100).toFixed(0)}c</span>
      <span className="text-[10px] tabular-nums text-neutral-500">{formatCountdown(countdown)}</span>
    </div>
  )
}

function IndicatorBar({ label, value, min, max, color }: { label: string; value: number; min: number; max: number; color: string }) {
  const range = max - min
  const pct = Math.max(0, Math.min(100, ((value - min) / range) * 100))
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-neutral-500 w-8 shrink-0 uppercase">{label}</span>
      <div className="flex-1 h-1.5 bg-neutral-800 relative">
        <div className={`absolute top-0 left-0 h-full ${color}`} style={{ width: `${pct}%` }} />
        {label === 'RSI' && (
          <>
            <div className="absolute top-0 h-full w-px bg-neutral-600" style={{ left: '30%' }} />
            <div className="absolute top-0 h-full w-px bg-neutral-600" style={{ left: '70%' }} />
          </>
        )}
      </div>
      <span className={`text-[10px] tabular-nums w-12 text-right ${color.replace('bg-', 'text-').replace('/80', '')}`}>
        {value.toFixed(label === 'Vol' ? 4 : 2)}{label === 'RSI' ? '' : '%'}
      </span>
    </div>
  )
}

function MicroPanel({ micro }: { micro: Microstructure }) {
  const rsiColor = micro.rsi < 30 ? 'bg-green-500/80' : micro.rsi > 70 ? 'bg-red-500/80' : 'bg-neutral-400/80'
  const momColor = micro.momentum_5m >= 0 ? 'bg-green-500/80' : 'bg-red-500/80'
  const vwapColor = micro.vwap_deviation >= 0 ? 'bg-green-500/80' : 'bg-red-500/80'
  const smaColor = micro.sma_crossover >= 0 ? 'bg-green-500/80' : 'bg-red-500/80'

  return (
    <div className="space-y-1">
      <IndicatorBar label="RSI" value={micro.rsi} min={0} max={100} color={rsiColor} />
      <IndicatorBar label="Mom" value={micro.momentum_5m} min={-0.2} max={0.2} color={momColor} />
      <IndicatorBar label="VWAP" value={micro.vwap_deviation} min={-0.2} max={0.2} color={vwapColor} />
      <IndicatorBar label="SMA" value={micro.sma_crossover} min={-0.1} max={0.1} color={smaColor} />
      <IndicatorBar label="Vol" value={micro.volatility} min={0} max={0.1} color="bg-blue-500/80" />
      <div className="text-[9px] text-neutral-600 pt-0.5">
        Source: {micro.source} | Mom1m: {micro.momentum_1m >= 0 ? '+' : ''}{micro.momentum_1m.toFixed(4)}% | Mom15m: {micro.momentum_15m >= 0 ? '+' : ''}{micro.momentum_15m.toFixed(4)}%
      </div>
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

  const actionableCount = activeSignals.filter(s => s.actionable).length

  if (isLoading) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="relative w-10 h-10 mx-auto mb-4">
            <div className="absolute inset-0 border-2 border-neutral-800 rounded-full"></div>
            <div className="absolute inset-0 border-2 border-transparent border-t-orange-500 rounded-full animate-spin"></div>
          </div>
          <div className="text-xs text-neutral-400 uppercase tracking-wider">Connecting...</div>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="text-red-500 text-xs uppercase mb-2">Connection Error</div>
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
      {/* Top bar */}
      <header className="shrink-0 border-b border-neutral-800 px-3 py-1.5 flex items-center gap-4">
        <div className="flex items-center gap-2 shrink-0">
          <h1 className="text-xs font-semibold text-neutral-100 uppercase tracking-wider whitespace-nowrap">BTC 5m Bot</h1>
          <span className={`px-1.5 py-0.5 text-[9px] font-medium uppercase ${
            stats.is_running
              ? 'bg-green-500/10 text-green-500 border border-green-500/20'
              : 'bg-neutral-800 text-neutral-500 border border-neutral-700'
          }`}>
            {stats.is_running ? 'Live' : 'Idle'}
          </span>
          <span className="px-1.5 py-0.5 text-[9px] font-medium uppercase bg-orange-500/10 text-orange-400 border border-orange-500/20">
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

        <button
          onClick={() => scanMutation.mutate()}
          disabled={scanMutation.isPending}
          className="px-2.5 py-1 bg-neutral-800 border border-neutral-700 hover:border-neutral-600 text-neutral-300 text-[10px] uppercase tracking-wider transition-colors disabled:opacity-50 whitespace-nowrap shrink-0"
        >
          {scanMutation.isPending ? 'Scanning...' : 'Scan'}
        </button>
      </header>

      {/* Windows strip */}
      <div className="shrink-0 border-b border-neutral-800 px-3 py-1 flex items-center gap-1.5 overflow-x-auto">
        <span className="text-[10px] text-neutral-600 uppercase tracking-wider shrink-0 mr-1">Windows</span>
        {windows.length > 0 ? (
          windows.slice(0, 8).map(w => (
            <WindowPill key={w.slug} window={w} />
          ))
        ) : (
          <span className="text-[10px] text-neutral-600">No active windows</span>
        )}
      </div>

      {/* Main content: 3 columns */}
      <div className="flex-1 min-h-0 grid grid-cols-[minmax(280px,1fr),minmax(320px,1.2fr),minmax(320px,1.2fr)] gap-0">
        {/* Col 1: Indicators + Chart + Terminal */}
        <div className="flex flex-col border-r border-neutral-800 min-h-0">
          {/* Microstructure indicators */}
          {micro && (
            <div className="shrink-0 border-b border-neutral-800 px-2 py-2">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Indicators</span>
                <span className="text-[9px] text-neutral-600">{micro.source}</span>
              </div>
              <MicroPanel micro={micro} />
            </div>
          )}

          {/* Equity chart */}
          <div className="flex flex-col border-b border-neutral-800" style={{ height: micro ? '30%' : '45%' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Performance</span>
              <span className={`text-[10px] tabular-nums ${stats.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(0)}
              </span>
            </div>
            <div className="flex-1 p-2 min-h-0">
              <EquityChart
                data={equityCurve}
                initialBankroll={stats.bankroll - stats.total_pnl}
              />
            </div>
          </div>

          {/* Terminal */}
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

        {/* Col 2: Signals */}
        <div className="flex flex-col border-r border-neutral-800 min-h-0">
          <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
            <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Signals</span>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-neutral-600">{activeSignals.length} total</span>
              <span className="px-1.5 py-0.5 text-[9px] font-medium bg-amber-500/10 text-amber-500 border border-amber-500/20">
                {actionableCount} actionable
              </span>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            <SignalsTable
              signals={activeSignals}
              onSimulateTrade={(ticker) => tradeMutation.mutate(ticker)}
              isSimulating={tradeMutation.isPending}
            />
          </div>
        </div>

        {/* Col 3: Trades */}
        <div className="flex flex-col min-h-0">
          <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
            <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Trades</span>
            <span className="text-[10px] text-neutral-600 tabular-nums">{recentTrades.length}</span>
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            <TradesTable trades={recentTrades} />
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="shrink-0 border-t border-neutral-800 px-3 py-0.5 text-center text-neutral-700 text-[10px]">
        Binance/Coinbase + Polymarket | BTC 5-min Up/Down | Simulation
      </footer>
    </div>
  )
}

export default App
