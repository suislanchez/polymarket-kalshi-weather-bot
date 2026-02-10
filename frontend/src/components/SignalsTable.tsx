import { motion, AnimatePresence } from 'framer-motion'
import { Play, ArrowUpRight, ArrowDownRight, Zap, TrendingUp } from 'lucide-react'
import type { Signal } from '../types'

interface Props {
  signals: Signal[]
  onSimulateTrade: (ticker: string) => void
  isSimulating: boolean
}

export function SignalsTable({ signals, onSimulateTrade, isSimulating }: Props) {
  if (signals.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-gray-400">
        <Zap className="w-12 h-12 mb-4 opacity-20" />
        <p className="text-lg">No actionable signals</p>
        <p className="text-sm mt-1 opacity-60">Signals appear when edge exceeds 8%</p>
      </div>
    )
  }

  return (
    <div className="space-y-3 max-h-[400px] overflow-y-auto pr-2">
      <AnimatePresence>
        {signals.map((signal, index) => {
          const isPositiveEdge = signal.edge > 0
          const edgePercent = Math.abs(signal.edge * 100)

          return (
            <motion.div
              key={signal.market_ticker}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ delay: index * 0.05 }}
              className="glass-card p-4 card-hover"
            >
              {/* Header */}
              <div className="flex items-start justify-between gap-3 mb-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="badge badge-info uppercase text-[10px]">
                      {signal.platform}
                    </span>
                    {signal.city && (
                      <span className="badge bg-purple-500/20 text-purple-400 border-purple-500/30 capitalize text-[10px]">
                        {signal.city.replace('_', ' ')}
                      </span>
                    )}
                    <span className={`badge ${isPositiveEdge ? 'badge-success' : 'badge-danger'} text-[10px]`}>
                      {edgePercent.toFixed(1)}% edge
                    </span>
                  </div>
                  <p className="text-sm text-gray-300 truncate" title={signal.market_title}>
                    {signal.market_title}
                  </p>
                </div>

                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => onSimulateTrade(signal.market_ticker)}
                  disabled={isSimulating}
                  className="btn-success flex items-center gap-2 text-sm"
                >
                  <Play className="w-3 h-3" />
                  Trade
                </motion.button>
              </div>

              {/* Stats Grid */}
              <div className="grid grid-cols-4 gap-4">
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-gray-500">Direction</span>
                  <div className="flex items-center gap-1 mt-1">
                    {signal.direction === 'yes' ? (
                      <ArrowUpRight className="w-4 h-4 text-emerald-400" />
                    ) : (
                      <ArrowDownRight className="w-4 h-4 text-red-400" />
                    )}
                    <span className={`font-semibold uppercase text-sm ${
                      signal.direction === 'yes' ? 'text-emerald-400' : 'text-red-400'
                    }`}>
                      {signal.direction}
                    </span>
                  </div>
                </div>

                <div>
                  <span className="text-[10px] uppercase tracking-wider text-gray-500">Model</span>
                  <div className="text-sm font-semibold mt-1">
                    {(signal.model_probability * 100).toFixed(1)}%
                  </div>
                </div>

                <div>
                  <span className="text-[10px] uppercase tracking-wider text-gray-500">Market</span>
                  <div className="text-sm font-semibold mt-1 text-gray-400">
                    {(signal.market_probability * 100).toFixed(1)}%
                  </div>
                </div>

                <div>
                  <span className="text-[10px] uppercase tracking-wider text-gray-500">Size</span>
                  <div className="text-sm font-semibold mt-1 text-blue-400">
                    ${signal.suggested_size.toFixed(0)}
                  </div>
                </div>
              </div>

              {/* Confidence bar */}
              <div className="mt-3 pt-3 border-t border-gray-800/50">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-gray-500">Confidence</span>
                  <span className="text-gray-400">{(signal.confidence * 100).toFixed(0)}%</span>
                </div>
                <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${signal.confidence * 100}%` }}
                    transition={{ duration: 0.5, delay: index * 0.05 }}
                    className="h-full bg-gradient-to-r from-blue-500 to-emerald-500 rounded-full"
                  />
                </div>
              </div>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
