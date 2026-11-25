import type { WeatherForecast, WeatherSignal, WeatherMarket } from '../types'
import { platformStyles } from '../utils'

interface Props {
  forecasts: WeatherForecast[]
  signals: WeatherSignal[]
  markets: WeatherMarket[]
}

function YesNoBar({ yesPrice }: { yesPrice: number }) {
  const yesPct = Math.max(0, Math.min(100, yesPrice * 100))
  return (
    <div className="flex items-center gap-1 w-full">
      <span className="text-[9px] tabular-nums text-green-500 w-7 text-right">{yesPct.toFixed(0)}%</span>
      <div className="flex-1 flex h-[10px] rounded-sm overflow-hidden bg-neutral-800">
        <div
          className="bg-green-500 transition-all"
          style={{ width: `${yesPct}%` }}
        />
        <div
          className="bg-red-500 transition-all"
          style={{ width: `${100 - yesPct}%` }}
        />
      </div>
      <span className="text-[9px] tabular-nums text-red-400 w-7">{(yesPrice * 100).toFixed(0)}</span>
    </div>
  )
}

function MarketRow({ market, signal }: { market: WeatherMarket; signal?: WeatherSignal }) {
  const isActionable = signal?.actionable ?? false
  const predMean = market.pred_mean
  const predStd = market.pred_std
  const distLabel = predMean !== null && predMean !== undefined
    ? `μ${predMean.toFixed(0)}°Fσ±${predStd?.toFixed(0) ?? '?'}`
    : '—'

  return (
    <div className={`flex items-center gap-2 px-2 py-1.5 ${
      isActionable ? 'border-l-2 border-l-green-500 bg-green-500/5' : 'border-l-2 border-l-transparent'
    }`}>
      {/* City */}
      <div className="w-14 shrink-0">
        <div className="text-[9px] font-semibold text-neutral-200 truncate" title={market.city_name}>{market.city_name}</div>
        <div className="text-[8px] text-neutral-600 truncate" title={market.target_date}>{market.target_date.slice(5)}</div>
      </div>

      {/* Threshold & direction */}
      <div className="shrink-0 w-[72px]">
        <div className="text-[9px] tabular-nums text-amber-400">
          {market.metric === 'high' ? 'H' : 'L'}{' '}
          {market.direction === 'above' ? '>' : '<'}{Math.round(market.threshold_f)}°F
        </div>
        <div className="flex items-center gap-1 mt-0.5">
          <span className={`platform-badge px-0.5 ${
            platformStyles[market.platform.toLowerCase()]?.badge || 'bg-neutral-800 text-neutral-400 border-neutral-700 border'
          }`}>
            {platformStyles[market.platform.toLowerCase()]?.icon || '?'}
          </span>
          <span className="text-[8px] text-neutral-600">{distLabel}</span>
        </div>
      </div>

      {/* YES / NO bar */}
      <div className="flex-1 min-w-0">
        <YesNoBar yesPrice={market.yes_price} />
      </div>

      {/* Edge */}
      {signal && (
        <div className="shrink-0 w-12 text-right">
          <div className={`text-[9px] tabular-nums ${signal.edge > 0 ? 'text-green-500' : signal.edge < 0 ? 'text-red-500' : 'text-neutral-500'}`}>
            {signal.edge > 0 ? '+' : ''}{(signal.edge * 100).toFixed(1)}%
          </div>
          {isActionable && (
            <div className="text-[8px] text-green-400 font-bold uppercase leading-none">ALERT</div>
          )}
        </div>
      )}
    </div>
  )
}

