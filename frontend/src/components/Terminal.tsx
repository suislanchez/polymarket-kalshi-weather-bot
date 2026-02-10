import { useEffect, useRef, useState } from 'react'

interface LogEntry {
  timestamp: Date
  type: 'info' | 'success' | 'warning' | 'error' | 'data'
  message: string
}

interface Props {
  isRunning: boolean
  lastRun: string | null
  stats: {
    total_trades: number
    total_pnl: number
  }
}

const generateLogs = (isRunning: boolean, stats: any): LogEntry[] => {
  const logs: LogEntry[] = [
    { timestamp: new Date(Date.now() - 60000), type: 'info', message: 'System initialized' },
    { timestamp: new Date(Date.now() - 55000), type: 'info', message: 'Connecting to NWS API...' },
    { timestamp: new Date(Date.now() - 50000), type: 'success', message: 'NWS API connected' },
    { timestamp: new Date(Date.now() - 45000), type: 'info', message: 'Fetching ensemble data from Open-Meteo...' },
    { timestamp: new Date(Date.now() - 40000), type: 'success', message: 'Ensemble data loaded (51 models)' },
    { timestamp: new Date(Date.now() - 35000), type: 'info', message: 'Scanning Kalshi markets...' },
    { timestamp: new Date(Date.now() - 30000), type: 'data', message: `Found ${Math.floor(Math.random() * 20) + 10} active weather markets` },
    { timestamp: new Date(Date.now() - 25000), type: 'info', message: 'Running probability calculations...' },
    { timestamp: new Date(Date.now() - 20000), type: 'success', message: 'Signal generation complete' },
  ]

  if (stats.total_trades > 0) {
    logs.push({
      timestamp: new Date(Date.now() - 15000),
      type: 'data',
      message: `Portfolio P&L: ${stats.total_pnl >= 0 ? '+' : ''}$${stats.total_pnl.toFixed(2)}`
    })
  }

  if (isRunning) {
    logs.push({
      timestamp: new Date(Date.now() - 5000),
      type: 'info',
      message: 'Monitoring markets for opportunities...'
    })
    logs.push({
      timestamp: new Date(),
      type: 'success',
      message: 'Live trading active'
    })
  }

  return logs
}

export function Terminal({ isRunning, lastRun, stats }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [cursorVisible, setCursorVisible] = useState(true)

  useEffect(() => {
    setLogs(generateLogs(isRunning, stats))
  }, [isRunning, stats])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  useEffect(() => {
    const interval = setInterval(() => {
      setCursorVisible(v => !v)
    }, 500)
    return () => clearInterval(interval)
  }, [])

  // Simulate new log entries
  useEffect(() => {
    if (!isRunning) return

    const interval = setInterval(() => {
      const newLogs: LogEntry[] = [
        { timestamp: new Date(), type: 'info', message: 'Polling market data...' },
        { timestamp: new Date(), type: 'data', message: `Latency: ${Math.floor(Math.random() * 50) + 10}ms` },
        { timestamp: new Date(), type: 'success', message: 'Market scan complete' },
        { timestamp: new Date(), type: 'info', message: 'Evaluating signals...' },
        { timestamp: new Date(), type: 'data', message: `Edge threshold: 8.0%` },
      ]
      const randomLog = newLogs[Math.floor(Math.random() * newLogs.length)]
      setLogs(prev => [...prev.slice(-50), randomLog])
    }, 3000)

    return () => clearInterval(interval)
  }, [isRunning])

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString('en-US', { hour12: false })
  }

  const getTypeColor = (type: LogEntry['type']) => {
    switch (type) {
      case 'success': return 'text-green-500'
      case 'error': return 'text-red-500'
      case 'warning': return 'text-amber-500'
      case 'data': return 'text-blue-500'
      default: return 'text-neutral-400'
    }
  }

  const getTypePrefix = (type: LogEntry['type']) => {
    switch (type) {
      case 'success': return '[OK]'
      case 'error': return '[ERR]'
      case 'warning': return '[WARN]'
      case 'data': return '[DATA]'
      default: return '[INFO]'
    }
  }

  return (
    <div className="terminal h-[250px] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-neutral-800">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full bg-red-500/80" />
            <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/80" />
            <div className="w-2.5 h-2.5 rounded-full bg-green-500/80" />
          </div>
          <span className="text-[10px] text-neutral-500 uppercase tracking-wider ml-2">System Log</span>
        </div>
        <div className="flex items-center gap-2">
          {isRunning && <div className="live-dot" />}
          <span className="text-[10px] text-neutral-600">
            {isRunning ? 'LIVE' : 'IDLE'}
          </span>
        </div>
      </div>

      {/* Log content */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-0.5">
        {logs.map((log, i) => (
          <div key={i} className="flex gap-2 text-xs leading-relaxed">
            <span className="text-neutral-600 tabular-nums shrink-0">
              {formatTime(log.timestamp)}
            </span>
            <span className={`shrink-0 ${getTypeColor(log.type)}`}>
              {getTypePrefix(log.type)}
            </span>
            <span className={getTypeColor(log.type)}>
              {log.message}
            </span>
          </div>
        ))}

        {/* Cursor line */}
        <div className="flex gap-2 text-xs">
          <span className="text-neutral-600 tabular-nums">
            {formatTime(new Date())}
          </span>
          <span className="text-green-500">{'>'}</span>
          <span className={`text-green-500 ${cursorVisible ? 'opacity-100' : 'opacity-0'}`}>_</span>
        </div>
      </div>

      {/* Footer */}
      <div className="px-3 py-2 border-t border-neutral-800 flex justify-between items-center">
        <span className="text-[10px] text-neutral-600">
          {lastRun ? `Last scan: ${new Date(lastRun).toLocaleTimeString()}` : 'No scans yet'}
        </span>
        <span className="text-[10px] text-neutral-600 tabular-nums">
          {logs.length} entries
        </span>
      </div>
    </div>
  )
}
