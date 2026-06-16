import { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import type { Signal, WeatherSignal } from '../types'

interface Props {
  btcSignals: Signal[]
  weatherSignals: WeatherSignal[]
  showLegacySections?: boolean
}

const BUCKETS = ['0-2%', '2-5%', '5-10%', '10-20%', '20%+']

function getBucket(edge: number): string {
  const pct = Math.abs(edge) * 100
  if (pct < 2) return '0-2%'
  if (pct < 5) return '2-5%'
  if (pct < 10) return '5-10%'
  if (pct < 20) return '10-20%'
  return '20%+'
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload || !payload.length) return null
  return (
    <div className="bg-neutral-900 border border-neutral-800 px-2 py-1.5">
      <p className="text-[10px] text-neutral-400 mb-1">{label}</p>
      {payload.map((p: any) => (
        <p key={p.name} className="text-[10px] tabular-nums" style={{ color: p.color }}>
          {p.name}: {p.value}
        </p>
      ))}
    </div>
  )
}

export function EdgeDistribution({ btcSignals, weatherSignals, showLegacySections = false }: Props) {
  const data = useMemo(() => {
    const counts: Record<string, { btc: number; weather: number }> = {}
    BUCKETS.forEach(b => { counts[b] = { btc: 0, weather: 0 } })

    if (showLegacySections) {
      btcSignals.forEach(s => {
        const bucket = getBucket(s.edge)
        counts[bucket].btc++
      })
    }

    weatherSignals.forEach(s => {
      const bucket = getBucket(s.edge)
      counts[bucket].weather++
    })

    return BUCKETS.map(bucket => ({
      bucket,
      ...(showLegacySections ? { BTC: counts[bucket].btc } : {}),
      WX: counts[bucket].weather,
    }))
  }, [btcSignals, weatherSignals, showLegacySections])

  const total = (showLegacySections ? btcSignals.length : 0) + weatherSignals.length
  if (total === 0) {
    return (
      <div className="h-full flex items-center justify-center text-neutral-600 text-[10px]">
        No signals for distribution
      </div>
    )
  }

  return (
    <div className="h-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" vertical={false} />
          <XAxis
            dataKey="bucket"
            stroke="#525252"
            fontSize={9}
            tickLine={false}
            axisLine={false}
            fontFamily="JetBrains Mono"
          />
          <YAxis
            stroke="#525252"
            fontSize={9}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
            fontFamily="JetBrains Mono"
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            iconSize={8}
            wrapperStyle={{ fontSize: '9px', fontFamily: 'JetBrains Mono' }}
          />
          {showLegacySections && <Bar dataKey="BTC" stackId="a" fill="#d97706" radius={[0, 0, 0, 0]} />}
          <Bar dataKey="WX" stackId="a" fill="#06b6d4" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
