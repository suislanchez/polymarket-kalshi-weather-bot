import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDashboard, runScan, simulateTrade, startBot, stopBot, fetchAIStats } from './api'
import { StatsCards } from './components/StatsCards'
import { SignalsTable } from './components/SignalsTable'
import { TradesTable } from './components/TradesTable'
import { EquityChart } from './components/EquityChart'
import { Terminal } from './components/Terminal'
import { FilterBar, type FilterState } from './components/FilterBar'

function App() {
  const queryClient = useQueryClient()

  // Filter state
  const [signalFilters, setSignalFilters] = useState<FilterState>({
    search: '',
    platform: 'all',
    category: 'all',
    city: '',
    status: 'all'
  })

  const [tradeFilters, setTradeFilters] = useState<FilterState>({
    search: '',
    platform: 'all',
    category: 'all',
    city: '',
    status: 'all'
  })

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
    refetchInterval: 10000, // Faster refresh for aggressive trading
  })

  // AI cost tracking
  const { data: aiStats } = useQuery({
    queryKey: ['aiStats'],
    queryFn: fetchAIStats,
    refetchInterval: 30000,
  })

  const scanMutation = useMutation({
    mutationFn: runScan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const tradeMutation = useMutation({
    mutationFn: simulateTrade,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const startMutation = useMutation({
    mutationFn: startBot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const stopMutation = useMutation({
    mutationFn: stopBot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const activeSignals = data?.active_signals ?? []
  const recentTrades = data?.recent_trades ?? []
  const citiesData = data?.cities ?? []

  // Get unique cities from signals
  const cities = useMemo(() => {
    if (activeSignals.length === 0) return []
    const uniqueCities = new Set<string>()
    activeSignals.forEach(s => {
      if (s.city) uniqueCities.add(s.city)
    })
    return Array.from(uniqueCities).sort()
  }, [activeSignals])

  // Filter signals
  const filteredSignals = useMemo(() => {
    if (activeSignals.length === 0) return []
    return activeSignals.filter(signal => {
      if (signalFilters.search) {
        const search = signalFilters.search.toLowerCase()
        if (!signal.market_title.toLowerCase().includes(search) &&
            !signal.market_ticker.toLowerCase().includes(search)) {
          return false
        }
      }
      if (signalFilters.platform !== 'all' &&
          signal.platform.toLowerCase() !== signalFilters.platform) {
        return false
      }
      if (signalFilters.category !== 'all' &&
          (signal.category || 'other') !== signalFilters.category) {
        return false
      }
      if (signalFilters.city && signal.city !== signalFilters.city) {
        return false
      }
      return true
    })
  }, [activeSignals, signalFilters])

  // Filter trades
  const filteredTrades = useMemo(() => {
    if (recentTrades.length === 0) return []
    return recentTrades.filter(trade => {
      if (tradeFilters.search) {
        const search = tradeFilters.search.toLowerCase()
        if (!trade.market_ticker.toLowerCase().includes(search)) {
          return false
        }
      }
      if (tradeFilters.platform !== 'all' &&
          trade.platform.toLowerCase() !== tradeFilters.platform) {
        return false
      }
      if (tradeFilters.status !== 'all' && trade.result !== tradeFilters.status) {
        return false
      }
      return true
    })
  }, [recentTrades, tradeFilters])

  const cityHighlights = useMemo(() => {
    if (!citiesData.length) return []
    return [...citiesData]
      .sort((a, b) => b.confidence - a.confidence)
      .slice(0, 3)
  }, [citiesData])

  const highConfidenceCount = useMemo(() => {
    return citiesData.filter(city => city.confidence >= 0.7).length
  }, [citiesData])

  const platformBreakdown = useMemo(() => {
    const counts: Record<string, number> = {}
    activeSignals.forEach(signal => {
      const key = signal.platform.toLowerCase()
      counts[key] = (counts[key] || 0) + 1
    })
    return counts
  }, [activeSignals])

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
            <div className="absolute inset-0 border-2 border-transparent border-t-green-500 rounded-full animate-spin"></div>
          </div>
          <div className="text-sm font-medium text-neutral-300 uppercase tracking-wider mb-1">Loading</div>
          <div className="text-xs text-neutral-600">Connecting to trading systems...</div>
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
                  Prediction Market Trading Bot
                </h1>
                <span className={`px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${
                  stats.is_running
                    ? 'bg-green-500/10 text-green-500 border border-green-500/20'
                    : 'bg-neutral-800 text-neutral-500 border border-neutral-700'
                }`}>
                  {stats.is_running ? 'Live' : 'Idle'}
                </span>
                <span className="px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  Simulation
                </span>
              </div>
              <p className="text-neutral-600 text-xs">
                AI-enhanced trading across Weather, Crypto, Politics, Economics | Kalshi + Polymarket
                {stats.last_run && (
                  <span className="ml-2">| Last scan: {new Date(stats.last_run).toLocaleTimeString()}</span>
                )}
                {aiStats && (
                  <span className="ml-2">
                    | AI: {aiStats.today.total_calls} calls, ${aiStats.today.total_cost_usd.toFixed(4)} today
                    {aiStats.today.by_provider && Object.keys(aiStats.today.by_provider).length > 0 && (
                      <span className="text-neutral-500">
                        {' '}({Object.entries(aiStats.today.by_provider).map(([p, d]: [string, any]) => `${p}: ${d.calls}`).join(', ')})
                      </span>
                    )}
                  </span>
                )}
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => scanMutation.mutate()}
                disabled={scanMutation.isPending}
                className="px-4 py-2 bg-neutral-800 border border-neutral-700 hover:border-neutral-600 text-neutral-300 text-xs uppercase tracking-wider transition-colors flex items-center gap-2 disabled:opacity-50"
              >
                {scanMutation.isPending && (
                  <div className="w-3 h-3 border border-neutral-600 border-t-green-500 rounded-full animate-spin" />
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

        {/* Primary analytic layout */}
        <div className="grid gap-3 xl:grid-cols-[3fr,2fr] mb-3">
          {/* Equity Chart */}
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

          {/* System Log */}
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

        {/* Coverage summaries */}
        <div className="grid gap-3 md:grid-cols-2 mb-3">
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden">
            <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">3D Globe (Summary)</span>
              <span className="text-[10px] text-neutral-600">{citiesData.length} cities</span>
            </div>
            <div className="p-4 space-y-4">
              <div className="flex items-end justify-between">
                <div>
                  <div className="text-xs uppercase text-neutral-500 mb-1 tracking-wider">Active Cities</div>
                  <div className="text-3xl font-semibold text-neutral-100">{citiesData.length}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs uppercase text-neutral-500 mb-1 tracking-wider">High Confidence ≥70%</div>
                  <div className="text-xl font-semibold text-green-400">{highConfidenceCount}</div>
                </div>
              </div>
              <div className="space-y-2">
                {cityHighlights.length > 0 ? cityHighlights.map(city => (
                  <div key={city.city} className="flex items-center justify-between text-sm text-neutral-300 border border-neutral-800/80 px-3 py-2">
                    <span className="uppercase tracking-wide text-[11px]">{city.city}</span>
                    <span className="text-neutral-500 tabular-nums">
                      {city.high_temp.toFixed(0)}°F · {(city.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                )) : (
                  <div className="text-neutral-600 text-sm">Waiting for weather data...</div>
                )}
              </div>
            </div>
          </div>
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden">
            <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">Market Coverage</span>
              <span className="text-[10px] text-neutral-600">{activeSignals.length} signals</span>
            </div>
            <div className="p-4 space-y-4">
              <div className="flex items-end justify-between">
                <div>
                  <div className="text-xs uppercase text-neutral-500 mb-1 tracking-wider">Active Signals</div>
                  <div className="text-3xl font-semibold text-neutral-100">{activeSignals.length}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs uppercase text-neutral-500 mb-1 tracking-wider">Actionable</div>
                  <div className="text-xl font-semibold text-amber-400">{filteredSignals.length}</div>
                </div>
              </div>
              <div className="space-y-2">
                {Object.keys(platformBreakdown).length > 0 ? (
                  Object.entries(platformBreakdown).map(([platform, count]) => (
                    <div key={platform} className="flex items-center justify-between text-sm border border-neutral-800/80 px-3 py-2">
                      <span className="uppercase tracking-wide text-[11px]">{platform}</span>
                      <span className="text-neutral-500 tabular-nums">{count} markets</span>
                    </div>
                  ))
                ) : (
                  <div className="text-neutral-600 text-sm">No signals loaded yet</div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Signals & Trades */}
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden flex flex-col">
            <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">Active Signals</span>
              <span className="px-2 py-0.5 text-[10px] font-medium bg-amber-500/10 text-amber-500 border border-amber-500/20">
                {filteredSignals.length} / {activeSignals.length}
              </span>
            </div>
            <FilterBar
              filters={signalFilters}
              onFilterChange={setSignalFilters}
              cities={cities}
            />
            <div className="p-3 max-h-[360px] overflow-y-auto flex-1">
              <SignalsTable
                signals={filteredSignals}
                onSimulateTrade={(ticker) => tradeMutation.mutate(ticker)}
                isSimulating={tradeMutation.isPending}
              />
            </div>
          </div>
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden flex flex-col">
            <div className="px-3 py-2 border-b border-neutral-800 flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">Trade History</span>
              <span className="text-[10px] text-neutral-600 tabular-nums">
                {filteredTrades.length} / {data?.recent_trades?.length ?? 0}
              </span>
            </div>
            <FilterBar
              filters={tradeFilters}
              onFilterChange={setTradeFilters}
              cities={[]}
              showStatus
            />
            <div className="p-3 max-h-[360px] overflow-y-auto flex-1">
              <TradesTable trades={filteredTrades} />
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="mt-6 text-center text-neutral-700 text-xs">
          <p>Data: NWS, Open-Meteo, CoinGecko, FRED | AI: Claude + Groq | Platforms: Kalshi + Polymarket | Simulation mode</p>
        </footer>
      </div>
    </div>
  )
}

export default App
