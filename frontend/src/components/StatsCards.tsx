import { motion } from 'framer-motion'
import type { BotStats, BtcCalibrationSummary, WeatherCalibrationSummary } from '../types'

interface Props {
  stats: BotStats
  weatherCalibration?: WeatherCalibrationSummary | null
  weatherBotCalibration?: WeatherCalibrationSummary | null
  btcCalibration?: BtcCalibrationSummary | null
  showLegacySections?: boolean
}

export function StatsCards({ stats, weatherCalibration, weatherBotCalibration, btcCalibration, showLegacySections = false }: Props) {
  const weather = stats.weather_paper_account
  const btc = stats.btc_paper_account
  const entertainment = stats.entertainment_paper_account
  const primaryAccount = showLegacySections ? null : weather
  const primaryBankroll = primaryAccount?.current_equity ?? stats.bankroll
  const primaryPnl = primaryAccount?.realized_pnl ?? stats.total_pnl
  const primaryTrades = primaryAccount?.total_trades ?? stats.total_trades
  const primaryWinningTrades = primaryAccount?.winning_trades ?? stats.winning_trades
  const winRate = primaryTrades > 0 ? (primaryWinningTrades / primaryTrades * 100) : 0
  const returnPercent = primaryBankroll - primaryPnl > 0
    ? ((primaryPnl / (primaryBankroll - primaryPnl)) * 100)
    : 0
  const weatherLedgerState = weather
    ? weather.ledger_exposure_state === 'all_settled'
      ? 'all settled'
      : weather.ledger_exposure_state === 'open_positions'
        ? `open $${weather.pending_size.toFixed(0)}`
        : weather.ledger_exposure_state === 'no_trades'
          ? 'no trades'
          : weather.ledger_exposure_state
    : null
  const weatherPlatformBreakdown = weather?.platform_breakdown?.length
    ? weather.platform_breakdown.map((venue) => {
      const label = venue.platform === 'polymarket'
        ? 'PM'
        : venue.platform === 'kalshi'
          ? 'K'
          : venue.platform
      const sign = venue.realized_pnl >= 0 ? '+' : '-'
      return `${label} ${sign}$${Math.abs(venue.realized_pnl).toFixed(0)}`
    }).join(' · ')
    : null

  return (
    <div className="flex items-center gap-3">
      <motion.div className="flex items-center gap-1.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <span className="text-[10px] text-neutral-600 uppercase">Bank</span>
        <span className="text-sm font-semibold tabular-nums text-neutral-100">
          ${primaryBankroll >= 1000 ? (primaryBankroll / 1000).toFixed(1) + 'K' : primaryBankroll.toFixed(0)}
        </span>
      </motion.div>

      <div className="w-px h-3 bg-neutral-800" />

      <motion.div className="flex items-center gap-1.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.05 }}>
        <span className="text-[10px] text-neutral-600 uppercase">P&L</span>
        <span className={`text-sm font-semibold tabular-nums ${primaryPnl >= 0 ? 'text-green-500 glow-green' : 'text-red-500 glow-red'}`}>
          {primaryPnl >= 0 ? '+' : ''}${Math.abs(primaryPnl).toFixed(0)}
        </span>
        <span className={`text-[10px] tabular-nums ${returnPercent >= 0 ? 'text-green-500/60' : 'text-red-500/60'}`}>
          {returnPercent >= 0 ? '+' : ''}{returnPercent.toFixed(1)}%
        </span>
      </motion.div>

      <div className="w-px h-3 bg-neutral-800" />

      <motion.div className="flex items-center gap-1.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }}>
        <span className="text-[10px] text-neutral-600 uppercase">Win</span>
        <span className={`text-sm font-semibold tabular-nums ${winRate >= 55 ? 'text-green-500' : winRate >= 45 ? 'text-yellow-500' : 'text-red-500'}`}>
          {winRate.toFixed(0)}%
        </span>
        <span className="text-[10px] text-neutral-600 tabular-nums">
          {primaryWinningTrades}/{primaryTrades}
        </span>
      </motion.div>

      <div className="w-px h-3 bg-neutral-800" />

      <motion.div className="flex items-center gap-1.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }}>
        <span className="text-[10px] text-neutral-600 uppercase">Trades</span>
        <span className="text-sm font-semibold tabular-nums text-neutral-100">{primaryTrades}</span>
        {stats.is_running && <div className="live-dot" />}
      </motion.div>

      {showLegacySections && btc && (
        <>
          <div className="w-px h-3 bg-neutral-800" />
          <motion.div className="flex items-center gap-1.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 }}>
            <span className="text-[10px] text-neutral-600 uppercase">BTC Paper</span>
            <span className={`text-sm font-semibold tabular-nums ${btc.realized_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              ${btc.current_equity.toFixed(0)}
            </span>
            <span className="text-[10px] text-neutral-600 tabular-nums">
              {btc.progress_to_target_pct.toFixed(0)}% → ${btc.target_bankroll.toFixed(0)}
            </span>
            <span className="text-[10px] text-neutral-700 tabular-nums" title="BTC calibration is Chainlink boundary/outcome scoring scaffolding only, not paper P&L or bot alpha">
              {btcCalibration?.settled_forecasts && btcCalibration.brier_score !== null
                ? `Brier ${btcCalibration.brier_score.toFixed(3)}`
                : btcCalibration?.scoring_rows
                  ? `Cal rows ${btcCalibration.scoring_rows}`
                  : btc.settled_forecasts > 0 && btc.brier_score !== null
                    ? `Brier ${btc.brier_score.toFixed(3)}`
                    : '0 scored'}
            </span>
          </motion.div>
        </>
      )}

      {weather && (
        <>
          <div className="w-px h-3 bg-neutral-800" />
          <motion.div className="flex items-center gap-1.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 }}>
            <span className="text-[10px] text-neutral-600 uppercase">Weather Paper</span>
            <span className={`text-sm font-semibold tabular-nums ${weather.realized_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              ${weather.current_equity.toFixed(0)}
            </span>
            <span className="text-[10px] text-neutral-600 tabular-nums">
              {weather.progress_to_target_pct.toFixed(0)}% → ${weather.target_bankroll.toFixed(0)}
            </span>
            <span
              className="text-[10px] text-neutral-600 tabular-nums"
              title="Remaining to target and settled/open paper weather trade counts"
            >
              {`rem $${weather.remaining_to_target.toFixed(0)} · settled ${weather.settled_trades} / open ${weather.pending_trades}`}
            </span>
            {weatherLedgerState && (
              <span className="text-[10px] text-neutral-700 tabular-nums" title={weather.ledger_status_note}>
                {weatherLedgerState}
              </span>
            )}
            {weatherPlatformBreakdown && (
              <span
                className="text-[10px] text-neutral-700 tabular-nums"
                title="Venue split uses settled PnL only; pending venue size is audit metadata, not a separate bankroll"
              >
                {weatherPlatformBreakdown}
              </span>
            )}
            <span className="text-[10px] text-neutral-700 tabular-nums" title="Weather bot calibration is model-score QA only; market-implied calibration remains separate from paper P&L and bot alpha">
              {weatherBotCalibration?.settled_forecasts && weatherBotCalibration.brier_score !== null
                ? `Bot Brier ${weatherBotCalibration.brier_score.toFixed(3)}`
                : weatherCalibration?.settled_forecasts && weatherCalibration.brier_score !== null
                  ? `Mkt Brier ${weatherCalibration.brier_score.toFixed(3)}`
                : weather.settled_forecasts > 0 && weather.brier_score !== null
                  ? `Brier ${weather.brier_score.toFixed(3)}`
                  : '0 scored'}
            </span>
          </motion.div>
        </>
      )}

      {showLegacySections && entertainment && (
        <>
          <div className="w-px h-3 bg-neutral-800" />
          <motion.div className="flex items-center gap-1.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }}>
            <span className="text-[10px] text-neutral-600 uppercase">RT Paper</span>
            <span className={`text-sm font-semibold tabular-nums ${entertainment.realized_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              ${entertainment.current_equity.toFixed(0)}
            </span>
            <span className="text-[10px] text-neutral-600 tabular-nums">
              {entertainment.progress_to_target_pct.toFixed(0)}% → ${entertainment.target_bankroll.toFixed(0)}
            </span>
          </motion.div>
        </>
      )}
    </div>
  )
}
