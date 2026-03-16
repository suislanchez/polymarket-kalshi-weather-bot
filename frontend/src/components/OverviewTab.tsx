import { useState } from 'react'
import { Play, Pause, RefreshCw, ChevronDown, ChevronUp, Maximize2 } from 'lucide-react'
import { EquityChart } from './EquityChart'
import type { BotStats, EquityPoint, WeatherSignal, Signal, BtcPrice } from '../types'
import { formatDistanceToNow } from 'date-fns'

interface Props {
  stats: BotStats
  equityCurve: EquityPoint[]
  weatherSignals: WeatherSignal[]
  btcSignals: Signal[]
  pendingTradeCount: number
  onStart: () => void
  onStop: () => void
  onScan: () => void
  isScanning: boolean
  lastUpdated: Date
  btcPrice: BtcPrice | null
}

function MarketRow({ label, value, change, dotColor }: {
  label: string
  value: string
  change: string
  dotColor: string
}) {
  const isPositive = change.startsWith('+')
  return (
    <div className="yf-market-row">
      <div className="flex items-center gap-2.5">
        <span className={`w-2 h-2 rounded-full ${dotColor}`} />
        <span className="text-[15px] font-semibold text-white">{label}</span>
      </div>
      <div className="flex items-center gap-4">
        <span className="text-[15px] font-medium text-white tabular-nums">{value}</span>
        <span className={`text-[15px] font-medium tabular-nums ${isPositive ? 'text-[#00C805]' : 'text-[#FF3B30]'}`}>
          {change}
        </span>
      </div>
    </div>
  )
}

