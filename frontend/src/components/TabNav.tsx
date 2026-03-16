import { Home, Newspaper, Globe2, Users, TrendingUp } from 'lucide-react'

export type TabId = 'overview' | 'weather' | 'btc' | 'trades' | 'system'

interface Props {
  activeTab: TabId
  onTabChange: (tab: TabId) => void
  weatherCount?: number
  btcCount?: number
  pendingTrades?: number
}

const tabs: { id: TabId; label: string; icon: typeof Home }[] = [
  { id: 'overview', label: 'Home', icon: Home },
  { id: 'weather', label: 'Weather', icon: Globe2 },
  { id: 'btc', label: 'Markets', icon: TrendingUp },
  { id: 'trades', label: 'Trades', icon: Newspaper },
  { id: 'system', label: 'System', icon: Users },
]

export function TabNav({ activeTab, onTabChange, weatherCount, btcCount, pendingTrades }: Props) {
  const getBadge = (id: TabId): number | undefined => {
    if (id === 'weather') return weatherCount
    if (id === 'btc') return btcCount
    if (id === 'trades') return pendingTrades
    return undefined
  }

  return (
    <nav className="yf-bottom-nav">
      {tabs.map((tab) => {
        const Icon = tab.icon
        const isActive = activeTab === tab.id
        const badge = getBadge(tab.id)

        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={`yf-nav-item ${isActive ? 'active' : ''}`}
          >
            <div className="relative">
              <Icon className="w-5 h-5" strokeWidth={isActive ? 2.5 : 1.5} />
              {badge !== undefined && badge > 0 && (
                <span className="yf-nav-badge">{badge}</span>
              )}
            </div>
            <span className="yf-nav-label">{tab.label}</span>
          </button>
        )
      })}
    </nav>
  )
}
