/**
 * The mirror panel must never let a mirrored balance read as something the
 * system holds or can trade, and must never surface an account number.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MirrorPanel } from './MirrorPanel'
import type { MirrorSnapshot } from '../types'

function snapshot(overrides: Partial<MirrorSnapshot> = {}): MirrorSnapshot {
  return {
    available: true,
    venue: 'robinhood',
    captured_at: '2026-09-07T00:40:00Z',
    source_agent: 'claude-desktop-mcp',
    total_value: '5673.84004803',
    accounts: [
      {
        label: 'individual',
        account_ref: '••••0651',
        tradable_by_agent: false,
        currency: 'USD',
        total_value: '5673.84004803',
        cash: '1435.21',
        buying_power: '830.2100',
        positions: [
          { asset_class: 'stock', symbol: 'AAPL', quantity: '1.402732', average_cost: '182.850000' },
          { asset_class: 'stock', symbol: 'VOO', quantity: '1.137825', average_cost: '468.090000' },
        ],
      },
      {
        label: 'agentic',
        account_ref: '••••6625',
        tradable_by_agent: true,
        currency: 'USD',
        total_value: '0',
        cash: '0',
        buying_power: '0.0000',
        positions: [],
      },
    ],
    ...overrides,
  }
}

describe('MirrorPanel', () => {
  it('labels every render as a read-only mirror that cannot be traded', () => {
    render(<MirrorPanel snapshot={snapshot()} />)
    expect(screen.getByTestId('mirror-badge')).toHaveTextContent(/read-only mirror/i)
    expect(screen.getByTestId('mirror-badge')).toHaveTextContent(/not tradeable/i)
  })

  it('shows accounts by masked reference only', () => {
    const { container } = render(<MirrorPanel snapshot={snapshot()} />)
    expect(screen.getByTestId('mirror-account-••••0651')).toBeInTheDocument()
    expect(screen.getByTestId('mirror-account-••••6625')).toBeInTheDocument()
    // Two traps, both real: money carries long digit runs ("5673.84004803"),
    // and textContent concatenates adjacent cells with no separator, so
    // "1.402732" next to "182.850000" reads as the nine-digit "402732182".
    // Check each text NODE on its own: an account number is nine digits in one
    // node, and no single node may contain one.
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
    const nodes: string[] = []
    for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n.textContent ?? '')
    expect(nodes.some((t) => /\d{9,}/.test(t))).toBe(false)
    expect(nodes.some((t) => /••••0651/.test(t))).toBe(true)
    expect(nodes.some((t) => /••••6625/.test(t))).toBe(true)
  })

  it('renders positions with exact quantities as strings', () => {
    render(<MirrorPanel snapshot={snapshot()} />)
    const rows = screen.getAllByTestId('mirror-position')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('AAPL')
    expect(rows[0]).toHaveTextContent('1.402732')
  })

  it('reports an empty account as empty rather than hiding it', () => {
    render(<MirrorPanel snapshot={snapshot()} />)
    expect(screen.getByTestId('mirror-account-••••6625')).toHaveTextContent(/no positions/i)
  })

  it('reports absence rather than inventing a zero balance', () => {
    render(<MirrorPanel snapshot={{ available: false, venue: 'robinhood', captured_at: null, source_agent: null, total_value: null, accounts: [] }} />)
    expect(screen.getByTestId('mirror-unavailable')).toBeInTheDocument()
    expect(screen.queryByTestId('mirror-badge')).not.toBeInTheDocument()
  })
})
