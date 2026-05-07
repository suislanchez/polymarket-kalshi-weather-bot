"""
Weather Edge - Superior GFS Ensemble + METAR Signal Engine
============================================================
Replaces the original weather_signals.py with our proven Kalshi weather model.

Uses:
  - NOAA GFS 31-member ensemble via open-meteo (free, no key)
  - METAR real-time lock detection via aviationweather.gov (free, no key)
  - Kalshi public market API (no auth required for reads)

Supports rain, temperature_high, temperature_low, snow markets for 200+ tickers.
"""
import asyncio
import logging
import os
import pickle
import re
import time
import requests
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.models.database import SessionLocal, Signal

logger = logging.getLogger("trading_bot")

# ─── CONFIG ────────────────────────────────────────────────────────────────────
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
ENSEMBLE_BASE = "https://ensemble-api.open-meteo.com/v1/ensemble"
METAR_BASE = "https://aviationweather.gov/api/data/metar"
FEE_ESTIMATE = 0.07    # Kalshi ~7% effective fee
EDGE_THRESHOLD = 0.10  # Flag if |net edge| > this

# Weather market series to scan
WEATHER_SERIES = [
    "KXRAINNYC", "KXRAINHOUM", "KXRAINLAXM", "KXRAINSFOM",
    "KXRAINCHIM", "KXRAINDENM", "KXRAINMIAM", "KXRAINSEAM",
    "KXRAINDALM", "KXRAINAUSM",
    "KXHIGHNY",  "KXHIGHTLV",  "KXHIGHTPHX", "KXHIGHTHOU",
    "KXHIGHTSEA", "KXHIGHTDC", "KXHIGHTBOS", "KXHIGHTDAL",
    "KXHIGHTOKC", "KXHIGHTATL", "KXHIGHTMIN", "KXHIGHTPHIL",
    "KXHIGHTSFO", "KXHIGHTSATX", "KXHIGHTNOLA", "KXHIGHTCHI",
    "KXTEMPNYCH",
]

# City → ICAO airport code for METAR
CITY_AIRPORTS = {
    "New York": "KJFK",   "NYC": "KJFK",
    "Los Angeles": "KLAX", "LA": "KLAX",
    "Chicago": "KORD",    "Dallas": "KDFW",
    "Houston": "KIAH",    "Atlanta": "KATL",
    "Miami": "KMIA",      "Seattle": "KSEA",
    "Denver": "KDEN",     "Boston": "KBOS",
    "Phoenix": "KPHX",    "New Orleans": "KMSY", "NOLA": "KMSY",
    "Philadelphia": "KPHL", "Austin": "KAUS",
    "Las Vegas": "KLAS",  "Washington": "KDCA",
    "San Francisco": "KSFO", "Minneapolis": "KMSP",
    "Oklahoma City": "KOKC", "San Antonio": "KSAT",
}

# City timezone mapping
CITY_TIMEZONES = {
    "new york": "America/New_York",       "nyc": "America/New_York",
    "los angeles": "America/Los_Angeles", "lax": "America/Los_Angeles",
    "chicago": "America/Chicago",         "chi": "America/Chicago",
    "houston": "America/Chicago",         "hou": "America/Chicago",
    "dallas": "America/Chicago",          "dal": "America/Chicago",
    "miami": "America/New_York",          "mia": "America/New_York",
    "seattle": "America/Los_Angeles",     "sea": "America/Los_Angeles",
    "denver": "America/Denver",           "den": "America/Denver",
    "phoenix": "America/Phoenix",         "phx": "America/Phoenix",
    "las vegas": "America/Los_Angeles",   "tlv": "America/Los_Angeles",
    "las": "America/Los_Angeles",
    "washington": "America/New_York",     "dc": "America/New_York",
    "boston": "America/New_York",         "bos": "America/New_York",
    "san francisco": "America/Los_Angeles", "sf": "America/Los_Angeles",
    "sfo": "America/Los_Angeles",
    "atlanta": "America/New_York",        "atl": "America/New_York",
    "minneapolis": "America/Chicago",     "min": "America/Chicago",
    "oklahoma city": "America/Chicago",   "okc": "America/Chicago",
    "austin": "America/Chicago",          "aus": "America/Chicago",
    "san antonio": "America/Chicago",     "satx": "America/Chicago",
    "new orleans": "America/Chicago",     "nola": "America/Chicago",
    "philadelphia": "America/New_York",   "phil": "America/New_York",
    "phila": "America/New_York",
}

