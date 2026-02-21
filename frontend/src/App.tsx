import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDashboard, runScan, simulateTrade, startBot, stopBot } from './api'
import { StatsCards } from './components/StatsCards'
import { SignalsTable } from './components/SignalsTable'
import { TradesTable } from './components/TradesTable'
import { EquityChart } from './components/EquityChart'
import { Terminal } from './components/Terminal'
import { formatCountdown } from './utils'
import type { BtcWindow } from './types'

function BtcPriceHeader({ price, change24h }: { price: number; change24h: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-2xl font-bold tabular-nums text-neutral-100">
        ${price.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
      </span>
      <span className={`text-sm font-medium tabular-nums ${change24h >= 0 ? 'text-green-500' : 'text-red-500'}`}>
        {change24h >= 0 ? '+' : ''}{change24h.toFixed(2)}%
      </span>
    </div>
  )
}

function WindowCard({ window: w }: { window: BtcWindow }) {
  const [countdown, setCountdown] = useState(w.time_until_end)

  useEffect(() => {
    const interval = setInterval(() => {
      setCountdown(prev => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(interval)
  }, [w.time_until_end])

  const upPercent = (w.up_price * 100).toFixed(1)
  const downPercent = (w.down_price * 100).toFixed(1)
  const isActive = w.is_active

  return (
    <div className={`bg-neutral-900 border p-3 ${isActive ? 'border-amber-500/40' : 'border-neutral-800'}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {isActive && (
            <span className="px-1.5 py-0.5 text-[10px] font-bold uppercase bg-amber-500/20 text-amber-400 border border-amber-500/30">
              LIVE
            </span>
          )}
          {w.is_upcoming && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium uppercase bg-blue-500/10 text-blue-400 border border-blue-500/20">
              NEXT
            </span>
          )}
        </div>
        <span className="text-xs text-neutral-500 tabular-nums">
          {formatCountdown(countdown)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="text-center p-2 bg-green-500/5 border border-green-500/10">
          <div className="text-[10px] uppercase text-green-500/70 mb-1">Up</div>
          <div className="text-lg font-semibold tabular-nums text-green-400">{upPercent}%</div>
        </div>
        <div className="text-center p-2 bg-red-500/5 border border-red-500/10">
          <div className="text-[10px] uppercase text-red-500/70 mb-1">Down</div>
          <div className="text-lg font-semibold tabular-nums text-red-400">{downPercent}%</div>
        </div>
      </div>

      <div className="mt-2 text-[10px] text-neutral-600 truncate" title={w.slug}>
        {w.slug}
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

  if (isLoading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="relative w-12 h-12 mx-auto mb-6">
            <div className="absolute inset-0 border-2 border-neutral-800 rounded-full"></div>
            <div className="absolute inset-0 border-2 border-transparent border-t-orange-500 rounded-full animate-spin"></div>
          </div>
          <div className="text-sm font-medium text-neutral-300 uppercase tracking-wider mb-1">Loading</div>
          <div className="text-xs text-neutral-600">Connecting to BTC trading systems...</div>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="text-center max-w-md mx-auto p-8">
          <div className="text-red-500 text-xs uppercase tracking-wider mb-2">Connection Error</div>
          <div className="text-neutral-300 text-sm mb-6">
            Unable to connect to backend API. Check your connection and try again.
          </div>
          <button
            onClick={() => refetch()}
            className="px-4 py-2 bg-neutral-900 border border-neutral-700 hover:border-neutral-600 text-neutral-300 text-xs uppercase tracking-wider transition-colors"
          >
            Retry Connection
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-black text-neutral-200">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-6">
        {/* Header */}
        <header className="mb-6">
          <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
            <div>
              <div className="flex items-center gap-3 mb-1">
                <h1 className="text-lg font-semibold text-neutral-100 uppercase tracking-wider">
                  BTC 5-Min Trading Bot
                </h1>
                <span className={`px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${
                  stats.is_running
                    ? 'bg-green-500/10 text-green-500 border border-green-500/20'
                    : 'bg-neutral-800 text-neutral-500 border border-neutral-700'
                }`}>
                  {stats.is_running ? 'Live' : 'Idle'}
                </span>
                <span className="px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider bg-orange-500/10 text-orange-400 border border-orange-500/20">
                  Simulation
                </span>
              </div>
              <div className="flex items-center gap-4">
                {btcPrice && (
                  <BtcPriceHeader price={btcPrice.price} change24h={btcPrice.change_24h} />
                )}
                <p className="text-neutral-600 text-xs">
                  Polymarket Up/Down 5-min markets
                  {stats.last_run && (
                    <span className="ml-2">| Last scan: {new Date(stats.last_run).toLocaleTimeString()}</span>
                  )}
                </p>
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => scanMutation.mutate()}
                disabled={scanMutation.isPending}
                className="px-4 py-2 bg-neutral-800 border border-neutral-700 hover:border-neutral-600 text-neutral-300 text-xs uppercase tracking-wider transition-colors flex items-center gap-2 disabled:opacity-50"
              >
                {scanMutation.isPending && (
                  <div className="w-3 h-3 border border-neutral-600 border-t-orange-500 rounded-full animate-spin" />
                )}
                Scan Markets
              </button>
            </div>
          </div>
        </header>

        {/* Stats Grid */}
        <section className="mb-3">
          <StatsCards stats={stats} />
        </section>

        {/* BTC Windows + Equity Chart */}
        <div className="grid gap-3 xl:grid-cols-[2fr,3fr] mb-3">
          {/* Active Windows */}
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden">
            <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">5-Min Windows</span>
              <span className="text-[10px] text-neutral-600">{windows.length} markets</span>
            </div>
            <div className="p-3 space-y-2 max-h-[340px] overflow-y-auto">
              {windows.length > 0 ? (
                windows.slice(0, 6).map(w => (
                  <WindowCard key={w.slug} window={w} />
                ))
              ) : (
                <div className="text-neutral-600 text-sm py-8 text-center">
                  No active windows found
                </div>
              )}
            </div>
          </div>

          {/* Equity Chart + Terminal */}
          <div className="grid gap-3 grid-rows-[1fr,1fr]">
            <div className="bg-neutral-900 border border-neutral-800 overflow-hidden flex flex-col">
              <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
                <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">Portfolio Performance</span>
                <span className={`text-xs tabular-nums ${stats.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                  {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(0)}
                </span>
              </div>
              <div className="p-3 flex-1">
                <EquityChart
                  data={equityCurve}
                  initialBankroll={stats.bankroll - stats.total_pnl}
                />
              </div>
            </div>

            <div className="bg-neutral-900 border border-neutral-800 overflow-hidden">
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
        </div>

        {/* Signals & Trades */}
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden flex flex-col">
            <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">BTC Signals</span>
              <span className="px-2 py-0.5 text-[10px] font-medium bg-amber-500/10 text-amber-500 border border-amber-500/20">
                {activeSignals.length} actionable
              </span>
            </div>
            <div className="p-3 max-h-[360px] overflow-y-auto flex-1">
              <SignalsTable
                signals={activeSignals}
                onSimulateTrade={(ticker) => tradeMutation.mutate(ticker)}
                isSimulating={tradeMutation.isPending}
              />
            </div>
          </div>
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden flex flex-col">
            <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">Trade History</span>
              <span className="text-[10px] text-neutral-600 tabular-nums">
                {recentTrades.length} trades
              </span>
            </div>
            <div className="p-3 max-h-[360px] overflow-y-auto flex-1">
              <TradesTable trades={recentTrades} />
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="mt-6 text-center text-neutral-700 text-xs">
          <p>Data: CoinGecko, Polymarket | BTC 5-min Up/Down markets | Simulation mode</p>
        </footer>
      </div>
    </div>
  )
}

export default App
