import { motion } from 'framer-motion'
import { Play, Pause, RefreshCw, TrendingUp, TrendingDown, DollarSign, Target, BarChart3 } from 'lucide-react'
import { EquityChart } from './EquityChart'
import type { BotStats, EquityPoint, WeatherSignal, Signal } from '../types'

interface Props {
  stats: BotStats
  equityCurve: EquityPoint[]
  weatherSignals: WeatherSignal[]
  btcSignals: Signal[]
  pendingTradeCount: number
  onStart: () => void
  onStop: () => void
  onScan: () => void
  isScanning: boolean
}

function StatCard({ label, value, subValue, icon: Icon, color }: {
  label: string
  value: string
  subValue?: string
  icon: typeof DollarSign
  color: string
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-[#0a0a0a] border border-neutral-800 p-4 rounded-lg"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-neutral-500 uppercase tracking-wider font-medium">{label}</span>
        <Icon className={`w-4 h-4 ${color}`} />
      </div>
      <div className={`text-xl font-semibold tabular-nums font-mono ${color}`}>{value}</div>
      {subValue && <div className="text-[10px] text-neutral-600 mt-1 tabular-nums">{subValue}</div>}
    </motion.div>
  )
}

export function OverviewTab({ stats, equityCurve, weatherSignals, btcSignals, pendingTradeCount, onStart, onStop, onScan, isScanning }: Props) {
  const pnlPercent = stats.bankroll > 0 ? ((stats.total_pnl / (stats.bankroll - stats.total_pnl)) * 100) : 0
  const wxActionable = weatherSignals.filter(s => s.actionable).length
  const btcActionable = btcSignals.filter(s => s.actionable).length

  return (
    <div className="p-4 space-y-4 overflow-y-auto max-h-[calc(100vh-120px)]">
      {/* Bot Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium ${
            stats.is_running
              ? 'bg-green-500/10 text-green-400 border border-green-500/20'
              : 'bg-neutral-800 text-neutral-400 border border-neutral-700'
          }`}>
            <div className={`w-2 h-2 rounded-full ${stats.is_running ? 'bg-green-500 animate-pulse' : 'bg-neutral-600'}`} />
            {stats.is_running ? 'Running' : 'Paused'}
          </div>
          <span className="text-[10px] text-amber-500/80 font-medium uppercase tracking-wider">Simulation</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onScan}
            disabled={isScanning}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs rounded hover:bg-neutral-800 disabled:opacity-50 transition-colors"
          >
            <RefreshCw className={`w-3 h-3 ${isScanning ? 'animate-spin' : ''}`} />
            Scan
          </button>
          {stats.is_running ? (
            <button onClick={onStop} className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/10 border border-red-500/20 text-red-400 text-xs rounded hover:bg-red-500/20 transition-colors">
              <Pause className="w-3 h-3" /> Pause
            </button>
          ) : (
            <button onClick={onStart} className="flex items-center gap-1.5 px-3 py-1.5 bg-green-500/10 border border-green-500/20 text-green-400 text-xs rounded hover:bg-green-500/20 transition-colors">
              <Play className="w-3 h-3" /> Start
            </button>
          )}
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Bankroll"
          value={`$${stats.bankroll.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          icon={DollarSign}
          color="text-white"
        />
        <StatCard
          label="P&L"
          value={`${stats.total_pnl >= 0 ? '+' : ''}$${stats.total_pnl.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          subValue={`${pnlPercent >= 0 ? '+' : ''}${pnlPercent.toFixed(1)}%`}
          icon={stats.total_pnl >= 0 ? TrendingUp : TrendingDown}
          color={stats.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}
        />
        <StatCard
          label="Win Rate"
          value={`${(stats.win_rate * 100).toFixed(0)}%`}
          subValue={`${stats.winning_trades}W / ${stats.total_trades - stats.winning_trades}L`}
          icon={Target}
          color={stats.win_rate >= 0.55 ? 'text-green-400' : stats.win_rate >= 0.45 ? 'text-amber-400' : 'text-red-400'}
        />
        <StatCard
          label="Trades"
          value={`${stats.total_trades}`}
          subValue={`${pendingTradeCount} pending`}
          icon={BarChart3}
          color="text-cyan-400"
        />
      </div>

      {/* Activity Summary */}
      <div className="bg-[#0a0a0a] border border-neutral-800 rounded-lg p-4">
        <h3 className="text-xs text-neutral-500 uppercase tracking-wider font-medium mb-3">Active Signals</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-neutral-400">Weather</span>
            <span className={`text-sm font-mono font-semibold ${wxActionable > 0 ? 'text-green-400' : 'text-neutral-600'}`}>
              {wxActionable} actionable
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-neutral-400">BTC</span>
            <span className={`text-sm font-mono font-semibold ${btcActionable > 0 ? 'text-green-400' : 'text-neutral-600'}`}>
              {btcActionable} actionable
            </span>
          </div>
        </div>
      </div>

      {/* Equity Curve */}
      <div className="bg-[#0a0a0a] border border-neutral-800 rounded-lg p-4">
        <h3 className="text-xs text-neutral-500 uppercase tracking-wider font-medium mb-3">Equity Curve</h3>
        <div className="h-48 md:h-64">
          {equityCurve.length > 0 ? (
            <EquityChart data={equityCurve} initialBankroll={stats.bankroll - stats.total_pnl} />
          ) : (
            <div className="flex items-center justify-center h-full text-neutral-600 text-xs">
              No settled trades yet
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
