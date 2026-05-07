import { useState, useEffect, Suspense, lazy } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { fetchLiveData, runScan, startBot, stopBot } from './api'
import type { LiveData, WeatherSignal } from './types'
import { SignalsTable } from './components/SignalsTable'
import { Terminal } from './components/Terminal'
import { EdgeDistribution } from './components/EdgeDistribution'
import { SettingsModal } from './components/SettingsModal'
import { KalshiMarketsTab } from './components/KalshiMarketsTab'

const GlobeView = lazy(() => import('./components/GlobeView').then(m => ({ default: m.GlobeView })))

type Tab = 'overview' | 'kalshi'

function LiveClock() {
  const [time, setTime] = useState(new Date())
  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])
  return <span className="text-xs tabular-nums text-neutral-400">{time.toLocaleTimeString('en-US', { hour12: false })}</span>
}

function RefreshBar({ interval }: { interval: number }) {
  const [progress, setProgress] = useState(100)
  useEffect(() => {
    setProgress(100)
    const step = 100 / (interval / 1000)
    const timer = setInterval(() => setProgress(p => Math.max(0, p - step)), 1000)
    return () => clearInterval(timer)
  }, [interval])
  return <div className="refresh-bar w-16"><div className="refresh-fill" style={{ width: `${progress}%` }} /></div>
}

function fmt(n: number, decimals = 2) {
  return n.toFixed(decimals)
}

