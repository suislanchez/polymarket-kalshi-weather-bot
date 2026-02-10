/**
 * Utility functions for the trading bot dashboard
 */

/**
 * Generate a URL to view a market on its platform
 */
export function getMarketUrl(platform: string, ticker: string, eventSlug?: string): string {
  const platformLower = platform.toLowerCase()

  if (platformLower === 'kalshi') {
    // Kalshi ticker format: KXHIGHNYC-26FEB10-T45
    // Use full ticker, lowercased for URL
    return `https://kalshi.com/markets/${ticker.toLowerCase()}`
  }

  if (platformLower === 'polymarket') {
    // Polymarket uses event slugs - prefer slug over market ID
    if (eventSlug) {
      return `https://polymarket.com/event/${eventSlug}`
    }
    // Fallback to ticker (market ID) if no slug available
    return `https://polymarket.com/event/${ticker}`
  }

  return '#'
}

/**
 * Format a number as currency
 */
export function formatCurrency(value: number, showSign = false): string {
  const formatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  }).format(Math.abs(value))

  if (showSign && value !== 0) {
    return value >= 0 ? `+${formatted}` : `-${formatted}`
  }
  return value < 0 ? `-${formatted}` : formatted
}

/**
 * Format a percentage
 */
export function formatPercent(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`
}

/**
 * Get platform-specific styling
 */
export const platformStyles = {
  kalshi: {
    badge: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
    icon: 'K',
    name: 'Kalshi'
  },
  polymarket: {
    badge: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
    icon: 'P',
    name: 'Polymarket'
  }
} as const

/**
 * Market category types
 */
export type MarketCategory = 'weather' | 'crypto' | 'politics' | 'economics' | 'other'

/**
 * Get category-specific styling
 */
export const categoryStyles: Record<MarketCategory, { badge: string; icon: string; name: string }> = {
  weather: {
    badge: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
    icon: '🌡️',
    name: 'Weather'
  },
  crypto: {
    badge: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
    icon: '₿',
    name: 'Crypto'
  },
  politics: {
    badge: 'bg-red-500/10 text-red-400 border-red-500/20',
    icon: '🗳️',
    name: 'Politics'
  },
  economics: {
    badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    icon: '📊',
    name: 'Economics'
  },
  other: {
    badge: 'bg-neutral-500/10 text-neutral-400 border-neutral-500/20',
    icon: '?',
    name: 'Other'
  }
}

/**
 * Get confidence-based color
 */
export function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.7) return '#22c55e' // green
  if (confidence >= 0.4) return '#d97706' // amber
  return '#dc2626' // red
}

/**
 * Get P&L color class
 */
export function getPnlColorClass(pnl: number | null): string {
  if (pnl === null) return 'text-neutral-500'
  if (pnl > 0) return 'text-green-500'
  if (pnl < 0) return 'text-red-500'
  return 'text-neutral-400'
}

/**
 * Temperature to color for heatmap
 */
export function tempToColor(tempF: number): string {
  // Normalize temperature (assume range 0-100°F)
  const normalized = Math.max(0, Math.min(1, (tempF - 20) / 80))

  if (normalized < 0.25) return 'rgba(59, 130, 246, 0.6)' // Blue (cold)
  if (normalized < 0.5) return 'rgba(234, 179, 8, 0.6)'   // Yellow
  if (normalized < 0.75) return 'rgba(249, 115, 22, 0.6)' // Orange
  return 'rgba(239, 68, 68, 0.6)' // Red (hot)
}

/**
 * Debounce function for search inputs
 */
export function debounce<T extends (...args: any[]) => void>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeoutId: ReturnType<typeof setTimeout> | null = null

  return (...args: Parameters<T>) => {
    if (timeoutId) {
      clearTimeout(timeoutId)
    }
    timeoutId = setTimeout(() => {
      func(...args)
    }, wait)
  }
}
