# Weather Edge Research Notes

Weather Edge is now a Kalshi-only weather signal dashboard. Historical cross-venue and non-weather research was removed from the app package so the shipped code and documentation match the weather-only product.

## Current product scope

- Venue: Kalshi weather markets only.
- Data: Kalshi public market data, aviationweather.gov METAR observations, Open-Meteo GFS ensemble forecasts.
- Runtime: local FastAPI + React dashboard, localhost by default.
- Trading mode: simulation by default; optional Kalshi credentials for account/settlement checks.

## Core research assumptions

1. Same-day high-temperature locks should not fire while temperature is still printing the high. Weather Edge waits until the observed high has crossed the threshold and the current reading is cooling from that peak.
2. GFS ensemble output is probabilistic context, not a physical lock. It can support or veto a signal but should not be presented as settlement certainty.
3. METAR freshness matters. Cached METAR data must expire and stale observations must not create new locks.
4. Kalshi high-temperature YES semantics are inclusive: the day reaches the listed threshold. Low-temperature YES semantics are inclusive in the opposite direction.
5. All UI copy, API contracts, and code paths should remain weather-only.
