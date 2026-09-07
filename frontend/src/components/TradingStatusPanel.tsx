import type { MirrorSnapshot, TradingStatus, TradingVenueState } from '../types'

interface Props {
  status: TradingStatus
  /** Optional read-only mirrors keyed by venue; changes a deferred row's state text only. */
  mirrors?: Partial<Record<string, MirrorSnapshot>>
}

/** Venues the system will not connect until a separately approved phase. */
const DEFERRED_VENUES = ['robinhood', 'coinbase'] as const

interface VenueRow {
  key: string
  label: string
  state: string
  tone: string
}

/**
 * Alpaca's three states are distinct on purpose.
 *
 * "configured" means credentials are present but nothing is enabled to use
 * them, which is the safe resting state and must not read as "connected".
 * "connected" requires the venue to actually be present and execution-enabled
 * in the backend's own view, not merely that a key exists in the environment.
 */
function alpacaState(status: TradingStatus): { state: string; tone: string } {
  const configured = status.credentials?.alpaca_paper === true
  const venue = status.venues.find((entry) => entry.venue === 'alpaca_paper')
  if (!configured) return { state: 'Disconnected', tone: '#a1a1aa' }
  if (venue && venue.execution_enabled) return { state: 'Connected', tone: '#22c55e' }
  return { state: 'Configured', tone: '#d97706' }
}

function simulationState(venue: TradingVenueState): { state: string; tone: string } {
  if (venue.monitor_only) return { state: 'Simulation / monitor only', tone: '#d97706' }
  if (venue.simulation) return { state: 'Simulation', tone: '#38bdf8' }
  return { state: venue.execution_enabled ? 'Enabled' : 'Disabled', tone: '#a1a1aa' }
}

function venueRows(status: TradingStatus, mirrors?: Props['mirrors']): VenueRow[] {
  const rows: VenueRow[] = []

  const alpaca = alpacaState(status)
  rows.push({ key: 'alpaca_paper', label: 'Alpaca Paper', state: alpaca.state, tone: alpaca.tone })

  for (const venue of status.venues) {
    if (venue.venue === 'alpaca_paper') continue
    const simulation = simulationState(venue)
    rows.push({
      key: venue.venue,
      label: venue.venue.replace(/_/g, ' '),
      state: simulation.state,
      tone: simulation.tone,
    })
  }

  for (const venue of DEFERRED_VENUES) {
    // A mirror never makes a deferred venue executable. It only changes what
    // the row says: the system can *see* the account, not act on it.
    const mirror = mirrors?.[venue]
    rows.push(
      mirror?.available
        ? { key: venue, label: venue, state: 'Read-only mirror', tone: '#d97706' }
        : { key: venue, label: venue, state: 'Deferred / disabled', tone: '#525252' },
    )
  }

  return rows
}

export function TradingStatusPanel({ status, mirrors }: Props) {
  const paperOnly = status.paper_only
  const killEngaged = status.kill_switch.engaged
  const archivesAvailable = status.archives.root_available && status.archives.root_configured

  return (
    <div className="space-y-3">
      {/* The badge reports what the backend claims, and says so loudly when the
          claim is not "paper". Rendering "PAPER ONLY" unconditionally would make
          the most important indicator on the dashboard a decoration. */}
      <div
        data-testid="paper-only-badge"
        className="inline-block px-2 py-1 text-[11px] font-bold tracking-widest border"
        style={{
          color: paperOnly ? '#22c55e' : '#dc2626',
          borderColor: paperOnly ? '#22c55e' : '#dc2626',
        }}
      >
        {paperOnly ? 'PAPER ONLY' : `NOT PAPER-ONLY — mode: ${status.execution_mode || 'unknown'}`}
      </div>

      <div
        data-testid="kill-switch"
        className="flex items-center justify-between text-[10px] border-t border-neutral-800 pt-2"
      >
        <span className="text-neutral-500">Kill switch</span>
        <span className="tabular-nums" style={{ color: killEngaged ? '#dc2626' : '#22c55e' }}>
          {killEngaged ? 'ENGAGED' : 'Disengaged'}
          <span className="text-neutral-600"> · {status.kill_switch.source}</span>
        </span>
      </div>

      <div data-testid="archives-state" className="flex items-center justify-between text-[10px]">
        <span className="text-neutral-500">Archives root</span>
        <span style={{ color: archivesAvailable ? '#22c55e' : '#dc2626' }}>
          {archivesAvailable ? 'Available' : 'UNAVAILABLE'}
        </span>
      </div>

      <div className="space-y-1 border-t border-neutral-800 pt-2">
        {venueRows(status, mirrors).map((row) => (
          <div
            key={row.key}
            data-testid={`venue-${row.key}`}
            className="flex items-center justify-between text-[10px]"
          >
            <span className="text-neutral-500 uppercase">{row.label}</span>
            <span data-testid="venue-state" style={{ color: row.tone }}>
              {row.state}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
