import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { CloudSun, ChevronDown, ChevronUp, Thermometer } from 'lucide-react'
import type { WeatherSignal, WeatherForecast } from '../types'

interface Props {
  signals: WeatherSignal[]
  forecasts: WeatherForecast[]
  enabled: boolean
  onToggle: () => void
}

function ForecastCard({ forecast, signals }: { forecast: WeatherForecast; signals: WeatherSignal[] }) {
  const citySignals = signals.filter(s => s.city_key === forecast.city_key)
  const actionable = citySignals.filter(s => s.actionable)
  const bestEdge = actionable.length > 0 ? Math.max(...actionable.map(s => Math.abs(s.edge))) : 0

  return (
    <div className={`bg-[#111] border rounded-lg p-3 ${actionable.length > 0 ? 'border-green-500/30' : 'border-neutral-800'}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Thermometer className="w-3.5 h-3.5 text-cyan-400" />
          <span className="text-sm font-medium text-neutral-200">{forecast.city_name}</span>
        </div>
        {actionable.length > 0 && (
          <span className="px-2 py-0.5 text-[9px] font-bold bg-green-500/15 text-green-400 rounded-full border border-green-500/20">
            {actionable.length} signal{actionable.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2 text-[11px]">
        <div>
          <span className="text-neutral-600 block">High</span>
          <span className="text-neutral-200 font-mono">{forecast.mean_high.toFixed(0)}F <span className="text-neutral-500">+/-{forecast.std_high.toFixed(1)}</span></span>
        </div>
        <div>
          <span className="text-neutral-600 block">Agreement</span>
          <span className={`font-mono ${forecast.ensemble_agreement > 0.7 ? 'text-green-400' : 'text-amber-400'}`}>
            {(forecast.ensemble_agreement * 100).toFixed(0)}%
          </span>
        </div>
        <div>
          <span className="text-neutral-600 block">Best Edge</span>
          <span className={`font-mono ${bestEdge > 0.08 ? 'text-green-400' : 'text-neutral-500'}`}>
            {bestEdge > 0 ? `${(bestEdge * 100).toFixed(1)}%` : '-'}
          </span>
        </div>
      </div>
    </div>
  )
}

function SignalRow({ signal }: { signal: WeatherSignal }) {
  const [expanded, setExpanded] = useState(false)
  const isUp = signal.direction === 'above' || signal.direction === 'yes'

  return (
    <div className={`border-b border-neutral-800/50 ${signal.actionable ? '' : 'opacity-40'}`}>
      <div
        className="flex items-center py-3 px-3 cursor-pointer hover:bg-neutral-800/20 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex-1 min-w-0">
          <div className="text-sm text-neutral-200 truncate">
            {signal.city_name}: {signal.metric} {signal.direction} {signal.threshold_f.toFixed(0)}F
          </div>
          <div className="text-[10px] text-neutral-600 mt-0.5">{signal.target_date}</div>
        </div>
        <div className="flex items-center gap-4 shrink-0">
          <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${
            isUp ? 'text-green-400 bg-green-500/10' : 'text-red-400 bg-red-500/10'
          }`}>
            {signal.direction}
          </span>
          <span className={`text-sm font-mono font-semibold w-14 text-right ${
            signal.edge > 0.08 ? 'text-green-400' : signal.edge > 0 ? 'text-neutral-400' : 'text-red-400'
          }`}>
            {(Math.abs(signal.edge) * 100).toFixed(1)}%
          </span>
          <span className="text-blue-400 font-mono text-xs w-12 text-right">
            {signal.suggested_size > 0 ? `$${signal.suggested_size.toFixed(0)}` : '-'}
          </span>
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
            <div className="px-3 pb-3 space-y-2">
              <div className="grid grid-cols-2 gap-3 text-[11px]">
                <div>
                  <span className="text-neutral-600">Model probability</span>
                  <span className="text-neutral-200 font-mono block">{(signal.model_probability * 100).toFixed(0)}%</span>
                </div>
                <div>
                  <span className="text-neutral-600">Market price</span>
                  <span className="text-neutral-200 font-mono block">{(signal.market_probability * 100).toFixed(0)}%</span>
                </div>
                <div>
                  <span className="text-neutral-600">Ensemble</span>
                  <span className="text-neutral-200 font-mono block">{signal.ensemble_mean.toFixed(1)}F +/-{signal.ensemble_std.toFixed(1)} ({signal.ensemble_members}m)</span>
                </div>
                <div>
                  <span className="text-neutral-600">Confidence</span>
                  <span className="text-neutral-200 font-mono block">{(signal.confidence * 100).toFixed(0)}%</span>
                </div>
              </div>
              <div className="text-[10px] text-neutral-500 font-mono bg-neutral-900 p-2 rounded leading-relaxed">
                {signal.reasoning}
              </div>
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
    <div className="overflow-y-auto max-h-[calc(100vh-120px)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-800">
        <div className="flex items-center gap-2">
          <CloudSun className="w-4 h-4 text-cyan-400" />
          <span className="text-sm font-medium">Weather Markets</span>
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

      {/* Forecast Cards */}
      {forecasts.length > 0 && (
        <div className="p-4 space-y-2">
          <h3 className="text-[10px] text-neutral-500 uppercase tracking-wider font-medium">Forecasts</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {forecasts.map(f => (
              <ForecastCard key={f.city_key} forecast={f} signals={signals} />
            ))}
          </div>
        </div>
      )}

      {/* Signals List */}
      <div className="px-4 pt-2 pb-1">
        <h3 className="text-[10px] text-neutral-500 uppercase tracking-wider font-medium">Signals</h3>
      </div>
      {sorted.length > 0 ? (
        <div>
          {sorted.map(s => (
            <SignalRow key={s.market_id} signal={s} />
          ))}
        </div>
      ) : (
        <div className="flex items-center justify-center py-12 text-neutral-600 text-xs">
          No weather signals found
        </div>
      )}
    </div>
  )
}
