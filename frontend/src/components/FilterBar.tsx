import { Search, X } from 'lucide-react'

export interface FilterState {
  search: string
  status: 'all' | 'pending' | 'win' | 'loss'
}

interface Props {
  filters: FilterState
  onFilterChange: (filters: FilterState) => void
  showStatus?: boolean
}

const STATUSES = [
  { value: 'all', label: 'All Status' },
  { value: 'pending', label: 'Pending' },
  { value: 'win', label: 'Won' },
  { value: 'loss', label: 'Lost' }
] as const

export function FilterBar({ filters, onFilterChange, showStatus = false }: Props) {
  const hasActiveFilters = filters.search !== '' || filters.status !== 'all'

  const clearFilters = () => {
    onFilterChange({ search: '', status: 'all' })
  }

  return (
    <div className="flex flex-wrap items-center gap-3 p-3 bg-neutral-900/50 border border-neutral-800">
      <div className="relative flex-1 min-w-[200px]">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-600" />
        <input
          type="text"
          placeholder="Search..."
          value={filters.search}
          onChange={(e) => onFilterChange({ ...filters, search: e.target.value })}
          className="w-full pl-10 pr-4 py-2 bg-neutral-950 border border-neutral-800 text-sm text-neutral-300 placeholder-neutral-600 focus:outline-none focus:border-neutral-600 transition-colors"
        />
      </div>

      {showStatus && (
        <div className="relative">
          <select
            value={filters.status}
            onChange={(e) => onFilterChange({ ...filters, status: e.target.value as FilterState['status'] })}
            className="pl-4 pr-8 py-2 bg-neutral-950 border border-neutral-800 text-sm text-neutral-300 focus:outline-none focus:border-neutral-600 appearance-none cursor-pointer"
          >
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
          <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none">
            <svg className="w-4 h-4 text-neutral-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>
      )}

      {hasActiveFilters && (
        <button
          onClick={clearFilters}
          className="flex items-center gap-1.5 px-3 py-2 text-xs text-neutral-500 hover:text-neutral-300 border border-neutral-800 hover:border-neutral-600 transition-colors"
        >
          <X className="w-3 h-3" />
          Clear
        </button>
      )}
    </div>
  )
}
