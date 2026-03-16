import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronUp } from 'lucide-react'
import type { WeatherSignal, WeatherForecast } from '../types'

interface Props {
  signals: WeatherSignal[]
  forecasts: WeatherForecast[]
  enabled: boolean
  onToggle: () => void
}

function ForecastRow({ forecast, signals }: { forecast: WeatherForecast; signals: WeatherSignal[] }) {
  const citySignals = signals.filter(s => s.city_key === forecast.city_key)
  const actionable = citySignals.filter(s => s.actionable)
  const bestEdge = actionable.length > 0 ? Math.max(...actionable.map(s => Math.abs(s.edge))) : 0

  return (
    <div className="yf-market-row">
      <div className="flex items-center gap-2.5 flex-1 min-w-0">
        <span className={`w-2 h-2 rounded-full ${actionable.length > 0 ? 'bg-[#00C805]' : 'bg-neutral-600'}`} />
        <div className="min-w-0">
          <div className="text-[14px] font-semibold text-white truncate">{forecast.city_name}</div>
          <div className="text-[11px] text-neutral-500">
            {forecast.mean_high.toFixed(0)}F hi \u00B7 {forecast.mean_low.toFixed(0)}F lo \u00B7 {(forecast.ensemble_agreement * 100).toFixed(0)}% agree
          </div>
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="text-[14px] font-medium text-white tabular-nums">{forecast.mean_high.toFixed(1)}F</div>
        {bestEdge > 0 ? (
          <span className="text-[12px] font-medium text-[#00C805] tabular-nums">+{(bestEdge * 100).toFixed(1)}%</span>
        ) : (
          <span className="text-[12px] text-neutral-600">-</span>
        )}
      </div>
    </div>
  )
}

function SignalRow({ signal }: { signal: WeatherSignal }) {
  const [expanded, setExpanded] = useState(false)
  const isUp = signal.direction === 'above' || signal.direction === 'yes'

  return (
    <div className={signal.actionable ? '' : 'opacity-40'}>
      <div
        className="yf-trending-row cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex-1 min-w-0">
          <div className="text-[14px] font-bold text-white truncate">
            {signal.city_name}: {signal.threshold_f.toFixed(0)}F
          </div>
          <div className="text-[12px] text-neutral-500 truncate">
            {signal.metric} {signal.direction} \u00B7 {signal.target_date}
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <div className="text-right">
            <div className="text-[14px] font-semibold tabular-nums text-white">
              {(Math.abs(signal.edge) * 100).toFixed(1)}%
            </div>
            <div className={`text-[12px] font-medium ${isUp ? 'text-[#00C805]' : 'text-[#FF3B30]'}`}>
              {signal.suggested_size > 0 ? `$${signal.suggested_size.toFixed(0)}` : '-'}
            </div>
          </div>
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
            <div className="px-4 pb-3 space-y-2">
              <div className="grid grid-cols-2 gap-3">
                <div className="yf-detail-item">
                  <span className="yf-detail-label">Model prob</span>
                  <span className="yf-detail-value">{(signal.model_probability * 100).toFixed(0)}%</span>
                </div>
                <div className="yf-detail-item">
                  <span className="yf-detail-label">Market price</span>
                  <span className="yf-detail-value">{(signal.market_probability * 100).toFixed(0)}%</span>
                </div>
                <div className="yf-detail-item">
                  <span className="yf-detail-label">Ensemble</span>
                  <span className="yf-detail-value">{signal.ensemble_mean.toFixed(1)}F +/-{signal.ensemble_std.toFixed(1)}</span>
                </div>
                <div className="yf-detail-item">
                  <span className="yf-detail-label">Confidence</span>
                  <span className="yf-detail-value">{(signal.confidence * 100).toFixed(0)}%</span>
                </div>
              </div>
              <div className="yf-reasoning">{signal.reasoning}</div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function WeatherTab({ signals, forecasts, enabled, onToggle }: Props) {
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
          <h2 className="text-[18px] font-bold text-white">Weather Markets</h2>
          <p className="text-[12px] text-neutral-500">{actionable.length} actionable / {signals.length} total signals</p>
        </div>
        <button
          onClick={onToggle}
          className={`yf-toggle ${enabled ? 'active' : ''}`}
        >
          {enabled ? 'ON' : 'OFF'}
        </button>
      </div>

      {/* Forecasts */}
      {forecasts.length > 0 && (
        <div className="mx-4 mb-3">
          <h3 className="text-xs font-bold text-neutral-400 uppercase tracking-wider mb-2 px-1">Forecasts</h3>
          <div className="yf-card">
            {forecasts.map(f => (
              <ForecastRow key={f.city_key} forecast={f} signals={signals} />
            ))}
          </div>
        </div>
      )}

      {/* Signals */}
      <div className="mx-4">
        <h3 className="text-xs font-bold text-neutral-400 uppercase tracking-wider mb-2 px-1">Signals</h3>
        <div className="yf-card">
          {sorted.length > 0 ? (
            sorted.map(s => <SignalRow key={s.market_id} signal={s} />)
          ) : (
            <div className="px-4 py-8 text-center text-neutral-500 text-sm">
              No weather signals found
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
