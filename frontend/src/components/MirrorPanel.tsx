import type { MirrorSnapshot } from '../types'

interface Props {
  snapshot: MirrorSnapshot
}

/**
 * A mirrored brokerage account is an observation, not a position the system
 * holds. Every number here was pushed by an agent that read it; nothing here
 * can be traded, and the paper risk gate never sees it. The label says so on
 * every render because the distinction is the whole point of the panel.
 */
export function MirrorPanel({ snapshot }: Props) {
  if (!snapshot.available) {
    return (
      <div data-testid="mirror-unavailable" className="text-[10px] text-neutral-600 py-2">
        No {snapshot.venue} snapshot pushed yet.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span
          data-testid="mirror-badge"
          className="inline-block px-2 py-0.5 text-[10px] font-bold tracking-widest border"
          style={{ color: '#d97706', borderColor: '#d97706' }}
        >
          READ-ONLY MIRROR — NOT TRADEABLE
        </span>
        <span data-testid="mirror-captured" className="text-[10px] text-neutral-500 tabular-nums">
          {snapshot.captured_at ? new Date(snapshot.captured_at).toLocaleString() : '—'}
          {snapshot.source_agent ? ` · ${snapshot.source_agent}` : ''}
        </span>
      </div>

      {snapshot.accounts.map((account) => (
        <div key={account.account_ref} data-testid={`mirror-account-${account.account_ref}`} className="space-y-1">
          <div className="flex items-center justify-between text-[10px]">
            <span className="text-neutral-300 uppercase">
              {account.label} <span className="text-neutral-600">{account.account_ref}</span>
            </span>
            <span className="tabular-nums text-neutral-200">
              {account.total_value} {account.currency}
              <span className="text-neutral-600"> · cash {account.cash} · bp {account.buying_power}</span>
            </span>
          </div>
          {account.positions.length === 0 ? (
            <div className="text-[10px] text-neutral-600 pl-2">No positions.</div>
          ) : (
            <table className="w-full text-[10px]">
              <tbody>
                {account.positions.map((position) => (
                  <tr key={`${account.account_ref}-${position.symbol}`} data-testid="mirror-position" className="border-t border-neutral-900">
                    <td className="py-0.5 text-neutral-300">{position.symbol}</td>
                    <td className="text-neutral-500">{position.asset_class}</td>
                    <td className="tabular-nums text-right text-neutral-300">{position.quantity}</td>
                    <td className="tabular-nums text-right text-neutral-500">
                      {position.average_cost ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </div>
  )
}