export function OverviewTab({ stats, equityCurve, weatherSignals, btcSignals, pendingTradeCount, onStart, onStop, onScan, isScanning, lastUpdated }: Props) {
  const [collapsed, setCollapsed] = useState(false)
  const [chartPeriod, setChartPeriod] = useState('1D')
  const pnlPercent = stats.bankroll > 0 ? ((stats.total_pnl / (stats.bankroll - stats.total_pnl)) * 100) : 0
  const wxActionable = weatherSignals.filter(s => s.actionable).length
  const btcActionable = btcSignals.filter(s => s.actionable).length
  const periods = ['1D', '5D', '1M', '6M', 'YTD', '1Y', '5Y', 'ALL']

  let timeAgo = ''
  try {
    timeAgo = formatDistanceToNow(lastUpdated, { addSuffix: false })
  } catch {
    timeAgo = 'just now'
  }

  return (
    <div className="overflow-y-auto h-full pb-4">
      {/* Bot Controls */}
      <div className="flex items-center justify-between px-4 py-2.5">
        <div className="flex items-center gap-2">
          <button
            onClick={onScan}
            disabled={isScanning}
            className="yf-action-btn"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isScanning ? 'animate-spin' : ''}`} />
            Scan
          </button>
          {stats.is_running ? (
            <button onClick={onStop} className="yf-action-btn danger">
              <Pause className="w-3.5 h-3.5" /> Pause
            </button>
          ) : (
            <button onClick={onStart} className="yf-action-btn success">
              <Play className="w-3.5 h-3.5" /> Start
            </button>
          )}
        </div>
        <span className="text-[11px] text-amber-400/80 font-semibold uppercase tracking-wider">Simulation</span>
      </div>

      {/* Market Overview Card */}
      <div className="yf-card mx-4">
        {/* Tabs + Collapse */}
        <div className="flex items-center justify-between px-4 pt-3 pb-2">
          <div className="yf-tab-group">
            <button className="yf-tab active">Portfolio</button>
            <button className="yf-tab">Weather</button>
            <button className="yf-tab">BTC</button>
          </div>
          <button onClick={() => setCollapsed(!collapsed)} className="flex items-center gap-1 text-[13px] text-neutral-400 hover:text-white transition-colors">
            {collapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
        </div>

        {!collapsed && (
          <div className="px-1 pb-3">
            <MarketRow
              label="Bankroll"
              value={`$${stats.bankroll.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              change={`${pnlPercent >= 0 ? '+' : ''}${pnlPercent.toFixed(2)}%`}
              dotColor="bg-blue-500"
            />
            <MarketRow
              label="P&L"
              value={`$${Math.abs(stats.total_pnl).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              change={`${stats.total_pnl >= 0 ? '+' : '-'}$${Math.abs(stats.total_pnl).toFixed(2)}`}
              dotColor={stats.total_pnl >= 0 ? 'bg-[#00C805]' : 'bg-[#FF3B30]'}
            />
            <MarketRow
              label="Win Rate"
              value={`${(stats.win_rate * 100).toFixed(1)}%`}
              change={`${stats.winning_trades}W / ${stats.total_trades - stats.winning_trades}L`}
              dotColor={stats.win_rate >= 0.55 ? 'bg-[#00C805]' : stats.win_rate >= 0.45 ? 'bg-amber-500' : 'bg-[#FF3B30]'}
            />
            <MarketRow
              label="Trades"
              value={`${stats.total_trades}`}
              change={`${pendingTradeCount} pending`}
              dotColor="bg-purple-500"
            />
          </div>
        )}
      </div>

      {/* Equity Chart */}
      <div className="yf-card mx-4 mt-3">
        <div className="px-4 pt-3">
          <div className="flex items-center justify-between mb-1">
            <div>
              <div className="text-[22px] font-bold tabular-nums">
                {stats.total_pnl >= 0 ? '+' : '-'}${Math.abs(stats.total_pnl).toFixed(2)}
              </div>
              <div className={`text-[13px] font-medium tabular-nums ${pnlPercent >= 0 ? 'text-[#00C805]' : 'text-[#FF3B30]'}`}>
                {pnlPercent >= 0 ? '+' : ''}{pnlPercent.toFixed(2)}%
              </div>
            </div>
            <button className="text-neutral-400 hover:text-white">
              <Maximize2 className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="h-48 px-2">
          {equityCurve.length > 0 ? (
            <EquityChart data={equityCurve} initialBankroll={stats.bankroll - stats.total_pnl} />
          ) : (
            <div className="flex items-center justify-center h-full text-neutral-500 text-xs">
              No settled trades yet
            </div>
          )}
        </div>

        {/* Time Period Selector */}
        <div className="flex items-center justify-between px-4 py-3">
          {periods.map(p => (
            <button
              key={p}
              onClick={() => setChartPeriod(p)}
              className={`yf-period-btn ${chartPeriod === p ? 'active' : ''}`}
            >
              {p}
            </button>
          ))}
        </div>

        {/* Last Updated */}
        <div className="px-4 pb-3">
          <div className="text-[11px] text-red-400 font-medium">Last updated: {timeAgo} ago</div>
          <div className="text-[13px] text-neutral-300 mt-1 leading-snug">
            Bot tracking {weatherSignals.length + btcSignals.length} signals across weather and BTC markets
          </div>
        </div>
      </div>

      {/* Trending Signals */}
      <div className="mx-4 mt-4">
        <h3 className="text-xs font-bold text-neutral-400 uppercase tracking-wider mb-2 px-1">Trending Now</h3>
        <div className="yf-card">
          {[...weatherSignals.filter(s => s.actionable), ...btcSignals.filter(s => s.actionable)]
            .sort((a, b) => Math.abs(b.edge) - Math.abs(a.edge))
            .slice(0, 5)
            .map((signal, i) => {
              const isBtc = 'market_ticker' in signal && 'btc_price' in signal
              const name = isBtc
                ? ((signal as Signal).event_slug || (signal as Signal).market_ticker).replace('btc-updown-5m-', 'BTC ')
                : `${(signal as WeatherSignal).city_name}`
              const edge = Math.abs(signal.edge)
              const direction = signal.direction
              const isUp = direction === 'up' || direction === 'above' || direction === 'yes'

              return (
                <div key={i} className="yf-trending-row">
                  <div className="flex-1 min-w-0">
                    <div className="text-[14px] font-bold text-white truncate">{name}</div>
                    <div className="text-[12px] text-neutral-500 truncate">
                      {isBtc ? 'BTC 5-min' : (signal as WeatherSignal).metric}
                    </div>
                  </div>
                  <div className="yf-mini-chart">
                    <div className={`w-12 h-6 rounded ${isUp ? 'bg-[#00C805]/10' : 'bg-[#FF3B30]/10'}`} />
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-[14px] font-semibold tabular-nums text-white">
                      {(edge * 100).toFixed(1)}%
                    </div>
                    <div className={`text-[12px] font-medium ${isUp ? 'text-[#00C805]' : 'text-[#FF3B30]'}`}>
                      {isUp ? '\u25B2' : '\u25BC'} {direction}
                    </div>
                  </div>
                </div>
              )
            })}
          {wxActionable + btcActionable === 0 && (
            <div className="px-4 py-6 text-center text-neutral-500 text-sm">
              No actionable signals right now
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