# City → (latitude, longitude)
CITY_COORDS = {
    "new york":      (40.7128, -74.0060),  "nyc":           (40.7128, -74.0060),
    "los angeles":   (34.0522, -118.2437), "lax":           (34.0522, -118.2437),
    "chicago":       (41.8781, -87.6298),  "chi":           (41.8781, -87.6298),
    "houston":       (29.7604, -95.3698),  "hou":           (29.7604, -95.3698),
    "dallas":        (32.7767, -96.7970),  "dal":           (32.7767, -96.7970),
    "miami":         (25.7617, -80.1918),  "mia":           (25.7617, -80.1918),
    "seattle":       (47.6062, -122.3321), "sea":           (47.6062, -122.3321),
    "denver":        (39.7392, -104.9903), "den":           (39.7392, -104.9903),
    "phoenix":       (33.4484, -112.0740), "phx":           (33.4484, -112.0740),
    "las vegas":     (36.1699, -115.1398), "tlv":           (36.1699, -115.1398),
    "las":           (36.1699, -115.1398),
    "washington":    (38.9072, -77.0369),  "dc":            (38.9072, -77.0369),
    "boston":        (42.3601, -71.0589),  "bos":           (42.3601, -71.0589),
    "san francisco": (37.7749, -122.4194), "sf":            (37.7749, -122.4194),
    "sfo":           (37.7749, -122.4194),
    "atlanta":       (33.7490, -84.3880),  "atl":           (33.7490, -84.3880),
    "minneapolis":   (44.9778, -93.2650),  "min":           (44.9778, -93.2650),
    "oklahoma city": (35.4676, -97.5164),  "okc":           (35.4676, -97.5164),
    "austin":        (30.2672, -97.7431),  "aus":           (30.2672, -97.7431),
    "san antonio":   (29.4241, -98.4936),  "satx":          (29.4241, -98.4936),
    "new orleans":   (29.9511, -90.0715),  "nola":          (29.9511, -90.0715),
    "philadelphia":  (39.9526, -75.1652),  "phil":          (39.9526, -75.1652),
    "phila":         (39.9526, -75.1652),
}

# Module-level caches with TTL (GFS updates every 6h, METAR every 30min)
_ensemble_cache: dict = {}       # key -> (timestamp, data)
_metar_cache: dict = {}          # key -> (timestamp, data)
_ENSEMBLE_CACHE_TTL = 10800      # 3 hours — GFS data is stable
_METAR_CACHE_TTL = 1800          # 30 minutes — METAR is real-time

# Disk cache path — survives restarts
_DISK_CACHE_PATH = os.path.join(os.path.dirname(__file__), "../../../../.ensemble_cache.pkl")
_DISK_CACHE_PATH = os.path.abspath(_DISK_CACHE_PATH)

# Quota circuit breaker — tracks 429s per UTC day
# If we hit too many 429s, stop fetching until midnight UTC resets the quota
_quota_exhausted_date: Optional[str] = None   # "YYYY-MM-DD" if exhausted today
_consecutive_429s: int = 0
_MAX_CONSECUTIVE_429S = 3  # after this many in a row, mark quota exhausted

# Result cache — populated by scheduler, served instantly to dashboard
_last_signal_results: list = []
_last_signal_timestamp: float = 0.0


def _load_disk_cache():
    """Load ensemble cache from disk on startup to survive restarts."""
    global _ensemble_cache
    try:
        if os.path.exists(_DISK_CACHE_PATH):
            with open(_DISK_CACHE_PATH, "rb") as f:
                loaded = pickle.load(f)
            # Only keep entries that haven't expired
            now = time.time()
            valid = {k: v for k, v in loaded.items() if now - v[0] < _ENSEMBLE_CACHE_TTL}
            _ensemble_cache = valid
            if valid:
                logger.info(f"Loaded {len(valid)} ensemble cache entries from disk")
    except Exception as e:
        logger.warning(f"Failed to load disk cache: {e}")
        _ensemble_cache = {}


def _save_disk_cache():
    """Persist ensemble cache to disk."""
    try:
        with open(_DISK_CACHE_PATH, "wb") as f:
            pickle.dump(_ensemble_cache, f)
    except Exception as e:
        logger.warning(f"Failed to save disk cache: {e}")


def _is_quota_exhausted() -> bool:
    """Return True if open-meteo quota is exhausted for today (UTC)."""
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _quota_exhausted_date == today_utc


def _mark_quota_exhausted():
    global _quota_exhausted_date
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _quota_exhausted_date != today_utc:
        logger.warning(f"open-meteo quota exhausted for {today_utc} — suspending GFS fetches until midnight UTC")
        _quota_exhausted_date = today_utc


# Load disk cache on module import
_load_disk_cache()


def get_cached_signals() -> list:
    """Return the most recently scanned signals without triggering a new scan."""
    return _last_signal_results


def get_signal_cache_age_seconds() -> float:
    """Seconds since last signal scan completed."""
    import time
    return time.time() - _last_signal_timestamp if _last_signal_timestamp else float('inf')


# ─── DATA CLASSES ───────────────────────────────────────────────────────────────

@dataclass
class KalshiWeatherMarket:
    """Minimal market descriptor mirroring the WeatherMarket interface."""
    market_id: str
    slug: str
    platform: str = "kalshi"
    title: str = ""
    city_key: str = ""
    city_name: str = ""
    target_date: date = field(default_factory=date.today)
    threshold_f: float = 0.0
    threshold_c: float = 0.0
    threshold_mm: float = 0.0
    metric: str = "high"      # "high", "low", "rain", "snow"
    direction: str = "above"
    yes_price: float = 0.5
    no_price: float = 0.5
    volume: float = 0.0


