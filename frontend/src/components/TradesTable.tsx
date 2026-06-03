import { formatDistanceToNow } from 'date-fns'
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { Trade } from '../types'
import { platformStyles } from '../utils'

interface Props {
  trades: Trade[]
}

type SortKey = 'timestamp' | 'size' | 'pnl' | 'result'
type SortDir = 'asc' | 'desc'

export function TradesTable({ trades }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('timestamp')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sortedTrades = useMemo(() => {
    return [...trades].sort((a, b) => {
      let aVal: number | string, bVal: number | string
      switch (sortKey) {
        case 'timestamp':
          aVal = new Date(a.timestamp).getTime()
          bVal = new Date(b.timestamp).getTime()
          break
        case 'size':
          aVal = a.size; bVal = b.size; break
        case 'pnl':
          aVal = a.pnl ?? 0; bVal = b.pnl ?? 0; break
        case 'result':
          aVal = a.result; bVal = b.result; break
        default: return 0
      }
      if (typeof aVal === 'string') {
        return sortDir === 'asc'
          ? aVal.localeCompare(bVal as string)
          : (bVal as string).localeCompare(aVal)
      }
      return sortDir === 'asc' ? aVal - (bVal as number) : (bVal as number) - aVal
    })
  }, [trades, sortKey, sortDir])

  const SortIcon = ({ column }: { column: SortKey }) => {
    if (sortKey !== column) return <ArrowUpDown className="w-2.5 h-2.5 text-neutral-600" />
    return sortDir === 'asc'
      ? <ArrowUp className="w-2.5 h-2.5 text-amber-500" />
      : <ArrowDown className="w-2.5 h-2.5 text-amber-500" />
  }

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-neutral-600">
        <p className="text-xs">No trades yet</p>
        <p className="text-[10px] mt-0.5">Trades will appear here</p>
      </div>
    )
  }

  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#0a0a0a] z-10">
        <tr className="text-neutral-600 text-left text-[10px] border-b border-neutral-800">
          <th className="py-1.5 px-1.5 font-medium w-5"></th>
          <th
            className="py-1.5 px-1.5 font-medium cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('result')}
          >
            <div className="flex items-center gap-0.5">
              St <SortIcon column="result" />
            </div>
          </th>
          <th className="py-1.5 px-1.5 font-medium">Market</th>
          <th className="py-1.5 px-1.5 font-medium text-center">Dir</th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('size')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Size <SortIcon column="size" />
            </div>
          </th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('pnl')}
          >
            <div className="flex items-center justify-end gap-0.5">
              P&L <SortIcon column="pnl" />
            </div>
          </th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('timestamp')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Time <SortIcon column="timestamp" />
            </div>
          </th>
        </tr>
      </thead>
      <tbody>
        <AnimatePresence>
          {sortedTrades.map((trade, i) => {
            const isPending = trade.result === 'pending'
            const isWin = trade.result === 'win'
            const isUp = trade.direction === 'up'
            const style = platformStyles[trade.platform?.toLowerCase()]

            return (
              <motion.tr
                key={trade.id}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.02 }}
                className="border-b border-neutral-800/50 hover:bg-neutral-800/30 text-[11px]"
              >
                <td className="py-1 px-1.5">
                  {style && (
                    <span className={`platform-badge ${style.badge}`}>
                      {style.icon}
                    </span>
                  )}
                </td>
                <td className="py-1 px-1.5">
                  <span className={`text-[9px] font-medium uppercase ${
                    isPending ? 'text-amber-500' : isWin ? 'text-green-500' : 'text-red-500'
                  }`}>
                    {isPending ? 'PND' : isWin ? 'WIN' : 'LOSS'}
                  </span>
                </td>
                <td className="py-1 px-1.5">
                  <span className="text-neutral-400 truncate block max-w-[100px]" title={trade.event_slug || trade.market_ticker}>
                    {trade.event_slug || trade.market_ticker}
                  </span>
                </td>
                <td className="py-1 px-1.5 text-center">
                  <span className={`text-[10px] font-semibold uppercase ${isUp ? 'text-green-500' : 'text-red-500'}`}>
                    {trade.direction}
                  </span>
                </td>
                <td className="py-1 px-1.5 text-right text-neutral-300 tabular-nums">
                  ${trade.size.toFixed(0)}
                </td>
                <td className="py-1 px-1.5 text-right">
                  {trade.pnl !== null ? (
                    <span className={`font-semibold tabular-nums ${
                      trade.pnl >= 0 ? 'text-green-500' : 'text-red-500'
                    }`}>
                      {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(0)}
                    </span>
                  ) : (
                    <span className="text-neutral-600">-</span>
                  )}
                </td>
                <td className="py-1 px-1.5 text-right text-[10px] text-neutral-600 tabular-nums">
                  {formatDistanceToNow(new Date(trade.timestamp), { addSuffix: false })}
                </td>
              </motion.tr>
            )
          })}
        </AnimatePresence>
      </tbody>
    </table>
  )
}
