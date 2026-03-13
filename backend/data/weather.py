"""Weather data fetcher using Open-Meteo Ensemble API and NWS observations."""
import httpx
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import statistics
import time

logger = logging.getLogger("trading_bot")

# City configurations with lat/lon and NWS station identifiers
CITY_CONFIG: Dict[str, dict] = {
    "nyc": {
        "name": "New York City",
        "lat": 40.7128,
        "lon": -74.0060,
        "nws_station": "KNYC",
        "nws_office": "OKX",
        "nws_gridpoint": "OKX/33,37",
    },
    "chicago": {
        "name": "Chicago",
        "lat": 41.8781,
        "lon": -87.6298,
        "nws_station": "KORD",
        "nws_office": "LOT",
        "nws_gridpoint": "LOT/75,72",
    },
    "miami": {
        "name": "Miami",
        "lat": 25.7617,
        "lon": -80.1918,
        "nws_station": "KMIA",
        "nws_office": "MFL",
        "nws_gridpoint": "MFL/75,53",
    },
    "los_angeles": {
        "name": "Los Angeles",
        "lat": 34.0522,
        "lon": -118.2437,
        "nws_station": "KLAX",
        "nws_office": "LOX",
        "nws_gridpoint": "LOX/154,44",
    },
    "denver": {
        "name": "Denver",
        "lat": 39.7392,
        "lon": -104.9903,
        "nws_station": "KDEN",
        "nws_office": "BOU",
        "nws_gridpoint": "BOU/62,60",
    },
    "dallas": {
        "name": "Dallas",
        "lat": 32.7767,
        "lon": -96.7970,
    },
    "paris": {
        "name": "Paris",
        "lat": 48.8566,
        "lon": 2.3522,
    },
    "london": {
        "name": "London",
        "lat": 51.5074,
        "lon": -0.1278,
    },
    "tokyo": {
        "name": "Tokyo",
        "lat": 35.6762,
        "lon": 139.6503,
    },
    "sao_paulo": {
        "name": "Sao Paulo",
        "lat": -23.5505,
        "lon": -46.6333,
    },
    "singapore": {
        "name": "Singapore",
        "lat": 1.3521,
        "lon": 103.8198,
    },
    "wellington": {
        "name": "Wellington",
        "lat": -41.2865,
        "lon": 174.7762,
    },
    "buenos_aires": {
        "name": "Buenos Aires",
        "lat": -34.6037,
        "lon": -58.3816,
    },
    "tel_aviv": {
        "name": "Tel Aviv",
        "lat": 32.0853,
        "lon": 34.7818,
    },
    "sydney": {
        "name": "Sydney",
        "lat": -33.8688,
        "lon": 151.2093,
    },
    "toronto": {
        "name": "Toronto",
        "lat": 43.6532,
        "lon": -79.3832,
    },
    "berlin": {
        "name": "Berlin",
        "lat": 52.5200,
        "lon": 13.4050,
    },
    "dubai": {
        "name": "Dubai",
        "lat": 25.2048,
        "lon": 55.2708,
    },
    "amsterdam": {
        "name": "Amsterdam",
        "lat": 52.3676,
        "lon": 4.9041,
    },
}


@dataclass
class EnsembleForecast:
    """Ensemble weather forecast with per-member data."""
    city_key: str
    city_name: str
    target_date: date
    member_highs: List[float]  # Daily max temps (F) per ensemble member
    member_lows: List[float]   # Daily min temps (F) per ensemble member
    mean_high: float = 0.0
    std_high: float = 0.0
    mean_low: float = 0.0
    std_low: float = 0.0
    num_members: int = 0
    fetched_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if self.member_highs:
            self.mean_high = statistics.mean(self.member_highs)
            self.std_high = statistics.stdev(self.member_highs) if len(self.member_highs) > 1 else 0.0
            self.num_members = len(self.member_highs)
        if self.member_lows:
            self.mean_low = statistics.mean(self.member_lows)
            self.std_low = statistics.stdev(self.member_lows) if len(self.member_lows) > 1 else 0.0

    def probability_high_above(self, threshold_f: float) -> float:
        """Fraction of ensemble members with daily high above threshold."""
        if not self.member_highs:
            return 0.5
        count = sum(1 for h in self.member_highs if h > threshold_f)
        return count / len(self.member_highs)

    def probability_high_below(self, threshold_f: float) -> float:
        """Fraction of ensemble members with daily high below threshold."""
        return 1.0 - self.probability_high_above(threshold_f)

    def probability_low_above(self, threshold_f: float) -> float:
        """Fraction of ensemble members with daily low above threshold."""
        if not self.member_lows:
            return 0.5
        count = sum(1 for l in self.member_lows if l > threshold_f)
        return count / len(self.member_lows)

    def probability_low_below(self, threshold_f: float) -> float:
        """Fraction of ensemble members with daily low below threshold."""
        return 1.0 - self.probability_low_above(threshold_f)

    def probability_high_in_range(self, low_f: float, high_f: float) -> float:
        """Fraction of ensemble members with daily high between low_f and high_f (inclusive)."""
        if not self.member_highs:
            return 0.5
        count = sum(1 for h in self.member_highs if low_f <= h <= high_f)
        return count / len(self.member_highs)

    def probability_low_in_range(self, low_f: float, high_f: float) -> float:
        """Fraction of ensemble members with daily low between low_f and high_f (inclusive)."""
        if not self.member_lows:
            return 0.5
        count = sum(1 for l in self.member_lows if low_f <= l <= high_f)
        return count / len(self.member_lows)

    @property
    def ensemble_agreement(self) -> float:
        """How one-sided the ensemble is (0.5 = split, 1.0 = unanimous)."""
        if not self.member_highs:
            return 0.5
        median = statistics.median(self.member_highs)
        above = sum(1 for h in self.member_highs if h > median)
        frac = above / len(self.member_highs)
        return max(frac, 1 - frac)