@dataclass
class WeatherTradingSignal:
    """Trading signal for a Kalshi weather market."""
    market: KalshiWeatherMarket

    model_probability: float = 0.5
    market_probability: float = 0.5
    edge: float = 0.0
    net_edge: float = 0.0
    direction: str = "yes"      # "yes" or "no"

    confidence: float = 0.5
    kelly_fraction: float = 0.0
    suggested_size: float = 0.0

    sources: List[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    ensemble_mean: float = 0.0
    ensemble_std: float = 0.0
    ensemble_members: int = 0

    gfs_prob: float = 0.0
    signal_source: str = "GFS-ensemble"
    metar_note: str = ""

    @property
    def passes_threshold(self) -> bool:
        if self.signal_source == "METAR-early" or self.suggested_size <= 0:
            return False
        return self.net_edge >= settings.WEATHER_MIN_EDGE_THRESHOLD


# ─── UTILITY FUNCTIONS ───────────────────────────────────────────────────────────

def celsius_to_fahrenheit(c: float) -> float:
    return c * 9 / 5 + 32


def fahrenheit_to_celsius(f: float) -> float:
    return (f - 32) * 5 / 9


# ─── METAR FETCHING ─────────────────────────────────────────────────────────────

def fetch_metar(icao: str) -> Optional[list]:
    """Fetch recent METAR observations for an airport, honoring the METAR TTL."""
    now = time.time()
    cached = _metar_cache.get(icao)
    if cached is not None:
        cached_ts, cached_data = cached
        if now - cached_ts < _METAR_CACHE_TTL:
            return cached_data
    try:
        params = {"ids": icao, "format": "json", "hours": 12}
        resp = requests.get(METAR_BASE, params=params, timeout=10)
        if resp.status_code != 200:
            # Cache failures briefly only; METAR freshness matters for locks.
            _metar_cache[icao] = (now, None)
            return None
        data = resp.json()
        if not data:
            _metar_cache[icao] = (now, None)
            return None
        _metar_cache[icao] = (now, data)
        return data
    except Exception as e:
        logger.warning(f"METAR fetch error for {icao}: {e}")
        _metar_cache[icao] = (now, None)
        return None


def get_metar_temps(city: str, today: date) -> Optional[dict]:
    """
    Fetch METAR for a city and return current_temp_f, max_temp_f, local_hour, icao.
    """
    icao = None
    for key, code in CITY_AIRPORTS.items():
        if key.lower() == city.lower():
            icao = code
            break
    if not icao:
        return None

    obs_list = fetch_metar(icao)
    if not obs_list:
        return None

    today_str = today.isoformat()
    temps_today = []
    current_temp_f = None

    for obs in obs_list:
        temp_c = obs.get("temp")
        obs_time = obs.get("obsTime")
        if temp_c is None:
            continue
        temp_f = celsius_to_fahrenheit(temp_c)

        obs_date_str = None
        if isinstance(obs_time, (int, float)):
            obs_date_str = datetime.fromtimestamp(obs_time, tz=timezone.utc).strftime("%Y-%m-%d")
        elif isinstance(obs_time, str) and len(obs_time) >= 10:
            obs_date_str = obs_time[:10]

        if obs_date_str == today_str:
            temps_today.append(temp_f)
        if current_temp_f is None:
            current_temp_f = temp_f

    if current_temp_f is None:
        return None

    max_temp_f = max(temps_today) if temps_today else current_temp_f

    tz_name = CITY_TIMEZONES.get(city.lower(), "UTC")
    try:
        tz = ZoneInfo(tz_name)
        local_now = datetime.now(tz)
        local_hour = local_now.hour
    except Exception:
        local_hour = datetime.now(timezone.utc).hour

    return {
        "icao": icao,
        "current_temp_f": round(current_temp_f, 1),
        "max_temp_f": round(max_temp_f, 1),
        "local_hour": local_hour,
    }


def metar_high_probability(max_observed_temp_f: float, current_temp_f: float,
                            threshold_f: float, local_hour: int) -> tuple:
    """
    For Kalshi KXHIGHT markets: YES wins when the day's high reaches the
    listed threshold. Returns P(YES), confidence, note.

    If max already reaches threshold → YES is locked → P(YES) ≈ 0.99
    If max is very unlikely to reach threshold late in day → P(YES) is low.
    """
    if max_observed_temp_f >= threshold_f:
        cooling_from_peak = max_observed_temp_f - current_temp_f
        if cooling_from_peak >= 1.0:
            # Threshold was reached and temperature has started falling, so the
            # observed peak is no longer just an in-progress upward tick.
            return 0.99, "high", f"Max already {max_observed_temp_f}°F >= {threshold_f}°F and cooling {cooling_from_peak:.1f}°F from peak — YES locked"
        return 0.90, "medium", f"Max already {max_observed_temp_f}°F >= {threshold_f}°F, waiting for cooling before lock"

    if local_hour >= 17:
        headroom = 2
    elif local_hour >= 15:
        headroom = 4
    elif local_hour >= 13:
        headroom = 6
    else:
        headroom = None

    if headroom is not None:
        likely_max = current_temp_f + headroom
        if likely_max < threshold_f - 2:
            # Very unlikely to reach threshold — YES unlikely.
            return 0.05, "high", f"Current {current_temp_f}°F + {headroom}°F buffer = {likely_max:.1f}°F < {threshold_f}°F — YES unlikely"
        elif likely_max >= threshold_f:
            # Likely to reach threshold — monitor until physical lock.
            return 0.90, "medium", f"Current {current_temp_f}°F + {headroom}°F buffer = {likely_max:.1f}°F may hit {threshold_f}°F"

    return None, "low", "Too early for METAR lock"


# ─── KALSHI MARKET FETCHING ──────────────────────────────────────────────────────

def fetch_kalshi_weather_markets() -> list:
    """Fetch all open weather markets from Kalshi (public API, no auth)."""
    all_markets = []
    seen_tickers = set()

    for series in WEATHER_SERIES:
        try:
            url = f"{KALSHI_BASE}/markets"
            params = {"limit": 100, "status": "open", "series_ticker": series}
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                markets = resp.json().get("markets", [])
                new = [m for m in markets if m["ticker"] not in seen_tickers]
                all_markets.extend(new)
                for m in new:
                    seen_tickers.add(m["ticker"])
            else:
                logger.debug(f"Kalshi {series}: HTTP {resp.status_code}")
        except Exception as e:
            logger.debug(f"Kalshi {series}: {e}")

    logger.info(f"Kalshi: {len(all_markets)} weather markets found")
    return all_markets


# ─── MARKET PARSING ─────────────────────────────────────────────────────────────

def parse_market_date(market: dict) -> Optional[date]:
    """Extract the target date from a Kalshi market dict."""
    ticker = market.get("ticker", "")
    rules = market.get("rules_primary", "")

    for pat in [r"on (\w+ \d+, \d{4})", r"(\w+ \d+, \d{4})", r"(\d{4}-\d{2}-\d{2})"]:
        m = re.search(pat, rules)
        if m:
            try:
                ds = m.group(1)
                if "-" in ds:
                    return datetime.strptime(ds, "%Y-%m-%d").date()
                else:
                    return datetime.strptime(ds, "%B %d, %Y").date()
            except Exception:
                pass

    m = re.search(r"-(\d{2})(\w{3})(\d{2})-", ticker)
    if m:
        try:
            year = 2000 + int(m.group(1))
            return datetime.strptime(f"{year}-{m.group(2)}-{int(m.group(3)):02d}", "%Y-%b-%d").date()
        except Exception:
            pass

    ct = market.get("close_time", "")
    if ct:
        try:
            return datetime.fromisoformat(ct.replace("Z", "+00:00")).date()
        except Exception:
            pass
    return None


def parse_market_type(market: dict) -> dict:
    """
    Returns dict with type, city, threshold_mm, threshold_f, threshold_c.
    """
    ticker = market.get("ticker", "")
    title = market.get("title", "").lower()
    rules = market.get("rules_primary", "")

    result = {
        "type": "unknown", "city": None,
        "threshold_mm": 0.0, "threshold_f": None,
        "threshold_c": None, "threshold_inches": None,
    }

    if "rain" in title or "rain" in ticker.lower() or "precip" in rules.lower():
        result["type"] = "rain"
    elif "snow" in title or "snow" in ticker.lower():
        result["type"] = "snow"
    elif "high" in title or "max" in title or "high" in ticker.lower():
        result["type"] = "temperature_high"
    elif "low" in title or "min" in title or "low" in ticker.lower():
        result["type"] = "temperature_low"

    title_orig = market.get("title", "").lower()
    for city_key in CITY_COORDS:
        if city_key in title_orig:
            result["city"] = city_key
            break

    if not result["city"]:
        ticker_lower = ticker.lower()
        city_hints = {
            "nyc": "nyc", "hou": "houston", "lax": "los angeles",
            "sfo": "san francisco", "sfom": "san francisco", "sea": "seattle",
            "chi": "chicago", "den": "denver", "dal": "dallas",
            "mia": "miami", "phx": "phoenix", "tlv": "las vegas",
            "atl": "atlanta", "dc": "washington", "bos": "boston",
            "okc": "oklahoma city", "min": "minneapolis", "aus": "austin",
            "satx": "san antonio", "nola": "new orleans", "phil": "philadelphia",
        }
        for hint, city in city_hints.items():
            if hint in ticker_lower:
                result["city"] = city
                break

    temp_match = re.search(r"(\d+)\s*[°º]?\s*f\b", rules.lower() + " " + title_orig)
    if temp_match:
        f = float(temp_match.group(1))
        result["threshold_f"] = f
        result["threshold_c"] = fahrenheit_to_celsius(f)

    temp_c_match = re.search(r"(\d+(?:\.\d+)?)\s*[°º]?\s*c\b", rules.lower())
    if temp_c_match and result["threshold_c"] is None:
        c = float(temp_c_match.group(1))
        result["threshold_c"] = c
        result["threshold_f"] = celsius_to_fahrenheit(c)

    strike_match = re.search(r"T(\d+)$", ticker)
    if strike_match and result["threshold_f"] is None and result["type"] in ("temperature_high", "temperature_low"):
        f = float(strike_match.group(1))
        result["threshold_f"] = f
        result["threshold_c"] = fahrenheit_to_celsius(f)

    rain_match = re.search(r"strictly greater than\s+([\d.]+)\s*inch", rules.lower())
    if rain_match:
        result["threshold_inches"] = float(rain_match.group(1))
        result["threshold_mm"] = result["threshold_inches"] * 25.4

    return result


# ─── GFS ENSEMBLE FETCHING ──────────────────────────────────────────────────────

_last_openmeteo_request = 0.0
_OPENMETEO_MIN_INTERVAL = 1.5  # seconds between requests (slightly more conservative)

def fetch_ensemble(lat: float, lon: float, target_date: date) -> Optional[dict]:
    """Fetch GFS ensemble from open-meteo with a cache keyed by required horizon."""
    global _last_openmeteo_request, _consecutive_429s

    today = date.today()
    forecast_days = max(7, (target_date - today).days + 3)
    forecast_days = min(forecast_days, 16)
    cache_key = (round(lat, 2), round(lon, 2), forecast_days)

    # Return from in-memory cache if fresh and long enough for this target horizon.
    if cache_key in _ensemble_cache:
        cached_ts, cached_data = _ensemble_cache[cache_key]
        if time.time() - cached_ts < _ENSEMBLE_CACHE_TTL:
            return cached_data

    # Quota circuit breaker — don't fetch if exhausted today
    if _is_quota_exhausted():
        logger.debug(f"Quota exhausted, skipping open-meteo fetch for ({lat},{lon})")
        return None

    # Rate limit: enforce minimum gap between requests
    now = time.time()
    wait = _OPENMETEO_MIN_INTERVAL - (now - _last_openmeteo_request)
    if wait > 0:
        time.sleep(wait)
    _last_openmeteo_request = time.time()

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation,temperature_2m,snowfall",
        "models": "gfs_seamless",
        "forecast_days": forecast_days,
        "timezone": "UTC",
    }

    try:
        resp = requests.get(ENSEMBLE_BASE, params=params, timeout=30)
        if resp.status_code == 429:
            _consecutive_429s += 1
            logger.warning(f"open-meteo HTTP 429 for ({lat},{lon}) — consecutive: {_consecutive_429s}/{_MAX_CONSECUTIVE_429S}")
            if _consecutive_429s >= _MAX_CONSECUTIVE_429S:
                _mark_quota_exhausted()
                return None
            time.sleep(15)
            resp = requests.get(ENSEMBLE_BASE, params=params, timeout=30)
            if resp.status_code == 429:
                _consecutive_429s += 1
                if _consecutive_429s >= _MAX_CONSECUTIVE_429S:
                    _mark_quota_exhausted()
                return None
        if resp.status_code != 200:
            logger.warning(f"open-meteo HTTP {resp.status_code} for ({lat},{lon})")
            return None
        # Successful fetch — reset 429 counter
        _consecutive_429s = 0

        data = resp.json()
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            return None

        precip_members = sorted([k for k in hourly if k.startswith("precipitation")])
        temp_members = sorted([k for k in hourly if k.startswith("temperature")])
        snow_members = sorted([k for k in hourly if k.startswith("snowfall")])

        daily: dict = {}
        for i, time_str in enumerate(times):
            d = time_str[:10]
            if d not in daily:
                daily[d] = {
                    "precip_members": [[] for _ in precip_members],
                    "temp_members": [[] for _ in temp_members],
                    "snow_members": [[] for _ in snow_members],
                }
            for mi, col in enumerate(precip_members):
                v = hourly[col][i]
                if v is not None:
                    daily[d]["precip_members"][mi].append(v)
            for mi, col in enumerate(temp_members):
                v = hourly[col][i]
                if v is not None:
                    daily[d]["temp_members"][mi].append(v)
            for mi, col in enumerate(snow_members):
                v = hourly[col][i]
                if v is not None:
                    daily[d]["snow_members"][mi].append(v)

        result = {}
        for d_str, dd in daily.items():
            daily_precip = [sum(vals) for vals in dd["precip_members"] if vals]
            daily_temp_max = [max(vals) for vals in dd["temp_members"] if vals]
            daily_temp_min = [min(vals) for vals in dd["temp_members"] if vals]
            daily_snow = [sum(vals) for vals in dd["snow_members"] if vals]
            result[d_str] = {
                "precip_total_mm": daily_precip,
                "temp_max_c": daily_temp_max,
                "temp_min_c": daily_temp_min,
                "snow_total_cm": daily_snow,
                "n_members": len(daily_precip) or len(daily_temp_max),
            }

        _ensemble_cache[cache_key] = (time.time(), result)
        _save_disk_cache()
        return result

    except Exception as e:
        logger.warning(f"Ensemble fetch error for ({lat},{lon}): {e}")
        return None


