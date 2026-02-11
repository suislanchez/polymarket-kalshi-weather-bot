import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine
} from 'recharts'
import type { EquityPoint } from '../types'

interface Props {
  data: EquityPoint[]
  initialBankroll: number
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload || !payload.length) return null

  const value = payload[0].value
  const isPositive = value >= 0

  return (
    <div className="bg-neutral-900 border border-neutral-800 p-3">
      <p className="text-xs text-neutral-500 mb-1">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${isPositive ? 'text-green-500' : 'text-red-500'}`}>
        {isPositive ? '+' : ''}${value.toFixed(2)}
      </p>
    </div>
  )
}

export function EquityChart({ data, initialBankroll }: Props) {
  if (data.length === 0) {
    return (
      <div className="h-[220px] flex flex-col items-center justify-center text-neutral-600">
        <div className="text-4xl mb-4 opacity-30">📈</div>
        <p className="text-sm">No trade history</p>
        <p className="text-xs mt-1">Equity curve will appear after settled trades</p>
      </div>
    )
  }

  // Add starting point
  const chartData = [
    { timestamp: 'Start', pnl: 0, bankroll: initialBankroll },
    ...data.map(d => ({
      ...d,
      timestamp: new Date(d.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    }))
  ]

  const currentPnl = data.length > 0 ? data[data.length - 1].pnl : 0
  const isPositive = currentPnl >= 0
  const minPnl = Math.min(0, ...data.map(d => d.pnl))
  const maxPnl = Math.max(0, ...data.map(d => d.pnl))
  const padding = Math.max(Math.abs(minPnl), Math.abs(maxPnl)) * 0.2

  return (
    <div className="h-[220px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="colorPnl" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="5%"
                stopColor={isPositive ? '#22c55e' : '#ef4444'}
                stopOpacity={0.2}
              />
              <stop
                offset="95%"
                stopColor={isPositive ? '#22c55e' : '#ef4444'}
                stopOpacity={0}
              />
            </linearGradient>
          </defs>

          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#1a1a1a"
            vertical={false}
          />

          <XAxis
            dataKey="timestamp"
            stroke="#525252"
            fontSize={10}
            tickLine={false}
            axisLine={false}
            dy={10}
          />

          <YAxis
            stroke="#525252"
            fontSize={10}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => `$${value}`}
            domain={[minPnl - padding, maxPnl + padding]}
            dx={-10}
          />

          <Tooltip content={<CustomTooltip />} />

          <ReferenceLine
            y={0}
            stroke="#262626"
            strokeDasharray="3 3"
          />

          <Area
            type="monotone"
            dataKey="pnl"
            stroke={isPositive ? '#22c55e' : '#ef4444'}
            strokeWidth={1.5}
            fill="url(#colorPnl)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
