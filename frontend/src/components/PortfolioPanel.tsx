import type { TradingPortfolio } from '../types'

interface Props {
  portfolio: TradingPortfolio
}

/**
 * Absent state is shown as absent.
 *
 * The backend returns available=false with a reason rather than a placeholder,
 * because a risk decision made against invented exposure would be written to an
 * append-only ledger as though it were real. The panel keeps that property:
 * there is no "$0.00" fallback here.
 */
export function PortfolioPanel({ portfolio }: Props) {
  if (!portfolio.available) {
    return (
      <div data-testid="portfolio-unavailable" className="text-[10px] text-neutral-600 py-2">
        Portfolio unavailable{portfolio.reason ? ` · ${portfolio.reason}` : ''}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-4">
        <div>
          <div className="text-[10px] text-neutral-500">Equity</div>
          <div data-testid="portfolio-equity" className="text-lg font-bold tabular-nums text-neutral-200">
            {portfolio.equity ?? '—'}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-neutral-500">Cash</div>
          <div data-testid="portfolio-cash" className="text-lg font-bold tabular-nums text-neutral-200">
            {portfolio.cash ?? '—'}
          </div>
        </div>
      </div>

      {portfolio.positions.length === 0 ? (
        <div data-testid="positions-empty" className="text-[10px] text-neutral-600">
          No open positions.
        </div>
      ) : (
        <div className="space-y-1">
          {portfolio.positions.map((position) => (
            <div
              key={position.symbol}
              data-testid={`position-${position.symbol}`}
              className="flex items-center justify-between text-[10px]"
            >
              <span className="text-neutral-400">{position.symbol}</span>
              <span className="tabular-nums text-neutral-300">
                {position.quantity} · {position.notional}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
