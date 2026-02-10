import { formatDistanceToNow } from 'date-fns'
import type { Trade } from '../types'

interface Props {
  trades: Trade[]
}

export function TradesTable({ trades }: Props) {
  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-neutral-600">
        <div className="text-4xl mb-4 opacity-30">📋</div>
        <p className="text-sm">No trades yet</p>
        <p className="text-xs mt-1">Simulated trades will appear here</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="text-neutral-600 text-left text-xs border-b border-neutral-800">
            <th className="py-3 px-2 font-medium">Status</th>
            <th className="py-3 px-2 font-medium">Market</th>
            <th className="py-3 px-2 font-medium text-center">Direction</th>
            <th className="py-3 px-2 font-medium text-right">Size</th>
            <th className="py-3 px-2 font-medium text-right">Entry</th>
            <th className="py-3 px-2 font-medium text-right">P&L</th>
            <th className="py-3 px-2 font-medium text-right">Time</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => {
            const isPending = trade.result === 'pending'
            const isWin = trade.result === 'win'

            return (
              <tr
                key={trade.id}
                className="border-b border-neutral-800 hover:bg-neutral-900/50 transition-colors"
              >
                <td className="py-3 px-2">
                  <span className={`px-2 py-1 text-[10px] font-medium uppercase ${
                    isPending
                      ? 'bg-amber-500/10 text-amber-500 border border-amber-500/20'
                      : isWin
                        ? 'bg-green-500/10 text-green-500 border border-green-500/20'
                        : 'bg-red-500/10 text-red-500 border border-red-500/20'
                  }`}>
                    {isPending ? 'Pending' : isWin ? 'Win' : 'Loss'}
                  </span>
                </td>
                <td className="py-3 px-2">
                  <div className="max-w-[200px]">
                    <span className="px-1.5 py-0.5 text-[10px] font-medium uppercase bg-blue-500/10 text-blue-400 border border-blue-500/20 mr-2">
                      {trade.platform}
                    </span>
                    <span className="text-xs text-neutral-400 truncate">{trade.market_ticker}</span>
                  </div>
                </td>
                <td className="py-3 px-2 text-center">
                  <span className={`px-2 py-1 text-[10px] font-semibold uppercase ${
                    trade.direction === 'yes'
                      ? 'bg-green-500/10 text-green-500 border border-green-500/20'
                      : 'bg-red-500/10 text-red-500 border border-red-500/20'
                  }`}>
                    {trade.direction}
                  </span>
                </td>
                <td className="py-3 px-2 text-right text-sm text-neutral-300 tabular-nums">
                  ${trade.size.toFixed(0)}
                </td>
                <td className="py-3 px-2 text-right text-sm text-neutral-500 tabular-nums">
                  {(trade.entry_price * 100).toFixed(0)}¢
                </td>
                <td className="py-3 px-2 text-right">
                  {trade.pnl !== null ? (
                    <span className={`text-sm font-semibold tabular-nums ${
                      trade.pnl >= 0 ? 'text-green-500' : 'text-red-500'
                    }`}>
                      {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-sm text-neutral-600">-</span>
                  )}
                </td>
                <td className="py-3 px-2 text-right text-xs text-neutral-600">
                  {formatDistanceToNow(new Date(trade.timestamp), { addSuffix: true })}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
