import { useState, useEffect, Suspense, lazy } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { fetchLiveData, fetchWeatherStatus, runScan, startBot, stopBot } from './api'
import type { LiveData, KalshiPosition, PolyPosition, MetarV2Signal } from './types'
import { SignalsTable } from './components/SignalsTable'
import { Terminal } from './components/Terminal'
import { EdgeDistribution } from './components/EdgeDistribution'
import { SettingsModal } from './components/SettingsModal'
import { KalshiMarketsTab } from './components/KalshiMarketsTab'
import { PolyMarketsTab } from './components/PolyMarketsTab'

const GlobeView = lazy(() => import('./components/GlobeView').then(m => ({ default: m.GlobeView })))

type Tab = 'overview' | 'kalshi' | 'polymarket'

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

function RefreshBar({ interval }: { interval: number }) {
  const [progress, setProgress] = useState(100)
  useEffect(() => {
    setProgress(100)
    const step = 100 / (interval / 1000)
    const timer = setInterval(() => setProgress(p => Math.max(0, p - step)), 1000)
    return () => clearInterval(timer)
  }, [interval])
  return (
    <div className="refresh-bar w-16">
      <div className="refresh-fill" style={{ width: `${progress}%` }} />
    </div>
  )
}

function fmt(n: number, decimals = 2) {
  return n.toFixed(decimals)
}

function fmtAge(seconds?: number | null) {
  if (seconds === undefined || seconds === null) return '—'
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  return `${(seconds / 60).toFixed(1)}m`
}

function pnlColor(n: number) {
  if (n > 0) return 'text-green-400'
  if (n < 0) return 'text-red-400'
  return 'text-neutral-500'
}

