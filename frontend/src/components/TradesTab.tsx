import { useState, useMemo } from 'react'
import { formatDistanceToNow } from 'date-fns'
import type { Trade } from '../types'

interface Props {
  trades: Trade[]
}

type FilterType = 'all' | 'pending' | 'win' | 'loss'

function TradeRow({ trade }: { trade: Trade }) {
  const isPending = !trade.settled
  const isWin = trade.result === 'win'
  const isLoss = trade.result === 'loss'
  const directionUp = trade.direction === 'up' || trade.direction === 'yes' || trade.direction === 'above'

  const statusLabel = isPending ? 'Pending' : isWin ? 'Win' : isLoss ? 'Loss' : trade.result || 'Push'
  const statusColor = isPending ? 'text-amber-400' : isWin ? 'text-[#00C805]' : isLoss ? 'text-[#FF3B30]' : 'text-neutral-400'

  let timeAgo = ''
  try {
    timeAgo = formatDistanceToNow(new Date(trade.timestamp), { addSuffix: true })
  } catch {
    timeAgo = ''
  }

  return (
    <div className="yf-trending-row">
      <div className="flex-1 min-w-0">
        <div className="text-[14px] font-bold text-white truncate">
          {trade.market_ticker}
        </div>
        <div className="text-[12px] text-neutral-500 flex items-center gap-2">
          <span className={directionUp ? 'text-[#00C805]' : 'text-[#FF3B30]'}>{trade.direction}</span>
          <span>\u00B7</span>
          <span>{(trade.entry_price * 100).toFixed(0)}c</span>
          <span>\u00B7</span>
          <span>${trade.size.toFixed(0)}</span>
          <span>\u00B7</span>
          <span>{timeAgo}</span>
        </div>
      </div>
      <div className="text-right shrink-0">
        {trade.pnl !== null ? (
          <div className={`text-[15px] font-semibold tabular-nums ${trade.pnl >= 0 ? 'text-[#00C805]' : 'text-[#FF3B30]'}`}>
            {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}
          </div>
        ) : (
          <div className="text-[13px] font-semibold text-amber-400">Pending</div>
        )}
        <div className={`text-[11px] font-medium ${statusColor}`}>{statusLabel}</div>
      </div>
    </div>
  )
}

export function TradesTab({ trades }: Props) {
  const [filter, setFilter] = useState<FilterType>('all')

  const filtered = useMemo(() => {
    switch (filter) {
      case 'pending': return trades.filter(t => !t.settled)
      case 'win': return trades.filter(t => t.result === 'win')
      case 'loss': return trades.filter(t => t.result === 'loss')
      default: return trades
    }
  }, [trades, filter])

  const pending = trades.filter(t => !t.settled).length
  const wins = trades.filter(t => t.result === 'win').length
  const losses = trades.filter(t => t.result === 'loss').length
  const totalPnl = trades.reduce((sum, t) => sum + (t.pnl || 0), 0)

  const filters: { id: FilterType; label: string; count: number }[] = [
    { id: 'all', label: 'All', count: trades.length },
    { id: 'pending', label: 'Pending', count: pending },
    { id: 'win', label: 'Wins', count: wins },
    { id: 'loss', label: 'Losses', count: losses },
  ]

  return (
    <div className="overflow-y-auto h-full pb-4">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3">
        <div>
          <h2 className="text-[18px] font-bold text-white">Trade History</h2>
          <p className="text-[12px] text-neutral-500">{trades.length} trades total</p>
        </div>
        <div className={`text-[18px] font-bold tabular-nums ${totalPnl >= 0 ? 'text-[#00C805]' : 'text-[#FF3B30]'}`}>
          {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 px-4 pb-3 overflow-x-auto">
        {filters.map(f => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={`yf-filter-btn ${filter === f.id ? 'active' : ''}`}
          >
            {f.label} ({f.count})
          </button>
        ))}
      </div>

      {/* Trade List */}
      <div className="mx-4">
        <div className="yf-card">
          {filtered.length > 0 ? (
            filtered.map(t => <TradeRow key={t.id} trade={t} />)
          ) : (
            <div className="px-4 py-8 text-center text-neutral-500 text-sm">
              No trades to display
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
