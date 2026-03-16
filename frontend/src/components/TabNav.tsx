import { motion } from 'framer-motion'
import { BarChart3, CloudSun, Bitcoin, ArrowLeftRight, Settings } from 'lucide-react'

export type TabId = 'overview' | 'weather' | 'btc' | 'trades' | 'system'

interface Props {
  activeTab: TabId
  onTabChange: (tab: TabId) => void
  weatherCount?: number
  btcCount?: number
  pendingTrades?: number
}

const tabs: { id: TabId; label: string; icon: typeof BarChart3 }[] = [
  { id: 'overview', label: 'Overview', icon: BarChart3 },
  { id: 'weather', label: 'Weather', icon: CloudSun },
  { id: 'btc', label: 'BTC', icon: Bitcoin },
  { id: 'trades', label: 'Trades', icon: ArrowLeftRight },
  { id: 'system', label: 'System', icon: Settings },
]

export function TabNav({ activeTab, onTabChange, weatherCount, btcCount, pendingTrades }: Props) {
  const getBadge = (id: TabId): number | undefined => {
    if (id === 'weather') return weatherCount
    if (id === 'btc') return btcCount
    if (id === 'trades') return pendingTrades
    return undefined
  }

  return (
    <nav className="flex border-b border-neutral-800 bg-[#0a0a0a] overflow-x-auto">
      {tabs.map((tab) => {
        const Icon = tab.icon
        const isActive = activeTab === tab.id
        const badge = getBadge(tab.id)

        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={`relative flex items-center gap-1.5 px-4 py-3 text-xs font-medium uppercase tracking-wider whitespace-nowrap transition-colors ${
              isActive
                ? 'text-white'
                : 'text-neutral-500 hover:text-neutral-300'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            <span>{tab.label}</span>
            {badge !== undefined && badge > 0 && (
              <span className="ml-1 px-1.5 py-0.5 text-[9px] font-bold bg-green-500/20 text-green-400 rounded-full">
                {badge}
              </span>
            )}
            {isActive && (
              <motion.div
                layoutId="tab-indicator"
                className="absolute bottom-0 left-0 right-0 h-0.5 bg-green-500"
                transition={{ type: 'spring', stiffness: 500, damping: 30 }}
              />
            )}
          </button>
        )
      })}
    </nav>
  )
}
