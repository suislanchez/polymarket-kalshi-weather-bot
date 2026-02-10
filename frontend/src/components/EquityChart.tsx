import { motion } from 'framer-motion'
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
import { TrendingUp, BarChart3 } from 'lucide-react'
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
    <div className="glass-card p-3 border border-gray-700">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      <p className={`text-lg font-bold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
        {isPositive ? '+' : ''}${value.toFixed(2)}
      </p>
    </div>
  )
}

export function EquityChart({ data, initialBankroll }: Props) {
  if (data.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="h-[300px] flex flex-col items-center justify-center text-gray-400"
      >
        <BarChart3 className="w-16 h-16 mb-4 opacity-20" />
        <p className="text-lg">No trade history</p>
        <p className="text-sm mt-1 opacity-60">Equity curve will appear after settled trades</p>
      </motion.div>
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
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="h-[300px]"
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="colorPnl" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="5%"
                stopColor={isPositive ? '#10b981' : '#ef4444'}
                stopOpacity={0.3}
              />
              <stop
                offset="95%"
                stopColor={isPositive ? '#10b981' : '#ef4444'}
                stopOpacity={0}
              />
            </linearGradient>
          </defs>

          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#1f2937"
            vertical={false}
          />

          <XAxis
            dataKey="timestamp"
            stroke="#4b5563"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            dy={10}
          />

          <YAxis
            stroke="#4b5563"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => `$${value}`}
            domain={[minPnl - padding, maxPnl + padding]}
            dx={-10}
          />

          <Tooltip content={<CustomTooltip />} />

          <ReferenceLine
            y={0}
            stroke="#4b5563"
            strokeDasharray="3 3"
          />

          <Area
            type="monotone"
            dataKey="pnl"
            stroke={isPositive ? '#10b981' : '#ef4444'}
            strokeWidth={2}
            fill="url(#colorPnl)"
            animationDuration={1000}
          />
        </AreaChart>
      </ResponsiveContainer>
    </motion.div>
  )
}
