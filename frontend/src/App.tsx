import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDashboard, runScan, simulateTrade, startBot, stopBot } from './api'
import { TabNav, type TabId } from './components/TabNav'
import { OverviewTab } from './components/OverviewTab'
import { WeatherTab } from './components/WeatherTab'
import { BtcTab } from './components/BtcTab'
import { TradesTab } from './components/TradesTab'
import { SystemTab } from './components/SystemTab'
import { Bell, User } from 'lucide-react'

function App() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabId>('overview')
  const [weatherEnabled, setWeatherEnabled] = useState(true)
  const [btcEnabled, setBtcEnabled] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date())

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
    refetchInterval: 10000,
    retry: 3,
    retryDelay: 2000,
  })

  useEffect(() => {
    if (data) setLastUpdated(new Date())
  }, [data])

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
      <div className="h-screen bg-[#121216] flex items-center justify-center">
        <div className="text-center">
          <div className="relative w-10 h-10 mx-auto mb-4">
            <div className="absolute inset-0 border-2 border-neutral-800 rounded-full" />
            <div className="absolute inset-0 border-2 border-transparent border-t-[#7B61FF] rounded-full animate-spin" />
          </div>
          <div className="text-[11px] text-neutral-500 font-medium">Loading Dashboard...</div>
        </div>
      </div>
    )
  }

  // Error state
  if (error && !data) {
    return (
      <div className="h-screen bg-[#121216] flex items-center justify-center">
        <div className="text-center px-6">
          <div className="text-red-500 text-sm font-semibold mb-2">Connection Error</div>
          <div className="text-neutral-500 text-xs mb-4 max-w-xs mx-auto">{String(error)}</div>
          <button
            onClick={() => refetch()}
            className="px-5 py-2.5 bg-[#7B61FF] text-white text-xs font-semibold rounded-full hover:bg-[#6B51EF] transition-colors"
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
    <div className="h-screen bg-[#121216] text-white flex flex-col overflow-hidden">
      {/* Status Bar */}
      <div className="yf-status-bar">
        <div className={`yf-status-dot ${stats.is_running ? 'running' : ''}`} />
        <span>
          {stats.is_running ? 'BOT RUNNING' : 'BOT IDLE'}
          {stats.is_running && ' \u2022 Auto-refreshing every 10s'}
        </span>
      </div>

      {/* Header */}
      <header className="yf-header">
        <div className="yf-search-bar">
          <svg className="w-4 h-4 text-neutral-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <span className="text-neutral-500 text-sm">Search signals or markets</span>
        </div>
        <div className="flex items-center gap-3">
          <button className="yf-icon-btn relative">
            <Bell className="w-5 h-5" />
            {(wxActionable + btcActionable) > 0 && (
              <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-red-500 rounded-full border-2 border-[#121216]" />
            )}
          </button>
          <button className="yf-icon-btn">
            <User className="w-5 h-5" />
          </button>
        </div>
      </header>

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
            lastUpdated={lastUpdated}
            btcPrice={data?.btc_price ?? null}
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

      {/* Bottom Tab Navigation */}
      <TabNav
        activeTab={activeTab}
        onTabChange={setActiveTab}
        weatherCount={wxActionable}
        btcCount={btcActionable}
        pendingTrades={pendingTrades}
      />
    </div>
  )
}

export default App
