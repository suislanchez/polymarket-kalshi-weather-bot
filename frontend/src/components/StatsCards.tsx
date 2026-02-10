import { motion } from 'framer-motion'
import { TrendingUp, TrendingDown, Activity, DollarSign, Target, Percent } from 'lucide-react'
import type { BotStats } from '../types'

interface Props {
  stats: BotStats
}

const cardVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      delay: i * 0.1,
      duration: 0.5,
      ease: 'easeOut'
    }
  })
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0
  }).format(value)
}

function StatCard({
  icon: Icon,
  label,
  value,
  subValue,
  trend,
  index,
  glowClass
}: {
  icon: any
  label: string
  value: string
  subValue?: string
  trend?: 'up' | 'down' | 'neutral'
  index: number
  glowClass?: string
}) {
  const trendColor = trend === 'up' ? 'text-emerald-400' : trend === 'down' ? 'text-red-400' : 'text-gray-400'
  const trendBg = trend === 'up' ? 'bg-emerald-400/10' : trend === 'down' ? 'bg-red-400/10' : 'bg-gray-400/10'

  return (
    <motion.div
      custom={index}
      variants={cardVariants}
      initial="hidden"
      animate="visible"
      className={`glass-card p-5 card-hover ${glowClass || ''}`}
    >
      <div className="flex items-start justify-between mb-3">
        <div className={`p-2 rounded-lg ${trendBg}`}>
          <Icon className={`w-5 h-5 ${trendColor}`} />
        </div>
        {trend && trend !== 'neutral' && (
          <div className={`flex items-center gap-1 text-sm ${trendColor}`}>
            {trend === 'up' ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          </div>
        )}
      </div>

      <div className="space-y-1">
        <p className="text-sm text-gray-400">{label}</p>
        <p className={`text-2xl font-bold ${trendColor}`}>{value}</p>
        {subValue && (
          <p className="text-sm text-gray-500">{subValue}</p>
        )}
      </div>
    </motion.div>
  )
}

export function StatsCards({ stats }: Props) {
  const pnlTrend = stats.total_pnl >= 0 ? 'up' : 'down'
  const winRate = stats.total_trades > 0 ? stats.winning_trades / stats.total_trades : 0

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <StatCard
        icon={DollarSign}
        label="Virtual Bankroll"
        value={formatCurrency(stats.bankroll)}
        trend="neutral"
        index={0}
      />

      <StatCard
        icon={pnlTrend === 'up' ? TrendingUp : TrendingDown}
        label="Total P&L"
        value={`${stats.total_pnl >= 0 ? '+' : ''}${formatCurrency(stats.total_pnl)}`}
        subValue={`${((stats.total_pnl / (stats.bankroll - stats.total_pnl)) * 100).toFixed(1)}% return`}
        trend={pnlTrend}
        index={1}
        glowClass={stats.total_pnl >= 0 ? 'glow-green' : 'glow-red'}
      />

      <StatCard
        icon={Percent}
        label="Win Rate"
        value={`${(winRate * 100).toFixed(1)}%`}
        subValue={`${stats.winning_trades} of ${stats.total_trades} trades`}
        trend={winRate >= 0.55 ? 'up' : winRate >= 0.45 ? 'neutral' : 'down'}
        index={2}
      />

      <StatCard
        icon={Activity}
        label="Total Trades"
        value={stats.total_trades.toString()}
        subValue={stats.is_running ? 'Bot active' : 'Bot idle'}
        trend="neutral"
        index={3}
      />
    </div>
  )
}
