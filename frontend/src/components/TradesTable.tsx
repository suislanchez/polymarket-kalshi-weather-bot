import { formatDistanceToNow } from 'date-fns'
import { ExternalLink, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { useState, useMemo } from 'react'
import type { Trade } from '../types'
import { getMarketUrl, platformStyles } from '../utils'

interface Props {
  trades: Trade[]
}

type SortKey = 'timestamp' | 'size' | 'pnl' | 'platform' | 'result'
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
          aVal = a.size
          bVal = b.size
          break
        case 'pnl':
          aVal = a.pnl ?? 0
          bVal = b.pnl ?? 0
          break
        case 'platform':
          aVal = a.platform
          bVal = b.platform
          break
        case 'result':
          aVal = a.result
          bVal = b.result
          break
        default:
          return 0
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
    if (sortKey !== column) return <ArrowUpDown className="w-3 h-3 text-neutral-600" />
    return sortDir === 'asc'
      ? <ArrowUp className="w-3 h-3 text-green-500" />
      : <ArrowDown className="w-3 h-3 text-green-500" />
  }

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-neutral-600">
        <div className="text-4xl mb-4 opacity-30">---</div>
        <p className="text-sm">No trades yet</p>
        <p className="text-xs mt-1">Simulated trades will appear here</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="text-neutral-600 text-left text-xs border-b border-neutral-800">
            <th
              className="py-3 px-2 font-medium cursor-pointer hover:text-neutral-400 transition-colors"
              onClick={() => handleSort('result')}
            >
              <div className="flex items-center gap-1">
                Status <SortIcon column="result" />
              </div>
            </th>
            <th
              className="py-3 px-2 font-medium cursor-pointer hover:text-neutral-400 transition-colors"
              onClick={() => handleSort('platform')}
            >
              <div className="flex items-center gap-1">
                Market <SortIcon column="platform" />
              </div>
            </th>
            <th className="py-3 px-2 font-medium text-center">Direction</th>
            <th
              className="py-3 px-2 font-medium text-right cursor-pointer hover:text-neutral-400 transition-colors"
              onClick={() => handleSort('size')}
            >
              <div className="flex items-center justify-end gap-1">
                Size <SortIcon column="size" />
              </div>
            </th>
            <th className="py-3 px-2 font-medium text-right">Entry</th>
            <th
              className="py-3 px-2 font-medium text-right cursor-pointer hover:text-neutral-400 transition-colors"
              onClick={() => handleSort('pnl')}
            >
              <div className="flex items-center justify-end gap-1">
                P&L <SortIcon column="pnl" />
              </div>
            </th>
            <th
              className="py-3 px-2 font-medium text-right cursor-pointer hover:text-neutral-400 transition-colors"
              onClick={() => handleSort('timestamp')}
            >
              <div className="flex items-center justify-end gap-1">
                Time <SortIcon column="timestamp" />
              </div>
            </th>
          </tr>
        </thead>
        <tbody>
          {sortedTrades.map((trade) => {
            const isPending = trade.result === 'pending'
            const isWin = trade.result === 'win'
            const platformKey = trade.platform.toLowerCase() as keyof typeof platformStyles
            const style = platformStyles[platformKey] || platformStyles.kalshi
            const marketUrl = getMarketUrl(trade.platform, trade.market_ticker)

            return (
              <tr
                key={trade.id}
                className="border-b border-neutral-800 hover:bg-neutral-900/50 transition-colors"
              >
                <td className="py-3 px-2">
                  <span className={`px-2 py-1 text-[10px] font-medium uppercase ${
                    isPending
                      ? 'bg-amber-500/10 text-amber-500 border border-amber-500/20'
                      : isWin
                        ? 'bg-green-500/10 text-green-500 border border-green-500/20'
                        : 'bg-red-500/10 text-red-500 border border-red-500/20'
                  }`}>
                    {isPending ? 'Pending' : isWin ? 'Win' : 'Loss'}
                  </span>
                </td>
                <td className="py-3 px-2">
                  <div className="max-w-[220px]">
                    <span className={`px-1.5 py-0.5 text-[10px] font-medium uppercase border mr-2 ${style.badge}`}>
                      {style.icon} {style.name}
                    </span>
                    <a
                      href={marketUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group inline-flex items-center gap-1 text-xs text-neutral-400 hover:text-neutral-200 transition-colors"
                    >
                      <span className="truncate" title={trade.market_ticker}>
                        {trade.market_ticker}
                      </span>
                      <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 shrink-0" />
                    </a>
                  </div>
                </td>
                <td className="py-3 px-2 text-center">
                  <span className={`px-2 py-1 text-[10px] font-semibold uppercase ${
                    trade.direction === 'yes'
                      ? 'bg-green-500/10 text-green-500 border border-green-500/20'
                      : 'bg-red-500/10 text-red-500 border border-red-500/20'
                  }`}>
                    {trade.direction}
                  </span>
                </td>
                <td className="py-3 px-2 text-right text-sm text-neutral-300 tabular-nums">
                  ${trade.size.toFixed(0)}
                </td>
                <td className="py-3 px-2 text-right text-sm text-neutral-500 tabular-nums">
                  {(trade.entry_price * 100).toFixed(0)}c
                </td>
                <td className="py-3 px-2 text-right">
                  {trade.pnl !== null ? (
                    <span className={`text-sm font-semibold tabular-nums ${
                      trade.pnl >= 0 ? 'text-green-500' : 'text-red-500'
                    }`}>
                      {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-sm text-neutral-600">-</span>
                  )}
                </td>
                <td className="py-3 px-2 text-right text-xs text-neutral-600">
                  {formatDistanceToNow(new Date(trade.timestamp), { addSuffix: true })}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