// ─── V2 Signals Panel ────────────────────────────────────────────────────────
function V2SignalsPanel({ signals }: { signals: MetarV2Signal[] }) {
  const recommended = [...signals]
    .filter(s => s.recommend)
    .sort((a, b) => b.ev_net - a.ev_net)

  return (
    <div className="shrink-0 border-b border-neutral-800">
      <div className="px-2 py-1 border-b border-neutral-800 flex items-center gap-2">
        <span className="text-[10px] text-amber-400/80 uppercase tracking-wider">V2 Signals</span>
        <span className="px-1 py-0.5 text-[8px] font-bold uppercase bg-amber-500/10 text-amber-400 border border-amber-500/20">
          Paper
        </span>
        {recommended.length > 0 && (
          <span className="ml-auto text-[10px] text-amber-400 tabular-nums">{recommended.length} actionable</span>
        )}
      </div>

      {recommended.length === 0 ? (
        <div className="px-2 py-2 text-[10px] text-neutral-600">No recommended signals</div>
      ) : (
        <div className="max-h-[220px] overflow-y-auto">
          {recommended.map((sig, i) => (
            <div key={i} className="px-2 py-1.5 border-b border-neutral-800/60 hover:bg-neutral-900/40 transition-colors">
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className="text-[10px] font-semibold text-amber-300">{sig.city}</span>
                <span className={`px-1 py-0.5 text-[8px] font-bold uppercase ${sig.side.toLowerCase() === 'yes' ? 'bg-green-500/10 text-green-400 border border-green-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
                  {sig.side.toUpperCase()}
                </span>
                {sig.dry_run && (
                  <span className="px-1 py-0.5 text-[8px] font-bold uppercase bg-amber-500/10 text-amber-500 border border-amber-500/20">
                    DRY RUN
                  </span>
                )}
                <span className="ml-auto text-[10px] text-green-400 tabular-nums">
                  +{fmt(sig.ev_net, 3)}
                </span>
                <span className="text-[10px] text-neutral-500 tabular-nums">
                  {(sig.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <div className="text-[9px] text-neutral-500 leading-tight truncate">
                {sig.question.length > 72 ? sig.question.slice(0, 72) + '…' : sig.question}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Kalshi Tab ───────────────────────────────────────────────────────────────
function KalshiTab({ data }: { data: LiveData }) {
  const { kalshi, lifetime } = data
  const positions = kalshi?.positions ?? []

  return (
    <div className="flex-1 min-h-0 overflow-auto p-4 space-y-6">
      {/* Balances */}
      <div>
        <h2 className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Kalshi Balances</h2>
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'Cash', value: `$${fmt(kalshi.balance)}` },
            { label: 'Portfolio', value: `$${fmt(kalshi.portfolio_value)}` },
            { label: 'Total', value: `$${fmt(kalshi.total)}` },
            { label: 'Last Trade', value: kalshi.last_live_trade_ts || '—' },
          ].map(stat => (
            <div key={stat.label} className="bg-neutral-900 border border-neutral-800 px-3 py-2">
              <div className="text-[9px] text-neutral-500 uppercase tracking-wider mb-1">{stat.label}</div>
              <div className="text-sm text-white font-mono tabular-nums">{stat.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Lifetime stats */}
      <div>
        <h2 className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Lifetime Stats</h2>
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: 'Deposited', value: `$${fmt(lifetime.kalshi_deposited)}` },
            { label: 'Lifetime P&L', value: `${lifetime.kalshi_lifetime_pnl >= 0 ? '+' : ''}$${fmt(lifetime.kalshi_lifetime_pnl)}`, color: pnlColor(lifetime.kalshi_lifetime_pnl) },
            { label: 'Current Total', value: `$${fmt(kalshi.total)}` },
          ].map(stat => (
            <div key={stat.label} className="bg-neutral-900 border border-neutral-800 px-3 py-2">
              <div className="text-[9px] text-neutral-500 uppercase tracking-wider mb-1">{stat.label}</div>
              <div className={`text-sm font-mono tabular-nums ${stat.color ?? 'text-white'}`}>{stat.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Positions */}
      <div>
        <h2 className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Open Positions</h2>
        {positions.length === 0 ? (
          <div className="border border-neutral-800 px-4 py-6 text-center text-[10px] text-neutral-600">No open positions</div>
        ) : (
          <div className="border border-neutral-800 overflow-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900">
                  {['Ticker', 'Side', 'Contracts', 'Cost', 'Value', 'Unrealized P&L', 'Payout if Win'].map(h => (
                    <th key={h} className="px-3 py-1.5 text-left text-[9px] text-neutral-500 uppercase tracking-wider font-normal whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.map((p: KalshiPosition) => (
                  <tr key={p.ticker} className="border-b border-neutral-800/60 hover:bg-neutral-900/40">
                    <td className="px-3 py-1.5 font-mono text-cyan-400 whitespace-nowrap">{p.ticker}</td>
                    <td className="px-3 py-1.5">
                      <span className={`px-1 py-0.5 text-[8px] font-bold uppercase ${p.side === 'yes' ? 'bg-green-500/10 text-green-400 border border-green-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
                        {p.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 tabular-nums text-neutral-300">{p.contracts}</td>
                    <td className="px-3 py-1.5 tabular-nums text-neutral-400">${fmt(p.cost)}</td>
                    <td className="px-3 py-1.5 tabular-nums text-neutral-300">${fmt(p.value)}</td>
                    <td className={`px-3 py-1.5 tabular-nums ${pnlColor(p.unrealized_pnl)}`}>
                      {p.unrealized_pnl >= 0 ? '+' : ''}${fmt(p.unrealized_pnl)}
                    </td>
                    <td className="px-3 py-1.5 tabular-nums text-neutral-400">${fmt(p.payout_if_win)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Polymarket Tab ───────────────────────────────────────────────────────────
function PolyTab({ data }: { data: LiveData }) {
  const { polymarket, lifetime } = data
  const positions = (polymarket?.positions ?? []).filter((p: PolyPosition) => !p.garbage)

  return (
    <div className="flex-1 min-h-0 overflow-auto p-4 space-y-6">
      {/* Balances */}
      <div>
        <h2 className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Polymarket Balances</h2>
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'USDC Balance', value: `$${fmt(polymarket.balance)}` },
            { label: 'Position Value', value: `$${fmt(polymarket.position_value)}` },
            { label: 'Total', value: `$${fmt(polymarket.total)}` },
            { label: 'Last Trade', value: polymarket.last_live_trade_ts || '—' },
          ].map(stat => (
            <div key={stat.label} className="bg-neutral-900 border border-neutral-800 px-3 py-2">
              <div className="text-[9px] text-neutral-500 uppercase tracking-wider mb-1">{stat.label}</div>
              <div className="text-sm text-white font-mono tabular-nums">{stat.value}</div>
            </div>
          ))}
        </div>
        {polymarket.dry_run_warning && (
          <div className="mt-2 px-3 py-1.5 bg-amber-500/10 border border-amber-500/20 text-[10px] text-amber-400">
            ⚠ Dry run mode active — no real trades placed
          </div>
        )}
      </div>

      {/* Lifetime stats */}
      <div>
        <h2 className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Lifetime Stats</h2>
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: 'Deposited', value: `$${fmt(lifetime.poly_deposited)}` },
            { label: 'Lifetime P&L', value: `${lifetime.poly_lifetime_pnl >= 0 ? '+' : ''}$${fmt(lifetime.poly_lifetime_pnl)}`, color: pnlColor(lifetime.poly_lifetime_pnl) },
            { label: 'Current Total', value: `$${fmt(polymarket.total)}` },
          ].map(stat => (
            <div key={stat.label} className="bg-neutral-900 border border-neutral-800 px-3 py-2">
              <div className="text-[9px] text-neutral-500 uppercase tracking-wider mb-1">{stat.label}</div>
              <div className={`text-sm font-mono tabular-nums ${stat.color ?? 'text-white'}`}>{stat.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Positions */}
      <div>
        <h2 className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Open Positions</h2>
        {positions.length === 0 ? (
          <div className="border border-neutral-800 px-4 py-6 text-center text-[10px] text-neutral-600">No open positions</div>
        ) : (
          <div className="border border-neutral-800 overflow-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900">
                  {['Title', 'Outcome', 'Size', 'Avg Price', 'Current Price', 'P&L'].map(h => (
                    <th key={h} className="px-3 py-1.5 text-left text-[9px] text-neutral-500 uppercase tracking-wider font-normal whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.map((p: PolyPosition, i: number) => (
                  <tr key={p.token_id || i} className="border-b border-neutral-800/60 hover:bg-neutral-900/40">
                    <td className="px-3 py-1.5 text-neutral-300 max-w-[300px]">
                      <span title={p.title}>{p.title.length > 60 ? p.title.slice(0, 60) + '…' : p.title}</span>
                    </td>
                    <td className="px-3 py-1.5">
                      <span className={`px-1 py-0.5 text-[8px] font-bold uppercase ${p.outcome.toLowerCase() === 'yes' ? 'bg-green-500/10 text-green-400 border border-green-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
                        {p.outcome}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 tabular-nums text-neutral-300">{fmt(p.size, 2)}</td>
                    <td className="px-3 py-1.5 tabular-nums text-neutral-400">${fmt(p.avg_price, 3)}</td>
                    <td className="px-3 py-1.5 tabular-nums text-neutral-300">${fmt(p.current_price, 3)}</td>
                    <td className={`px-3 py-1.5 tabular-nums ${pnlColor(p.pnl)}`}>
                      {p.pnl >= 0 ? '+' : ''}${fmt(p.pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Main App ─────────────────────────────────────────────────────────────────
function App() {
  const queryClient = useQueryClient()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [tab, setTab] = useState<Tab>('overview')

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['liveData'],
    queryFn: fetchLiveData,
    refetchInterval: 10000,
  })

  const { data: weatherStatus } = useQuery({
    queryKey: ['weatherStatus'],
    queryFn: fetchWeatherStatus,
    refetchInterval: 10000,
  })

  const scanMutation = useMutation({
    mutationFn: runScan,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['liveData'] }),
  })

  const startMutation = useMutation({
    mutationFn: startBot,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['liveData'] }),
  })

  const stopMutation = useMutation({
    mutationFn: stopBot,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['liveData'] }),
  })

  // Derive state from live data
  const liveData = data as LiveData | undefined
  const isRunning = liveData?.system?.services?.some(s => s.running) ?? false
  const v2Signals = liveData?.metar_v2_signals ?? []
  const weatherSignals = liveData?.weather_signals ?? []
  const weatherForecasts = liveData?.weather_forecasts ?? []

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
          <button onClick={() => refetch()} className="px-3 py-1.5 bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs uppercase tracking-wider">
            Retry
          </button>
        </div>
      </div>
    )
  }

  const TABS: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'kalshi', label: 'Kalshi' },
    { id: 'polymarket', label: 'Polymarket' },
  ]

  return (
    <div className="h-screen bg-black text-neutral-200 flex flex-col overflow-hidden">
      {/* HEADER */}
      <motion.header
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="shrink-0 border-b border-neutral-800 px-3 py-1.5 flex items-center gap-4 relative"
      >
        <div className="scan-line" />

        {/* Title + status badges */}
        <div className="flex items-center gap-2 shrink-0">
          <h1 className="text-sm font-bold text-white uppercase tracking-widest whitespace-nowrap" style={{fontFamily: "'Inter', sans-serif", letterSpacing: '0.2em'}}>
            WEATHER EDGE
          </h1>
          <span className={`px-1.5 py-0.5 text-[9px] font-bold uppercase ${isRunning ? 'bg-green-500/10 text-green-500 border border-green-500/20' : 'bg-neutral-800 text-neutral-500 border border-neutral-700'}`}>
            {isRunning ? 'Live' : 'Idle'}
          </span>
          <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            GFS+METAR
          </span>
        </div>

        {/* Tab nav */}
        <nav className="flex items-end gap-0 h-full shrink-0">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1 text-[11px] uppercase tracking-wider transition-colors border-b-2 ${
                tab === t.id
                  ? 'text-white border-white'
                  : 'text-neutral-500 border-transparent hover:text-neutral-300'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div className="flex-1" />

        {/* Right side controls */}
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => scanMutation.mutate()}
            disabled={scanMutation.isPending}
            className="px-2.5 py-1 bg-neutral-900 border border-neutral-700 hover:border-neutral-600 text-neutral-300 text-[10px] uppercase tracking-wider transition-colors disabled:opacity-50"
          >
            {scanMutation.isPending ? 'Scanning...' : 'Scan Now'}
          </button>
          <button onClick={() => setSettingsOpen(true)} title="Settings" className="px-2 py-1 bg-neutral-900 border border-neutral-700 hover:border-neutral-600 text-neutral-400 hover:text-neutral-200 text-sm transition-colors leading-none">
            ⚙
          </button>
          <LiveClock />
        </div>
      </motion.header>

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}

      {/* TAB CONTENT */}
      {tab === 'overview' && (
        <div className="flex-1 min-h-0 grid grid-cols-[280px_1fr_520px] grid-rows-[1fr] gap-0">

          {/* LEFT COLUMN */}
          <div className="flex flex-col border-r border-neutral-800 min-h-0 overflow-hidden">
            {/* Signal engine info */}
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="shrink-0 border-b border-neutral-800 px-2 py-2">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Signal Engine</span>
                <span className="px-1 py-0.5 text-[8px] font-bold uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">GFS+METAR</span>
              </div>
              <div className="space-y-1.5">
                <div className="flex justify-between text-[10px]">
                  <span className="text-neutral-500">Model</span>
                  <span className="text-cyan-400">GFS 31-member ensemble</span>
                </div>
                <div className="flex justify-between text-[10px]">
                  <span className="text-neutral-500">Real-time</span>
                  <span className="text-cyan-400">METAR lock detection</span>
                </div>
                <div className="flex justify-between text-[10px]">
                  <span className="text-neutral-500">V2 signals</span>
                  <span className="text-amber-400">{v2Signals.length} detected</span>
                </div>
                <div className="flex justify-between text-[10px]">
                  <span className="text-neutral-500">Actionable</span>
                  <span className={v2Signals.filter(s => s.recommend).length > 0 ? 'text-green-400' : 'text-neutral-600'}>
                    {v2Signals.filter(s => s.recommend).length} recommended
                  </span>
                </div>
                <div className="flex justify-between text-[10px]">
                  <span className="text-neutral-500">Fee estimate</span>
                  <span className="text-neutral-400">~7% Kalshi</span>
                </div>
              </div>
            </motion.div>

            {/* Weather freshness / nowcast SLO */}
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="shrink-0 border-b border-neutral-800 px-2 py-2">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Weather Status</span>
                <span className={`px-1 py-0.5 text-[8px] font-bold uppercase ${weatherStatus?.enabled ? 'bg-green-500/10 text-green-400 border border-green-500/20' : 'bg-neutral-800 text-neutral-500 border border-neutral-700'}`}>
                  {weatherStatus?.enabled ? 'Nowcast' : 'Disabled'}
                </span>
              </div>
              <div className="space-y-1.5">
                <div className="flex justify-between text-[10px]">
                  <span className="text-neutral-500">Next fast</span>
                  <span className="text-cyan-400 tabular-nums">{fmtAge(weatherStatus?.next_fast_scan_in_seconds)}</span>
                </div>
                <div className="flex justify-between text-[10px]">
                  <span className="text-neutral-500">Obs age</span>
                  <span className="text-cyan-400 tabular-nums">{fmtAge(weatherStatus?.last_observation_age_seconds)}</span>
                </div>
                <div className="flex justify-between text-[10px]">
                  <span className="text-neutral-500">Station</span>
                  <span className="text-neutral-400 tabular-nums">{weatherStatus?.last_observation?.station_id || '—'}</span>
                </div>
                <div className="flex justify-between text-[10px]">
                  <span className="text-neutral-500">Last change</span>
                  <span className="text-neutral-400 tabular-nums">{String(weatherStatus?.last_change?.state || '—')}</span>
                </div>
              </div>
            </motion.div>

            {/* Edge distribution */}
            <div className="border-b border-neutral-800" style={{ height: '28%', minHeight: '120px' }}>
              <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Edge Distribution</span>
              </div>
              <div className="h-[calc(100%-24px)] p-1">
                <EdgeDistribution btcSignals={[]} weatherSignals={weatherSignals} />
              </div>
            </div>

            {/* Terminal */}
            <div className="flex-1 min-h-0">
              <Terminal
                isRunning={isRunning}
                lastRun={null}
                stats={{ total_trades: 0, total_pnl: liveData?.lifetime?.lifetime_pnl ?? 0 }}
                onStart={() => startMutation.mutate()}
                onStop={() => stopMutation.mutate()}
                onScan={() => scanMutation.mutate()}
              />
            </div>
          </div>

          {/* CENTER COLUMN */}
          <div className="flex flex-col min-h-0 border-r border-neutral-800">
            <div className="relative flex-1 min-h-0">
              <div className="absolute inset-0 flex items-center justify-center">
                <Suspense fallback={
                  <div className="w-full h-full flex items-center justify-center bg-black">
                    <span className="text-[10px] text-neutral-600 uppercase tracking-wider">Loading Globe...</span>
                  </div>
                }>
                  <GlobeView forecasts={weatherForecasts} signals={weatherSignals} />
                </Suspense>
              </div>
              <div className="absolute top-2 left-2 z-10">
                <div className="px-2 py-1 bg-black/80 border border-neutral-800 text-[10px]">
                  <span className="text-neutral-500 uppercase tracking-wider mr-2">V2 Signals</span>
                  <span className="text-amber-500 tabular-nums">{v2Signals.filter(s => s.recommend).length} recommended</span>
                </div>
              </div>
            </div>
          </div>

          {/* RIGHT COLUMN — V2 Signals + legacy signals */}
          <div className="flex flex-col min-h-0 overflow-hidden">
            <V2SignalsPanel signals={v2Signals} />
            <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Weather Signals</span>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0">
              <SignalsTable signals={[]} weatherSignals={weatherSignals} onSimulateTrade={() => {}} isSimulating={false} />
            </div>
          </div>
        </div>
      )}

      {tab === 'kalshi' && (
        <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
          <KalshiMarketsTab />
        </div>
      )}

      {tab === 'polymarket' && (
        <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
          <PolyMarketsTab />
        </div>
      )}

      {/* FOOTER */}
      <footer className="shrink-0 border-t border-neutral-800 px-3 py-0.5 flex items-center justify-between">
        <span className="text-[10px] text-neutral-700 font-mono">
          Open-Meteo GFS Ensemble · METAR Real-Time · Kalshi + Polymarket
        </span>
        <div className="flex items-center gap-3">
          <RefreshBar interval={10000} />
          <span className="text-[10px] text-neutral-700 font-mono">Weather Edge v2.0</span>
          <div className="flex items-center gap-1">
            <div className={`w-1.5 h-1.5 rounded-full ${liveData?.system?.socks_up ? 'bg-green-500' : 'bg-red-500'}`} />
            <span className="text-[10px] text-neutral-600 font-mono">{liveData?.system?.socks_up ? 'SOCKS OK' : 'SOCKS DOWN'}</span>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
