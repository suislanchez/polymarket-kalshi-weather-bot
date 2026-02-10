import type { Signal } from '../types'

interface Props {
  signals: Signal[]
  onSimulateTrade: (ticker: string) => void
  isSimulating: boolean
}

export function SignalsTable({ signals, onSimulateTrade, isSimulating }: Props) {
  if (signals.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-neutral-600">
        <div className="text-4xl mb-4 opacity-30">⚡</div>
        <p className="text-sm">No actionable signals</p>
        <p className="text-xs mt-1">Signals appear when edge exceeds 8%</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="text-neutral-600 text-left text-xs border-b border-neutral-800">
            <th className="py-3 px-2 font-medium">Market</th>
            <th className="py-3 px-2 font-medium text-center">Direction</th>
            <th className="py-3 px-2 font-medium text-right">Edge</th>
            <th className="py-3 px-2 font-medium text-right">Model</th>
            <th className="py-3 px-2 font-medium text-right">Market</th>
            <th className="py-3 px-2 font-medium text-right">Size</th>
            <th className="py-3 px-2 font-medium text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((signal) => {
            const edgePercent = Math.abs(signal.edge * 100)
            return (
              <tr
                key={signal.market_ticker}
                className="border-b border-neutral-800 hover:bg-neutral-900/50 transition-colors"
              >
                <td className="py-3 px-2">
                  <div className="max-w-[200px]">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="px-1.5 py-0.5 text-[10px] font-medium uppercase bg-blue-500/10 text-blue-400 border border-blue-500/20">
                        {signal.platform}
                      </span>
                      {signal.city && (
                        <span className="px-1.5 py-0.5 text-[10px] font-medium capitalize bg-purple-500/10 text-purple-400 border border-purple-500/20">
                          {signal.city.replace('_', ' ')}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-neutral-400 truncate" title={signal.market_title}>
                      {signal.market_title}
                    </div>
                  </div>
                </td>
                <td className="py-3 px-2 text-center">
                  <span className={`px-2 py-1 text-[10px] font-semibold uppercase ${
                    signal.direction === 'yes'
                      ? 'bg-green-500/10 text-green-500 border border-green-500/20'
                      : 'bg-red-500/10 text-red-500 border border-red-500/20'
                  }`}>
                    {signal.direction}
                  </span>
                </td>
                <td className="py-3 px-2 text-right">
                  <span className={`text-sm font-semibold tabular-nums ${
                    signal.edge > 0 ? 'text-green-500' : 'text-red-500'
                  }`}>
                    {edgePercent.toFixed(1)}%
                  </span>
                </td>
                <td className="py-3 px-2 text-right text-sm text-neutral-300 tabular-nums">
                  {(signal.model_probability * 100).toFixed(1)}%
                </td>
                <td className="py-3 px-2 text-right text-sm text-neutral-500 tabular-nums">
                  {(signal.market_probability * 100).toFixed(1)}%
                </td>
                <td className="py-3 px-2 text-right text-sm text-blue-400 tabular-nums">
                  ${signal.suggested_size.toFixed(0)}
                </td>
                <td className="py-3 px-2 text-right">
                  <button
                    onClick={() => onSimulateTrade(signal.market_ticker)}
                    disabled={isSimulating}
                    className="px-3 py-1.5 text-[10px] font-medium uppercase bg-green-500/10 text-green-500 border border-green-500/20 hover:bg-green-500/20 transition-colors disabled:opacity-50"
                  >
                    Trade
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
