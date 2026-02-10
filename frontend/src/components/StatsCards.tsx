import type { BotStats } from '../types'

interface Props {
  stats: BotStats
}

function formatNumber(n: number): string {
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(2) + 'K'
  return n.toFixed(0)
}

function ProgressBar({ value, max = 100, color = 'neutral' }: { value: number; max?: number; color?: string }) {
  const percent = Math.min((value / max) * 100, 100)
  const colors: Record<string, string> = {
    neutral: 'bg-neutral-500',
    red: 'bg-red-500',
    green: 'bg-green-500',
    yellow: 'bg-yellow-500',
  }
  return (
    <div className="w-full h-1 bg-neutral-800 overflow-hidden mt-2">
      <div
        className={`h-full ${colors[color]} transition-all duration-300`}
        style={{ width: `${percent}%` }}
      />
    </div>
  )
}

export function StatsCards({ stats }: Props) {
  const winRate = stats.total_trades > 0 ? stats.winning_trades / stats.total_trades : 0
  const winRatePercent = winRate * 100
  const returnPercent = stats.bankroll - stats.total_pnl > 0
    ? ((stats.total_pnl / (stats.bankroll - stats.total_pnl)) * 100)
    : 0

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
      <div className="bg-neutral-900 border border-neutral-800 p-4">
        <div className="text-neutral-500 text-xs uppercase tracking-wider mb-2">Virtual Bankroll</div>
        <div className="text-xl font-semibold tabular-nums text-neutral-100">
          ${formatNumber(stats.bankroll)}
        </div>
        <div className="text-neutral-600 text-xs mt-1">Simulation mode</div>
      </div>

      <div className="bg-neutral-900 border border-neutral-800 p-4">
        <div className="text-neutral-500 text-xs uppercase tracking-wider mb-2">Total P&L</div>
        <div className={`text-xl font-semibold tabular-nums ${stats.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
          {stats.total_pnl >= 0 ? '+' : ''}${formatNumber(Math.abs(stats.total_pnl))}
        </div>
        <div className="text-neutral-600 text-xs mt-1">
          ROI: {returnPercent >= 0 ? '+' : ''}{returnPercent.toFixed(1)}%
        </div>
        <ProgressBar value={Math.abs(returnPercent)} max={50} color={stats.total_pnl >= 0 ? 'green' : 'red'} />
      </div>

      <div className="bg-neutral-900 border border-neutral-800 p-4">
        <div className="text-neutral-500 text-xs uppercase tracking-wider mb-2">Win Rate</div>
        <div className={`text-xl font-semibold tabular-nums ${winRatePercent >= 55 ? 'text-green-500' : winRatePercent >= 45 ? 'text-yellow-500' : 'text-red-500'}`}>
          {winRatePercent.toFixed(1)}%
        </div>
        <div className="text-neutral-600 text-xs mt-1">
          {stats.winning_trades}/{stats.total_trades} trades won
        </div>
        <ProgressBar
          value={winRatePercent}
          color={winRatePercent >= 55 ? 'green' : winRatePercent >= 45 ? 'yellow' : 'red'}
        />
      </div>

      <div className="bg-neutral-900 border border-neutral-800 p-4">
        <div className="text-neutral-500 text-xs uppercase tracking-wider mb-2">Total Trades</div>
        <div className={`text-xl font-semibold tabular-nums ${stats.is_running ? 'text-green-500' : 'text-neutral-100'}`}>
          {stats.total_trades}
        </div>
        <div className="flex items-center gap-2 mt-1">
          {stats.is_running && <div className="live-dot" />}
          <span className="text-neutral-600 text-xs">{stats.is_running ? 'Active' : 'Idle'}</span>
        </div>
      </div>
    </div>
  )
}
