import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { Signal, WeatherSignal } from '../types'
import { platformStyles } from '../utils'

interface Props {
  signals: Signal[]
  weatherSignals: WeatherSignal[]
  onSimulateTrade: (ticker: string) => void
  isSimulating: boolean
}

type SortKey = 'edge' | 'model_probability' | 'suggested_size'
type SortDir = 'asc' | 'desc'

interface UnifiedSignal {
  key: string
  ticker: string
  title: string
  platform: string
  category: 'BTC' | 'WX'
  direction: string
  edge: number
  modelProb: number
  marketProb: number
  confidence: number
  suggestedSize: number
  reasoning: string
  actionable: boolean
}

function PlatformBadge({ platform }: { platform: string }) {
  const style = platformStyles[platform.toLowerCase()]
  if (!style) return null
  return (
    <span className={`platform-badge ${style.badge}`}>
      {style.icon}
    </span>
  )
}

function CategoryBadge({ category }: { category: 'BTC' | 'WX' }) {
  return category === 'BTC'
    ? <span className="text-[8px] font-bold px-1 py-0.5 bg-amber-500/10 text-amber-500 border border-amber-500/20">BTC</span>
    : <span className="text-[8px] font-bold px-1 py-0.5 bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">WX</span>
}

function EdgeBar({ edge }: { edge: number }) {
  const absEdge = Math.abs(edge) * 100
  const width = Math.min(100, absEdge * 5)
  const color = edge > 0.05 ? '#22c55e' : edge > 0 ? '#22c55e80' : '#dc2626'
  return (
    <div className="edge-bar">
      <div className="edge-fill" style={{ width: `${width}%`, backgroundColor: color }} />
    </div>
  )
}

