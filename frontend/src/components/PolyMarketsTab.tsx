import { useQuery } from '@tanstack/react-query'
import { fetchPolyMarkets } from '../api'
import type { PolyMarket } from '../types'

const STATUS_CONFIG = {
  holding: {
    label: 'Holding',
    color: 'bg-emerald-500/15 border-l-2 border-emerald-500',
    badge: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30',
    dot: 'bg-emerald-500',
    desc: 'Position open, collecting',
  },
  bet_placed: {
    label: 'Bet Placed',
    color: 'bg-sky-500/10 border-l-2 border-sky-500',
    badge: 'bg-sky-500/20 text-sky-400 border border-sky-500/30',
    dot: 'bg-sky-500',
    desc: 'Order executed today',
  },
  scanned: {
    label: 'Scanned',
    color: 'bg-amber-500/8 border-l-2 border-amber-700',
    badge: 'bg-amber-500/15 text-amber-500 border border-amber-500/25',
    dot: 'bg-amber-600',
    desc: 'METAR lock seen, evaluating',
  },
  dry_run: {
    label: 'Paper',
    color: '',
    badge: 'bg-neutral-800 text-neutral-500 border border-neutral-700',
    dot: 'bg-neutral-600',
    desc: 'Simulated only — dry run mode',
  },
}

function StatusDot({ status }: { status: PolyMarket['status'] }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.dry_run
  return <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
}

function SideBadge({ side }: { side: string }) {
  return side === 'yes'
    ? <span className="text-[9px] font-bold px-1.5 py-0.5 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded">YES</span>
    : <span className="text-[9px] font-bold px-1.5 py-0.5 bg-red-500/20 text-red-400 border border-red-500/30 rounded">NO</span>
}

function pnlColor(v: number | null) {
  if (v == null) return 'text-neutral-500'
  return v > 0 ? 'text-emerald-400' : v < 0 ? 'text-red-400' : 'text-neutral-500'
}

export function PolyMarketsTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['poly-markets'],
    queryFn: fetchPolyMarkets,
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

  const { markets, count } = data
  const holdingCount = markets.filter(m => m.status === 'holding').length
  const betCount = markets.filter(m => m.status === 'bet_placed').length

  return (
    <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
      {/* Header stats */}
      <div className="shrink-0 border-b border-neutral-800 px-4 py-2 flex items-center gap-6">
        <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Polymarket METAR Markets</span>
        <span className="text-[10px] text-neutral-400 tabular-nums">{count} markets</span>
        <span className="text-[10px] text-emerald-400 tabular-nums">{holdingCount} holding</span>
        <span className="text-[10px] text-sky-400 tabular-nums">{betCount} placed today</span>
      </div>

      {/* Legend */}
      <div className="shrink-0 border-b border-neutral-800 px-4 py-1.5 flex items-center gap-4 flex-wrap">
        {(Object.entries(STATUS_CONFIG) as [string, typeof STATUS_CONFIG.holding][]).map(([key, cfg]) => (
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
        style={{ gridTemplateColumns: '130px 1fr 60px 70px 70px 70px 80px 80px 130px' }}
      >
        <div>City</div>
        <div>Market Question</div>
        <div>Side</div>
        <div className="text-right">Temp °F</div>
        <div className="text-right">Entry ¢</div>
        <div className="text-right">Curr ¢</div>
        <div className="text-right">Entry ROI</div>
        <div className="text-right">P&L</div>
        <div className="text-right">Trigger</div>
      </div>

      {/* Market rows */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {markets.map((m) => {
          const cfg = STATUS_CONFIG[m.status] || STATUS_CONFIG.dry_run
          return (
            <div
              key={m.condition_id}
              className={`grid px-4 py-1.5 border-b border-neutral-900 hover:bg-neutral-900/50 transition-colors text-[11px] ${cfg.color}`}
              style={{ gridTemplateColumns: '130px 1fr 60px 70px 70px 70px 80px 80px 130px' }}
            >
              <div className="flex items-center gap-1.5 min-w-0">
                <StatusDot status={m.status} />
                <span className="font-semibold text-neutral-200 truncate">{m.city}</span>
              </div>
              <div className="truncate text-neutral-400 pr-2" title={m.question}>
                {m.question.replace(/^Will the highest temperature in [^b]+be /, '').replace(/\?$/, '')}
              </div>
              <div><SideBadge side={m.side} /></div>
              <div className="text-right tabular-nums text-neutral-300">
                {m.metar_temp_f != null ? `${m.metar_temp_f.toFixed(1)}°` : '—'}
              </div>
              <div className="text-right tabular-nums text-neutral-400">
                {m.price != null ? `${(m.price * 100).toFixed(0)}¢` : '—'}
              </div>
              <div className="text-right tabular-nums text-neutral-300">
                {m.current_price != null ? `${(m.current_price * 100).toFixed(0)}¢` : '—'}
              </div>
              <div className="text-right tabular-nums text-neutral-400">
                {m.roi_pct != null ? `+${m.roi_pct.toFixed(0)}%` : '—'}
              </div>
              <div className={`text-right tabular-nums font-semibold ${pnlColor(m.current_pnl)}`}>
                {m.current_pnl != null ? `${m.current_pnl >= 0 ? '+' : ''}$${m.current_pnl.toFixed(2)}` : '—'}
              </div>
              <div className="text-right text-[9px] text-neutral-600 truncate pl-2" title={m.trigger}>
                {m.score_desc || m.trigger}
              </div>
            </div>
          )
        })}
        {markets.length === 0 && (
          <div className="flex items-center justify-center h-32 text-[10px] text-neutral-600 uppercase tracking-wider">
            No markets found
          </div>
        )}
      </div>
    </div>
  )
}
