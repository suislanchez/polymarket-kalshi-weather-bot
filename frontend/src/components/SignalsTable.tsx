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
        <p className="text-xs">No signals</p>
        <p className="text-[10px] mt-0.5">Waiting for market data...</p>
      </div>
    )
  }

  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-neutral-900 z-10">
        <tr className="text-neutral-600 text-left text-[10px] border-b border-neutral-800">
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

          return (
            <tr
              key={signal.market_ticker + signal.event_slug}
              className="border-b border-neutral-800/50 hover:bg-neutral-800/30 text-[11px]"
            >
              <td className="py-1 px-2">
                <span className="text-neutral-400 truncate block max-w-[140px]" title={signal.event_slug || signal.market_title}>
                  {signal.event_slug?.replace('btc-updown-5m-', '') || signal.market_title}
                </span>
              </td>
              <td className="py-1 px-2 text-center">
                <span className={`text-[10px] font-semibold uppercase ${isUp ? 'text-green-500' : 'text-red-500'}`}>
                  {signal.direction}
                </span>
              </td>
              <td className="py-1 px-2 text-right">
                <span className={`font-semibold tabular-nums ${signal.edge > 0 ? 'text-green-500' : 'text-red-500'}`}>
                  {Math.abs(signal.edge * 100).toFixed(1)}%
                </span>
              </td>
              <td className="py-1 px-2 text-right text-neutral-300 tabular-nums">
                {(signal.model_probability * 100).toFixed(0)}%
              </td>
              <td className="py-1 px-2 text-right text-neutral-500 tabular-nums">
                {(signal.market_probability * 100).toFixed(0)}%
              </td>
              <td className="py-1 px-2 text-right text-blue-400 tabular-nums">
                ${signal.suggested_size.toFixed(0)}
              </td>
              <td className="py-1 px-2 text-right">
                <button
                  onClick={() => onSimulateTrade(signal.market_ticker)}
                  disabled={isSimulating}
                  className="px-1.5 py-0.5 text-[9px] font-medium uppercase bg-orange-500/10 text-orange-400 border border-orange-500/20 hover:bg-orange-500/20 disabled:opacity-50"
                >
                  Trade
                </button>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
