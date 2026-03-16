import { useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import { ArrowLeftRight, Filter } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import type { Trade } from '../types'

interface Props {
  trades: Trade[]
}

type FilterType = 'all' | 'pending' | 'win' | 'loss'

function TradeCard({ trade }: { trade: Trade }) {
  const isPending = !trade.settled
  const isWin = trade.result === 'win'
  const isLoss = trade.result === 'loss'
  const directionUp = trade.direction === 'up' || trade.direction === 'yes' || trade.direction === 'above'

  const statusColor = isPending ? 'text-amber-400' : isWin ? 'text-green-400' : isLoss ? 'text-red-400' : 'text-neutral-400'
  const statusBg = isPending ? 'bg-amber-500/10 border-amber-500/20' : isWin ? 'bg-green-500/10 border-green-500/20' : isLoss ? 'bg-red-500/10 border-red-500/20' : 'bg-neutral-800 border-neutral-700'
  const statusLabel = isPending ? 'Pending' : isWin ? 'Win' : isLoss ? 'Loss' : trade.result || 'Push'

  let timeAgo = ''
  try {
    timeAgo = formatDistanceToNow(new Date(trade.timestamp), { addSuffix: true })
  } catch {
    timeAgo = ''
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-[#0a0a0a] border border-neutral-800 rounded-lg p-3"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`px-2 py-0.5 text-[9px] font-bold uppercase rounded border ${statusBg} ${statusColor}`}>
            {statusLabel}
          </span>
          <span className={`text-[10px] font-semibold uppercase ${directionUp ? 'text-green-400' : 'text-red-400'}`}>
            {trade.direction}
          </span>
        </div>
        <span className="text-[10px] text-neutral-600">{timeAgo}</span>
      </div>

      <div className="text-xs text-neutral-300 font-mono truncate mb-2">
        {trade.market_ticker}
      </div>

      <div className="flex items-center justify-between text-[11px]">
        <div className="flex items-center gap-4">
          <div>
            <span className="text-neutral-600">Entry </span>
            <span className="text-neutral-300 font-mono">{(trade.entry_price * 100).toFixed(0)}c</span>
          </div>
          <div>
            <span className="text-neutral-600">Size </span>
            <span className="text-neutral-300 font-mono">${trade.size.toFixed(0)}</span>
          </div>
        </div>
        {trade.pnl !== null && (
          <span className={`font-mono font-semibold ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}
          </span>
        )}
      </div>
    </motion.div>
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
    <div className="overflow-y-auto max-h-[calc(100vh-120px)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-800">
        <div className="flex items-center gap-2">
          <ArrowLeftRight className="w-4 h-4 text-neutral-400" />
          <span className="text-sm font-medium">Trade History</span>
        </div>
        <span className={`text-sm font-mono font-semibold ${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
        </span>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 px-4 py-3 overflow-x-auto">
        <Filter className="w-3 h-3 text-neutral-600 shrink-0" />
        {filters.map(f => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={`px-3 py-1 text-[10px] font-medium uppercase rounded-full border whitespace-nowrap transition-colors ${
              filter === f.id
                ? 'bg-white/10 text-white border-neutral-600'
                : 'bg-transparent text-neutral-500 border-neutral-800 hover:text-neutral-300'
            }`}
          >
            {f.label} ({f.count})
          </button>
        ))}
      </div>

      {/* Trade Cards */}
      <div className="px-4 pb-4 space-y-2">
        {filtered.length > 0 ? (
          filtered.map(t => <TradeCard key={t.id} trade={t} />)
        ) : (
          <div className="flex items-center justify-center py-12 text-neutral-600 text-xs">
            No trades to display
          </div>
        )}
      </div>
    </div>
  )
}