# Simple cache: (city_key, target_date_str) -> (timestamp, EnsembleForecast)
_forecast_cache: Dict[str, tuple] = {}
_CACHE_TTL = 900  # 15 minutes


def _celsius_to_fahrenheit(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


async def fetch_ensemble_forecast(city_key: str, target_date: Optional[date] = None) -> Optional[EnsembleForecast]:
    """
    Fetch ensemble forecast from Open-Meteo Ensemble API (free, 31-member GFS).
    Returns per-member daily max/min temperatures in Fahrenheit.
    """
    if city_key not in CITY_CONFIG:
        logger.warning(f"Unknown city key: {city_key}")
        return None

    if target_date is None:
        target_date = date.today()

    cache_key = f"{city_key}_{target_date.isoformat()}"
    now = time.time()
    if cache_key in _forecast_cache:
        cached_time, cached_forecast = _forecast_cache[cache_key]
        if now - cached_time < _CACHE_TTL:
            return cached_forecast

    city = CITY_CONFIG[city_key]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Open-Meteo Ensemble API — GFS ensemble with 31 members
            params = {
                "latitude": city["lat"],
                "longitude": city["lon"],
                "daily": "temperature_2m_max,temperature_2m_min",
                "temperature_unit": "fahrenheit",
                "start_date": target_date.isoformat(),
                "end_date": target_date.isoformat(),
                "models": "gfs_seamless",
            }

            response = await client.get(
                "https://ensemble-api.open-meteo.com/v1/ensemble",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            daily = data.get("daily", {})

            # Open-Meteo returns each ensemble member as a separate key:
            #   temperature_2m_max (control), temperature_2m_max_member01, ..., _member30
            # Collect all member values for highs and lows
            member_highs = []
            member_lows = []

            for key, values in daily.items():
                if not isinstance(values, list) or not values:
                    continue
                val = values[0]
                if val is None:
                    continue
                if "temperature_2m_max" in key:
                    member_highs.append(float(val))
                elif "temperature_2m_min" in key:
                    member_lows.append(float(val))

            if not member_highs:
                logger.warning(f"No ensemble data for {city_key} on {target_date}")
                return None

            forecast = EnsembleForecast(
                city_key=city_key,
                city_name=city["name"],
                target_date=target_date,
                member_highs=member_highs,
                member_lows=member_lows,
            )

            _forecast_cache[cache_key] = (now, forecast)
            logger.info(f"Ensemble forecast for {city['name']} on {target_date}: "
                        f"High {forecast.mean_high:.1f}F +/- {forecast.std_high:.1f}F "
                        f"({forecast.num_members} members)")

            return forecast

    except Exception as e:
        logger.warning(f"Failed to fetch ensemble forecast for {city_key}: {e}")
        return None


async def fetch_nws_observed_temperature(city_key: str, target_date: Optional[date] = None) -> Optional[Dict[str, float]]:
    """
    Fetch observed temperature from NWS API for settlement.
    Returns dict with 'high' and 'low' in Fahrenheit, or None if not available.
    """
    if city_key not in CITY_CONFIG:
        return None

    city = CITY_CONFIG[city_key]
    if target_date is None:
        target_date = date.today()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # NWS observations endpoint
            station = city["nws_station"]
            url = f"https://api.weather.gov/stations/{station}/observations"
            headers = {"User-Agent": "(trading-bot, contact@example.com)"}

            # Get observations for the target date
            start = datetime.combine(target_date, datetime.min.time()).isoformat() + "Z"
            end = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).isoformat() + "Z"

            response = await client.get(url, params={"start": start, "end": end}, headers=headers)
            response.raise_for_status()
            data = response.json()

            features = data.get("features", [])
            if not features:
                return None

            temps = []
            for obs in features:
                props = obs.get("properties", {})
                temp_c = props.get("temperature", {}).get("value")
                if temp_c is not None:
                    temps.append(_celsius_to_fahrenheit(temp_c))

            if not temps:
                return None

            return {
                "high": max(temps),
                "low": min(temps),
            }

    except Exception as e:
        logger.warning(f"Failed to fetch NWS observations for {city_key}: {e}")
        return None
