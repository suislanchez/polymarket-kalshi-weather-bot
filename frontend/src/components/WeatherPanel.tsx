import type { WeatherForecast, WeatherSignal } from '../types'
import { platformStyles } from '../utils'

interface Props {
  forecasts: WeatherForecast[]
  signals: WeatherSignal[]
}

function AgreementBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value * 100))
  const color = value > 0.7 ? '#22c55e' : value > 0.5 ? '#d97706' : '#dc2626'
  return (
    <div className="edge-bar w-12">
      <div className="edge-fill" style={{ width: `${pct}%`, backgroundColor: color }} />
    </div>
  )
}

function formatLatency(seconds?: number) {
  if (seconds === undefined || seconds === null) return '—'
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  return `${(seconds / 60).toFixed(1)}m`
}

export function WeatherPanel({ forecasts, signals }: Props) {
  if (forecasts.length === 0 && signals.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-neutral-600 text-[10px]">
        No weather data
      </div>
    )
  }

  const signalsByCity = new Map<string, WeatherSignal[]>()
  signals.forEach(s => {
    const existing = signalsByCity.get(s.city_key) || []
    existing.push(s)
    signalsByCity.set(s.city_key, existing)
  })

  return (
    <div className="space-y-1 overflow-y-auto max-h-full">
      {forecasts.map(f => {
        const citySignals = signalsByCity.get(f.city_key) || []
        const actionable = citySignals.filter(s => s.actionable)
        const bestEdge = citySignals.length > 0
          ? citySignals.reduce((a, b) => Math.abs(a.edge) > Math.abs(b.edge) ? a : b)
          : null

        return (
          <div
            key={f.city_key}
            className={`flex items-center gap-2 px-2 py-1.5 ${
              actionable.length > 0 ? 'border-l-2 border-l-green-500 bg-green-500/5' : 'border-l-2 border-l-transparent'
            }`}
          >
            <div className="w-12 shrink-0">
              <div className="text-[10px] font-medium text-neutral-300">{f.city_name}</div>
            </div>
            <div className="flex-1 flex items-center gap-3 text-[10px] tabular-nums">
              <span className="text-neutral-300">
                {f.mean_high.toFixed(0)}F
                <span className="text-neutral-600 ml-0.5">+/-{f.std_high.toFixed(0)}</span>
              </span>
              <AgreementBar value={f.ensemble_agreement} />
              <span className={`${f.ensemble_agreement > 0.7 ? 'text-green-500' : 'text-amber-500'}`}>
                {(f.ensemble_agreement * 100).toFixed(0)}%
              </span>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              {bestEdge && (
                <div className="flex flex-col items-end gap-0.5">
                  <span className={`text-[10px] tabular-nums ${bestEdge.edge > 0 ? 'text-green-500' : 'text-red-500'}`}>
                    {bestEdge.edge > 0 ? '+' : ''}{(bestEdge.edge * 100).toFixed(1)}%
                  </span>
                  {(bestEdge.signal_source || bestEdge.station_id || bestEdge.observation_latency_seconds !== undefined) && (
                    <span className="text-[8px] text-neutral-500 tabular-nums" title={bestEdge.metar_note || bestEdge.source_url || undefined}>
                      {bestEdge.signal_source || 'METAR'} · {bestEdge.station_id || 'station?'} · obs {formatLatency(bestEdge.observation_latency_seconds)}
                    </span>
                  )}
                  {(bestEdge.fusion_lock_state || (bestEdge.fusion_conflicts && bestEdge.fusion_conflicts.length > 0)) && (
                    <span className="text-[8px] text-neutral-500 tabular-nums" title={(bestEdge.fusion_conflicts || []).join('; ') || bestEdge.fusion_skip_reason || undefined}>
                      fusion {bestEdge.fusion_lock_state || 'unknown'} · authority {bestEdge.fusion_authority_source || 'missing'}
                    </span>
                  )}
                </div>
              )}
              {citySignals.length > 0 && citySignals[0].platform && (
                <span className={`platform-badge ${
                  platformStyles[citySignals[0].platform.toLowerCase()]?.badge || 'bg-neutral-800 text-neutral-400 border-neutral-700'
                }`}>
                  {platformStyles[citySignals[0].platform.toLowerCase()]?.icon || '?'}
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