export function WeatherPanel({ forecasts, signals, markets }: Props) {
  const signalsByCity = new Map<string, WeatherSignal[]>()
  signals.forEach(s => {
    const existing = signalsByCity.get(s.city_key) || []
    existing.push(s)
    signalsByCity.set(s.city_key, existing)
  })

  // Group markets by city+date for compact display
  const marketGroups = new Map<string, WeatherMarket[]>()
  markets.forEach(m => {
    const key = `${m.city_key}_${m.target_date}`
    const group = marketGroups.get(key) || []
    group.push(m)
    marketGroups.set(key, group)
  })

  const hasMarkets = markets.length > 0
  const hasForecasts = forecasts.length > 0

  if (!hasMarkets && !hasForecasts) {
    return (
      <div className="h-full flex items-center justify-center text-neutral-600 text-[10px]">
        No weather data
      </div>
    )
  }

  return (
    <div className="space-y-1 overflow-y-auto max-h-full pb-1">
      {/* Ensemble forecasts row */}
      {hasForecasts && (
        <div className="px-2 pt-1 pb-0.5">
          <div className="text-[8px] text-neutral-600 uppercase tracking-wider mb-1">Ensemble Forecast</div>
          {forecasts.map(f => {
            const citySignals = signalsByCity.get(f.city_key) || []
            const actionable = citySignals.filter(s => s.actionable)

            return (
              <div
                key={f.city_key}
                className={`flex items-center gap-2 py-1 border-b border-neutral-800/50 last:border-0 ${
                  actionable.length > 0 ? 'border-l-2 border-l-green-500 pl-1.5' : ''
                }`}
              >
                <div className="w-14 shrink-0">
                  <div className="text-[9px] font-medium text-neutral-300 truncate">{f.city_name}</div>
                </div>
                <div className="flex-1 flex items-center gap-3 text-[9px] tabular-nums">
                  <span className="text-neutral-300">
                    H:{f.mean_high.toFixed(0)}
                    <span className="text-neutral-600 ml-0.5">±{f.std_high.toFixed(0)}</span>
                  </span>
                  <span className="text-neutral-700">|</span>
                  <span className="text-neutral-300">
                    L:{f.mean_low.toFixed(0)}
                    <span className="text-neutral-600 ml-0.5">±{f.std_low.toFixed(0)}</span>
                  </span>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <div className="edge-bar w-10">
                    <div
                      className="edge-fill"
                      style={{
                        width: `${Math.max(0, Math.min(100, f.ensemble_agreement * 100))}%`,
                        backgroundColor: f.ensemble_agreement > 0.7 ? '#22c55e' : f.ensemble_agreement > 0.5 ? '#d97706' : '#dc2626',
                      }}
                    />
                  </div>
                  <span className={`text-[8px] tabular-nums ${f.ensemble_agreement > 0.7 ? 'text-green-500' : 'text-amber-500'}`}>
                    {(f.ensemble_agreement * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Active markets */}
      {hasMarkets && (
        <div className="px-2 pt-1.5 pb-0.5">
          <div className="text-[8px] text-neutral-600 uppercase tracking-wider mb-1">Markets ({markets.length})</div>
        </div>
      )}
      {Array.from(marketGroups.entries()).map(([key, group]) => {
        const [cityKey, targetDate] = key.split('_')
        const citySignals = signalsByCity.get(cityKey) || []
        const first = group[0]

        return (
          <div key={key} className="mb-0.5">
            {/* City header */}
            <div className="flex items-center gap-2 px-2 py-1 border-b border-neutral-800">
              <span className="text-[9px] font-semibold text-neutral-400">{first.city_name}</span>
              <span className="text-[8px] text-neutral-600">{targetDate}</span>
              <span className="text-[8px] text-neutral-700">· {group.length} market{group.length > 1 ? 's' : ''}</span>
              {group.some(m => m.pred_mean !== null && m.pred_mean !== undefined) && (
                <span className="text-[8px] text-cyan-600">
                  μ{group[0].pred_mean?.toFixed(0)}°F ±{group[0].pred_std?.toFixed(0) ?? '?'}
                </span>
              )}
            </div>
            {/* Market rows */}
            {group.map(m => {
              const signal = citySignals.find(s => s.market_id === m.market_id)
              return (
                <MarketRow key={m.market_id} market={m} signal={signal} />
              )
            })}
          </div>
        )
      })}
    </div>
  )
}
