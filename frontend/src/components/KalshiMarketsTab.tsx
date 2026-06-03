import { useQuery } from '@tanstack/react-query'
import { fetchKalshiMarkets } from '../api'
import type { KalshiMarket } from '../types'

const STATUS_CONFIG = {
  bet_placed: {
    label: 'Bet Placed',
    color: 'bg-emerald-500/15 border-l-2 border-emerald-500',
    badge: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30',
    dot: 'bg-emerald-500',
    desc: 'Position entered, awaiting resolution',
  },
  watching_hot: {
    label: 'Hot Signal',
    color: 'bg-amber-500/10 border-l-2 border-amber-500',
    badge: 'bg-amber-500/20 text-amber-400 border border-amber-500/30',
    dot: 'bg-amber-500',
    desc: 'Strong edge detected — trigger imminent',
  },
  watching: {
    label: 'Watching',
    color: 'bg-sky-500/8 border-l-2 border-sky-700',
    badge: 'bg-sky-500/15 text-sky-400 border border-sky-500/25',
    dot: 'bg-sky-500',
    desc: 'Signal present, monitoring for entry',
  },
  flagged: {
    label: 'Flagged',
    color: 'bg-red-500/10 border-l-2 border-red-600',
    badge: 'bg-red-500/20 text-red-400 border border-red-500/30',
    dot: 'bg-red-500',
    desc: 'Informed trader detected — avoid',
  },
  neutral: {
    label: 'Neutral',
    color: '',
    badge: 'bg-neutral-800 text-neutral-500 border border-neutral-700',
    dot: 'bg-neutral-600',
    desc: 'No actionable edge — monitoring only',
  },
}

function StatusDot({ status }: { status: KalshiMarket['status'] }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.neutral
  return <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
}

function SideBadge({ side }: { side: string }) {
  return side === 'yes'
    ? <span className="text-[9px] font-bold px-1.5 py-0.5 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded">YES</span>
    : <span className="text-[9px] font-bold px-1.5 py-0.5 bg-red-500/20 text-red-400 border border-red-500/30 rounded">NO</span>
}

function pct(v: number | null, decimals = 1) {
  if (v == null) return '—'
  return `${(v * 100).toFixed(decimals)}%`
}

function temp(v: number | null) {
  if (v == null) return '—'
  return `${v.toFixed(1)}°F`
}

export function KalshiMarketsTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['kalshi-markets'],
    queryFn: fetchKalshiMarkets,
    refetchInterval: 30000,
  })

  if (isLoading) return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-[10px] text-neutral-500 uppercase tracking-wider">Loading markets…</div>
    </div>
  )

  if (error || !data) return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-[10px] text-red-500 uppercase tracking-wider">Failed to load markets</div>
    </div>
  )

  const { markets, count, traded_today_count } = data

  return (
    <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
      {/* Header stats */}
      <div className="shrink-0 border-b border-neutral-800 px-4 py-2 flex items-center gap-6">
        <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Kalshi Weather Markets</span>
        <span className="text-[10px] text-neutral-400 tabular-nums">{count} markets scanned</span>
        <span className="text-[10px] text-emerald-400 tabular-nums">{traded_today_count} bet today</span>
        <span className="text-[10px] text-amber-400 tabular-nums">{markets.filter(m => m.status === 'watching_hot').length} hot signals</span>
      </div>

      {/* Legend */}
      <div className="shrink-0 border-b border-neutral-800 px-4 py-1.5 flex items-center gap-4 flex-wrap">
        {(Object.entries(STATUS_CONFIG) as [string, typeof STATUS_CONFIG.neutral][]).map(([key, cfg]) => (
          <div key={key} className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${cfg.dot}`} />
            <span className="text-[9px] text-neutral-500">{cfg.label}</span>
            <span className="text-[9px] text-neutral-700">— {cfg.desc}</span>
          </div>
        ))}
      </div>

      {/* Column headers */}
      <div
        className="shrink-0 border-b border-neutral-800 px-4 py-1 grid text-[9px] text-neutral-600 uppercase tracking-wider font-semibold"
        style={{ gridTemplateColumns: '160px 1fr 70px 70px 70px 70px 80px 80px 140px' }}
      >
        <div>City</div>
        <div>Market Question</div>
        <div>Side</div>
        <div className="text-right">Curr °F</div>
        <div className="text-right">Conf</div>
        <div className="text-right">Mkt</div>
        <div className="text-right">EV Net</div>
        <div className="text-right">Entry ROI</div>
        <div className="text-right">Trigger</div>
      </div>

      {/* Market rows */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {markets.map((m) => {
          const cfg = STATUS_CONFIG[m.status] || STATUS_CONFIG.neutral
          return (
            <div
              key={m.condition_id}
              className={`grid px-4 py-1.5 border-b border-neutral-900 hover:bg-neutral-900/50 transition-colors text-[11px] ${cfg.color}`}
              style={{ gridTemplateColumns: '160px 1fr 70px 70px 70px 70px 80px 80px 140px' }}
            >
              <div className="flex items-center gap-1.5 min-w-0">
                <StatusDot status={m.status} />
                <span className="font-semibold text-neutral-200 truncate">{m.city}</span>
              </div>
              <div className="truncate text-neutral-400 pr-2" title={m.question}>
                {m.question.replace(/^Will the highest temperature in [^b]+be /, '').replace(/\?$/, '')}
              </div>
              <div><SideBadge side={m.side} /></div>
              <div className="text-right tabular-nums text-neutral-300">{temp(m.current_temp_f)}</div>
              <div className="text-right tabular-nums text-sky-400">{pct(m.confidence)}</div>
              <div className="text-right tabular-nums text-neutral-400">{pct(m.raw_price)}</div>
              <div className={`text-right tabular-nums font-semibold ${(m.ev_net ?? 0) > 0.3 ? 'text-emerald-400' : (m.ev_net ?? 0) > 0 ? 'text-amber-400' : 'text-red-400'}`}>
                {m.ev_net != null ? `+${(m.ev_net * 100).toFixed(1)}%` : '—'}
              </div>
              <div className="text-right tabular-nums text-neutral-400">
                {m.roi_pct != null ? `+${m.roi_pct.toFixed(0)}%` : '—'}
              </div>
              <div className="text-right text-[9px] text-neutral-600 truncate pl-2" title={m.trigger}>
                {m.trigger}
              </div>
            </div>
          )
        })}
        {markets.length === 0 && (
          <div className="flex items-center justify-center h-32 text-[10px] text-neutral-600 uppercase tracking-wider">
            No markets found — scanner runs every 2 min
          </div>
        )}
      </div>
    </div>
  )
}
