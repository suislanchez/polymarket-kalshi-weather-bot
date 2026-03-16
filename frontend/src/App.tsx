import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDashboard, runScan, simulateTrade, startBot, stopBot } from './api'
import { TabNav, type TabId } from './components/TabNav'
import { OverviewTab } from './components/OverviewTab'
import { WeatherTab } from './components/WeatherTab'
import { BtcTab } from './components/BtcTab'
import { TradesTab } from './components/TradesTab'
import { SystemTab } from './components/SystemTab'

function App() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabId>('overview')
  const [weatherEnabled, setWeatherEnabled] = useState(true)
  const [btcEnabled, setBtcEnabled] = useState(true)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
    refetchInterval: 10000,
    retry: 3,
    retryDelay: 2000,
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

  // Loading state
  if (isLoading && !data) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="relative w-10 h-10 mx-auto mb-4">
            <div className="absolute inset-0 border-2 border-neutral-800 rounded-full" />
            <div className="absolute inset-0 border-2 border-transparent border-t-green-500 rounded-full animate-spin" />
          </div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">Connecting...</div>
        </div>
      </div>
    )
  }

  // Error state (only if we have no data at all)
  if (error && !data) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center px-6">
          <div className="text-red-500 text-sm uppercase mb-2 tracking-wider font-medium">Connection Error</div>
          <div className="text-neutral-600 text-xs mb-4 max-w-xs mx-auto">{String(error)}</div>
          <button
            onClick={() => refetch()}
            className="px-4 py-2 bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs uppercase tracking-wider rounded hover:bg-neutral-800 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  const stats = data?.stats ?? {
    is_running: false,
    last_run: null,
    total_trades: 0,
    total_pnl: 0,
    bankroll: 10000,
    winning_trades: 0,
    win_rate: 0
  }

  const weatherSignals = data?.weather_signals ?? []
  const btcSignals = data?.active_signals ?? []
  const trades = data?.recent_trades ?? []
  const equityCurve = data?.equity_curve ?? []
  const forecasts = data?.weather_forecasts ?? []
  const calibration = data?.calibration ?? null
  const pendingTrades = trades.filter(t => !t.settled).length
  const wxActionable = weatherSignals.filter(s => s.actionable).length
  const btcActionable = btcSignals.filter(s => s.actionable).length

  return (
    <div className="h-screen bg-black text-neutral-200 flex flex-col overflow-hidden">
      {/* Header */}
      <header className="shrink-0 border-b border-neutral-800 px-4 py-3 flex items-center justify-between bg-[#0a0a0a]">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-semibold tracking-wider uppercase">Kalshi Bot</h1>
          <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-medium ${
            stats.is_running
              ? 'bg-green-500/10 text-green-400'
              : 'bg-neutral-800 text-neutral-500'
          }`}>
            <div className={`w-1.5 h-1.5 rounded-full ${stats.is_running ? 'bg-green-500 animate-pulse' : 'bg-neutral-600'}`} />
            {stats.is_running ? 'Live' : 'Idle'}
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right hidden sm:block">
            <div className="text-xs font-mono text-neutral-300 tabular-nums">
              ${stats.bankroll.toLocaleString('en-US', { minimumFractionDigits: 0 })}
            </div>
            <div className={`text-[10px] font-mono tabular-nums ${stats.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(2)}
            </div>
          </div>
        </div>
      </header>

      {/* Tab Navigation */}
      <TabNav
        activeTab={activeTab}
        onTabChange={setActiveTab}
        weatherCount={wxActionable}
        btcCount={btcActionable}
        pendingTrades={pendingTrades}
      />

      {/* Tab Content */}
      <main className="flex-1 min-h-0 overflow-hidden">
        {activeTab === 'overview' && (
          <OverviewTab
            stats={stats}
            equityCurve={equityCurve}
            weatherSignals={weatherSignals}
            btcSignals={btcSignals}
            pendingTradeCount={pendingTrades}
            onStart={() => startMutation.mutate()}
            onStop={() => stopMutation.mutate()}
            onScan={() => scanMutation.mutate()}
            isScanning={scanMutation.isPending}
          />
        )}
        {activeTab === 'weather' && (
          <WeatherTab
            signals={weatherSignals}
            forecasts={forecasts}
            enabled={weatherEnabled}
            onToggle={() => setWeatherEnabled(!weatherEnabled)}
          />
        )}
        {activeTab === 'btc' && (
          <BtcTab
            signals={btcSignals}
            btcPrice={data?.btc_price ?? null}
            microstructure={data?.microstructure ?? null}
            windows={data?.windows ?? []}
            enabled={btcEnabled}
            onToggle={() => setBtcEnabled(!btcEnabled)}
            onSimulateTrade={(ticker) => tradeMutation.mutate(ticker)}
            isSimulating={tradeMutation.isPending}
          />
        )}
        {activeTab === 'trades' && (
          <TradesTab trades={trades} />
        )}
        {activeTab === 'system' && (
          <SystemTab
            calibration={calibration}
            isRunning={stats.is_running}
            simulationMode={true}
          />
        )}
      </main>
    </div>
  )
}

export default App
