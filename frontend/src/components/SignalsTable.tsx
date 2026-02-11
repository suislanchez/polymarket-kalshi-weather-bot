import { ExternalLink, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { useState, useMemo } from 'react'
import type { Signal, MarketCategory } from '../types'
import { getMarketUrl, platformStyles, categoryStyles } from '../utils'

interface Props {
  signals: Signal[]
  onSimulateTrade: (ticker: string) => void
  isSimulating: boolean
}

type SortKey = 'edge' | 'model_probability' | 'suggested_size' | 'platform'
type SortDir = 'asc' | 'desc'

export function SignalsTable({ signals, onSimulateTrade, isSimulating }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('edge')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sortedSignals = useMemo(() => {
    return [...signals].sort((a, b) => {
      let aVal: number | string, bVal: number | string
      switch (sortKey) {
        case 'edge':
          aVal = Math.abs(a.edge)
          bVal = Math.abs(b.edge)
          break
        case 'model_probability':
          aVal = a.model_probability
          bVal = b.model_probability
          break
        case 'suggested_size':
          aVal = a.suggested_size
          bVal = b.suggested_size
          break
        case 'platform':
          aVal = a.platform
          bVal = b.platform
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
  }, [signals, sortKey, sortDir])

  const SortIcon = ({ column }: { column: SortKey }) => {
    if (sortKey !== column) return <ArrowUpDown className="w-3 h-3 text-neutral-600" />
    return sortDir === 'asc'
      ? <ArrowUp className="w-3 h-3 text-green-500" />
      : <ArrowDown className="w-3 h-3 text-green-500" />
  }

  // Edge threshold for actionable signals (3%)
  const EDGE_THRESHOLD = 0.03
  const actionableCount = signals.filter(s => Math.abs(s.edge) >= EDGE_THRESHOLD).length

  if (signals.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-neutral-600">
        <div className="text-4xl mb-4 opacity-30">---</div>
        <p className="text-sm">No signals detected</p>
        <p className="text-xs mt-1">Waiting for market data...</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <div className="flex items-center justify-between px-2 py-2 border-b border-neutral-800 text-xs">
        <span className="text-neutral-500">
          {signals.length} signals ({actionableCount} actionable)
        </span>
        <span className="text-neutral-600">
          Edge threshold: 3%
        </span>
      </div>
      <table className="w-full">
        <thead>
          <tr className="text-neutral-600 text-left text-xs border-b border-neutral-800">
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
              onClick={() => handleSort('edge')}
            >
              <div className="flex items-center justify-end gap-1">
                Edge <SortIcon column="edge" />
              </div>
            </th>
            <th
              className="py-3 px-2 font-medium text-right cursor-pointer hover:text-neutral-400 transition-colors"
              onClick={() => handleSort('model_probability')}
            >
              <div className="flex items-center justify-end gap-1">
                Model <SortIcon column="model_probability" />
              </div>
            </th>
            <th className="py-3 px-2 font-medium text-right">Market</th>
            <th
              className="py-3 px-2 font-medium text-right cursor-pointer hover:text-neutral-400 transition-colors"
              onClick={() => handleSort('suggested_size')}
            >
              <div className="flex items-center justify-end gap-1">
                Size <SortIcon column="suggested_size" />
              </div>
            </th>
            <th className="py-3 px-2 font-medium text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          {sortedSignals.map((signal) => {
            const edgePercent = Math.abs(signal.edge * 100)
            const isActionable = Math.abs(signal.edge) >= EDGE_THRESHOLD
            const platformKey = signal.platform.toLowerCase() as keyof typeof platformStyles
            const style = platformStyles[platformKey] || platformStyles.kalshi
            const marketUrl = getMarketUrl(signal.platform, signal.market_ticker, signal.event_slug)
            const catKey = (signal.category || 'other') as MarketCategory
            const catStyle = categoryStyles[catKey] || categoryStyles.other

            return (
              <tr
                key={signal.market_ticker}
                className={`border-b border-neutral-800 hover:bg-neutral-900/50 transition-colors ${
                  !isActionable ? 'opacity-50' : ''
                }`}
              >
                <td className="py-3 px-2">
                  <div className="max-w-[280px]">
                    <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                      <span className={`px-1.5 py-0.5 text-[10px] font-medium uppercase border ${style.badge}`}>
                        {style.icon} {style.name}
                      </span>
                      <span className={`px-1.5 py-0.5 text-[10px] font-medium uppercase border ${catStyle.badge}`}>
                        {catStyle.icon} {catStyle.name}
                      </span>
                      {signal.city && (
                        <span className="px-1.5 py-0.5 text-[10px] font-medium capitalize bg-neutral-800 text-neutral-400 border border-neutral-700">
                          {signal.city.replace('_', ' ')}
                        </span>
                      )}
                      {isActionable && (
                        <span className="px-1.5 py-0.5 text-[10px] font-bold uppercase bg-green-500/20 text-green-400 border border-green-500/30">
                          ACTIONABLE
                        </span>
                      )}
                    </div>
                    <a
                      href={marketUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group flex items-center gap-1 text-xs text-neutral-400 hover:text-neutral-200 transition-colors"
                    >
                      <span className="truncate" title={signal.market_title}>
                        {signal.market_title}
                      </span>
                      <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 shrink-0" />
                    </a>
                  </div>
                </td>
                <td className="py-3 px-2 text-center">
                  <span className={`px-2 py-1 text-[10px] font-semibold uppercase ${
                    signal.direction === 'yes'
                      ? 'bg-green-500/10 text-green-500 border border-green-500/20'
                      : 'bg-red-500/10 text-red-500 border border-red-500/20'
                  }`}>
                    {signal.direction}
                  </span>
                </td>
                <td className="py-3 px-2 text-right">
                  <span className={`text-sm font-semibold tabular-nums ${
                    signal.edge > 0 ? 'text-green-500' : 'text-red-500'
                  }`}>
                    {edgePercent.toFixed(1)}%
                  </span>
                </td>
                <td className="py-3 px-2 text-right text-sm text-neutral-300 tabular-nums">
                  {(signal.model_probability * 100).toFixed(1)}%
                </td>
                <td className="py-3 px-2 text-right text-sm text-neutral-500 tabular-nums">
                  {(signal.market_probability * 100).toFixed(1)}%
                </td>
                <td className="py-3 px-2 text-right text-sm text-blue-400 tabular-nums">
                  ${signal.suggested_size.toFixed(0)}
                </td>
                <td className="py-3 px-2 text-right">
                  <button
                    onClick={() => onSimulateTrade(signal.market_ticker)}
                    disabled={isSimulating}
                    className="px-3 py-1.5 text-[10px] font-medium uppercase bg-green-500/10 text-green-500 border border-green-500/20 hover:bg-green-500/20 transition-colors disabled:opacity-50"
                  >
                    Trade
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
