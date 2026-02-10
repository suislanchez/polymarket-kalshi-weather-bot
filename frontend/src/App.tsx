import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDashboard, runScan, simulateTrade } from './api'
import { Map } from './components/Map'
import { Globe } from './components/Globe'
import { StatsCards } from './components/StatsCards'
import { SignalsTable } from './components/SignalsTable'
import { TradesTable } from './components/TradesTable'
import { EquityChart } from './components/EquityChart'
import { Terminal } from './components/Terminal'

function App() {
  const queryClient = useQueryClient()

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
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
            Unable to connect to backend. Ensure server is running on port 8000.
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
                  Weather Prediction Markets
                </h1>
                <span className={`px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${
                  data.stats.is_running
                    ? 'bg-green-500/10 text-green-500 border border-green-500/20'
                    : 'bg-neutral-800 text-neutral-500 border border-neutral-700'
                }`}>
                  {data.stats.is_running ? 'Live' : 'Idle'}
                </span>
              </div>
              <p className="text-neutral-600 text-xs">
                Ensemble weather forecasting for prediction market edge
                {data.stats.last_run && (
                  <span className="ml-2">| Last scan: {new Date(data.stats.last_run).toLocaleTimeString()}</span>
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
        <section className="mb-4">
          <StatsCards stats={data.stats} />
        </section>

        {/* Main Grid - Globe, Map, Terminal */}
        <div className="grid lg:grid-cols-3 gap-2 mb-4">
          {/* Globe */}
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden">
            <div className="px-4 py-3 border-b border-neutral-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">3D Globe</span>
                <div className="live-dot" />
              </div>
              <span className="text-[10px] text-neutral-600 tabular-nums">{data.cities.length} markets</span>
            </div>
            <Globe cities={data.cities} />
          </div>

          {/* Map */}
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden">
            <div className="px-4 py-3 border-b border-neutral-800 flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">Market Coverage</span>
              <span className="text-[10px] text-neutral-600">US Markets</span>
            </div>
            <Map cities={data.cities} />
          </div>

          {/* Terminal */}
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden">
            <Terminal
              isRunning={data.stats.is_running}
              lastRun={data.stats.last_run}
              stats={{ total_trades: data.stats.total_trades, total_pnl: data.stats.total_pnl }}
            />
          </div>
        </div>

        {/* Charts Row */}
        <div className="grid lg:grid-cols-2 gap-2 mb-4">
          {/* Equity Chart */}
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden">
            <div className="px-4 py-3 border-b border-neutral-800 flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">Portfolio Performance</span>
              <span className={`text-xs tabular-nums ${data.stats.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                {data.stats.total_pnl >= 0 ? '+' : ''}${data.stats.total_pnl.toFixed(0)}
              </span>
            </div>
            <div className="p-4">
              <EquityChart
                data={data.equity_curve}
                initialBankroll={data.stats.bankroll - data.stats.total_pnl}
              />
            </div>
          </div>

          {/* Signals */}
          <div className="bg-neutral-900 border border-neutral-800 overflow-hidden">
            <div className="px-4 py-3 border-b border-neutral-800 flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">Active Signals</span>
              <span className="px-2 py-0.5 text-[10px] font-medium bg-amber-500/10 text-amber-500 border border-amber-500/20">
                {data.active_signals.length} signals
              </span>
            </div>
            <div className="p-4 max-h-[340px] overflow-y-auto">
              <SignalsTable
                signals={data.active_signals}
                onSimulateTrade={(ticker) => tradeMutation.mutate(ticker)}
                isSimulating={tradeMutation.isPending}
              />
            </div>
          </div>
        </div>

        {/* Trades Table */}
        <div className="bg-neutral-900 border border-neutral-800 overflow-hidden">
          <div className="px-4 py-3 border-b border-neutral-800 flex items-center justify-between">
            <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">Trade History</span>
            <span className="text-[10px] text-neutral-600 tabular-nums">{data.recent_trades.length} trades</span>
          </div>
          <div className="p-4">
            <TradesTable trades={data.recent_trades} />
          </div>
        </div>

        {/* Footer */}
        <footer className="mt-6 text-center text-neutral-700 text-xs">
          <p>Data: NWS API, Open-Meteo Ensemble | Simulation mode - no real trades</p>
        </footer>
      </div>
    </div>
  )
}

export default App
