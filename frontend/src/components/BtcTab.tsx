import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronUp, TrendingUp, TrendingDown } from 'lucide-react'
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
  const isUp = change >= 0

  return (
    <div className="yf-card p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[12px] text-neutral-500 font-medium mb-1">Bitcoin</div>
          <div className="text-[28px] font-bold text-white tabular-nums leading-none">
            ${price.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </div>
          <div className={`text-[14px] font-medium tabular-nums mt-1 ${isUp ? 'text-[#00C805]' : 'text-[#FF3B30]'}`}>
            {isUp ? <TrendingUp className="w-3.5 h-3.5 inline mr-1" /> : <TrendingDown className="w-3.5 h-3.5 inline mr-1" />}
            {isUp ? '+' : ''}{change.toFixed(2)}%
          </div>
        </div>
      </div>
      {micro && (
        <div className="grid grid-cols-3 gap-3 mt-4 pt-3 border-t border-[#2A2A2E]">
          <div>
            <span className="text-[11px] text-neutral-500 block">RSI</span>
            <span className={`text-[14px] font-semibold tabular-nums ${micro.rsi > 70 ? 'text-[#FF3B30]' : micro.rsi < 30 ? 'text-[#00C805]' : 'text-white'}`}>
              {micro.rsi.toFixed(0)}
            </span>
          </div>
          <div>
            <span className="text-[11px] text-neutral-500 block">Momentum</span>
            <span className={`text-[14px] font-semibold tabular-nums ${micro.momentum_5m >= 0 ? 'text-[#00C805]' : 'text-[#FF3B30]'}`}>
              {micro.momentum_5m >= 0 ? '+' : ''}{(micro.momentum_5m * 100).toFixed(2)}%
            </span>
          </div>
          <div>
            <span className="text-[11px] text-neutral-500 block">Volatility</span>
            <span className="text-[14px] font-semibold text-white tabular-nums">{(micro.volatility * 100).toFixed(3)}%</span>
          </div>
        </div>
      )}
    </div>
  )
}

function WindowRow({ window: w }: { window: BtcWindow }) {
  return (
    <div className="yf-market-row">
      <div className="flex items-center gap-2.5">
        <span className={`w-2 h-2 rounded-full ${w.is_active ? 'bg-amber-500' : 'bg-blue-500'}`} />
        <div>
          <div className="text-[13px] font-semibold text-white">
            {w.is_active && <span className="text-amber-400 mr-1">LIVE</span>}
            {w.is_upcoming && <span className="text-blue-400 mr-1">NEXT</span>}
            Window
          </div>
        </div>
      </div>
      <div className="flex items-center gap-4">
        <span className="text-[13px] tabular-nums">
          <span className="text-[#00C805]">{(w.up_price * 100).toFixed(0)}c</span>
          <span className="text-neutral-600 mx-1">/</span>
          <span className="text-[#FF3B30]">{(w.down_price * 100).toFixed(0)}c</span>
        </span>
        <span className="text-[12px] tabular-nums text-neutral-500">{formatCountdown(w.time_until_end)}</span>
      </div>
    </div>
  )
}

function SignalRow({ signal, onTrade, isSimulating }: { signal: Signal; onTrade: (ticker: string) => void; isSimulating: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const isUp = signal.direction === 'up'

  return (
    <div className={signal.actionable ? '' : 'opacity-40'}>
      <div
        className="yf-trending-row cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex-1 min-w-0">
          <div className="text-[14px] font-bold text-white truncate">
            {(signal.event_slug || signal.market_ticker).replace('btc-updown-5m-', '')}
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className={`text-[11px] font-bold uppercase px-2 py-0.5 rounded ${
            isUp ? 'text-[#00C805] bg-[#00C805]/10' : 'text-[#FF3B30] bg-[#FF3B30]/10'
          }`}>
            {signal.direction}
          </span>
          <div className="text-right w-14">
            <div className={`text-[14px] font-semibold tabular-nums ${
              signal.edge > 0.02 ? 'text-[#00C805]' : 'text-neutral-400'
            }`}>
              {(Math.abs(signal.edge) * 100).toFixed(1)}%
            </div>
          </div>
          {signal.actionable && (
            <button
              onClick={(e) => { e.stopPropagation(); onTrade(signal.market_ticker) }}
              disabled={isSimulating}
              className="px-3 py-1.5 text-[11px] font-bold bg-[#7B61FF] text-white rounded-full hover:bg-[#6B51EF] disabled:opacity-50 transition-colors"
            >
              Trade
            </button>
          )}
          {expanded ? <ChevronUp className="w-4 h-4 text-neutral-500" /> : <ChevronDown className="w-4 h-4 text-neutral-500" />}
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
            <div className="px-4 pb-3">
              <div className="yf-reasoning">{signal.reasoning}</div>
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
    <div className="overflow-y-auto h-full pb-4">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3">
        <div>
          <h2 className="text-[18px] font-bold text-white">BTC 5-Min Markets</h2>
          <p className="text-[12px] text-neutral-500">{actionable.length} actionable / {signals.length} total signals</p>
        </div>
        <button
          onClick={onToggle}
          className={`yf-toggle ${enabled ? 'active' : ''}`}
        >
          {enabled ? 'ON' : 'OFF'}
        </button>
      </div>

      <div className="px-4 space-y-3">
        {/* Price Card */}
        <PriceCard btcPrice={btcPrice} micro={microstructure} />

        {/* Windows */}
        {windows.length > 0 && (
          <div>
            <h3 className="text-xs font-bold text-neutral-400 uppercase tracking-wider mb-2 px-1">Active Windows</h3>
            <div className="yf-card">
              {windows.slice(0, 6).map(w => (
                <WindowRow key={w.slug} window={w} />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Signals */}
      <div className="mx-4 mt-3">
        <h3 className="text-xs font-bold text-neutral-400 uppercase tracking-wider mb-2 px-1">Signals</h3>
        <div className="yf-card">
          {sorted.length > 0 ? (
            sorted.map(s => (
              <SignalRow key={s.market_ticker} signal={s} onTrade={onSimulateTrade} isSimulating={isSimulating} />
            ))
          ) : (
            <div className="px-4 py-8 text-center text-neutral-500 text-sm">
              No BTC signals found
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
