import { useState, useEffect, Suspense, lazy } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { fetchDashboard, fetchPolymarketWeatherSourceStates, runScan, simulateTrade, startBot, stopBot } from './api'
import { StatsCards } from './components/StatsCards'
import { SignalsTable } from './components/SignalsTable'
import { TradesTable } from './components/TradesTable'
import { EquityChart } from './components/EquityChart'
import { Terminal } from './components/Terminal'
import { MicrostructurePanel } from './components/MicrostructurePanel'
import { CalibrationPanel } from './components/CalibrationPanel'
import { WeatherPanel } from './components/WeatherPanel'
import { EdgeDistribution } from './components/EdgeDistribution'
import { formatCountdown } from './utils'
import type { BtcCalibrationRow, BtcCalibrationSummary, BtcWindow, OpenPositionRiskRow, OpenPositionRiskSummary, PolymarketWeatherSourceState, PolymarketWeatherSourceStateSummary, RottenTomatoesSourceState, SignalReviewQueue, WeatherBotCalibrationRow, WeatherCalibrationRow, WeatherCalibrationSummary, WeatherSignalReviewCandidate } from './types'

const GlobeView = lazy(() => import('./components/GlobeView').then(m => ({ default: m.GlobeView })))

function LiveClock() {
  const [time, setTime] = useState(new Date())
  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])
  return (
    <span className="text-xs tabular-nums text-neutral-400">
      {time.toLocaleTimeString('en-US', { hour12: false })}
    </span>
  )
}

