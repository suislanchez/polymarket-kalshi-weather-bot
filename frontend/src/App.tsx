import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { fetchDashboard, runScan, simulateTrade } from './api'
import { Globe } from './components/Globe'
import { StatsCards } from './components/StatsCards'
import { SignalsTable } from './components/SignalsTable'
import { TradesTable } from './components/TradesTable'
import { EquityChart } from './components/EquityChart'
import { RefreshCw, Zap, Activity, CloudSun, TrendingUp, History } from 'lucide-react'

function App() {
  const queryClient = useQueryClient()

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
    refetchInterval: 30000, // Auto-refresh every 30 seconds
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
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.5 }}
          className="relative"
        >
          <div className="w-16 h-16 border-4 border-blue-500/30 rounded-full" />
          <div className="absolute inset-0 w-16 h-16 border-4 border-transparent border-t-blue-500 rounded-full animate-spin" />
        </motion.div>
        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="text-lg text-gray-400"
        >
          Loading dashboard...
        </motion.p>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-6">
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="text-center"
        >
          <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-red-500/20 flex items-center justify-center">
            <Activity className="w-10 h-10 text-red-400" />
          </div>
          <h2 className="text-xl font-bold text-red-400 mb-2">Connection Failed</h2>
          <p className="text-gray-400 mb-6">Make sure the backend is running on port 8000</p>
          <button
            onClick={() => refetch()}
            className="btn-primary"
          >
            Retry Connection
          </button>
        </motion.div>
      </div>
    )
  }

  return (
    <div className="min-h-screen p-4 lg:p-8">
      {/* Header */}
      <motion.header
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-8"
      >
        <div className="flex items-center gap-4">
          <div className="p-3 rounded-xl bg-gradient-to-br from-amber-500/20 to-yellow-500/20 border border-amber-500/30">
            <Zap className="w-8 h-8 text-amber-400" />
          </div>
          <div>
            <h1 className="text-2xl lg:text-3xl font-bold bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
              Prediction Market Bot
            </h1>
            <p className="text-sm text-gray-500 mt-1 flex items-center gap-2">
              <CloudSun className="w-4 h-4" />
              Weather markets • Simulation mode
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-2 px-4 py-2 rounded-full glass-card ${
            data.stats.is_running ? 'border-emerald-500/50' : 'border-gray-700'
          }`}>
            <span className={`pulse-dot ${data.stats.is_running ? 'bg-emerald-400' : 'bg-gray-500'}`} />
            <span className="text-sm font-medium">
              {data.stats.is_running ? 'Live' : 'Idle'}
            </span>
          </div>

          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => scanMutation.mutate()}
            disabled={scanMutation.isPending}
            className="btn-primary flex items-center gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${scanMutation.isPending ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Scan Markets</span>
            <span className="sm:hidden">Scan</span>
          </motion.button>
        </div>
      </motion.header>

      {/* Stats Cards */}
      <StatsCards stats={data.stats} />

      {/* Main Grid - Globe and Equity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
        {/* Globe Map */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="glass-card p-6"
        >
          <div className="flex items-center gap-2 mb-4">
            <CloudSun className="w-5 h-5 text-blue-400" />
            <h2 className="text-lg font-semibold">Global Weather Data</h2>
            <span className="badge badge-info ml-auto">
              {data.cities.length} cities
            </span>
          </div>
          <Globe cities={data.cities} />
        </motion.div>

        {/* Equity Curve */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="glass-card p-6"
        >
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="w-5 h-5 text-emerald-400" />
            <h2 className="text-lg font-semibold">Equity Curve</h2>
            {data.equity_curve.length > 0 && (
              <span className={`badge ml-auto ${
                data.stats.total_pnl >= 0 ? 'badge-success' : 'badge-danger'
              }`}>
                {data.stats.total_pnl >= 0 ? '+' : ''}{data.stats.total_pnl.toFixed(0)} P&L
              </span>
            )}
          </div>
          <EquityChart
            data={data.equity_curve}
            initialBankroll={data.stats.bankroll - data.stats.total_pnl}
          />
        </motion.div>
      </div>

      {/* Signals and Trades */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
        {/* Active Signals */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.4 }}
          className="glass-card p-6"
        >
          <div className="flex items-center gap-2 mb-4">
            <Zap className="w-5 h-5 text-amber-400" />
            <h2 className="text-lg font-semibold">Active Signals</h2>
            <span className="badge badge-warning ml-auto">
              {data.active_signals.length} opportunities
            </span>
          </div>
          <SignalsTable
            signals={data.active_signals}
            onSimulateTrade={(ticker) => tradeMutation.mutate(ticker)}
            isSimulating={tradeMutation.isPending}
          />
        </motion.div>

        {/* Recent Trades */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.5 }}
          className="glass-card p-6"
        >
          <div className="flex items-center gap-2 mb-4">
            <History className="w-5 h-5 text-purple-400" />
            <h2 className="text-lg font-semibold">Recent Trades</h2>
            <span className="badge bg-purple-500/20 text-purple-400 border-purple-500/30 ml-auto">
              {data.recent_trades.length} trades
            </span>
          </div>
          <TradesTable trades={data.recent_trades} />
        </motion.div>
      </div>

      {/* Footer */}
      <motion.footer
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.6 }}
        className="mt-10 pt-6 border-t border-gray-800/50 text-center"
      >
        <p className="text-sm text-gray-500 mb-2">
          Last updated: {data.stats.last_run
            ? new Date(data.stats.last_run).toLocaleString()
            : 'Never'
          }
        </p>
        <p className="text-xs text-gray-600">
          Data sources: NWS API • Open-Meteo Ensemble • Polymarket • Kalshi
        </p>
      </motion.footer>
    </div>
  )
}

export default App
