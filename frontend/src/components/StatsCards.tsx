import type { BotStats } from '../types'

interface Props {
  stats: BotStats
}

export function StatsCards({ stats }: Props) {
  const winRate = stats.total_trades > 0 ? (stats.winning_trades / stats.total_trades * 100) : 0
  const returnPercent = stats.bankroll - stats.total_pnl > 0
    ? ((stats.total_pnl / (stats.bankroll - stats.total_pnl)) * 100)
    : 0

  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-neutral-600 uppercase">Bank</span>
        <span className="text-xs font-semibold tabular-nums text-neutral-100">
          ${stats.bankroll >= 1000 ? (stats.bankroll / 1000).toFixed(1) + 'K' : stats.bankroll.toFixed(0)}
        </span>
      </div>

      <div className="w-px h-3 bg-neutral-800" />

      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-neutral-600 uppercase">P&L</span>
        <span className={`text-xs font-semibold tabular-nums ${stats.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
          {stats.total_pnl >= 0 ? '+' : ''}${Math.abs(stats.total_pnl).toFixed(0)}
        </span>
        <span className={`text-[10px] tabular-nums ${returnPercent >= 0 ? 'text-green-500/60' : 'text-red-500/60'}`}>
          {returnPercent >= 0 ? '+' : ''}{returnPercent.toFixed(1)}%
        </span>
      </div>

      <div className="w-px h-3 bg-neutral-800" />

      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-neutral-600 uppercase">Win</span>
        <span className={`text-xs font-semibold tabular-nums ${winRate >= 55 ? 'text-green-500' : winRate >= 45 ? 'text-yellow-500' : 'text-red-500'}`}>
          {winRate.toFixed(0)}%
        </span>
        <span className="text-[10px] text-neutral-600 tabular-nums">
          {stats.winning_trades}/{stats.total_trades}
        </span>
      </div>

      <div className="w-px h-3 bg-neutral-800" />

      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-neutral-600 uppercase">Trades</span>
        <span className="text-xs font-semibold tabular-nums text-neutral-100">{stats.total_trades}</span>
        {stats.is_running && <div className="live-dot" />}
      </div>
    </div>
  )
}
