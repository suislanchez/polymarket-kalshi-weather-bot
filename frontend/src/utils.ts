/**
 * Utility functions for the BTC 5-min trading bot dashboard
 */

export function getMarketUrl(platform: string, ticker: string, eventSlug?: string): string {
  const platformLower = platform.toLowerCase()

  if (platformLower === 'polymarket') {
    if (eventSlug) {
      return `https://polymarket.com/event/${eventSlug}`
    }
    return `https://polymarket.com/event/${ticker}`
  }

  return '#'
}

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

export function formatPercent(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`
}

export const platformStyles = {
  polymarket: {
    badge: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
    icon: 'P',
    name: 'Polymarket'
  }
} as const

export function getPnlColorClass(pnl: number | null): string {
  if (pnl === null) return 'text-neutral-500'
  if (pnl > 0) return 'text-green-500'
  if (pnl < 0) return 'text-red-500'
  return 'text-neutral-400'
}

export function formatCountdown(seconds: number): string {
  if (seconds <= 0) return 'Ended'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

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
