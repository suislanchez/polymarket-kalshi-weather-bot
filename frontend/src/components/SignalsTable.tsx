import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { useState, useMemo } from 'react'
import type { Signal } from '../types'

interface Props {
  signals: Signal[]
  onSimulateTrade: (ticker: string) => void
  isSimulating: boolean
}

type SortKey = 'edge' | 'model_probability' | 'suggested_size'
type SortDir = 'asc' | 'desc'

export function SignalsTable({ signals, onSimulateTrade, isSimulating }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('edge')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [expandedSlug, setExpandedSlug] = useState<string | null>(null)

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sortedSignals = useMemo(() => {
    // Actionable signals first, then sort by key
    return [...signals].sort((a, b) => {
      if (a.actionable !== b.actionable) return a.actionable ? -1 : 1
      let aVal: number, bVal: number
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
        default:
          return 0
      }
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal
    })
  }, [signals, sortKey, sortDir])

  const SortIcon = ({ column }: { column: SortKey }) => {
    if (sortKey !== column) return <ArrowUpDown className="w-2.5 h-2.5 text-neutral-600" />
    return sortDir === 'asc'
      ? <ArrowUp className="w-2.5 h-2.5 text-orange-500" />
      : <ArrowDown className="w-2.5 h-2.5 text-orange-500" />
  }

  if (signals.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-neutral-600">
        <p className="text-xs">No signals generated</p>
        <p className="text-[10px] mt-0.5 text-neutral-700">Run a scan or wait for next cycle</p>
      </div>
    )
  }

  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-neutral-900 z-10">
        <tr className="text-neutral-600 text-left text-[10px] border-b border-neutral-800">
          <th className="py-1.5 px-2 font-medium">Status</th>
          <th className="py-1.5 px-2 font-medium">Window</th>
          <th className="py-1.5 px-2 font-medium text-center">Dir</th>
          <th
            className="py-1.5 px-2 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('edge')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Edge <SortIcon column="edge" />
            </div>
          </th>
          <th
            className="py-1.5 px-2 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('model_probability')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Mod <SortIcon column="model_probability" />
            </div>
          </th>
          <th className="py-1.5 px-2 font-medium text-right">Mkt</th>
          <th className="py-1.5 px-2 font-medium text-right">Conf</th>
          <th
            className="py-1.5 px-2 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('suggested_size')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Size <SortIcon column="suggested_size" />
            </div>
          </th>
          <th className="py-1.5 px-2 font-medium text-right"></th>
        </tr>
      </thead>
      <tbody>
        {sortedSignals.map((signal) => {
          const isUp = signal.direction === 'up'
          const slug = signal.event_slug || signal.market_ticker
          const isExpanded = expandedSlug === slug

          return (
            <>
              <tr
                key={slug}
                className={`border-b border-neutral-800/50 hover:bg-neutral-800/30 text-[11px] cursor-pointer ${
                  signal.actionable ? '' : 'opacity-50'
                }`}
                onClick={() => setExpandedSlug(isExpanded ? null : slug)}
              >
                <td className="py-1 px-2">
                  {signal.actionable ? (
                    <span className="text-[9px] font-bold uppercase text-green-500 bg-green-500/10 border border-green-500/20 px-1 py-0.5">GO</span>
                  ) : (
                    <span className="text-[9px] font-medium uppercase text-neutral-600 bg-neutral-800 border border-neutral-700 px-1 py-0.5">--</span>
                  )}
                </td>
                <td className="py-1 px-2">
                  <span className="text-neutral-400 truncate block max-w-[120px]" title={slug}>
                    {slug.replace('btc-updown-5m-', '')}
                  </span>
                </td>
                <td className="py-1 px-2 text-center">
                  <span className={`text-[10px] font-semibold uppercase ${isUp ? 'text-green-500' : 'text-red-500'}`}>
                    {signal.direction}
                  </span>
                </td>
                <td className="py-1 px-2 text-right">
                  <span className={`font-semibold tabular-nums ${
                    signal.edge > 0 ? 'text-green-500' : signal.edge < 0 ? 'text-red-500' : 'text-neutral-600'
                  }`}>
                    {signal.edge === 0 ? '-' : `${Math.abs(signal.edge * 100).toFixed(1)}%`}
                  </span>
                </td>
                <td className="py-1 px-2 text-right text-neutral-300 tabular-nums">
                  {(signal.model_probability * 100).toFixed(0)}%
                </td>
                <td className="py-1 px-2 text-right text-neutral-500 tabular-nums">
                  {(signal.market_probability * 100).toFixed(0)}%
                </td>
                <td className="py-1 px-2 text-right text-neutral-500 tabular-nums">
                  {(signal.confidence * 100).toFixed(0)}%
                </td>
                <td className="py-1 px-2 text-right text-blue-400 tabular-nums">
                  {signal.suggested_size > 0 ? `$${signal.suggested_size.toFixed(0)}` : '-'}
                </td>
                <td className="py-1 px-2 text-right">
                  {signal.actionable && (
                    <button
                      onClick={(e) => { e.stopPropagation(); onSimulateTrade(signal.market_ticker) }}
                      disabled={isSimulating}
                      className="px-1.5 py-0.5 text-[9px] font-medium uppercase bg-orange-500/10 text-orange-400 border border-orange-500/20 hover:bg-orange-500/20 disabled:opacity-50"
                    >
                      Trade
                    </button>
                  )}
                </td>
              </tr>
              {isExpanded && (
                <tr key={slug + '-detail'} className="border-b border-neutral-800/50">
                  <td colSpan={9} className="px-3 py-2 bg-neutral-900/50">
                    <div className="text-[10px] text-neutral-400 font-mono leading-relaxed whitespace-pre-wrap break-all">
                      {signal.reasoning}
                    </div>
                    {signal.btc_price > 0 && (
                      <div className="mt-1 text-[10px] text-neutral-600">
                        BTC: ${signal.btc_price.toLocaleString()} | Window: {signal.window_end ? new Date(signal.window_end).toLocaleTimeString() : '?'}
                      </div>
                    )}
                  </td>
                </tr>
              )}
            </>
          )
        })}
      </tbody>
    </table>
  )
}
