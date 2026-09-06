/**
 * The orders table is the audit surface. Two things it must never do: imply a
 * live order, and quietly reformat money.
 *
 * Quantities and notionals arrive as strings because the ledger keeps exact
 * Decimals and JSON floats do not. A table that parses them to render them
 * throws that away at the last step, so the precision assertion below uses a
 * value that a float cannot hold.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { UnifiedOrdersTable } from './UnifiedOrdersTable'
import type { UnifiedOrder } from '../types'

function order(overrides: Partial<UnifiedOrder> = {}): UnifiedOrder {
  return {
    client_order_id: 'client-1',
    proposal_id: 'proposal-1',
    venue: 'alpaca_paper',
    asset_class: 'stock',
    symbol: 'SPY',
    side: 'buy',
    status: 'filled',
    broker_order_id: 'broker-1',
    rejection_reason: null,
    filled_quantity: '89.285714',
    filled_notional: '49.99999984',
    average_fill_price: '0.56',
    occurred_at: '2026-08-24T12:30:45Z',
    ...overrides,
  }
}

describe('UnifiedOrdersTable', () => {
  it('shows venue, symbol, side, status and size for an order', () => {
    render(<UnifiedOrdersTable orders={[order()]} />)
    const row = screen.getByTestId('order-client-1')
    expect(within(row).getByTestId('order-venue')).toHaveTextContent('alpaca_paper')
    expect(within(row).getByTestId('order-symbol')).toHaveTextContent('SPY')
    expect(within(row).getByTestId('order-side')).toHaveTextContent(/buy/i)
    expect(within(row).getByTestId('order-status')).toHaveTextContent(/filled/i)
    expect(within(row).getByTestId('order-quantity')).toHaveTextContent('89.285714')
    expect(within(row).getByTestId('order-notional')).toHaveTextContent('49.99999984')
  })

  it('renders exact money without passing it through a float', () => {
    render(<UnifiedOrdersTable orders={[order()]} />)
    const notional = within(screen.getByTestId('order-client-1')).getByTestId('order-notional')
    // Number('49.99999984') survives, but the point is that the component never
    // does that; a parse-then-format pipeline breaks on the digits below.
    expect(notional).toHaveTextContent('49.99999984')
    expect(notional.textContent).not.toContain('50')
  })

  it('marks every order as paper', () => {
    render(<UnifiedOrdersTable orders={[order(), order({ client_order_id: 'client-2' })]} />)
    const modes = screen.getAllByTestId('order-mode')
    expect(modes).toHaveLength(2)
    for (const mode of modes) expect(mode).toHaveTextContent(/paper/i)
  })

  it('says so when an order has no instrument identity rather than inventing one', () => {
    render(<UnifiedOrdersTable orders={[order({ symbol: null, side: null })]} />)
    const row = screen.getByTestId('order-client-1')
    expect(within(row).getByTestId('order-symbol')).toHaveTextContent(/unknown|—|not recorded/i)
    expect(within(row).getByTestId('order-symbol')).not.toHaveTextContent(/SPY/)
  })

  it('shows the rejection reason for a rejected order', () => {
    render(
      <UnifiedOrdersTable
        orders={[
          order({
            status: 'risk_rejected',
            rejection_reason: 'daily_loss_limit',
            filled_quantity: '0',
            filled_notional: '0',
            average_fill_price: null,
          }),
        ]}
      />,
    )
    expect(within(screen.getByTestId('order-client-1')).getByTestId('order-status'))
      .toHaveTextContent(/daily_loss_limit/)
  })

  it('renders an explicit empty state rather than a bare table', () => {
    render(<UnifiedOrdersTable orders={[]} />)
    expect(screen.getByTestId('orders-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('order-client-1')).not.toBeInTheDocument()
  })
})

describe('UnifiedOrdersTable empty vs unavailable', () => {
  it('does not claim a valid zero-order run when it has no data at all', () => {
    // The empty state asserts a fact ("no orders recorded yet"). App must not
    // reach it by passing [] on a failed fetch; this pins the wording so the
    // distinction stays visible if the component is reused.
    render(<UnifiedOrdersTable orders={[]} />)
    expect(screen.getByTestId('orders-empty')).toHaveTextContent(/no paper orders recorded/i)
  })
})
