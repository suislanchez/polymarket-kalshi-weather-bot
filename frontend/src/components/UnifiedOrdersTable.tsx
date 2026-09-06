import type { UnifiedOrder } from '../types'

interface Props {
  orders: UnifiedOrder[]
}

const STATUS_TONE: Record<string, string> = {
  filled: '#22c55e',
  partially_filled: '#38bdf8',
  submitted: '#38bdf8',
  approved: '#a1a1aa',
  proposed: '#a1a1aa',
  canceled: '#a1a1aa',
  rejected: '#dc2626',
  risk_rejected: '#dc2626',
}

/**
 * Money and quantities are rendered as the strings the API sent.
 *
 * They are exact Decimals in the ledger and cross the boundary as strings for
 * that reason; Number(...) here would undo the whole arrangement at the last
 * step. Nothing in this file does arithmetic on them.
 */
function exact(value: string | null): string {
  return value === null || value === '' ? '—' : value
}

/** An absent identity is reported, never guessed. */
function identity(value: string | null): string {
  return value === null || value === '' ? 'not recorded' : value
}

export function UnifiedOrdersTable({ orders }: Props) {
  if (orders.length === 0) {
    return (
      <div data-testid="orders-empty" className="text-[10px] text-neutral-600 py-3">
        No paper orders recorded yet. A run with zero orders is a valid run.
      </div>
    )
  }

  return (
    <table className="w-full text-[10px]">
      <thead>
        <tr className="text-neutral-500 text-left">
          <th className="font-normal py-1">Venue</th>
          <th className="font-normal">Symbol</th>
          <th className="font-normal">Side</th>
          <th className="font-normal">Status</th>
          <th className="font-normal text-right">Qty</th>
          <th className="font-normal text-right">Notional</th>
          <th className="font-normal text-right">Mode</th>
        </tr>
      </thead>
      <tbody>
        {orders.map((order) => (
          <tr
            key={order.client_order_id}
            data-testid={`order-${order.client_order_id}`}
            className="border-t border-neutral-900"
          >
            <td data-testid="order-venue" className="py-1 text-neutral-400">
              {order.venue}
            </td>
            <td data-testid="order-symbol" className="text-neutral-300">
              {identity(order.symbol)}
            </td>
            <td data-testid="order-side" className="uppercase text-neutral-400">
              {identity(order.side)}
            </td>
            <td data-testid="order-status" style={{ color: STATUS_TONE[order.status] ?? '#a1a1aa' }}>
              {order.status}
              {order.rejection_reason ? (
                <span className="text-neutral-500"> · {order.rejection_reason}</span>
              ) : null}
            </td>
            <td data-testid="order-quantity" className="tabular-nums text-right text-neutral-300">
              {exact(order.filled_quantity)}
            </td>
            <td data-testid="order-notional" className="tabular-nums text-right text-neutral-300">
              {exact(order.filled_notional)}
            </td>
            {/* Every venue this table can show is a paper venue; the column
                exists so the reader never has to infer it. */}
            <td data-testid="order-mode" className="text-right text-neutral-500">
              PAPER
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
