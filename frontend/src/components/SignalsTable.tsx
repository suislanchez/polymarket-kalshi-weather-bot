import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import type { WeatherSignal } from '../types'

type SortKey = 'edge' | 'model_probability' | 'suggested_size'

interface Props {
  weatherSignals: WeatherSignal[]
}

function pct(v: number, decimals = 1) {
  return `${(v * 100).toFixed(decimals)}%`
}

function EdgeBar({ edge }: { edge: number }) {
  const width = Math.min(Math.abs(edge) * 250, 100)
  const color = edge > 0 ? 'bg-emerald-500' : 'bg-red-500'
  return <div className="h-1 w-12 bg-neutral-800"><div className={`h-full ${color}`} style={{ width: `${width}%` }} /></div>
}

function SourceBadge({ source }: { source?: string }) {
  const label = source || 'GFS'
  const cls = label === 'METAR-lock'
    ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
    : label === 'METAR-early'
      ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
      : label === 'GFS-veto'
        ? 'bg-red-500/15 text-red-400 border-red-500/30'
        : 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30'
  return <span className={`text-[8px] font-bold px-1 py-0.5 border ${cls}`}>{label}</span>
}

export function SignalsTable({ weatherSignals }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('edge')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [expandedKey, setExpandedKey] = useState<string | null>(null)

  const sorted = useMemo(() => {
    return [...weatherSignals].sort((a, b) => {
      if (a.actionable !== b.actionable) return a.actionable ? -1 : 1
      let aVal: number, bVal: number
      switch (sortKey) {
        case 'edge': aVal = Math.abs(a.edge); bVal = Math.abs(b.edge); break
        case 'model_probability': aVal = a.model_probability; bVal = b.model_probability; break
        case 'suggested_size': aVal = a.suggested_size; bVal = b.suggested_size; break
      }
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal
    })
  }, [weatherSignals, sortKey, sortDir])

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const SortIcon = ({ column }: { column: SortKey }) => {
    if (sortKey !== column) return <ArrowUpDown className="w-2.5 h-2.5 text-neutral-600" />
    return sortDir === 'asc' ? <ArrowUp className="w-2.5 h-2.5 text-cyan-500" /> : <ArrowDown className="w-2.5 h-2.5 text-cyan-500" />
  }

  if (sorted.length === 0) {
    return <div className="flex flex-col items-center justify-center py-8 text-neutral-600"><p className="text-xs">No weather signals generated</p><p className="text-[10px] mt-0.5 text-neutral-700">Run a scan or wait for the next cycle</p></div>
  }

  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#0a0a0a] z-10">
        <tr className="text-neutral-600 text-left text-[10px] border-b border-neutral-800">
          <th className="py-1.5 px-1.5 font-medium">Source</th>
          <th className="py-1.5 px-1.5 font-medium">Market</th>
          <th className="py-1.5 px-1.5 font-medium text-center">Side</th>
          <th className="py-1.5 px-1.5 font-medium text-right cursor-pointer" onClick={() => handleSort('edge')}><div className="flex items-center justify-end gap-0.5">Edge <SortIcon column="edge" /></div></th>
          <th className="py-1.5 px-1.5 font-medium text-right cursor-pointer" onClick={() => handleSort('model_probability')}><div className="flex items-center justify-end gap-0.5">Model <SortIcon column="model_probability" /></div></th>
          <th className="py-1.5 px-1.5 font-medium text-right cursor-pointer" onClick={() => handleSort('suggested_size')}><div className="flex items-center justify-end gap-0.5">Size <SortIcon column="suggested_size" /></div></th>
        </tr>
      </thead>
      <tbody>
        <AnimatePresence>
          {sorted.map((sig, i) => {
            const key = sig.market_id
            const isExpanded = expandedKey === key
            const isYes = sig.direction === 'yes'
            return (
              <motion.tr key={key} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.015 }} className={`border-b border-neutral-800/50 hover:bg-neutral-800/30 text-[11px] cursor-pointer ${sig.actionable ? '' : 'opacity-50'}`} onClick={() => setExpandedKey(isExpanded ? null : key)}>
                <td className="py-1 px-1.5"><SourceBadge source={sig.signal_source} /></td>
                <td className="py-1 px-1.5"><span className="text-neutral-300 truncate block max-w-[180px]" title={sig.reasoning}>{sig.city_name} {sig.metric} {sig.threshold_f.toFixed(0)}°F</span>{isExpanded && <div className="text-[10px] text-neutral-500 mt-1 leading-relaxed max-w-[430px]">{sig.reasoning}</div>}</td>
                <td className="py-1 px-1.5 text-center"><span className={`text-[10px] font-semibold uppercase ${isYes ? 'text-emerald-500' : 'text-red-500'}`}>{sig.direction}</span></td>
                <td className="py-1 px-1.5 text-right"><span className={`font-semibold tabular-nums ${sig.edge > 0 ? 'text-emerald-500' : 'text-red-500'}`}>{pct(sig.edge)}</span><div className="flex justify-end mt-0.5"><EdgeBar edge={sig.edge} /></div></td>
                <td className="py-1 px-1.5 text-right tabular-nums text-cyan-400">{pct(sig.model_probability)}</td>
                <td className="py-1 px-1.5 text-right tabular-nums text-neutral-300">${sig.suggested_size.toFixed(0)}</td>
              </motion.tr>
            )
          })}
        </AnimatePresence>
      </tbody>
    </table>
  )
}