def compute_probability(ensemble_data: dict, target_date: date, market_info: dict) -> Optional[dict]:
    """
    Compute P(event=YES) from ensemble members.
    Returns dict with prob, mean, std, n_members or None.
    """
    d_str = target_date.strftime("%Y-%m-%d")
    day_data = ensemble_data.get(d_str)
    if not day_data:
        for delta in [-1, 1, 2]:
            alt = (target_date + timedelta(days=delta)).strftime("%Y-%m-%d")
            if alt in ensemble_data:
                day_data = ensemble_data[alt]
                break
    if not day_data:
        return None

    mtype = market_info["type"]
    n = day_data["n_members"]
    if n == 0:
        return None

    if mtype == "rain":
        threshold_mm = market_info.get("threshold_mm", 0.0)
        vals = day_data["precip_total_mm"]
        if not vals:
            return None
        yes_count = sum(1 for v in vals if v > threshold_mm)
        mean_val = sum(vals) / len(vals)
        variance = sum((v - mean_val) ** 2 for v in vals) / len(vals)
        std_val = variance ** 0.5
        return {"prob": yes_count / len(vals), "mean": mean_val, "std": std_val, "n": len(vals)}

    elif mtype == "snow":
        threshold_cm = market_info.get("threshold_cm", 0.0)
        vals = day_data["snow_total_cm"]
        if not vals:
            return None
        yes_count = sum(1 for v in vals if v > threshold_cm)
        mean_val = sum(vals) / len(vals)
        variance = sum((v - mean_val) ** 2 for v in vals) / len(vals)
        std_val = variance ** 0.5
        return {"prob": yes_count / len(vals), "mean": mean_val, "std": std_val, "n": len(vals)}

    elif mtype == "temperature_high":
        # Kalshi KXHIGHT markets: "Will the max temp be X°F or higher?" →
        # YES = max temp AT OR ABOVE threshold. Prior version had this
        # inverted (YES = below) — comment AND implementation both wrong.
        # Fixed 2026-04-20 after the inversion sweep that also turned up
        # the copy-trader inversion. Confirmed against internal metar_v3
        # historical_base_rate strategy: NO buys at $0.4-0.6 consistently
        # settle at $0.99 (NO wins), meaning the market resolves "high
        # did NOT reach threshold" → NO territory, i.e. YES = at/above.
        threshold_c = market_info.get("threshold_c")
        if threshold_c is None:
            return None
        vals = [celsius_to_fahrenheit(v) for v in day_data["temp_max_c"]]
        if not vals:
            return None
        threshold_f = market_info.get("threshold_f", threshold_c * 9/5 + 32)
        yes_count = sum(1 for v in vals if v >= threshold_f)  # YES = at/above threshold
        mean_val = sum(vals) / len(vals)
        variance = sum((v - mean_val) ** 2 for v in vals) / len(vals)
        std_val = variance ** 0.5
        return {"prob": yes_count / len(vals), "mean": mean_val, "std": std_val, "n": len(vals)}

    elif mtype == "temperature_low":
        # Kalshi KXLOWT markets: "Will the low temp be X°F or lower?" →
        # YES = min temp AT OR BELOW threshold. Changed from strict `<` to
        # `<=` 2026-04-20 to match the inclusive Kalshi boundary + the
        # v2.3 Gumroad zip semantics.
        threshold_c = market_info.get("threshold_c")
        if threshold_c is None:
            return None
        vals = [celsius_to_fahrenheit(v) for v in day_data["temp_min_c"]]
        if not vals:
            return None
        threshold_f = market_info.get("threshold_f", threshold_c * 9/5 + 32)
        yes_count = sum(1 for v in vals if v <= threshold_f)  # YES = at/below threshold
        mean_val = sum(vals) / len(vals)
        variance = sum((v - mean_val) ** 2 for v in vals) / len(vals)
        std_val = variance ** 0.5
        return {"prob": yes_count / len(vals), "mean": mean_val, "std": std_val, "n": len(vals)}

    return None


