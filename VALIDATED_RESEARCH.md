# Validated Research — Weather Edge

This file records currently validated, product-relevant facts for the Weather Edge Kalshi weather dashboard.

## Data sources

### Kalshi weather markets

- Source: Kalshi public market endpoints for market discovery and prices.
- Optional authenticated Kalshi API is used only when the user configures credentials for account/settlement checks.
- Product scope is Kalshi weather only.

### METAR observations

- Source: aviationweather.gov METAR JSON endpoint.
- Use for real-time airport observation context.
- High-temperature locks must wait for the current observation to cool from the observed peak before declaring a METAR lock, preventing premature locks on the way up.
- METAR cache must expire; stale observations cannot create fresh locks.

### GFS ensemble forecasts

- Source: Open-Meteo ensemble API using GFS data.
- Use as probabilistic model context and disagreement/veto context.
- Cache by required forecast horizon so a short-horizon cached payload does not mask farther target dates.

## Verified implementation contracts

- The backend defaults to 127.0.0.1 and all sensitive/admin mutations are localhost-gated.
- Startup is paused; scans begin only after Start or manual Scan.
- The frontend consumes weather_signals and weather_forecasts from /api/data.
- METAR Lock UI only shows actionable signals whose signal_source is METAR-lock.
- Legacy non-weather runtime modules and UI components are removed from the shipped app.