function WeatherLocksPanel({ signals }: { signals: WeatherSignal[] }) {
  const recommended = [...signals].filter(s => s.actionable && s.signal_source === 'METAR-lock').sort((a, b) => Math.abs(b.edge) - Math.abs(a.edge))
  return (
    <div className="shrink-0 border-b border-neutral-800">
      <div className="px-2 py-1 border-b border-neutral-800 flex items-center gap-2">
        <span className="text-[10px] text-amber-400/80 uppercase tracking-wider">METAR Lock Signals</span>
        {recommended.length > 0 && <span className="ml-auto text-[10px] text-amber-400 tabular-nums">{recommended.length} actionable</span>}
      </div>
      {recommended.length === 0 ? (
        <div className="px-2 py-2 text-[10px] text-neutral-600">No actionable locks</div>
      ) : (
        <div className="max-h-[220px] overflow-y-auto">
          {recommended.slice(0, 12).map(sig => (
            <div key={sig.market_id} className="px-2 py-1.5 border-b border-neutral-800/60 hover:bg-neutral-900/40 transition-colors">
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className="text-[10px] font-semibold text-amber-300">{sig.city_name}</span>
                <span className={`px-1 py-0.5 text-[8px] font-bold uppercase ${sig.direction === 'yes' ? 'bg-green-500/10 text-green-400 border border-green-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>{sig.direction}</span>
                <span className="px-1 py-0.5 text-[8px] font-bold uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">{sig.signal_source || 'GFS'}</span>
                <span className="ml-auto text-[10px] text-green-400 tabular-nums">{(sig.edge * 100).toFixed(1)}%</span>
                <span className="text-[10px] text-neutral-500 tabular-nums">{(sig.confidence * 100).toFixed(0)}%</span>
              </div>
              <div className="text-[9px] text-neutral-500 leading-tight truncate">{sig.reasoning.length > 90 ? sig.reasoning.slice(0, 90) + '…' : sig.reasoning}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function App() {
  const queryClient = useQueryClient()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [tab, setTab] = useState<Tab>('overview')

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['liveData'],
    queryFn: fetchLiveData,
    refetchInterval: 10000,
  })

  const scanMutation = useMutation({ mutationFn: runScan, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['liveData'] }) })
  const startMutation = useMutation({ mutationFn: startBot, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['liveData'] }) })
  const stopMutation = useMutation({ mutationFn: stopBot, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['liveData'] }) })

  const liveData = data as LiveData | undefined
  const isRunning = liveData?.system?.services?.some(s => s.running) ?? false
  const weatherSignals = liveData?.weather_signals ?? []
  const weatherForecasts = liveData?.weather_forecasts ?? []
  const actionableCount = weatherSignals.filter(s => s.actionable).length
  const cacheAge = liveData?.system?.signal_cache_age_seconds

  if (isLoading) {
    return <div className="h-screen bg-black flex items-center justify-center"><div className="text-center"><div className="relative w-10 h-10 mx-auto mb-4"><div className="absolute inset-0 border-2 border-neutral-800 rounded-full" /><div className="absolute inset-0 border-2 border-transparent border-t-green-500 rounded-full animate-spin" /></div><div className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">Initializing</div></div></div>
  }

  if (error || !data) {
    return <div className="h-screen bg-black flex items-center justify-center"><div className="text-center"><div className="text-red-500 text-xs uppercase mb-2 tracking-wider">Connection Error</div><button onClick={() => refetch()} className="px-3 py-1.5 bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs uppercase tracking-wider">Retry</button></div></div>
  }

  const TABS: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'kalshi', label: 'Kalshi Markets' },
  ]

  return (
    <div className="h-screen bg-black text-neutral-200 flex flex-col overflow-hidden">
      <motion.header initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="shrink-0 border-b border-neutral-800 px-3 py-1.5 flex items-center gap-4 relative">
        <div className="scan-line" />
        <div className="flex items-center gap-2 shrink-0">
          <h1 className="text-sm font-bold text-white uppercase tracking-widest whitespace-nowrap" style={{fontFamily: "'Inter', sans-serif", letterSpacing: '0.2em'}}>WEATHER EDGE</h1>
          <span className={`px-1.5 py-0.5 text-[9px] font-bold uppercase ${isRunning ? 'bg-green-500/10 text-green-500 border border-green-500/20' : 'bg-neutral-800 text-neutral-500 border border-neutral-700'}`}>{isRunning ? 'Live' : 'Idle'}</span>
          <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">GFS+METAR</span>
        </div>
        <nav className="flex items-end gap-0 h-full shrink-0">
          {TABS.map(t => <button key={t.id} onClick={() => setTab(t.id)} className={`px-3 py-1 text-[11px] uppercase tracking-wider transition-colors border-b-2 ${tab === t.id ? 'text-white border-white' : 'text-neutral-500 border-transparent hover:text-neutral-300'}`}>{t.label}</button>)}
        </nav>
        <div className="flex-1" />
        <div className="flex items-center gap-2 shrink-0">
          <button onClick={() => scanMutation.mutate()} disabled={scanMutation.isPending} className="px-2.5 py-1 bg-neutral-900 border border-neutral-700 hover:border-neutral-600 text-neutral-300 text-[10px] uppercase tracking-wider transition-colors disabled:opacity-50">{scanMutation.isPending ? 'Scanning...' : 'Scan Now'}</button>
          <button onClick={() => setSettingsOpen(true)} title="Settings" className="px-2 py-1 bg-neutral-900 border border-neutral-700 hover:border-neutral-600 text-neutral-400 hover:text-neutral-200 text-sm transition-colors leading-none">⚙</button>
          <LiveClock />
        </div>
      </motion.header>
      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}

      {tab === 'overview' && (
        <div className="flex-1 min-h-0 grid grid-cols-[280px_1fr_520px] grid-rows-[1fr] gap-0">
          <div className="flex flex-col border-r border-neutral-800 min-h-0 overflow-hidden">
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="shrink-0 border-b border-neutral-800 px-2 py-2">
              <div className="flex items-center justify-between mb-2"><span className="text-[10px] text-neutral-500 uppercase tracking-wider">Signal Engine</span><span className="px-1 py-0.5 text-[8px] font-bold uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">Weather-only</span></div>
              <div className="space-y-1.5">
                <div className="flex justify-between text-[10px]"><span className="text-neutral-500">Model</span><span className="text-cyan-400">GFS ensemble</span></div>
                <div className="flex justify-between text-[10px]"><span className="text-neutral-500">Lock rule</span><span className="text-cyan-400">METAR on way down</span></div>
                <div className="flex justify-between text-[10px]"><span className="text-neutral-500">Signals</span><span className="text-amber-400">{weatherSignals.length} detected</span></div>
                <div className="flex justify-between text-[10px]"><span className="text-neutral-500">Actionable</span><span className={actionableCount > 0 ? 'text-green-400' : 'text-neutral-600'}>{actionableCount} recommended</span></div>
                <div className="flex justify-between text-[10px]"><span className="text-neutral-500">Cache age</span><span className="text-neutral-400">{cacheAge == null ? 'never' : `${Math.round(cacheAge)}s`}</span></div>
              </div>
            </motion.div>
            <div className="border-b border-neutral-800" style={{ height: '28%', minHeight: '120px' }}><div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0"><span className="text-[10px] text-neutral-500 uppercase tracking-wider">Edge Distribution</span></div><div className="h-[calc(100%-24px)] p-1"><EdgeDistribution weatherSignals={weatherSignals} /></div></div>
            <div className="flex-1 min-h-0"><Terminal isRunning={isRunning} lastRun={null} stats={{ total_trades: 0, total_pnl: liveData?.lifetime?.lifetime_pnl ?? 0 }} onStart={() => startMutation.mutate()} onStop={() => stopMutation.mutate()} onScan={() => scanMutation.mutate()} /></div>
          </div>
          <div className="flex flex-col min-h-0 border-r border-neutral-800"><div className="relative flex-1 min-h-0"><div className="absolute inset-0 flex items-center justify-center"><Suspense fallback={<div className="w-full h-full flex items-center justify-center bg-black"><span className="text-[10px] text-neutral-600 uppercase tracking-wider">Loading Globe...</span></div>}><GlobeView forecasts={weatherForecasts} signals={weatherSignals} /></Suspense></div><div className="absolute top-2 left-2 z-10"><div className="px-2 py-1 bg-black/80 border border-neutral-800 text-[10px]"><span className="text-neutral-500 uppercase tracking-wider mr-2">Weather Signals</span><span className="text-amber-500 tabular-nums">{actionableCount} actionable</span></div></div></div></div>
          <div className="flex flex-col min-h-0 overflow-hidden"><WeatherLocksPanel signals={weatherSignals} /><div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0"><span className="text-[10px] text-neutral-500 uppercase tracking-wider">All Weather Signals</span></div><div className="flex-1 overflow-y-auto min-h-0"><SignalsTable weatherSignals={weatherSignals} /></div></div>
        </div>
      )}
      {tab === 'kalshi' && <div className="flex-1 min-h-0 overflow-hidden flex flex-col"><KalshiMarketsTab /></div>}
      <footer className="shrink-0 border-t border-neutral-800 px-3 py-0.5 flex items-center justify-between"><span className="text-[10px] text-neutral-700 font-mono">Open-Meteo GFS Ensemble · METAR Real-Time · Kalshi Weather</span><div className="flex items-center gap-3"><RefreshBar interval={10000} /><span className="text-[10px] text-neutral-700 font-mono">Weather Edge v2.3</span><div className="flex items-center gap-1"><div className={`w-1.5 h-1.5 rounded-full ${liveData?.system?.kalshi_configured ? 'bg-green-500' : 'bg-amber-500'}`} /><span className="text-[10px] text-neutral-600 font-mono">{liveData?.system?.kalshi_configured ? 'KALSHI OK' : 'SIM MODE'}</span></div></div></footer>
    </div>
  )
}

export default App