# ─── SIGNAL GENERATION (SYNC) ───────────────────────────────────────────────────

def _build_signals_sync() -> List[WeatherTradingSignal]:
    """
    Core signal generation logic (synchronous).
    Fetches Kalshi markets, GFS ensemble, METAR and builds WeatherTradingSignal list.
    """
    global _ensemble_cache, _metar_cache
    # Don't clear caches — use TTL expiry instead to avoid hammering open-meteo

    today = date.today()
    bankroll = settings.INITIAL_BANKROLL

    # Step 1: Fetch markets
    raw_markets = fetch_kalshi_weather_markets()
    if not raw_markets:
        logger.warning("No Kalshi weather markets found")
        return []

    # Step 2: Parse and filter
    enriched = []
    for m in raw_markets:
        target_date = parse_market_date(m)
        if not target_date:
            continue
        days_out = (target_date - today).days
        if days_out < 0 or days_out > 7:
            continue

        market_info = parse_market_type(m)
        if market_info["type"] == "unknown" or not market_info["city"]:
            continue
        if market_info["type"] in ("temperature_high", "temperature_low") and market_info["threshold_c"] is None:
            continue

        coords = CITY_COORDS.get(market_info["city"])
        if not coords:
            continue

        yes_bid = float(m.get("yes_bid_dollars", 0) or 0)
        yes_ask = float(m.get("yes_ask_dollars", 0) or 0)
        last = float(m.get("last_price_dollars", 0) or 0)

        if yes_bid > 0 and yes_ask > 0:
            kalshi_prob = (yes_bid + yes_ask) / 2
        elif last > 0:
            kalshi_prob = last
        else:
            continue

        enriched.append({
            "market": m, "target_date": target_date, "days_out": days_out,
            "market_info": market_info, "coords": coords, "kalshi_prob": kalshi_prob,
        })

    logger.info(f"Weather: {len(enriched)} parseable markets within 7d")

    # Step 3: Compute signals
    signals: List[WeatherTradingSignal] = []

    for item in enriched:
        city = item["market_info"]["city"]
        lat, lon = item["coords"]
        target_date = item["target_date"]
        mtype = item["market_info"]["type"]

        ensemble = fetch_ensemble(lat, lon, target_date)
        if not ensemble:
            continue

        prob_result = compute_probability(ensemble, target_date, item["market_info"])
        if prob_result is None:
            continue

        p_gfs = prob_result["prob"]
        ensemble_mean = prob_result["mean"]
        ensemble_std = prob_result["std"]
        n_members = prob_result["n"]

        # METAR override for same-day HIGH temp markets
        p_final = p_gfs
        signal_source = "GFS-ensemble"
        metar_note = ""

        is_same_day = (target_date == today)
        threshold_f = item["market_info"].get("threshold_f")

        if is_same_day and mtype == "temperature_high" and threshold_f is not None:
            metar_data = get_metar_temps(city, today)
            if metar_data:
                p_metar, confidence, note = metar_high_probability(
                    metar_data["max_temp_f"],
                    metar_data["current_temp_f"],
                    threshold_f,
                    metar_data["local_hour"],
                )
                metar_note = note
                if p_metar is not None and confidence == "high":
                    p_final = p_metar
                    signal_source = "METAR-lock"
                elif p_metar is not None and confidence == "medium":
                    # METAR-early = GFS projection, not a physical lock.
                    # Show as informational context only — do NOT trade on this.
                    signal_source = "METAR-early"
                    p_final = p_metar
                    # Force below edge threshold so it never appears as actionable
                    # (will still appear in dashboard as a "watch" signal)

        kalshi_prob = item["kalshi_prob"]
        yes_edge = p_final - kalshi_prob
        no_edge = (1 - p_final) - (1 - kalshi_prob)
        yes_net_edge = yes_edge - FEE_ESTIMATE
        no_net_edge = no_edge - FEE_ESTIMATE

        # Direction and suggested size use the selected side's edge after fees.
        if yes_net_edge >= no_net_edge:
            direction = "yes"
            edge = yes_edge
            net_edge = yes_net_edge
            entry_price = kalshi_prob
        else:
            direction = "no"
            edge = no_edge
            net_edge = no_net_edge
            entry_price = 1 - kalshi_prob

        # METAR-early signals are never tradeable — GFS projection only, not a physical lock
        if signal_source == "METAR-early":
            suggested_size = 0.0
        elif abs(net_edge) > EDGE_THRESHOLD:
            suggested_size = min(settings.WEATHER_MAX_TRADE_SIZE, bankroll * 0.01)
        else:
            suggested_size = min(settings.WEATHER_MAX_TRADE_SIZE * 0.5, bankroll * 0.005)

        # Kelly fraction estimate
        kelly_fraction = 0.0 if signal_source == "METAR-early" else min(0.1, abs(net_edge) * 0.5)

        # Confidence: based on signal source
        agreement = max(p_final, 1 - p_final)
        if signal_source == "METAR-lock":
            confidence = 0.95
        elif signal_source == "METAR-early":
            confidence = 0.0   # not actionable — shown in dashboard as monitor-only
        else:
            confidence = min(0.85, 0.4 + agreement * 0.5)

        m_raw = item["market"]
        ticker = m_raw.get("ticker", "")
        title = m_raw.get("title", "")

        # Build city name (proper display names)
        CITY_DISPLAY_NAMES = {
            "nyc": "New York City", "chicago": "Chicago", "miami": "Miami",
            "los_angeles": "Los Angeles", "denver": "Denver", "boston": "Boston",
            "seattle": "Seattle", "dallas": "Dallas", "houston": "Houston",
            "phoenix": "Phoenix", "new_orleans": "New Orleans", "atlanta": "Atlanta",
            "philadelphia": "Philadelphia", "austin": "Austin", "las_vegas": "Las Vegas",
            "oklahoma_city": "Oklahoma City", "kansas_city": "Kansas City",
            "minneapolis": "Minneapolis", "detroit": "Detroit", "portland": "Portland",
        }
        city_name = CITY_DISPLAY_NAMES.get(city.lower().replace(' ', '_'), city.replace('_', ' ').title())
        # Normalize metric/direction
        if mtype == "temperature_high":
            metric = "high"
            mkt_direction = "above"
        elif mtype == "temperature_low":
            metric = "low"
            mkt_direction = "above"
        elif mtype == "rain":
            metric = "rain"
            mkt_direction = "above"
        elif mtype == "snow":
            metric = "snow"
            mkt_direction = "above"
        else:
            metric = mtype
            mkt_direction = "above"

        filter_status = "ACTIONABLE" if abs(net_edge) >= settings.WEATHER_MIN_EDGE_THRESHOLD else "FILTERED"
        threshold_str = f"{threshold_f:.0f}°F" if threshold_f else f"{item['market_info'].get('threshold_mm',0):.1f}mm"
        reasoning = (
            f"[{filter_status}] {city_name} {metric} {threshold_str} on {target_date} ({item['days_out']}d) | "
            f"GFS: {p_gfs:.0%} → Final: {p_final:.0%} [{signal_source}] vs Kalshi: {kalshi_prob:.0%} | "
            f"Edge: {edge:+.1%} Net: {net_edge:+.1%} → {direction.upper()} | "
            f"Ensemble: {ensemble_mean:.1f} ±{ensemble_std:.1f} ({n_members} members)"
        )
        if metar_note:
            reasoning += f" | METAR: {metar_note}"

        market_obj = KalshiWeatherMarket(
            market_id=ticker,
            slug=ticker,
            platform="kalshi",
            title=title,
            city_key=city,
            city_name=city_name,
            target_date=target_date,
            threshold_f=threshold_f or 0.0,
            threshold_c=item["market_info"].get("threshold_c", 0.0),
            threshold_mm=item["market_info"].get("threshold_mm", 0.0),
            metric=metric,
            direction=mkt_direction,
            yes_price=kalshi_prob,
            no_price=round(1 - kalshi_prob, 4),
            volume=float(m_raw.get("open_interest_fp", 0) or 0),
        )

        signal = WeatherTradingSignal(
            market=market_obj,
            model_probability=round(p_final, 4),
            market_probability=round(kalshi_prob, 4),
            edge=round(edge, 4),
            net_edge=round(net_edge, 4),
            direction=direction,
            confidence=round(confidence, 3),
            kelly_fraction=round(kelly_fraction, 4),
            suggested_size=round(suggested_size, 2),
            sources=[signal_source, "open_meteo_gfs"],
            reasoning=reasoning,
            ensemble_mean=round(ensemble_mean, 2),
            ensemble_std=round(ensemble_std, 2),
            ensemble_members=n_members,
            gfs_prob=round(p_gfs, 4),
            signal_source=signal_source,
            metar_note=metar_note,
        )
        signals.append(signal)

    # Sort: best net_edge first
    signals.sort(key=lambda s: abs(s.net_edge), reverse=True)

    actionable = [s for s in signals if s.passes_threshold]
    logger.info(f"Weather scan complete: {len(signals)} signals, {len(actionable)} actionable")

    for sig in actionable[:5]:
        logger.info(
            f"  {sig.market.city_name} {sig.market.metric} {sig.market.threshold_f:.0f}°F | "
            f"Net edge: {sig.net_edge:+.1%} → {sig.direction.upper()}"
        )

    return signals


