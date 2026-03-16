import { useRef, useState, useEffect, useCallback } from 'react'
import { Settings, Wifi, WifiOff, Activity } from 'lucide-react'
import type { CalibrationSummary } from '../types'

interface Props {
  calibration: CalibrationSummary | null
  isRunning: boolean
  simulationMode: boolean
}

interface LogEntry {
  timestamp: string
  type: string
  message: string
}

const API_URL = import.meta.env.VITE_API_URL || `${window.location.protocol}//${window.location.hostname}:8000`
const WS_URL = API_URL.replace(/^http/, 'ws') + '/ws/events'

const logColors: Record<string, string> = {
  success: 'text-green-400',
  error: 'text-red-400',
  warning: 'text-amber-400',
  trade: 'text-purple-400',
  data: 'text-blue-400',
  info: 'text-neutral-400',
}

export function SystemTab({ calibration, isRunning, simulationMode }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [wsConnected, setWsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchEvents = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/events?limit=50`)
      if (res.ok) {
        const events = await res.json()
        setLogs(events.filter((e: LogEntry) => e.type !== 'heartbeat'))
      }
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    const connectWs = () => {
      try {
        const ws = new WebSocket(WS_URL)
        wsRef.current = ws
        ws.onopen = () => setWsConnected(true)
        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)
            if (data.type === 'heartbeat') return
            setLogs(prev => [...prev.slice(-100), data])
          } catch {
            // ignore
          }
        }
        ws.onclose = () => {
          setWsConnected(false)
          wsRef.current = null
          reconnectTimeoutRef.current = setTimeout(connectWs, 5000)
        }
        ws.onerror = () => ws.close()
      } catch {
        setWsConnected(false)
      }
    }

    fetchEvents()
    connectWs()

    return () => {
      if (wsRef.current) wsRef.current.close()
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
    }
  }, [fetchEvents])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  return (
    <div className="overflow-y-auto max-h-[calc(100vh-120px)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-800">
        <div className="flex items-center gap-2">
          <Settings className="w-4 h-4 text-neutral-400" />
          <span className="text-sm font-medium">System</span>
        </div>
        <div className="flex items-center gap-2">
          {wsConnected ? (
            <span className="flex items-center gap-1 text-[10px] text-green-400"><Wifi className="w-3 h-3" /> Live</span>
          ) : (
            <span className="flex items-center gap-1 text-[10px] text-neutral-500"><WifiOff className="w-3 h-3" /> Polling</span>
          )}
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* Status Cards */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-[#0a0a0a] border border-neutral-800 rounded-lg p-3">
            <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">Bot Status</div>
            <div className={`text-sm font-medium ${isRunning ? 'text-green-400' : 'text-neutral-500'}`}>
              {isRunning ? 'Running' : 'Paused'}
            </div>
          </div>
          <div className="bg-[#0a0a0a] border border-neutral-800 rounded-lg p-3">
            <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">Mode</div>
            <div className={`text-sm font-medium ${simulationMode ? 'text-amber-400' : 'text-green-400'}`}>
              {simulationMode ? 'Simulation' : 'Live Trading'}
            </div>
          </div>
        </div>

        {/* Kalshi Connection */}
        <div className="bg-[#0a0a0a] border border-neutral-800 rounded-lg p-3">
          <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-2">Kalshi API</div>
          <KalshiStatus />
        </div>

        {/* Calibration */}
        {calibration && calibration.total_with_outcome > 0 && (
          <div className="bg-[#0a0a0a] border border-neutral-800 rounded-lg p-4">
            <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-3">Model Calibration</div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-[10px] text-neutral-600">Accuracy</div>
                <div className={`text-lg font-mono font-semibold ${
                  calibration.accuracy >= 0.55 ? 'text-green-400' : calibration.accuracy < 0.5 ? 'text-red-400' : 'text-neutral-300'
                }`}>
                  {(calibration.accuracy * 100).toFixed(0)}%
                </div>
              </div>
              <div>
                <div className="text-[10px] text-neutral-600">Brier Score</div>
                <div className={`text-lg font-mono font-semibold ${
                  calibration.brier_score <= 0.2 ? 'text-green-400' : calibration.brier_score <= 0.25 ? 'text-amber-400' : 'text-red-400'
                }`}>
                  {calibration.brier_score.toFixed(3)}
                </div>
              </div>
              <div>
                <div className="text-[10px] text-neutral-600">Predicted Edge</div>
                <div className="text-sm font-mono text-neutral-300">
                  {(calibration.avg_predicted_edge * 100).toFixed(1)}%
                </div>
              </div>
              <div>
                <div className="text-[10px] text-neutral-600">Actual Edge</div>
                <div className={`text-sm font-mono ${calibration.avg_actual_edge >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {(calibration.avg_actual_edge * 100).toFixed(1)}%
                </div>
              </div>
            </div>
            <div className="text-[10px] text-neutral-600 mt-2">
              {calibration.total_with_outcome} settled / {calibration.total_signals} total signals
            </div>
          </div>
        )}

        {/* Terminal */}
        <div className="bg-[#0a0a0a] border border-neutral-800 rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-neutral-800">
            <div className="flex items-center gap-2">
              <Activity className="w-3 h-3 text-neutral-500" />
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Event Log</span>
            </div>
            <span className="text-[10px] text-neutral-600">{logs.length} events</span>
          </div>
          <div
            ref={scrollRef}
            className="h-64 md:h-80 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed"
          >
            {logs.length === 0 ? (
              <div className="text-neutral-700">Waiting for events...</div>
            ) : (
              logs.map((log, i) => (
                <div key={i} className="py-0.5">
                  <span className="text-neutral-700">{new Date(log.timestamp).toLocaleTimeString('en-US', { hour12: false })}</span>
                  {' '}
                  <span className={logColors[log.type] || 'text-neutral-400'}>{log.message}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function KalshiStatus() {
  const [status, setStatus] = useState<{ connected: boolean; error?: string } | null>(null)

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const API = import.meta.env.VITE_API_URL || `${window.location.protocol}//${window.location.hostname}:8000`
        const res = await fetch(`${API}/api/kalshi/status`)
        if (res.ok) {
          setStatus(await res.json())
        }
      } catch {
        setStatus({ connected: false, error: 'Failed to check' })
      }
    }
    checkStatus()
  }, [])

  if (!status) return <span className="text-[11px] text-neutral-600">Checking...</span>

  return (
    <div className="flex items-center gap-2">
      <div className={`w-2 h-2 rounded-full ${status.connected ? 'bg-green-500' : 'bg-red-500'}`} />
      <span className={`text-[11px] ${status.connected ? 'text-green-400' : 'text-red-400'}`}>
        {status.connected ? 'Connected' : status.error || 'Disconnected'}
      </span>
    </div>
  )
}
