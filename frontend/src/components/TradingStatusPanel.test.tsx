/**
 * The status panel is the operator's answer to "can this thing spend money?"
 *
 * Every assertion here is about a claim the panel makes on screen. The one that
 * matters most is negative: the API sends credential PRESENCE as booleans and
 * never values, so the panel must have nothing to leak -- but a future edit
 * that starts rendering a credential object would still look fine to a test
 * that only checked for the words "connected".
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TradingStatusPanel } from './TradingStatusPanel'
import type { TradingStatus } from '../types'

function status(overrides: Partial<TradingStatus> = {}): TradingStatus {
  return {
    execution_mode: 'paper',
    paper_only: true,
    kill_switch: { engaged: false, source: 'TRADING_KILL_SWITCH' },
    lanes: { stock_crypto: false, weather_unified_ledger: true, scheduler_autostart: false },
    venues: [
      { venue: 'polymarket_paper', simulation: true, execution_enabled: true, monitor_only: false },
      { venue: 'kalshi_paper', simulation: true, execution_enabled: false, monitor_only: true },
    ],
    credentials: { alpaca_paper: false, kalshi: false, polymarket_api: false },
    archives: {
      root_configured: true,
      root_available: true,
      runtime_paths_contained: true,
      required_directories_present: true,
    },
    ...overrides,
  }
}

describe('TradingStatusPanel', () => {
  it('states PAPER ONLY prominently', () => {
    render(<TradingStatusPanel status={status()} />)
    expect(screen.getByTestId('paper-only-badge')).toHaveTextContent(/paper only/i)
  })

  it('warns instead of reassuring when the backend does not claim paper-only', () => {
    render(<TradingStatusPanel status={status({ paper_only: false, execution_mode: 'live' })} />)
    const badge = screen.getByTestId('paper-only-badge')
    expect(badge).not.toHaveTextContent(/^paper only$/i)
    expect(badge).toHaveTextContent(/not paper|unsafe|live/i)
  })

  it('shows Alpaca as disconnected when no credentials are present', () => {
    render(<TradingStatusPanel status={status()} />)
    expect(within(screen.getByTestId('venue-alpaca_paper')).getByTestId('venue-state'))
      .toHaveTextContent(/disconnected/i)
  })

  it('shows Alpaca as configured when credentials exist but the lane is off', () => {
    render(
      <TradingStatusPanel
        status={status({ credentials: { alpaca_paper: true }, lanes: { stock_crypto: false } })}
      />,
    )
    expect(within(screen.getByTestId('venue-alpaca_paper')).getByTestId('venue-state'))
      .toHaveTextContent(/configured/i)
  })

  it('shows Alpaca as connected only when credentials and an enabled venue agree', () => {
    render(
      <TradingStatusPanel
        status={status({
          credentials: { alpaca_paper: true },
          lanes: { stock_crypto: true },
          venues: [
            { venue: 'alpaca_paper', simulation: false, execution_enabled: true, monitor_only: false },
          ],
        })}
      />,
    )
    expect(within(screen.getByTestId('venue-alpaca_paper')).getByTestId('venue-state'))
      .toHaveTextContent(/connected/i)
  })

  it('renders Robinhood and Coinbase as deferred and disabled', () => {
    render(<TradingStatusPanel status={status()} />)
    for (const venue of ['robinhood', 'coinbase']) {
      expect(within(screen.getByTestId(`venue-${venue}`)).getByTestId('venue-state'))
        .toHaveTextContent(/deferred \/ disabled/i)
    }
  })

  it('distinguishes a simulated venue from a monitor-only one', () => {
    render(<TradingStatusPanel status={status()} />)
    expect(within(screen.getByTestId('venue-polymarket_paper')).getByTestId('venue-state'))
      .toHaveTextContent(/simulation/i)
    expect(within(screen.getByTestId('venue-kalshi_paper')).getByTestId('venue-state'))
      .toHaveTextContent(/monitor/i)
  })

  it('makes the kill switch state and its authoritative source visible', () => {
    render(<TradingStatusPanel status={status({ kill_switch: { engaged: true, source: 'TRADING_KILL_SWITCH' } })} />)
    const killSwitch = screen.getByTestId('kill-switch')
    expect(killSwitch).toHaveTextContent(/engaged/i)
    expect(killSwitch).toHaveTextContent('TRADING_KILL_SWITCH')
  })

  it('reports a disengaged kill switch as disengaged rather than omitting it', () => {
    render(<TradingStatusPanel status={status()} />)
    expect(screen.getByTestId('kill-switch')).toHaveTextContent(/disengaged/i)
  })

  it('surfaces an unavailable Archives root rather than hiding it', () => {
    render(
      <TradingStatusPanel
        status={status({
          archives: {
            root_configured: true,
            root_available: false,
            runtime_paths_contained: true,
            required_directories_present: true,
          },
        })}
      />,
    )
    expect(screen.getByTestId('archives-state')).toHaveTextContent(/unavailable/i)
  })

  it('renders no credential values, only presence', () => {
    const { container } = render(
      <TradingStatusPanel status={status({ credentials: { alpaca_paper: true } })} />,
    )
    // Presence is a boolean in the payload; nothing key-shaped can appear.
    expect(container.textContent).not.toMatch(/PK[A-Z0-9]{8,}/)
    expect(container.textContent).not.toMatch(/secret/i)
  })
})


describe('TradingStatusPanel with a mirror', () => {
  const mirror = {
    available: true, venue: 'robinhood', captured_at: '2026-09-07T00:40:00Z',
    source_agent: 'claude-desktop-mcp', total_value: '1', accounts: [],
  }

  it('shows a mirrored deferred venue as read-only, never as connected', () => {
    render(<TradingStatusPanel status={status()} mirrors={{ robinhood: mirror }} />)
    const state = within(screen.getByTestId('venue-robinhood')).getByTestId('venue-state')
    expect(state).toHaveTextContent(/read-only mirror/i)
    expect(state).not.toHaveTextContent(/connected/i)
  })

  it('leaves an unmirrored deferred venue as deferred', () => {
    render(<TradingStatusPanel status={status()} mirrors={{ robinhood: mirror }} />)
    expect(within(screen.getByTestId('venue-coinbase')).getByTestId('venue-state'))
      .toHaveTextContent(/deferred \/ disabled/i)
  })
})