async def scan_for_weather_signals() -> List[WeatherTradingSignal]:
    """
    Async wrapper for signal generation. Runs sync IO in executor to avoid blocking.
    Populates _last_signal_results cache so dashboard can serve instantly.
    """
    global _last_signal_results, _last_signal_timestamp
    import time
    loop = asyncio.get_event_loop()
    try:
        signals = await loop.run_in_executor(None, _build_signals_sync)
    except Exception as e:
        logger.error(f"Weather scan failed: {e}")
        signals = []

    _last_signal_results = signals
    _last_signal_timestamp = time.time()
    _persist_weather_signals(signals)
    return signals


def _persist_weather_signals(signals: List[WeatherTradingSignal]):
    """Save weather signals to DB for calibration tracking."""
    to_save = [s for s in signals if abs(s.edge) > 0]
    if not to_save:
        return

    db = SessionLocal()
    try:
        for signal in to_save:
            existing = db.query(Signal).filter(
                Signal.market_ticker == signal.market.market_id,
                Signal.timestamp >= signal.timestamp.replace(second=0, microsecond=0),
            ).first()
            if existing:
                continue

            db_signal = Signal(
                market_ticker=signal.market.market_id,
                platform="kalshi",
                market_type="weather",
                timestamp=signal.timestamp,
                direction=signal.direction,
                model_probability=signal.model_probability,
                market_price=signal.market_probability,
                edge=signal.edge,
                confidence=signal.confidence,
                kelly_fraction=signal.kelly_fraction,
                suggested_size=signal.suggested_size,
                sources=signal.sources,
                reasoning=signal.reasoning,
                executed=False,
            )
            db.add(db_signal)

        db.commit()
    except Exception as e:
        logger.warning(f"Failed to persist weather signals: {e}")
        db.rollback()
    finally:
        db.close()
