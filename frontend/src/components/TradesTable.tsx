import { motion, AnimatePresence } from 'framer-motion'
import { CheckCircle2, Clock, XCircle, ArrowUpRight, ArrowDownRight, History } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import type { Trade } from '../types'

interface Props {
  trades: Trade[]
}

export function TradesTable({ trades }: Props) {
  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-gray-400">
        <History className="w-12 h-12 mb-4 opacity-20" />
        <p className="text-lg">No trades yet</p>
        <p className="text-sm mt-1 opacity-60">Simulated trades will appear here</p>
      </div>
    )
  }

  return (
    <div className="space-y-2 max-h-[400px] overflow-y-auto pr-2">
      <AnimatePresence>
        {trades.map((trade, index) => {
          const isPending = trade.result === 'pending'
          const isWin = trade.result === 'win'

          const StatusIcon = isPending ? Clock : isWin ? CheckCircle2 : XCircle
          const statusColor = isPending ? 'text-amber-400' : isWin ? 'text-emerald-400' : 'text-red-400'
          const statusBg = isPending ? 'bg-amber-400/10' : isWin ? 'bg-emerald-400/10' : 'bg-red-400/10'

          return (
            <motion.div
              key={trade.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ delay: index * 0.03 }}
              className="flex items-center gap-4 p-3 rounded-lg bg-gray-800/30 hover:bg-gray-800/50 transition-colors"
            >
              {/* Status Icon */}
              <div className={`p-2 rounded-lg ${statusBg}`}>
                <StatusIcon className={`w-4 h-4 ${statusColor}`} />
              </div>

              {/* Trade Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] uppercase tracking-wider text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
                    {trade.platform}
                  </span>
                  <span className={`flex items-center gap-0.5 text-[10px] uppercase tracking-wider ${
                    trade.direction === 'yes' ? 'text-emerald-400' : 'text-red-400'
                  }`}>
                    {trade.direction === 'yes' ? (
                      <ArrowUpRight className="w-3 h-3" />
                    ) : (
                      <ArrowDownRight className="w-3 h-3" />
                    )}
                    {trade.direction}
                  </span>
                </div>
                <p className="text-sm text-gray-300 truncate">
                  {trade.market_ticker}
                </p>
                <p className="text-xs text-gray-500 mt-0.5">
                  {formatDistanceToNow(new Date(trade.timestamp), { addSuffix: true })}
                </p>
              </div>

              {/* P&L */}
              <div className="text-right">
                <div className={`text-lg font-bold ${
                  trade.pnl === null ? 'text-gray-400' :
                  trade.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                }`}>
                  {trade.pnl !== null ? (
                    `${trade.pnl >= 0 ? '+' : ''}$${trade.pnl.toFixed(2)}`
                  ) : (
                    <span className="text-sm">Pending</span>
                  )}
                </div>
                <div className="text-xs text-gray-500">
                  ${trade.size.toFixed(0)} @ {(trade.entry_price * 100).toFixed(0)}¢
                </div>
              </div>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
