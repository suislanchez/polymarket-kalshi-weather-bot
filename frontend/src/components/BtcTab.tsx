import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Bitcoin, ChevronDown, ChevronUp, TrendingUp, TrendingDown } from 'lucide-react'
import type { Signal, BtcPrice, Microstructure, BtcWindow } from '../types'
import { formatCountdown } from '../utils'

interface Props {
  signals: Signal[]
  btcPrice: BtcPrice | null
  microstructure: Microstructure | null
  windows: BtcWindow[]
  enabled: boolean
  onToggle: () => void
  onSimulateTrade: (ticker: string) => void
  isSimulating: boolean
}

function PriceCard({ btcPrice, micro }: { btcPrice: BtcPrice | null; micro: Microstructure | null }) {
  const price = micro?.price || btcPrice?.price || 0
  const change = btcPrice?.change_24h || 0

  return (
    <div className="bg-[#111] border border-neutral-800 rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">BTC Price</div>
          <div className="text-2xl font-mono font-semibold text-white tabular-nums">
            ${price.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </div>
        </div>
        <div className={`flex items-center gap-1 text-sm font-mono ${change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {change >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          {change >= 0 ? '+' : ''}{change.toFixed(2)}%
        </div>
      </div>
      {micro && (
        <div className="grid grid-cols-3 gap-3 mt-3 pt-3 border-t border-neutral-800">
          <div>
            <span className="text-[10px] text-neutral-600 block">RSI</span>
            <span className={`text-xs font-mono ${micro.rsi > 70 ? 'text-red-400' : micro.rsi < 30 ? 'text-green-400' : 'text-neutral-300'}`}>
              {micro.rsi.toFixed(0)}
            </span>
          </div>
          <div>
            <span className="text-[10px] text-neutral-600 block">Momentum</span>
            <span className={`text-xs font-mono ${micro.momentum_5m >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {micro.momentum_5m >= 0 ? '+' : ''}{(micro.momentum_5m * 100).toFixed(2)}%
            </span>
          </div>
          <div>
            <span className="text-[10px] text-neutral-600 block">Volatility</span>
            <span className="text-xs font-mono text-neutral-300">{(micro.volatility * 100).toFixed(3)}%</span>
          </div>
        </div>
      )}
    </div>
  )
}

function WindowPill({ window: w }: { window: BtcWindow }) {
  const [countdown, setCountdown] = useState(w.time_until_end)

  useState(() => {
    const interval = setInterval(() => {
      setCountdown(prev => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(interval)
  })

  return (
    <div className={`flex items-center gap-3 px-3 py-2 border rounded-lg ${
      w.is_active ? 'border-amber-500/30 bg-amber-500/5' : 'border-neutral-800 bg-[#111]'
    }`}>
      {w.is_active && <span className="text-[9px] font-bold text-amber-400 uppercase">Live</span>}
      {w.is_upcoming && <span className="text-[9px] font-medium text-blue-400 uppercase">Next</span>}
      <span className="text-xs tabular-nums text-green-400 font-mono">{(w.up_price * 100).toFixed(0)}c</span>
      <span className="text-neutral-600 text-xs">/</span>
      <span className="text-xs tabular-nums text-red-400 font-mono">{(w.down_price * 100).toFixed(0)}c</span>
      <span className="text-xs tabular-nums text-neutral-500 font-mono ml-auto">{formatCountdown(countdown)}</span>
    </div>
  )
}

function SignalRow({ signal, onTrade, isSimulating }: { signal: Signal; onTrade: (ticker: string) => void; isSimulating: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const isUp = signal.direction === 'up'

  return (
    <div className={`border-b border-neutral-800/50 ${signal.actionable ? '' : 'opacity-40'}`}>
      <div
        className="flex items-center py-3 px-3 cursor-pointer hover:bg-neutral-800/20 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex-1 min-w-0">
          <div className="text-sm text-neutral-200 font-mono truncate">
            {(signal.event_slug || signal.market_ticker).replace('btc-updown-5m-', '')}
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${
            isUp ? 'text-green-400 bg-green-500/10' : 'text-red-400 bg-red-500/10'
          }`}>
            {signal.direction}
          </span>
          <span className={`text-sm font-mono font-semibold w-14 text-right ${
            signal.edge > 0.02 ? 'text-green-400' : 'text-neutral-400'
          }`}>
            {(Math.abs(signal.edge) * 100).toFixed(1)}%
          </span>
          {signal.actionable && (
            <button
              onClick={(e) => { e.stopPropagation(); onTrade(signal.market_ticker) }}
              disabled={isSimulating}
              className="px-2 py-1 text-[9px] font-medium uppercase bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded hover:bg-amber-500/20 disabled:opacity-50"
            >
              Trade
            </button>
          )}
          {expanded ? <ChevronUp className="w-3 h-3 text-neutral-600" /> : <ChevronDown className="w-3 h-3 text-neutral-600" />}
        </div>
      </div>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 text-[10px] text-neutral-500 font-mono bg-neutral-900 mx-3 mb-3 p-2 rounded leading-relaxed">
              {signal.reasoning}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function BtcTab({ signals, btcPrice, microstructure, windows, enabled, onToggle, onSimulateTrade, isSimulating }: Props) {
  const actionable = signals.filter(s => s.actionable)
  const sorted = [...signals].sort((a, b) => {
    if (a.actionable !== b.actionable) return a.actionable ? -1 : 1
    return Math.abs(b.edge) - Math.abs(a.edge)
  })

  return (
    <div className="overflow-y-auto max-h-[calc(100vh-120px)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-800">
        <div className="flex items-center gap-2">
          <Bitcoin className="w-4 h-4 text-amber-400" />
          <span className="text-sm font-medium">BTC 5-Min Markets</span>
          <span className="text-[10px] text-neutral-500">{actionable.length} actionable / {signals.length} total</span>
        </div>
        <button
          onClick={onToggle}
          className={`px-3 py-1 text-[10px] font-medium uppercase rounded-full border transition-colors ${
            enabled
              ? 'bg-green-500/10 text-green-400 border-green-500/20 hover:bg-green-500/20'
              : 'bg-neutral-800 text-neutral-500 border-neutral-700 hover:bg-neutral-700'
          }`}
        >
          {enabled ? 'Enabled' : 'Disabled'}
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* Price Card */}
        <PriceCard btcPrice={btcPrice} micro={microstructure} />

        {/* Windows */}
        {windows.length > 0 && (
          <div>
            <h3 className="text-[10px] text-neutral-500 uppercase tracking-wider font-medium mb-2">Active Windows</h3>
            <div className="space-y-2">
              {windows.slice(0, 6).map(w => (
                <WindowPill key={w.slug} window={w} />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Signals */}
      <div className="px-4 pt-2 pb-1">
        <h3 className="text-[10px] text-neutral-500 uppercase tracking-wider font-medium">Signals</h3>
      </div>
      {sorted.length > 0 ? (
        <div>
          {sorted.map(s => (
            <SignalRow key={s.market_ticker} signal={s} onTrade={onSimulateTrade} isSimulating={isSimulating} />
          ))}
        </div>
      ) : (
        <div className="flex items-center justify-center py-12 text-neutral-600 text-xs">
          No BTC signals found
        </div>
      )}
    </div>
  )
}
