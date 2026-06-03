# Gumroad Listing — Weather Edge v2.2 (refreshed 2026-04-19)

## Product Title
Weather Edge — Kalshi Weather Market Signal Engine

## Tagline
Spot mispriced Kalshi weather contracts the moment the airport thermometer locks the outcome. GFS ensemble + real-time METAR, 100% free data, local-only, no subscriptions.

## Price
- Dashboard bundle (React + FastAPI + CLI): **$149**
- CLI-only starter: **$99**

## File
`WeatherEdge-gumroad-v2.2-2026-04-19.zip` (1 MB, 55 source files)

---

## Description (paste into Gumroad editor)

**Kalshi weather markets don't close until midnight. Airport thermometers lock the day's high by mid-afternoon. Weather Edge finds the window in between.**

This is a local dashboard that scans Kalshi's active high-temp and low-temp contracts every 5 minutes, computes a model probability from the GFS 31-member ensemble, and flags markets where the observed temperature already determines the outcome. Those are METAR locks — and the dashboard now pops a browser notification + plays a chime the instant a new one appears.

Everything runs on your machine. No accounts. No cloud. No telemetry.

---

### What you get

✅ **Live signal dashboard** — React + FastAPI web app on localhost:8000. Scans Kalshi + GFS + METAR every 5 minutes when armed.

✅ **20 US cities** — NYC, Chicago, LA, Houston, Dallas, Miami, Seattle, Denver, Phoenix, Boston, DC, SF, Atlanta, Minneapolis, OKC, Austin, San Antonio, New Orleans, Philadelphia, Las Vegas.

✅ **GFS 31-member ensemble** via Open-Meteo — fraction of members satisfying the market condition → model probability.

✅ **METAR real-time lock detection** via aviationweather.gov — after 1pm local, observed temperatures are checked for same-day high-temp markets. If the high is already guaranteed above or mathematically capped below the threshold, that row shows a gold `🔒 LOCK` badge.

✅ **🔔 Browser notifications + sound alert** — one-click toggle in the header. The moment a new METAR lock is detected, you get a desktop notification and a chime. Close the dashboard tab and you still get the pop-up when the next lock hits.

✅ **Edge calculation** — `|model_prob − kalshi_prob| − 7% fee`. Signals only flag as actionable above your configurable threshold (default 8%).

✅ **Kalshi API integration (optional)** — drop your RSA key ID + private key PEM into the Settings modal and the dashboard pulls your real balance, fills, and equity curve. PEM is written with `0600` file permissions. Keys stay local.

✅ **Simulation mode** — $10,000 paper bankroll so you can watch the strategy run for a few days before going live. This is the default.

✅ **One-command setup** — `start.bat` on Windows, `./start.sh` on Mac/Linux. Creates the venv, installs deps, launches the app. ~90 seconds on a fresh machine.

✅ **100% free data** — Open-Meteo (GFS), aviationweather.gov (METAR), Kalshi public market endpoints. No paid API keys required.

✅ **FastAPI `/docs`** — full OpenAPI schema at `localhost:8000/docs` if you want to script against it.

---

### What's new in v2.2 (2026-04-19)

**🔔 Lock alerts** — browser notification + two-tone chime the instant a new METAR lock is detected. One click in the header to enable. Works in the background.

**No auto-scan on startup.** Earlier builds fetched from Open-Meteo the moment you launched. Now the app boots paused and waits for you to press Start. Zero outbound requests until you're in the driver's seat.

**Weather-only codebase.** Stripped ~2,000 lines of unrelated modules that had leaked in from other prototypes. The code you install is the code that runs — no dead paths, no surprise dependencies.

**Localhost-only CORS.** Bound to `127.0.0.1` with a CORS allowlist of `localhost:8000` / `:5173`. Nothing else on your network can poke the API.

**Gold-highlighted locks.** METAR-lock rows get an amber row background and a `🔒 LOCK` pill so they don't blend in with GFS-only informational signals.

**Hardened Kalshi key handling.** PEM uploads are validated, stored with `0600` permissions, and never leave your machine.

**Graceful shutdown.** Ctrl+C now waits for the in-flight scan to finish before the process exits.

---

### The edge in plain English

Kalshi's `KXHIGHT*` contracts settle against the day's peak temperature. Every major US airport (NYC, ORD, DFW, etc.) publishes METAR observations every hour. By mid-afternoon, the day's high is either already above the threshold (YES is a sure thing) or mathematically capped below it (NO is a sure thing). The market knows this — but not always instantly, and not always efficiently, especially on thinly-traded city/threshold combinations.

Weather Edge watches for those moments and tells you about them — now with a notification, so you don't have to have the tab open.

---

### How it behaves on your machine

- Binds to `127.0.0.1:8000` only. No LAN exposure unless you change that yourself.
- Boots **paused**. Zero API calls to Kalshi or Open-Meteo until you press Start in the UI.
- One SQLite file (`tradingbot.db`) in the app directory. Holds simulated trades only. No credentials.
- No installer, no service, no autostart hook. When you close the terminal, the app is gone.
- If you want it to run at login, wire it up yourself with `launchctl` / `systemd` / Task Scheduler — there's a section in the README explaining why we don't do that for you (short answer: it's the kind of thing that gets a product flagged as malware, correctly).

---

### Requirements

- Python 3.10+ (3.13 tested)
- Node.js 18+ (only if you want to modify the UI — pre-built bundle is included)
- ~90 seconds of setup
- No paid API keys needed

---

### vs. the competition

The $67 competitor ships a CLI script with no METAR, no GFS ensemble, 5 cities, and no dashboard. Weather Edge v2.2 ships 20 cities, the 31-member ensemble, real-time METAR lock detection, browser alerts, a dashboard, and optional Kalshi API integration for **$149**.

---

### Refund policy

If Weather Edge doesn't work on your machine, message me and I'll refund the same day. No interrogation.

---

## Tags
kalshi, prediction markets, weather trading, algorithmic trading, python, fastapi, react, signal generation, gfs, metar, temperature contracts

## Category
Software > Finance / Trading Tools

## File
WeatherEdge-gumroad-v2.2-2026-04-19.zip
