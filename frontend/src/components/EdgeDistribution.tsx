import { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import type { WeatherSignal } from '../types'

interface Props {
  weatherSignals: WeatherSignal[]
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
      {payload.map((p: any) => <p key={p.name} className="text-[10px] tabular-nums" style={{ color: p.color }}>{p.name}: {p.value}</p>)}
    </div>
  )
}

export function EdgeDistribution({ weatherSignals }: Props) {
  const data = useMemo(() => {
    const counts: Record<string, { actionable: number; monitor: number }> = {}
    BUCKETS.forEach(b => { counts[b] = { actionable: 0, monitor: 0 } })
    weatherSignals.forEach(s => {
      const bucket = getBucket(s.edge)
      if (s.actionable) counts[bucket].actionable++
      else counts[bucket].monitor++
    })
    return BUCKETS.map(bucket => ({ bucket, Actionable: counts[bucket].actionable, Monitor: counts[bucket].monitor }))
  }, [weatherSignals])

  if (weatherSignals.length === 0) {
    return <div className="h-full flex items-center justify-center text-neutral-600 text-[10px]">No weather signals for distribution</div>
  }

  return (
    <div className="h-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" vertical={false} />
          <XAxis dataKey="bucket" stroke="#525252" fontSize={9} tickLine={false} axisLine={false} fontFamily="JetBrains Mono" />
          <YAxis stroke="#525252" fontSize={9} tickLine={false} axisLine={false} allowDecimals={false} fontFamily="JetBrains Mono" />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="Monitor" stackId="a" fill="#d97706" radius={[0, 0, 0, 0]} />
          <Bar dataKey="Actionable" stackId="a" fill="#06b6d4" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