export function SignalsTable({ signals, weatherSignals, onSimulateTrade, isSimulating }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('edge')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [expandedKey, setExpandedKey] = useState<string | null>(null)

  const unified: UnifiedSignal[] = useMemo(() => {
    const btc: UnifiedSignal[] = signals.map(s => ({
      key: `btc-${s.market_ticker}`,
      ticker: s.market_ticker,
      title: s.event_slug || s.market_ticker,
      platform: s.platform || 'kalshi',
      category: 'BTC',
      direction: s.direction,
      edge: s.edge,
      modelProb: s.model_probability,
      marketProb: s.market_probability,
      confidence: s.confidence,
      suggestedSize: s.suggested_size,
      reasoning: s.reasoning,
      actionable: s.actionable,
    }))

    const wx: UnifiedSignal[] = weatherSignals.map(s => ({
      key: `wx-${s.market_id}`,
      ticker: s.market_id,
      title: `${s.city_name} ${s.metric} ${s.direction} ${s.threshold_f}F`,
      platform: s.platform || 'kalshi',
      category: 'WX',
      direction: s.direction,
      edge: s.edge,
      modelProb: s.model_probability,
      marketProb: s.market_probability,
      confidence: s.confidence,
      suggestedSize: s.suggested_size,
      reasoning: s.reasoning,
      actionable: s.actionable,
    }))

    return [...btc, ...wx]
  }, [signals, weatherSignals])

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sorted = useMemo(() => {
    return [...unified].sort((a, b) => {
      if (a.actionable !== b.actionable) return a.actionable ? -1 : 1
      let aVal: number, bVal: number
      switch (sortKey) {
        case 'edge':
          aVal = Math.abs(a.edge); bVal = Math.abs(b.edge); break
        case 'model_probability':
          aVal = a.modelProb; bVal = b.modelProb; break
        case 'suggested_size':
          aVal = a.suggestedSize; bVal = b.suggestedSize; break
        default: return 0
      }
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal
    })
  }, [unified, sortKey, sortDir])

  const SortIcon = ({ column }: { column: SortKey }) => {
    if (sortKey !== column) return <ArrowUpDown className="w-2.5 h-2.5 text-neutral-600" />
    return sortDir === 'asc'
      ? <ArrowUp className="w-2.5 h-2.5 text-amber-500" />
      : <ArrowDown className="w-2.5 h-2.5 text-amber-500" />
  }

  if (unified.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-neutral-600">
        <p className="text-xs">No signals generated</p>
        <p className="text-[10px] mt-0.5 text-neutral-700">Run a scan or wait for next cycle</p>
      </div>
    )
  }

  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#0a0a0a] z-10">
        <tr className="text-neutral-600 text-left text-[10px] border-b border-neutral-800">
          <th className="py-1.5 px-1.5 font-medium w-6"></th>
          <th className="py-1.5 px-1.5 font-medium w-5"></th>
          <th className="py-1.5 px-1.5 font-medium">Signal</th>
          <th className="py-1.5 px-1.5 font-medium text-center w-8">Dir</th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('edge')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Edge <SortIcon column="edge" />
            </div>
          </th>
          <th className="py-1.5 px-1.5 font-medium text-right w-10"></th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('model_probability')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Mod <SortIcon column="model_probability" />
            </div>
          </th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-neutral-400"
            onClick={() => handleSort('suggested_size')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Size <SortIcon column="suggested_size" />
            </div>
          </th>
          <th className="py-1.5 px-1.5 font-medium text-right w-10"></th>
        </tr>
      </thead>
      <tbody>
        <AnimatePresence>
          {sorted.map((sig, i) => {
            const isExpanded = expandedKey === sig.key
            const isUp = sig.direction === 'up' || sig.direction === 'above'

            return (
              <motion.tr
                key={sig.key}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.02 }}
                className={`border-b border-neutral-800/50 hover:bg-neutral-800/30 text-[11px] cursor-pointer ${
                  sig.actionable ? '' : 'opacity-40'
                }`}
                onClick={() => setExpandedKey(isExpanded ? null : sig.key)}
              >
                <td className="py-1 px-1.5">
                  <PlatformBadge platform={sig.platform} />
                </td>
                <td className="py-1 px-1.5">
                  <CategoryBadge category={sig.category} />
                </td>
                <td className="py-1 px-1.5">
                  <span className="text-neutral-400 truncate block max-w-[110px]" title={sig.title}>
                    {sig.title}
                  </span>
                </td>
                <td className="py-1 px-1.5 text-center">
                  <span className={`text-[10px] font-semibold uppercase ${isUp ? 'text-green-500' : 'text-red-500'}`}>
                    {sig.direction}
                  </span>
                </td>
                <td className="py-1 px-1.5 text-right">
                  <span className={`font-semibold tabular-nums ${
                    sig.edge > 0 ? 'text-green-500' : sig.edge < 0 ? 'text-red-500' : 'text-neutral-600'
                  }`}>
                    {sig.edge === 0 ? '-' : `${Math.abs(sig.edge * 100).toFixed(1)}%`}
                  </span>
                </td>
                <td className="py-1 px-1.5">
                  <EdgeBar edge={sig.edge} />
                </td>
                <td className="py-1 px-1.5 text-right text-neutral-300 tabular-nums">
                  {(sig.modelProb * 100).toFixed(0)}%
                </td>
                <td className="py-1 px-1.5 text-right text-blue-400 tabular-nums">
                  {sig.suggestedSize > 0 ? `$${sig.suggestedSize.toFixed(0)}` : '-'}
                </td>
                <td className="py-1 px-1.5 text-right">
                  {sig.actionable && sig.category === 'BTC' && (
                    <button
                      onClick={(e) => { e.stopPropagation(); onSimulateTrade(sig.ticker) }}
                      disabled={isSimulating}
                      className="px-1.5 py-0.5 text-[8px] font-medium uppercase bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 disabled:opacity-50"
                    >
                      Trade
                    </button>
                  )}
                </td>
              </motion.tr>
            )
          })}
        </AnimatePresence>
      </tbody>
    </table>
  )
}
