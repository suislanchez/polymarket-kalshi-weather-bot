/**
 * The trading posture must survive a slow weather dashboard.
 *
 * /api/dashboard aggregates several upstreams and can hang; App returns a
 * full-screen spinner while it loads. That early return used to hide the
 * paper-only badge and the kill switch -- the two indicators an operator most
 * needs precisely when something is not responding.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { TradingStatus } from './types'

const STATUS: TradingStatus = {
  execution_mode: 'paper',
  paper_only: true,
  kill_switch: { engaged: false, source: 'LIVE_TRADING_ENABLED' },
  lanes: { stock_crypto: false },
  venues: [],
  credentials: { alpaca_paper: false },
  archives: {
    root_configured: true,
    root_available: true,
    runtime_paths_contained: true,
    required_directories_present: true,
  },
}

vi.mock('./api', () => ({
  // A fetch that never settles, which is the failure being guarded. Defined
  // inside the factory because vi.mock is hoisted above module-scope consts.
  fetchDashboard: vi.fn(() => new Promise(() => {})),
  fetchPolymarketWeatherSourceStates: vi.fn(() => new Promise(() => {})),
  fetchTradingStatus: vi.fn(async () => STATUS),
  fetchMirrorSnapshot: vi.fn(async () => ({ available: false, venue: 'robinhood', captured_at: null, source_agent: null, total_value: null, accounts: [] })),
  fetchTradingOrders: vi.fn(async () => []),
  fetchTradingPortfolio: vi.fn(async () => ({
    available: false,
    reason: 'no adapter',
    equity: null,
    cash: null,
    positions: [],
  })),
  runScan: vi.fn(),
  simulateTrade: vi.fn(),
  startBot: vi.fn(),
  stopBot: vi.fn(),
}))

// The globe pulls in WebGL; it is irrelevant to this assertion.
vi.mock('./components/GlobeView', () => ({ GlobeView: () => null }))

import App from './App'

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

describe('App when the weather dashboard has failed', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the Connection Error screen, confirming the guarded branch', async () => {
    const api = await import('./api')
    vi.mocked(api.fetchDashboard).mockRejectedValue(new Error('upstream down'))
    renderApp()
    expect(await screen.findByText(/connection error/i)).toBeInTheDocument()
  })

  it('still reports paper-only state', async () => {
    const api = await import('./api')
    vi.mocked(api.fetchDashboard).mockRejectedValue(new Error('upstream down'))
    renderApp()
    expect(await screen.findByTestId('paper-only-badge')).toHaveTextContent(/paper only/i)
  })

  it('still reports the kill switch', async () => {
    const api = await import('./api')
    vi.mocked(api.fetchDashboard).mockRejectedValue(new Error('upstream down'))
    renderApp()
    expect(await screen.findByTestId('kill-switch')).toHaveTextContent(/disengaged/i)
  })
})

describe('App while the weather dashboard is still loading', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the spinner, confirming the guarded branch is the one under test', async () => {
    renderApp()
    expect(await screen.findByText(/initializing/i)).toBeInTheDocument()
  })

  it('still reports paper-only state', async () => {
    renderApp()
    expect(await screen.findByTestId('paper-only-badge')).toHaveTextContent(/paper only/i)
  })

  it('still reports the kill switch', async () => {
    renderApp()
    expect(await screen.findByTestId('kill-switch')).toHaveTextContent(/disengaged/i)
  })
})