function WindowPill({ window: w }: { window: BtcWindow }) {
  const [countdown, setCountdown] = useState(w.time_until_end)
  const upText = w.up_bid != null && w.up_ask != null
    ? `${(w.up_bid * 100).toFixed(0)}-${(w.up_ask * 100).toFixed(0)}c`
    : `${(w.up_price * 100).toFixed(0)}c`
  const downText = w.down_bid != null && w.down_ask != null
    ? `${(w.down_bid * 100).toFixed(0)}-${(w.down_ask * 100).toFixed(0)}c`
    : `${(w.down_price * 100).toFixed(0)}c`
  const depthText = w.up_ask_size != null || w.down_ask_size != null
    ? `ask ${w.up_ask_size?.toFixed(0) ?? '—'}/${w.down_ask_size?.toFixed(0) ?? '—'}`
    : w.settlement_source

  useEffect(() => {
    const interval = setInterval(() => {
      setCountdown(prev => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(interval)
  }, [w.time_until_end])

  return (
    <div className={`flex items-center gap-2 px-2 py-1 border shrink-0 ${w.is_active ? 'border-amber-500/30 bg-amber-500/5' : 'border-neutral-800 bg-neutral-900/50'}`}>
      {w.is_active && <span className="text-[9px] font-bold text-amber-400 uppercase">Live</span>}
      {w.is_upcoming && <span className="text-[9px] font-medium text-blue-400 uppercase">Next</span>}
      <span className="text-[10px] tabular-nums text-green-400">UP {upText}</span>
      <span className="text-neutral-600 text-[10px]">/</span>
      <span className="text-[10px] tabular-nums text-red-400">DN {downText}</span>
      <span className="text-[9px] tabular-nums text-neutral-600">{depthText}</span>
      <span className="text-[10px] tabular-nums text-neutral-500">{formatCountdown(countdown)}</span>
    </div>
  )
}

function formatSignedDelta(value: number, suffix = '') {
  return `${value >= 0 ? '+' : ''}${value}${suffix}`
}

function RefreshBar({ interval }: { interval: number }) {
  const [progress, setProgress] = useState(100)

  useEffect(() => {
    setProgress(100)
    const step = 100 / (interval / 1000)
    const timer = setInterval(() => {
      setProgress(p => Math.max(0, p - step))
    }, 1000)
    return () => clearInterval(timer)
  }, [interval])

  return (
    <div className="refresh-bar w-16">
      <div className="refresh-fill" style={{ width: `${progress}%` }} />
    </div>
  )
}

function RottenTomatoesSourcePanel({ states }: { states: RottenTomatoesSourceState[] }) {
  if (states.length === 0) {
    return <div className="text-[10px] text-neutral-600 p-2">No direct RT source snapshots</div>
  }

  return (
    <div className="space-y-1 p-1">
      {states.slice(0, 5).map((state, idx) => (
        <div key={`${state.event_slug ?? state.title ?? 'rt'}-${idx}`} className="border border-neutral-800 bg-neutral-950/60 p-1.5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-[10px] font-medium text-neutral-300">{state.title ?? state.event_slug ?? 'Untitled RT source'}</div>
              <div className="mt-0.5 text-[9px] text-neutral-600 truncate">{state.source_method ?? 'unknown source method'}</div>
            </div>
            <span className="shrink-0 rounded-sm border border-purple-500/20 bg-purple-500/10 px-1 py-0.5 text-[8px] font-bold uppercase text-purple-300">RT</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-[9px] tabular-nums">
            <span className={state.direct_source_status === 'fresh' ? 'text-green-400' : 'text-amber-400'}>{state.direct_source_status}</span>
            <span className="text-neutral-500">score {state.tomatometer_score ?? '—'}</span>
            <span className="text-neutral-500">reviews {state.review_count ?? '—'}</span>
            {(state.score_delta != null || state.review_count_delta != null) && (
              <span className="text-purple-300">
                Δ {state.score_delta != null ? formatSignedDelta(state.score_delta, 'pt') : '—'}
                {state.review_count_delta != null ? ` / ${formatSignedDelta(state.review_count_delta)} reviews` : ''}
              </span>
            )}
          </div>
          <div className="mt-1 text-[9px] text-neutral-600 line-clamp-2">
            {state.timing_risk_label ?? state.no_trade_reasons?.[0] ?? state.no_trade_reason}
          </div>
        </div>
      ))}
    </div>
  )
}

type SourceStateFilter = 'all' | 'warn' | 'part' | 'hko' | 'obs' | 'src'
type SourceStateCategory = Exclude<SourceStateFilter, 'all'>
type SourceStateMarketStateFilter = 'all' | 'open' | 'closed'

const sourceStateFilterOptions: { filter: SourceStateFilter; label: string }[] = [
  { filter: 'all', label: 'ALL' },
  { filter: 'warn', label: 'WARN' },
  { filter: 'part', label: 'PART' },
  { filter: 'hko', label: 'HKO' },
  { filter: 'obs', label: 'OBS' },
  { filter: 'src', label: 'SRC' },
]

const sourceStateMarketStateFilterOptions: { filter: SourceStateMarketStateFilter; label: string }[] = [
  { filter: 'all', label: 'ALL' },
  { filter: 'open', label: 'OPEN' },
  { filter: 'closed', label: 'CLOSED' },
]

const sourceStateFilterValues = sourceStateFilterOptions.map(option => option.filter)
const sourceStateMarketStateFilterValues = sourceStateMarketStateFilterOptions.map(option => option.filter)

function readUrlSearchParam(name: string): string {
  if (typeof window === 'undefined') {
    return ''
  }
  return new URLSearchParams(window.location.search).get(name)?.trim().toLowerCase() ?? ''
}

function readSourceStateFilterFromUrl(): SourceStateFilter {
  const value = readUrlSearchParam('polyWxCategory') as SourceStateFilter
  return sourceStateFilterValues.includes(value) ? value : 'all'
}

function readSourceStateMarketStateFilterFromUrl(): SourceStateMarketStateFilter {
  const value = readUrlSearchParam('polyWxMarketState') as SourceStateMarketStateFilter
  return sourceStateMarketStateFilterValues.includes(value) ? value : 'all'
}

function syncSourceStateUrlFilters(category: SourceStateFilter, marketState: SourceStateMarketStateFilter) {
  if (typeof window === 'undefined') {
    return
  }

  const url = new URL(window.location.href)
  if (category === 'all') {
    url.searchParams.delete('polyWxCategory')
  } else {
    url.searchParams.set('polyWxCategory', category)
  }
  if (marketState === 'all') {
    url.searchParams.delete('polyWxMarketState')
  } else {
    url.searchParams.set('polyWxMarketState', marketState)
  }

  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`
  const nextPath = `${url.pathname}${url.search}${url.hash}`
  if (nextPath !== currentPath) {
    window.history.replaceState(window.history.state, '', nextPath)
  }
}

function sourceStateCategory(row: PolymarketWeatherSourceState): SourceStateCategory {
  const status = (row.source_capture_status ?? '').toLowerCase()
  const anomaly = (row.station_anomaly_status ?? '').toLowerCase()
  const source = (row.settlement_source ?? '').toLowerCase()

  if (anomaly.startsWith('warning')) {
    return 'warn'
  }
  if (status.includes('partial')) {
    return 'part'
  }
  if (source === 'hko' && status.includes('missing_target')) {
    return 'hko'
  }
  if (row.source_observed_value != null) {
    return 'obs'
  }
  return 'src'
}

function sourceStateBadge(row: PolymarketWeatherSourceState): { label: string; className: string } {
  const category = sourceStateCategory(row)

  if (category === 'warn') {
    return { label: 'WARN', className: 'border-red-500/20 bg-red-500/10 text-red-300' }
  }
  if (category === 'part') {
    return { label: 'PART', className: 'border-amber-500/20 bg-amber-500/10 text-amber-300' }
  }
  if (category === 'hko') {
    return { label: 'HKO', className: 'border-amber-500/20 bg-amber-500/10 text-amber-300' }
  }
  if (category === 'obs') {
    return { label: 'OBS', className: 'border-green-500/20 bg-green-500/10 text-green-300' }
  }
  return { label: 'SRC', className: 'border-violet-500/20 bg-violet-500/10 text-violet-300' }
}

function WeatherCalibrationAuditPanel({
  summary,
  botSummary,
  rows,
  botRows,
  reviewCandidates,
  polymarketSourceStates,
  polymarketSourceSummary,
}: {
  summary: WeatherCalibrationSummary | null
  botSummary: WeatherCalibrationSummary | null
  rows: WeatherCalibrationRow[]
  botRows: WeatherBotCalibrationRow[]
  reviewCandidates: WeatherSignalReviewCandidate[]
  polymarketSourceStates: PolymarketWeatherSourceState[]
  polymarketSourceSummary: PolymarketWeatherSourceStateSummary | null
}) {
  const [sourceStateFilter, setSourceStateFilter] = useState<SourceStateFilter>(() => readSourceStateFilterFromUrl())
  const [sourceStateMarketStateFilter, setSourceStateMarketStateFilter] = useState<SourceStateMarketStateFilter>(() => readSourceStateMarketStateFilterFromUrl())
  useEffect(() => {
    syncSourceStateUrlFilters(sourceStateFilter, sourceStateMarketStateFilter)
  }, [sourceStateFilter, sourceStateMarketStateFilter])
  const sourceStateDrilldownQuery = useQuery({
    queryKey: ['polymarket-weather-source-states', sourceStateFilter, sourceStateMarketStateFilter],
    queryFn: () => fetchPolymarketWeatherSourceStates({
      category: sourceStateFilter,
      marketState: sourceStateMarketStateFilter,
      limit: 25,
    }),
    enabled: polymarketSourceStates.length > 0 || polymarketSourceSummary != null,
    refetchInterval: 30000,
  })
  const sourceStateFilterCountsByMarketState = polymarketSourceStates.reduce<Record<SourceStateMarketStateFilter, Record<SourceStateFilter, number>>>(
    (counts, row) => {
      const category = sourceStateCategory(row)
      const marketState = row.closed ? 'closed' : 'open'
      counts.all.all += 1
      counts.all[category] += 1
      counts[marketState].all += 1
      counts[marketState][category] += 1
      return counts
    },
    {
      all: { all: 0, warn: 0, part: 0, hko: 0, obs: 0, src: 0 },
      open: { all: 0, warn: 0, part: 0, hko: 0, obs: 0, src: 0 },
      closed: { all: 0, warn: 0, part: 0, hko: 0, obs: 0, src: 0 },
    }
  )
  const sourceStateFilterCounts = sourceStateFilterCountsByMarketState.all
  const sourceStateBatchCategoryCounts: Record<SourceStateFilter, number> = {
    all: polymarketSourceSummary?.source_state_rows ?? sourceStateFilterCounts.all,
    warn: polymarketSourceSummary?.category_warning_rows ?? sourceStateFilterCounts.warn,
    part: polymarketSourceSummary?.category_partial_rows ?? sourceStateFilterCounts.part,
    hko: polymarketSourceSummary?.category_hko_rows ?? sourceStateFilterCounts.hko,
    obs: polymarketSourceSummary?.category_observed_rows ?? sourceStateFilterCounts.obs,
    src: polymarketSourceSummary?.category_source_only_rows ?? sourceStateFilterCounts.src,
  }
  const sourceStateFilterCountsForActiveMarketState = sourceStateFilterCountsByMarketState[sourceStateMarketStateFilter]
  const sourceStateSampleMarketStateCounts: Record<SourceStateMarketStateFilter, number> = {
    all: sourceStateFilterCountsByMarketState.all.all,
    open: sourceStateFilterCountsByMarketState.open.all,
    closed: sourceStateFilterCountsByMarketState.closed.all,
  }
  const sourceStateMarketStateCounts: Record<SourceStateMarketStateFilter, number> = {
    all: polymarketSourceSummary?.source_state_rows ?? sourceStateSampleMarketStateCounts.all,
    open: polymarketSourceSummary?.open_rows ?? sourceStateSampleMarketStateCounts.open,
    closed: polymarketSourceSummary?.closed_rows ?? sourceStateSampleMarketStateCounts.closed,
  }
  const sourceStateBatchCategoryCountsByMarketState: Record<SourceStateMarketStateFilter, Record<SourceStateFilter, number>> = {
    all: sourceStateBatchCategoryCounts,
    open: {
      all: polymarketSourceSummary?.open_rows ?? sourceStateSampleMarketStateCounts.open,
      warn: polymarketSourceSummary?.open_category_warning_rows ?? sourceStateFilterCounts.warn,
      part: polymarketSourceSummary?.open_category_partial_rows ?? sourceStateFilterCounts.part,
      hko: polymarketSourceSummary?.open_category_hko_rows ?? sourceStateFilterCounts.hko,
      obs: polymarketSourceSummary?.open_category_observed_rows ?? sourceStateFilterCounts.obs,
      src: polymarketSourceSummary?.open_category_source_only_rows ?? sourceStateFilterCounts.src,
    },
    closed: {
      all: polymarketSourceSummary?.closed_rows ?? sourceStateSampleMarketStateCounts.closed,
      warn: polymarketSourceSummary?.closed_category_warning_rows ?? sourceStateFilterCounts.warn,
      part: polymarketSourceSummary?.closed_category_partial_rows ?? sourceStateFilterCounts.part,
      hko: polymarketSourceSummary?.closed_category_hko_rows ?? sourceStateFilterCounts.hko,
      obs: polymarketSourceSummary?.closed_category_observed_rows ?? sourceStateFilterCounts.obs,
      src: polymarketSourceSummary?.closed_category_source_only_rows ?? sourceStateFilterCounts.src,
    },
  }
  const sourceStateBatchCategoryCountsForActiveMarketState = sourceStateBatchCategoryCountsByMarketState[sourceStateMarketStateFilter]
  const hasSourceStateDrilldownRows = sourceStateDrilldownQuery.data != null
  const sourceStateDrilldownRows = sourceStateDrilldownQuery.data ?? []
  const visiblePolymarketSourceStates = hasSourceStateDrilldownRows
    ? sourceStateDrilldownRows
    : sourceStateFilter === 'all'
      ? polymarketSourceStates
      : polymarketSourceStates.filter(row => sourceStateCategory(row) === sourceStateFilter)

  if (!summary && !botSummary && rows.length === 0 && botRows.length === 0 && reviewCandidates.length === 0 && polymarketSourceStates.length === 0 && !polymarketSourceSummary) {
    return <div className="text-[10px] text-neutral-600 p-2">No weather calibration rows</div>
  }

  return (
    <div className="space-y-1 p-1">
      {summary && (
        <div className="border border-cyan-500/20 bg-cyan-500/5 px-1.5 py-1">
          <div className="flex items-center justify-between gap-2 text-[9px] tabular-nums">
            <span className="text-cyan-300">Mkt Brier {summary.brier_score != null ? summary.brier_score.toFixed(4) : '—'}</span>
            <span className="text-neutral-500">{summary.settled_forecasts} rows</span>
          </div>
          <div className="mt-0.5 truncate text-[8px] text-neutral-600">batch {summary.latest_scored_at ?? 'none'} · market-implied only · no paper PnL</div>
        </div>
      )}
      {botSummary && (
        <div className="border border-emerald-500/20 bg-emerald-500/5 px-1.5 py-1">
          <div className="flex items-center justify-between gap-2 text-[9px] tabular-nums">
            <span className="text-emerald-300">Bot Brier {botSummary.brier_score != null ? botSummary.brier_score.toFixed(4) : '—'}</span>
            <span className="text-neutral-500">{botSummary.settled_forecasts} rows</span>
          </div>
          <div className="mt-0.5 truncate text-[8px] text-neutral-600">batch {botSummary.latest_scored_at ?? 'none'} · bot-model calibration only · non-actionable</div>
        </div>
      )}
      {reviewCandidates && reviewCandidates.length > 0 && (
        <div className="border border-amber-500/20 bg-amber-500/5 px-1.5 py-1">
          <div className="flex items-center justify-between gap-2 text-[9px] tabular-nums">
            <span className="text-amber-300">WX Review {reviewCandidates.length}</span>
            <span className="text-neutral-500">zero-size</span>
          </div>
          <div className="mt-0.5 truncate text-[8px] text-neutral-600">threshold candidates · review-only · no paper PnL</div>
        </div>
      )}
      {polymarketSourceSummary && (
        <div className="border border-violet-500/20 bg-violet-500/5 px-1.5 py-1">
          <div className="flex items-center justify-between gap-2 text-[9px] tabular-nums">
            <span className="text-violet-300">Poly WX Src {polymarketSourceSummary.source_state_rows}</span>
            <span className="text-neutral-500">{polymarketSourceSummary.unique_events} ev / {polymarketSourceSummary.unique_stations} stn</span>
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[8px] tabular-nums text-neutral-500">
            <span>urls {polymarketSourceSummary.direct_source_url_rows}</span>
            <span>dates {polymarketSourceSummary.target_date_rows}</span>
            <span>books {polymarketSourceSummary.line_book_rows}</span>
            <span>open rows {polymarketSourceSummary.open_rows}</span>
            <span>open books {polymarketSourceSummary.open_line_book_rows}</span>
            <span>mkt p {polymarketSourceSummary.market_probability_rows}</span>
            <span>pairs {polymarketSourceSummary.complete_binary_condition_pairs}/{polymarketSourceSummary.unique_conditions}</span>
            <span>depth {polymarketSourceSummary.top_ask_size_rows}</span>
            <span>open depth {polymarketSourceSummary.open_top_ask_size_rows}</span>
            {polymarketSourceSummary.closed_line_book_rows > 0 && <span className="text-amber-300">closed books {polymarketSourceSummary.closed_line_book_rows}</span>}
            <span>anom pending {polymarketSourceSummary.station_anomaly_not_checked_rows}</span>
            {polymarketSourceSummary.station_anomaly_neighbor_evidence_rows > 0 && <span>anom neigh {polymarketSourceSummary.station_anomaly_neighbor_evidence_rows}{polymarketSourceSummary.station_anomaly_neighbor_evidence_max_count > 0 ? ` max ${polymarketSourceSummary.station_anomaly_neighbor_evidence_max_count}` : ''}</span>}
            {polymarketSourceSummary.station_anomaly_warning_rows > 0 && <span className="text-red-300">anom warn {polymarketSourceSummary.station_anomaly_warning_rows}/{polymarketSourceSummary.station_anomaly_warning_unique_stations} stn{polymarketSourceSummary.station_anomaly_warning_max_delta != null ? ` Δ${polymarketSourceSummary.station_anomaly_warning_max_delta.toFixed(1)}` : ''}</span>}
            <span>src cap {polymarketSourceSummary.source_capture_attempted_rows}</span>
            <span>src urls {polymarketSourceSummary.source_capture_unique_urls}/{polymarketSourceSummary.unique_source_urls}</span>
            {polymarketSourceSummary.history_capture_rows > 0 && <span>hist {polymarketSourceSummary.history_observed_value_rows}/{polymarketSourceSummary.history_capture_rows}</span>}
            {polymarketSourceSummary.history_complete_rows > 0 && <span>hist complete {polymarketSourceSummary.history_complete_rows}/{polymarketSourceSummary.history_unique_source_urls} src</span>}
            {polymarketSourceSummary.history_partial_rows > 0 && <span className="text-amber-300">hist partial {polymarketSourceSummary.history_partial_rows} · partial src {polymarketSourceSummary.history_partial_unique_source_urls}/{polymarketSourceSummary.history_partial_unique_stations} stn</span>}
            {polymarketSourceSummary.hko_rows > 0 && <span>hko obs {polymarketSourceSummary.hko_observed_value_rows}/{polymarketSourceSummary.hko_rows}</span>}
            {polymarketSourceSummary.hko_missing_target_date_rows > 0 && <span className="text-amber-300">hko miss {polymarketSourceSummary.hko_missing_target_date_rows}</span>}
            {polymarketSourceSummary.hko_error_rows > 0 && <span className="text-red-300">hko err {polymarketSourceSummary.hko_error_rows}</span>}
            {polymarketSourceSummary.source_capture_missing_rows > 0 && <span className="text-amber-300">src miss {polymarketSourceSummary.source_capture_missing_rows}</span>}
            {polymarketSourceSummary.closed_rows > 0 && <span className="text-amber-300">closed {polymarketSourceSummary.closed_rows}</span>}
          </div>
          <div className="mt-0.5 truncate text-[8px] tabular-nums text-neutral-600">
            yes mass {polymarketSourceSummary.yes_market_probability_mass_min != null ? polymarketSourceSummary.yes_market_probability_mass_min.toFixed(2) : '—'}–{polymarketSourceSummary.yes_market_probability_mass_max != null ? polymarketSourceSummary.yes_market_probability_mass_max.toFixed(2) : '—'} · sanity pass {polymarketSourceSummary.yes_market_probability_mass_sanity_passed_count}/{polymarketSourceSummary.yes_market_probability_mass_event_count}
            {polymarketSourceSummary.source_capture_attempted_rows > 0 && ` · observed ${polymarketSourceSummary.source_capture_observed_value_rows} / no data ${polymarketSourceSummary.source_capture_no_data_rows} / err ${polymarketSourceSummary.source_capture_error_rows}`}
          </div>
          <div className="mt-0.5 truncate text-[8px] text-neutral-600">batch {polymarketSourceSummary.latest_captured_at ?? 'none'} · source-state only · non-actionable</div>
        </div>
      )}
      {polymarketSourceStates.length > 0 && (
        <div className="border border-violet-500/20 bg-violet-500/5 px-1.5 py-1">
          <div className="flex items-center justify-between gap-2 text-[9px] tabular-nums">
            <span className="text-violet-300">Poly WX sample {visiblePolymarketSourceStates.length}/{hasSourceStateDrilldownRows ? sourceStateDrilldownRows.length : polymarketSourceStates.length}</span>
            <span className="text-neutral-500">source-only · filter {sourceStateFilter.toUpperCase()} · {sourceStateMarketStateFilter.toUpperCase()}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1" aria-label="Poly WX filters">
            {sourceStateFilterOptions.map(({ filter, label }) => {
              const isActive = sourceStateFilter === filter
              return (
                <button
                  key={filter}
                  type="button"
                  onClick={() => setSourceStateFilter(filter)}
                  className={`rounded-sm border px-1 py-0.5 text-[8px] font-bold uppercase tabular-nums ${isActive ? 'border-violet-400/40 bg-violet-500/20 text-violet-200' : 'border-neutral-800 bg-neutral-950/60 text-neutral-500'}`}
                  title={`Show ${label} Polymarket weather source-state sample rows`}
                >
                  {label} {sourceStateFilterCountsForActiveMarketState[filter]}/{sourceStateBatchCategoryCountsForActiveMarketState[filter]}
                </button>
              )
            })}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1" aria-label="Poly WX market-state filters">
            {sourceStateMarketStateFilterOptions.map(({ filter, label }) => {
              const isActive = sourceStateMarketStateFilter === filter
              return (
                <button
                  key={filter}
                  type="button"
                  onClick={() => setSourceStateMarketStateFilter(filter)}
                  className={`rounded-sm border px-1 py-0.5 text-[8px] font-bold uppercase tabular-nums ${isActive ? 'border-cyan-400/40 bg-cyan-500/20 text-cyan-200' : 'border-neutral-800 bg-neutral-950/60 text-neutral-500'}`}
                  title={`Fetch ${label} Polymarket weather source-state drilldown rows`}
                >
                  {label} {sourceStateMarketStateCounts[filter]}
                </button>
              )
            })}
          </div>
          <div className="mt-0.5 truncate text-[8px] text-neutral-600">sample/batch category counts · open/closed drilldown uses backend source-state endpoint · non-actionable{sourceStateDrilldownQuery.isFetching ? ' · loading drilldown' : ''}</div>
        </div>
      )}
      {polymarketSourceStates.length > 0 && visiblePolymarketSourceStates.length === 0 && (
        <div className="border border-neutral-800 bg-neutral-950/60 p-1.5 text-[9px] text-neutral-600">
          No {sourceStateFilter.toUpperCase()} rows in the current API sample; summary counts above may still show blockers outside the compact sample.
        </div>
      )}
      {visiblePolymarketSourceStates.map(row => {
        const badge = sourceStateBadge(row)
        return (
          <div key={`${row.captured_at}-${row.condition_id}-${row.outcome ?? 'outcome'}`} className="border border-neutral-800 bg-neutral-950/60 p-1.5">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-[10px] font-medium text-neutral-300">{row.event_slug ?? row.condition_id}</div>
                <div className="mt-0.5 truncate text-[9px] text-neutral-600">{row.settlement_source ?? 'source'} · {row.settlement_station ?? row.settlement_station_name ?? 'station pending'}</div>
              </div>
              <span className={`shrink-0 rounded-sm border px-1 py-0.5 text-[8px] font-bold uppercase ${badge.className}`}>{badge.label}</span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-[9px] tabular-nums">
              <span className="text-neutral-500">{row.outcome ?? 'outcome'}</span>
              {row.target_date && <span className="text-neutral-600">date {row.target_date}</span>}
              {row.market_probability != null && <span className="text-neutral-500">p {(row.market_probability * 100).toFixed(1)}%</span>}
              {row.source_capture_status && <span className="text-violet-300">src {row.source_capture_status}</span>}
              {row.station_anomaly_status && <span className={row.station_anomaly_status.startsWith('warning') ? 'text-red-300' : 'text-amber-300'}>anom {row.station_anomaly_status}</span>}
              {row.station_anomaly_neighbor_values && row.station_anomaly_neighbor_values.length > 0 && <span className="text-neutral-600">neigh {row.station_anomaly_neighbor_values.slice(0, 3).map(value => value.toFixed(1)).join('/')}</span>}
              {row.source_observed_value != null && <span className="text-neutral-500">obs {row.source_observed_value}{row.source_observed_unit ? ` ${row.source_observed_unit}` : ''}</span>}
              {row.best_bid != null || row.best_ask != null ? <span className="text-neutral-500">book {row.best_bid != null ? (row.best_bid * 100).toFixed(1) : '—'}/{row.best_ask != null ? (row.best_ask * 100).toFixed(1) : '—'}¢</span> : null}
              {row.execution_spread != null && <span className="text-neutral-600">spr {(row.execution_spread * 100).toFixed(1)}¢</span>}
              {row.top_ask_size != null && <span className="text-neutral-600">ask {row.top_ask_size.toFixed(0)}</span>}
            </div>
            <div className="mt-0.5 truncate text-[8px] text-neutral-700">{row.paper_actionable ? 'unexpected actionable source row' : row.source_state_label} · {row.captured_at}</div>
          </div>
        )
      })}
      {reviewCandidates?.slice(0, 3).map(row => (
        <div key={`${row.captured_at}-${row.market_key}-${row.direction ?? 'dir'}`} className="border border-neutral-800 bg-neutral-950/60 p-1.5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-[10px] font-medium text-neutral-300">{row.market_key}</div>
              <div className="mt-0.5 truncate text-[9px] text-neutral-600">{row.title ?? row.city ?? 'weather review candidate'}</div>
            </div>
            <span className="shrink-0 rounded-sm border border-amber-500/20 bg-amber-500/10 px-1 py-0.5 text-[8px] font-bold uppercase text-amber-300">REV</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-[9px] tabular-nums">
            {row.model_probability != null && <span className="text-neutral-500">model {(row.model_probability * 100).toFixed(1)}%</span>}
            {row.market_probability != null && <span className="text-neutral-600">mkt {(row.market_probability * 100).toFixed(1)}%</span>}
            {row.edge != null && <span className="text-amber-300">edge {(row.edge * 100).toFixed(1)}%</span>}
            {row.best_bid != null && row.best_ask != null && <span className="text-neutral-500">book {(row.best_bid * 100).toFixed(0)}/{(row.best_ask * 100).toFixed(0)}¢</span>}
          </div>
          <div className="mt-0.5 truncate text-[8px] text-neutral-700">{row.paper_actionable || row.executed || row.suggested_size !== 0 ? 'unexpected actionable/executed row' : 'review-only / non-actionable / $0 size'} · {row.no_trade_reasons[0] ?? row.captured_at}</div>
        </div>
      ))}
      {botRows?.slice(0, 4).map(row => (
        <div key={`${row.scored_at}-${row.signal_id ?? row.market_key}-${row.outcome ?? 'outcome'}`} className="border border-neutral-800 bg-neutral-950/60 p-1.5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-[10px] font-medium text-neutral-300">{row.market_key}</div>
              <div className="mt-0.5 truncate text-[9px] text-neutral-600">{row.outcome ?? 'unknown outcome'}</div>
            </div>
            <span className="shrink-0 rounded-sm border border-emerald-500/20 bg-emerald-500/10 px-1 py-0.5 text-[8px] font-bold uppercase text-emerald-300">BOT</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-[9px] tabular-nums">
            <span className="text-neutral-500">model {(row.model_probability * 100).toFixed(1)}%</span>
            {row.market_probability != null && <span className="text-neutral-600">mkt {(row.market_probability * 100).toFixed(1)}%</span>}
            <span className={row.resolved_yes >= 0.5 ? 'text-green-400' : 'text-red-400'}>resolved {row.resolved_yes >= 0.5 ? 'Yes' : 'No'}</span>
            <span className="text-amber-300">Brier {row.brier_score != null ? row.brier_score.toFixed(3) : '—'}</span>
          </div>
          <div className="mt-0.5 truncate text-[8px] text-neutral-700">{row.paper_actionable || row.executed ? 'unexpected actionable/executed row' : 'bot calibration-only / non-actionable'} · {row.signal_ts ?? row.scored_at}</div>
        </div>
      ))}
      {rows.slice(0, 4).map(row => (
        <div key={`${row.scored_at}-${row.market_key}-${row.outcome ?? 'outcome'}`} className="border border-neutral-800 bg-neutral-950/60 p-1.5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-[10px] font-medium text-neutral-300">{row.market_key}</div>
              <div className="mt-0.5 truncate text-[9px] text-neutral-600">{row.outcome ?? 'unknown outcome'}</div>
            </div>
            <span className="shrink-0 rounded-sm border border-cyan-500/20 bg-cyan-500/10 px-1 py-0.5 text-[8px] font-bold uppercase text-cyan-300">MKT</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-[9px] tabular-nums">
            <span className="text-neutral-500">p {(row.market_probability * 100).toFixed(1)}%</span>
            <span className={row.resolved_yes >= 0.5 ? 'text-green-400' : 'text-red-400'}>resolved {row.resolved_yes >= 0.5 ? 'Yes' : 'No'}</span>
            <span className="text-amber-300">Brier {row.brier_score != null ? row.brier_score.toFixed(3) : '—'}</span>
          </div>
          <div className="mt-0.5 truncate text-[8px] text-neutral-700">{row.paper_actionable ? 'unexpected actionable row' : 'calibration-only / non-actionable'} · {row.quote_ts}</div>
        </div>
      ))}
    </div>
  )
}

function BtcCalibrationAuditPanel({
  summary,
  rows,
}: {
  summary: BtcCalibrationSummary | null
  rows: BtcCalibrationRow[]
}) {
  if (!summary && rows.length === 0) {
    return <div className="text-[10px] text-neutral-600 p-2">No BTC calibration rows</div>
  }

  return (
    <div className="space-y-1 p-1">
      {summary && (
        <div className="border border-orange-500/20 bg-orange-500/5 px-1.5 py-1">
          <div className="flex items-center justify-between gap-2 text-[9px] tabular-nums">
            <span className="text-orange-300">BTC rows {summary.scoring_rows}</span>
            <span className="text-neutral-500">exact {summary.exact_boundary_rows}</span>
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[8px] tabular-nums text-neutral-500">
            <span>requests {summary.report_request_rows}</span>
            {summary.auth_required_report_requests > 0 && <span className="text-amber-300">auth req {summary.auth_required_report_requests}</span>}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[8px] tabular-nums text-neutral-500">
            <span>windows {summary.unique_window_count}</span>
            <span>active {summary.active_window_count}</span>
            <span>upcoming {summary.upcoming_window_count}</span>
            <span>expired {summary.expired_window_count}</span>
            <span>books {summary.line_book_rows}</span>
            <span>depth {summary.top_ask_size_rows}</span>
            <span>model p {summary.model_probability_rows}</span>
            <span className={summary.exchange_spot_model_rows > 0 ? 'text-amber-300' : 'text-neutral-500'}>spot ctx {summary.exchange_spot_model_rows}</span>
            <span className={summary.source_mismatch_rows > 0 ? 'text-amber-300' : 'text-neutral-500'}>src block {summary.source_mismatch_rows}</span>
            <span className={summary.chainlink_auth_blocked_rows > 0 ? 'text-amber-300' : 'text-neutral-500'}>auth rows {summary.chainlink_auth_blocked_rows}</span>
            <span>max spr {summary.max_execution_spread != null ? (summary.max_execution_spread * 100).toFixed(0) : '—'}¢</span>
            <span>min ask {summary.min_signal_top_ask_size != null ? summary.min_signal_top_ask_size.toFixed(0) : '—'}</span>
          </div>
          <div className="mt-0.5 truncate text-[8px] text-neutral-600">batch {summary.latest_scored_at ?? 'none'} · Chainlink-boundary audit · non-actionable</div>
        </div>
      )}
      {rows.slice(0, 4).map(row => (
        <div key={`${row.ts}-${row.market_key}`} className="border border-neutral-800 bg-neutral-950/60 p-1.5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-[10px] font-medium text-neutral-300">{row.event_slug}</div>
              <div className="mt-0.5 truncate text-[9px] text-neutral-600">{row.direction ?? 'unknown'} · {row.status ?? 'pending'}</div>
            </div>
            <span className="shrink-0 rounded-sm border border-orange-500/20 bg-orange-500/10 px-1 py-0.5 text-[8px] font-bold uppercase text-orange-300">BTC</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-[9px] tabular-nums">
            <span className="text-neutral-500">book {row.signal_yes_bid != null ? (row.signal_yes_bid * 100).toFixed(0) : '—'}/{row.signal_yes_ask != null ? (row.signal_yes_ask * 100).toFixed(0) : '—'}¢</span>
            <span className="text-neutral-500">spr {row.execution_spread != null ? (row.execution_spread * 100).toFixed(0) : '—'}¢</span>
            <span className="text-neutral-500">ask {row.signal_top_ask_size != null ? row.signal_top_ask_size.toFixed(0) : '—'}</span>
            <span className={row.exact_boundary_available ? 'text-green-400' : 'text-amber-400'}>{row.exact_boundary_available ? 'exact boundary' : row.partial_boundary_available ? 'partial boundary' : 'pending boundary'}</span>
            <span className="text-neutral-500">Brier {row.brier_score != null ? row.brier_score.toFixed(3) : '—'}</span>
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[8px] tabular-nums text-neutral-600">
            {row.chainlink_start_report_status && <span>start {row.chainlink_start_report_status}</span>}
            {row.chainlink_end_report_status && <span>end {row.chainlink_end_report_status}</span>}
            {(row.chainlink_start_report_boundary_ts || row.chainlink_end_report_boundary_ts) && <span>{row.chainlink_start_report_boundary_ts ?? '—'}→{row.chainlink_end_report_boundary_ts ?? '—'}</span>}
            {(row.chainlink_start_report_requires_authentication || row.chainlink_end_report_requires_authentication) && <span className="text-amber-300">auth required</span>}
          </div>
          <div className="mt-0.5 truncate text-[8px] text-neutral-700">{row.no_trade_reasons[0] ?? 'calibration-only / non-actionable'} · {row.quote_ts ?? row.ts}</div>
        </div>
      ))}
    </div>
  )
}

function OpenPositionRiskPanel({ rows, summary }: { rows: OpenPositionRiskRow[], summary: OpenPositionRiskSummary }) {
  if (rows.length === 0) {
    return (
      <div className="text-[10px] text-neutral-600 p-2">
        No open paper positions with cash-out risk marks
      </div>
    )
  }

  const actionColor = (action: string) => {
    if (action === 'exit') return 'text-red-300 border-red-500/20 bg-red-500/10'
    if (action === 'reduce') return 'text-orange-300 border-orange-500/20 bg-orange-500/10'
    if (action === 'watch') return 'text-amber-300 border-amber-500/20 bg-amber-500/10'
    return 'text-green-300 border-green-500/20 bg-green-500/10'
  }
  const riskSourceLabels: Record<string, string> = {
    closed_market_or_stale_token: 'closed/stale',
    live_weather_exit_quote_fetch_error: 'quote fetch error',
    live_weather_exit_quote: 'live quote',
    missing_executable_exit_bid: 'missing exit bid',
    latest_weather_signal_quote_not_executable: 'signal only',
    missing_live_quote: 'missing quote',
  }

  return (
    <div className="space-y-1 p-1">
      <div className="grid grid-cols-4 gap-1 text-[8px] tabular-nums">
        {['hold', 'watch', 'reduce', 'exit'].map(action => (
          <div key={action} className="border border-neutral-800 bg-neutral-950/60 px-1 py-0.5">
            <div className="uppercase text-neutral-600">{action}</div>
            <div className={actionColor(action).split(' ')[0]}>{summary.action_counts?.[action] ?? 0}</div>
          </div>
        ))}
      </div>
      <div className="border border-blue-500/20 bg-blue-500/5 px-1.5 py-1 text-[8px] text-neutral-500">
        {summary.recommendations_only ? 'recommendations-only' : 'paper auto-exit enabled'} · {summary.total_open_positions} open · {summary.stale_mark_count ?? 0} stale marks · {summary.live_exit_quote_error_count ?? 0} quote errors · {summary.closed_market_or_stale_token_count ?? 0} closed/stale tokens · no live trades
        {summary.latest_checked_at && <span> · latest {summary.latest_checked_at}</span>}
      </div>
      {Object.keys(summary.source_status_counts ?? {}).length > 0 && (
        <div className="flex flex-wrap gap-1 text-[8px] uppercase text-neutral-600">
          {Object.entries(summary.source_status_counts).map(([status, count]) => (
            <span key={status} className="rounded-sm border border-neutral-800 bg-neutral-950/60 px-1 py-0.5 tabular-nums">
              {riskSourceLabels[status] ?? status.replace(/_/g, ' ')} {count}
            </span>
          ))}
        </div>
      )}
      {rows.slice(0, 5).map(row => (
        <div key={`${row.trade_id}-${row.checked_at}`} className="border border-neutral-800 bg-neutral-950/60 p-1.5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-[10px] font-medium text-neutral-300">{row.event_slug ?? row.market_ticker}</div>
              <div className="mt-0.5 truncate text-[9px] text-neutral-600">{row.market_type} · {row.direction} · entry {(row.entry_price * 100).toFixed(1)}¢</div>
            </div>
            <span className={`shrink-0 rounded-sm border px-1 py-0.5 text-[8px] font-bold uppercase ${actionColor(row.action)}`}>{row.action}</span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-[9px] tabular-nums">
            <span className="text-neutral-500">exit {row.current_exit_price != null ? `${(row.current_exit_price * 100).toFixed(1)}¢` : '—'}</span>
            <span className={row.unrealized_pnl != null && row.unrealized_pnl < 0 ? 'text-red-300' : 'text-green-300'}>
              uPnL {row.unrealized_pnl != null ? `${row.unrealized_pnl >= 0 ? '+' : ''}$${row.unrealized_pnl.toFixed(2)}` : '—'}
            </span>
            {row.model_probability_for_held_side != null && <span className="text-neutral-600">model {(row.model_probability_for_held_side * 100).toFixed(1)}%</span>}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[8px] tabular-nums text-neutral-600">
            <span className={row.live_exit_quote_bid != null ? 'text-blue-300' : 'text-amber-300'}>
              live bid {row.live_exit_quote_bid != null ? `${(row.live_exit_quote_bid * 100).toFixed(1)}¢` : '—'}
            </span>
            {row.live_exit_quote_ask != null && <span>ask {(row.live_exit_quote_ask * 100).toFixed(1)}¢</span>}
            {row.live_exit_quote_top_bid_size != null && <span>depth {row.live_exit_quote_top_bid_size.toFixed(0)}</span>}
            {row.live_exit_quote_source && <span>{row.live_exit_quote_source.replace(/_/g, ' ')}</span>}
            {row.live_exit_quote_error && <span className="text-amber-300">quote err {row.live_exit_quote_error.split('\n')[0].slice(0, 72)}</span>}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[8px] tabular-nums text-neutral-600">
            <span className={row.settlement_source_known ? 'text-blue-300' : 'text-amber-300'}>
              {row.settlement_source_known ? 'source mapped' : 'source missing'}
            </span>
            <span className={row.station_known ? 'text-blue-300' : 'text-amber-300'}>
              {row.station_known ? 'station mapped' : 'station missing'}
            </span>
            {row.latest_signal_model_probability_for_held_side != null && <span>sig p {(row.latest_signal_model_probability_for_held_side * 100).toFixed(1)}%</span>}
            {row.latest_signal_market_price != null && <span>sig mkt {(row.latest_signal_market_price * 100).toFixed(1)}¢</span>}
            {row.latest_signal_edge != null && <span>sig edge {(row.latest_signal_edge * 100).toFixed(1)}pp</span>}
            {row.latest_signal_suggested_size != null && <span>sig size ${row.latest_signal_suggested_size.toFixed(0)}</span>}
          </div>
          <div className="mt-0.5 text-[8px] text-neutral-700 line-clamp-2">
            {row.risk_scan_stale ? 'stale mark / scan pending' : (row.reasons?.[0] ?? row.source_status ?? 'risk scan pending')}
            {row.source_status && <span> · src {row.source_status}</span>}
            {row.risk_evidence?.source_confidence != null && <span> · conf {String(row.risk_evidence.source_confidence)}</span>}
            {' '}· {row.checked_at}
          </div>
        </div>
      ))}
    </div>
  )
}

function SignalReviewQueuePanel({ queue }: { queue: SignalReviewQueue }) {
  if (queue.total_blocked === 0) {
    return <div className="text-[10px] text-neutral-600 p-2">No blocked paper candidates with review reasons</div>
  }

  const sourceLabels: Record<string, string> = {
    btc_signal: 'BTC sig',
    weather_signal: 'WX sig',
    weather_review_candidate: 'WX rev',
    polymarket_weather_source_state: 'WX src',
    rt_source_state: 'RT src',
  }

  return (
    <div className="space-y-1 p-1">
      <div className="grid grid-cols-3 gap-1 text-[9px] tabular-nums">
        {Object.entries(queue.blocked_by_vertical).map(([vertical, count]) => (
          <div key={vertical} className="border border-neutral-800 bg-neutral-950/60 px-1.5 py-1">
            <div className="uppercase text-neutral-600">{vertical.replace('_entertainment', '')}</div>
            <div className="text-amber-300">{count} blocked</div>
          </div>
        ))}
      </div>
      {Object.keys(queue.blocked_by_source ?? {}).length > 0 && (
        <div className="flex flex-wrap gap-1 text-[8px] uppercase text-neutral-600">
          {Object.entries(queue.blocked_by_source).map(([source, count]) => (
            <span key={source} className="rounded-sm border border-neutral-800 bg-neutral-950/60 px-1 py-0.5 tabular-nums">
              {sourceLabels[source] ?? source.replace(/_/g, ' ')} {count}
            </span>
          ))}
        </div>
      )}
      {queue.top_blockers.slice(0, 2).map((blocker, idx) => (
        <div key={`${blocker.reason}-${idx}`} className="border border-amber-500/20 bg-amber-500/5 px-1.5 py-1">
          <div className="text-[9px] text-amber-300 line-clamp-2">{blocker.reason}</div>
          <div className="mt-0.5 text-[8px] uppercase text-neutral-600">{blocker.count} matching candidate{blocker.count === 1 ? '' : 's'}</div>
        </div>
      ))}
      {queue.items.slice(0, 4).map(item => (
        <div key={`${item.vertical}-${item.market_key}`} className="border border-neutral-800 bg-neutral-950/60 p-1.5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-[10px] font-medium text-neutral-300">{item.title}</div>
              <div className="mt-0.5 text-[9px] text-neutral-600 truncate">{item.market_key}</div>
            </div>
            <span className="shrink-0 rounded-sm border border-red-500/20 bg-red-500/10 px-1 py-0.5 text-[8px] font-bold uppercase text-red-300">
              {item.source_kind ? (sourceLabels[item.source_kind] ?? item.source_kind.replace(/_/g, ' ')) : 'review'} · P{item.review_priority}
            </span>
          </div>
          <div className="mt-1 text-[9px] text-neutral-500 line-clamp-2">{item.primary_blocker}</div>
          <div className="mt-1 flex items-center gap-2 text-[8px] uppercase text-neutral-600">
            <span>{item.vertical.replace('_entertainment', '')}</span>
            {item.edge != null && <span>edge {(item.edge * 100).toFixed(1)}%</span>}
            {item.best_bid != null && item.best_ask != null && <span>book {(item.best_bid * 100).toFixed(1)}/{(item.best_ask * 100).toFixed(1)}¢</span>}
            {item.threshold != null && <span>thr {item.threshold}</span>}
            {item.box_office_bucket_label && <span>bucket {item.box_office_bucket_label}</span>}
            {item.box_office_bucket_set_size != null && (
              <span>
                set {item.box_office_bucket_set_size}
                {item.box_office_bucket_set_sanity_passed != null ? (item.box_office_bucket_set_sanity_passed ? ' ✓' : ' !') : ''}
                {item.box_office_resolved_winner_label ? ` win ${item.box_office_resolved_winner_label}` : ''}
              </span>
            )}
            {item.market_closed && <span>closed</span>}
            {item.market_probability != null && <span>mkt {(item.market_probability * 100).toFixed(1)}%</span>}
            {item.model_probability != null && <span>model {(item.model_probability * 100).toFixed(1)}%</span>}
            {item.execution_spread != null && <span>spread {(item.execution_spread * 100).toFixed(1)}¢</span>}
            {item.top_ask_size != null && <span>ask {item.top_ask_size.toFixed(0)}</span>}
          </div>
          {(item.settlement_source || item.settlement_station || item.settlement_units || item.model_price_source || item.source_method || item.direct_source_status || item.station_anomaly_status || item.review_count != null || item.timing_risk_label || item.cutoff_time) && (
            <div className="mt-0.5 text-[8px] text-neutral-700 truncate">
              {item.settlement_source && <span>settles: {item.settlement_source}</span>}
              {item.settlement_station && <span>{item.settlement_source ? ' · ' : ''}station: {item.settlement_station}</span>}
              {item.settlement_units && <span>{(item.settlement_source || item.settlement_station) ? ' · ' : ''}unit: {item.settlement_units}{item.settlement_precision ? `/${item.settlement_precision}` : ''}</span>}
              {item.model_price_source && <span>{(item.settlement_source || item.settlement_station || item.settlement_units) ? ' · ' : ''}model: {item.model_price_source}</span>}
              {item.source_method && <span>{(item.settlement_source || item.settlement_station || item.settlement_units || item.model_price_source) ? ' · ' : ''}method: {item.source_method}</span>}
              {item.direct_source_status && <span>{(item.settlement_source || item.settlement_station || item.settlement_units || item.model_price_source || item.source_method) ? ' · ' : ''}source: {item.direct_source_status}</span>}
              {item.station_anomaly_status && <span> · anom {item.station_anomaly_status}{item.station_anomaly_max_delta != null ? ` Δ${item.station_anomaly_max_delta}` : ''}</span>}
              {item.review_count != null && <span> · reviews {item.review_count}</span>}
              {(item.score_delta != null || item.review_count_delta != null) && (
                <span> · Δ {item.score_delta != null ? formatSignedDelta(item.score_delta, 'pt') : '—'}{item.review_count_delta != null ? ` / ${formatSignedDelta(item.review_count_delta)} reviews` : ''}</span>
              )}
              {item.timing_risk_label && <span> · {item.timing_risk_label}</span>}
              {item.cutoff_time && <span> · cutoff {item.cutoff_time}</span>}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function App() {
  const queryClient = useQueryClient()

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
    refetchInterval: 10000,
  })

  const scanMutation = useMutation({
    mutationFn: runScan,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  const tradeMutation = useMutation({
    mutationFn: simulateTrade,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  const startMutation = useMutation({
    mutationFn: startBot,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  const stopMutation = useMutation({
    mutationFn: stopBot,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  const dashboard = data
  const showLegacyDashboardSections = data?.legacy_dashboard_sections_enabled ?? false
  const activeProductScope = data?.active_product_scope ?? 'weather'
  const legacyDashboardNote = data?.legacy_dashboard_note ?? null
  const activeSignals = data?.active_signals ?? []
  const recentTrades = data?.recent_trades ?? []
  const btcPrice = data?.btc_price
  const micro = data?.microstructure
  const windows = data?.windows ?? []
  const weatherSignals = data?.weather_signals ?? []
  const weatherForecasts = data?.weather_forecasts ?? []
  const rottenTomatoesSourceStates = data?.rotten_tomatoes_source_states ?? []
  const signalReviewQueue = data?.signal_review_queue ?? {
    total_blocked: 0,
    blocked_by_vertical: {},
    blocked_by_source: {},
    top_blockers: [],
    items: [],
  }
  const openPositionRiskRows = dashboard ? dashboard.open_position_risk_rows : []
  const openPositionRiskSummary = dashboard ? dashboard.open_position_risk_summary : {
    total_open_positions: openPositionRiskRows.length,
    action_counts: {},
    auto_exit_enabled: false,
    recommendations_only: true,
    stale_mark_count: 0,
    live_exit_quote_error_count: 0,
    closed_market_or_stale_token_count: 0,
    source_status_counts: {},
    latest_checked_at: null,
    exited_count: 0,
  }

  const stats = data?.stats ?? {
    is_running: false,
    last_run: null,
    total_trades: 0,
    total_pnl: 0,
    bankroll: 10000,
    winning_trades: 0,
    win_rate: 0,
    weather_paper_account: {
      initial_bankroll: 1000,
      target_bankroll: 1100,
      current_equity: 1000,
      realized_pnl: 0,
      remaining_to_target: 100,
      progress_to_target_pct: 0,
      total_trades: 0,
      settled_trades: 0,
      pending_trades: 0,
      pending_size: 0,
      platform_breakdown: [],
      winning_trades: 0,
      win_rate: 0,
      settled_forecasts: 0,
      brier_score: null,
      log_loss: null,
      paper_only: true,
      selective_no_forced_trade: true,
      market_scope: 'weather' as const,
      ledger_exposure_state: 'no_trades' as const,
      ledger_status_note: 'No weather paper trades; selective/no-forced-trade mode is preserved.',
    },
    btc_paper_account: {
      initial_bankroll: 1000,
      target_bankroll: 1100,
      current_equity: 1000,
      realized_pnl: 0,
      remaining_to_target: 100,
      progress_to_target_pct: 0,
      total_trades: 0,
      settled_trades: 0,
      pending_trades: 0,
      winning_trades: 0,
      win_rate: 0,
      settled_forecasts: 0,
      brier_score: null,
      log_loss: null,
      paper_only: true,
      selective_no_forced_trade: true,
    },
    entertainment_paper_account: {
      initial_bankroll: 1000,
      target_bankroll: 1100,
      current_equity: 1000,
      realized_pnl: 0,
      remaining_to_target: 100,
      progress_to_target_pct: 0,
      total_trades: 0,
      settled_trades: 0,
      pending_trades: 0,
      winning_trades: 0,
      win_rate: 0,
      settled_forecasts: 0,
      brier_score: null,
      log_loss: null,
      paper_only: true,
      selective_no_forced_trade: true,
      market_scope: 'rotten_tomatoes_entertainment' as const,
    },
  }
  const equityCurve = data?.equity_curve ?? []
  const calibration = data?.calibration ?? null
  const weatherCalibration = data?.weather_calibration ?? null
  const weatherBotCalibration = data?.weather_bot_calibration ?? null
  const weatherCalibrationRows = data?.weather_calibration_rows ?? []
  const weatherBotCalibrationRows = data?.weather_bot_calibration_rows ?? []
  const weatherSignalReviewCandidates = data?.weather_signal_review_candidates ?? []
  const polymarketWeatherSourceStates = data?.polymarket_weather_source_states ?? []
  const polymarketWeatherSourceStateSummary = data?.polymarket_weather_source_state_summary ?? null
  const btcCalibration = data?.btc_calibration ?? null
  const btcCalibrationRows = data?.btc_calibration_rows ?? []

  const actionableCount = activeSignals.filter(s => s.actionable).length + weatherSignals.filter(s => s.actionable).length

  if (isLoading) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="relative w-10 h-10 mx-auto mb-4">
            <div className="absolute inset-0 border-2 border-neutral-800 rounded-full" />
            <div className="absolute inset-0 border-2 border-transparent border-t-green-500 rounded-full animate-spin" />
          </div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">Initializing</div>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="text-red-500 text-xs uppercase mb-2 tracking-wider">Connection Error</div>
          <button
            onClick={() => refetch()}
            className="px-3 py-1.5 bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs uppercase tracking-wider"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen bg-black text-neutral-200 flex flex-col overflow-hidden">
      {/* ===== HEADER ===== */}
      <motion.header
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="shrink-0 border-b border-neutral-800 px-3 py-1.5 flex items-center gap-4 relative"
      >
        <div className="scan-line" />

        <div className="flex items-center gap-2 shrink-0">
          <h1 className="text-xs font-bold text-neutral-100 uppercase tracking-widest whitespace-nowrap font-mono">
            WEATHER PAPER TERMINAL
          </h1>
          <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
            {activeProductScope.replace(/[_-]/g, ' ')}
          </span>
          <span className={`px-1.5 py-0.5 text-[9px] font-bold uppercase ${
            stats.is_running
              ? 'bg-green-500/10 text-green-500 border border-green-500/20'
              : 'bg-neutral-800 text-neutral-500 border border-neutral-700'
          }`}>
            {stats.is_running ? 'Live' : 'Idle'}
          </span>
          <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase bg-amber-500/10 text-amber-400 border border-amber-500/20">
            Sim
          </span>
        </div>

        {btcPrice && (
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-sm font-bold tabular-nums text-neutral-100">
              ${btcPrice.price.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
            <span className={`text-[10px] tabular-nums ${btcPrice.change_24h >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              {btcPrice.change_24h >= 0 ? '+' : ''}{btcPrice.change_24h.toFixed(2)}%
            </span>
          </div>
        )}

        <div className="flex-1" />

        <StatsCards
          stats={stats}
          weatherCalibration={weatherCalibration}
          weatherBotCalibration={weatherBotCalibration}
          btcCalibration={btcCalibration}
          showLegacySections={showLegacyDashboardSections}
        />

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => scanMutation.mutate()}
            disabled={scanMutation.isPending}
            className="px-2.5 py-1 bg-neutral-900 border border-neutral-700 hover:border-neutral-600 text-neutral-300 text-[10px] uppercase tracking-wider transition-colors disabled:opacity-50 whitespace-nowrap"
          >
            {scanMutation.isPending ? 'Scanning...' : 'Scan'}
          </button>
          <LiveClock />
        </div>
      </motion.header>

      {/* ===== MAIN GRID ===== */}
      <div className="flex-1 min-h-0 grid grid-cols-[300px_1fr_340px] grid-rows-[1fr] gap-0">

        {/* ===== LEFT COLUMN ===== */}
        <div className="flex flex-col border-r border-neutral-800 min-h-0 overflow-hidden">
          {/* Microstructure */}
          {micro && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="shrink-0 border-b border-neutral-800 px-2 py-2"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Microstructure</span>
                <span className="text-[9px] text-neutral-600 tabular-nums">{micro.source}</span>
              </div>
              <MicrostructurePanel micro={micro} />
            </motion.div>
          )}

          {/* Equity chart */}
          <div className="border-b border-neutral-800" style={{ height: '28%', minHeight: '120px' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Equity</span>
              <span className={`text-[10px] tabular-nums ${stats.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(0)}
              </span>
            </div>
            <div className="h-[calc(100%-24px)] p-1">
              <EquityChart data={equityCurve} initialBankroll={stats.bankroll - stats.total_pnl} />
            </div>
          </div>

          {/* Calibration */}
          {calibration && calibration.total_with_outcome > 0 && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="shrink-0 border-b border-neutral-800 px-2 py-2"
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Calibration</span>
                <span className="text-[9px] text-neutral-600 tabular-nums">{calibration.total_with_outcome} settled</span>
              </div>
              <CalibrationPanel calibration={calibration} />
            </motion.div>
          )}

          {/* Terminal fills remaining */}
          <div className="flex-1 min-h-0">
            <Terminal
              isRunning={stats.is_running}
              lastRun={stats.last_run}
              stats={{ total_trades: stats.total_trades, total_pnl: stats.total_pnl }}
              onStart={() => startMutation.mutate()}
              onStop={() => stopMutation.mutate()}
              onScan={() => scanMutation.mutate()}
            />
          </div>
        </div>

        {/* ===== CENTER COLUMN ===== */}
        <div className="flex flex-col min-h-0 border-r border-neutral-800">
          {/* Globe - top 60% */}
          <div className="relative" style={{ height: '58%' }}>
            <div className="absolute inset-0">
              <Suspense fallback={
                <div className="w-full h-full flex items-center justify-center bg-black">
                  <span className="text-[10px] text-neutral-600 uppercase tracking-wider">Loading Globe...</span>
                </div>
              }>
                <GlobeView forecasts={weatherForecasts} signals={weatherSignals} />
              </Suspense>
            </div>
            {/* Globe overlay: actionable count */}
            <div className="absolute top-2 left-2 z-10">
              <div className="px-2 py-1 bg-black/80 border border-neutral-800 text-[10px]">
                <span className="text-neutral-500 uppercase tracking-wider mr-2">Markets</span>
                <span className="text-amber-500 tabular-nums">{actionableCount} actionable</span>
              </div>
            </div>
          </div>

          {/* Bottom panels */}
          <div className={`flex-1 min-h-0 grid ${showLegacyDashboardSections ? 'grid-cols-5' : 'grid-cols-4'} border-t border-neutral-800`}>
            {/* Edge Distribution */}
            <div className="border-r border-neutral-800 flex flex-col min-h-0">
              <div className="px-2 py-1 border-b border-neutral-800 shrink-0">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Edge Distribution</span>
              </div>
              <div className="flex-1 min-h-0 p-1">
                <EdgeDistribution btcSignals={activeSignals} weatherSignals={weatherSignals} showLegacySections={showLegacyDashboardSections} />
              </div>
            </div>

            {/* BTC Windows */}
            {showLegacyDashboardSections && (
              <div className="border-r border-neutral-800 flex flex-col min-h-0">
                <div className="px-2 py-1 border-b border-neutral-800 shrink-0">
                  <span className="text-[10px] text-neutral-500 uppercase tracking-wider">BTC Windows</span>
                </div>
                <div className="flex-1 min-h-0 overflow-y-auto p-1 space-y-1">
                  {windows.length > 0 ? (
                    windows.slice(0, 6).map(w => (
                      <WindowPill key={w.slug} window={w} />
                    ))
                  ) : (
                    <div className="text-[10px] text-neutral-600 p-2">No active windows</div>
                  )}
                  <BtcCalibrationAuditPanel summary={btcCalibration} rows={btcCalibrationRows} />
                </div>
              </div>
            )}

            {/* Weather Forecasts */}
            <div className="border-r border-neutral-800 flex flex-col min-h-0">
              <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Weather</span>
                <span className="px-1 py-0.5 text-[8px] font-bold uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">WX</span>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto">
                <WeatherPanel forecasts={weatherForecasts} signals={weatherSignals} />
              </div>
            </div>

            {/* Weather Calibration */}
            <div className="border-r border-neutral-800 flex flex-col min-h-0">
              <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">WX Cal</span>
                <span className="text-[9px] text-cyan-300 tabular-nums">{weatherCalibrationRows.length + weatherBotCalibrationRows.length + weatherSignalReviewCandidates.length + polymarketWeatherSourceStates.length}</span>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto">
                <WeatherCalibrationAuditPanel summary={weatherCalibration} botSummary={weatherBotCalibration} rows={weatherCalibrationRows} botRows={weatherBotCalibrationRows} reviewCandidates={weatherSignalReviewCandidates} polymarketSourceStates={polymarketWeatherSourceStates} polymarketSourceSummary={polymarketWeatherSourceStateSummary} />
              </div>
            </div>

            {/* Rotten Tomatoes Source State */}
            {showLegacyDashboardSections ? (
              <div className="flex flex-col min-h-0">
                <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
                  <span className="text-[10px] text-neutral-500 uppercase tracking-wider">RT Source</span>
                  <span className="text-[9px] text-purple-300 tabular-nums">{rottenTomatoesSourceStates.length}</span>
                </div>
                <div className="flex-1 min-h-0 overflow-y-auto">
                  <RottenTomatoesSourcePanel states={rottenTomatoesSourceStates} />
                </div>
              </div>
            ) : legacyDashboardNote ? (
              <div className="flex flex-col min-h-0">
                <div className="px-2 py-1 border-b border-neutral-800 shrink-0">
                  <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Scope</span>
                </div>
                <div className="flex-1 min-h-0 p-2 text-[10px] leading-relaxed text-neutral-500">
                  {legacyDashboardNote}
                </div>
              </div>
            ) : null}
          </div>
        </div>

        {/* ===== RIGHT COLUMN ===== */}
        <div className="flex flex-col min-h-0 overflow-hidden">
          {/* Signals - top portion */}
          <div className="flex flex-col min-h-0" style={{ height: '40%' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Signals</span>
              <div className="flex items-center gap-2">
                {showLegacyDashboardSections && (
                  <span className="text-[10px] text-amber-400 tabular-nums">{activeSignals.length} BTC</span>
                )}
                {weatherSignals.length > 0 && (
                  <span className="text-[10px] text-cyan-400 tabular-nums">{weatherSignals.length} WX</span>
                )}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0">
              <SignalsTable
                signals={activeSignals}
                weatherSignals={weatherSignals}
                onSimulateTrade={(ticker) => tradeMutation.mutate(ticker)}
                isSimulating={tradeMutation.isPending}
              />
            </div>
          </div>

          {/* Signal review queue */}
          <div className="flex flex-col min-h-0 border-t border-neutral-800" style={{ height: '25%' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Review Queue</span>
              <span className="text-[10px] text-red-300 tabular-nums">{signalReviewQueue.total_blocked} blocked</span>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0">
              <SignalReviewQueuePanel queue={signalReviewQueue} />
            </div>
          </div>

          {/* Open-position cash-out risk */}
          <div className="flex flex-col min-h-0 border-t border-neutral-800" style={{ height: '25%' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Cash-out Risk</span>
              <span className="text-[10px] text-blue-300 tabular-nums">{openPositionRiskSummary.total_open_positions} open</span>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0">
              <OpenPositionRiskPanel rows={openPositionRiskRows} summary={openPositionRiskSummary} />
            </div>
          </div>

          {/* Trades */}
          <div className="flex flex-col min-h-0 border-t border-neutral-800" style={{ height: '25%' }}>
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Trades</span>
              <span className="text-[10px] text-neutral-600 tabular-nums">{recentTrades.length}</span>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0">
              <TradesTable trades={recentTrades} />
            </div>
          </div>
        </div>
      </div>

      {/* ===== FOOTER ===== */}
      <footer className="shrink-0 border-t border-neutral-800 px-3 py-0.5 flex items-center justify-between">
        <span className="text-[10px] text-neutral-700 font-mono">
          Open-Meteo / NWS / Wunderground / HKO | Polymarket + Kalshi weather
        </span>
        <div className="flex items-center gap-3">
          <RefreshBar interval={10000} />
          <span className="text-[10px] text-neutral-700 font-mono">Weather temp paper ledger + source QA</span>
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
            <span className="text-[10px] text-neutral-600 font-mono">Connected</span>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
