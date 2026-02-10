"""Weather data fetchers - NWS, Open-Meteo Ensemble, ECMWF."""
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import asyncio
from dataclasses import dataclass

from backend.config import settings


@dataclass
class WeatherPrediction:
    """Structured weather prediction with probability."""
    city: str
    date: datetime
    high_temp: float  # Deterministic best estimate
    low_temp: float
    ensemble_highs: List[float]  # All ensemble member predictions
    ensemble_lows: List[float]
    source: str

    def prob_above(self, threshold: float, use_high: bool = True) -> float:
        """Calculate probability temperature exceeds threshold."""
        temps = self.ensemble_highs if use_high else self.ensemble_lows
        if not temps:
            # Fallback to simple estimate if no ensemble data
            point = self.high_temp if use_high else self.low_temp
            # Assume ~3°F standard deviation for NWS forecasts
            std_dev = 3.0
            from scipy import stats
            return 1 - stats.norm.cdf(threshold, loc=point, scale=std_dev)

        above = sum(1 for t in temps if t > threshold)
        return above / len(temps)

    def prob_below(self, threshold: float, use_high: bool = True) -> float:
        """Calculate probability temperature is below threshold."""
        return 1 - self.prob_above(threshold, use_high)

    def confidence(self) -> float:
        """Return confidence score based on ensemble agreement."""
        if not self.ensemble_highs:
            return 0.5  # Low confidence without ensemble

        import numpy as np
        std = np.std(self.ensemble_highs)
        # Lower std = higher confidence, normalize to 0-1
        # Typical std ranges from 1-10°F
        confidence = max(0, min(1, 1 - (std / 10)))
        return confidence


async def fetch_nws_forecast(city: str) -> Optional[WeatherPrediction]:
    """
    Fetch NWS forecast for a city.
    Returns deterministic point forecast (no ensemble).
    """
    if city.lower() not in settings.NWS_GRID_POINTS:
        return None

    office, grid_x, grid_y = settings.NWS_GRID_POINTS[city.lower()]
    url = f"https://api.weather.gov/gridpoints/{office}/{grid_x},{grid_y}/forecast"

    headers = {
        "User-Agent": "(TradingBot, contact@example.com)",
        "Accept": "application/geo+json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            periods = data.get("properties", {}).get("periods", [])
            if not periods:
                return None

            # Find today's high and low
            today = datetime.now().date()
            high_temp = None
            low_temp = None

            for period in periods[:4]:  # Check first 4 periods
                temp = period.get("temperature")
                is_day = period.get("isDaytime", True)

                if is_day and high_temp is None:
                    high_temp = temp
                elif not is_day and low_temp is None:
                    low_temp = temp

            if high_temp is None:
                high_temp = periods[0].get("temperature", 50)
            if low_temp is None:
                low_temp = high_temp - 15  # Rough estimate

            return WeatherPrediction(
                city=city,
                date=datetime.now(),
                high_temp=float(high_temp),
                low_temp=float(low_temp),
                ensemble_highs=[],  # NWS doesn't provide ensemble
                ensemble_lows=[],
                source="nws"
            )

        except Exception as e:
            print(f"NWS fetch error for {city}: {e}")
            return None


async def fetch_openmeteo_ensemble(
    lat: float,
    lon: float,
    city: str
) -> Optional[WeatherPrediction]:
    """
    Fetch Open-Meteo ensemble forecast.
    Returns all ensemble members for probability calculation.
    """
    # Use GFS ensemble - 31 members, free, reliable
    url = "https://ensemble-api.open-meteo.com/v1/ensemble"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "models": "gfs_seamless",
        "forecast_days": 3
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            data = response.json()

            hourly = data.get("hourly", {})
            times = hourly.get("time", [])

            # Find all temperature columns (one per ensemble member)
            temp_keys = [k for k in hourly.keys() if k.startswith("temperature_2m")]

            if not temp_keys or not times:
                return None

            # Get today's date range
            today = datetime.now().date()
            tomorrow = today + timedelta(days=1)

            # Find indices for today (daytime hours: 8 AM - 8 PM local)
            today_indices = []
            for i, t in enumerate(times):
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                if dt.date() == today and 8 <= dt.hour <= 20:
                    today_indices.append(i)

            if not today_indices:
                # Use first available day
                for i, t in enumerate(times):
                    dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                    if 8 <= dt.hour <= 20:
                        today_indices.append(i)
                        if len(today_indices) >= 12:
                            break

            # Extract max temp from each ensemble member
            ensemble_highs = []
            ensemble_lows = []

            for key in temp_keys:
                temps = hourly.get(key, [])
                if temps and today_indices:
                    member_temps = [temps[i] for i in today_indices if i < len(temps) and temps[i] is not None]
                    if member_temps:
                        ensemble_highs.append(max(member_temps))
                        ensemble_lows.append(min(member_temps))

            if not ensemble_highs:
                return None

            # Convert from Celsius to Fahrenheit
            ensemble_highs_f = [t * 9/5 + 32 for t in ensemble_highs]
            ensemble_lows_f = [t * 9/5 + 32 for t in ensemble_lows]

            return WeatherPrediction(
                city=city,
                date=datetime.now(),
                high_temp=sum(ensemble_highs_f) / len(ensemble_highs_f),
                low_temp=sum(ensemble_lows_f) / len(ensemble_lows_f),
                ensemble_highs=ensemble_highs_f,
                ensemble_lows=ensemble_lows_f,
                source="openmeteo_gfs_ensemble"
            )

        except Exception as e:
            print(f"Open-Meteo fetch error for {city}: {e}")
            return None


async def fetch_weather_prediction(city: str) -> Optional[WeatherPrediction]:
    """
    Fetch weather prediction combining multiple sources.
    Priority: Open-Meteo ensemble (probability) > NWS (settlement reference)
    """
    coords = settings.CITY_COORDS.get(city.lower())

    # Try Open-Meteo ensemble first (gives us probabilities)
    if coords:
        lat, lon = coords
        ensemble_pred = await fetch_openmeteo_ensemble(lat, lon, city)
        if ensemble_pred and ensemble_pred.ensemble_highs:
            return ensemble_pred

    # Fallback to NWS (deterministic, but matches Kalshi settlement)
    nws_pred = await fetch_nws_forecast(city)
    return nws_pred


async def fetch_all_cities() -> Dict[str, WeatherPrediction]:
    """Fetch weather predictions for all supported cities."""
    cities = list(settings.CITY_COORDS.keys())

    tasks = [fetch_weather_prediction(city) for city in cities]
    results = await asyncio.gather(*tasks)

    return {
        city: pred
        for city, pred in zip(cities, results)
        if pred is not None
    }


# Quick test
if __name__ == "__main__":
    async def test():
        pred = await fetch_weather_prediction("nyc")
        if pred:
            print(f"NYC High: {pred.high_temp:.1f}°F")
            print(f"Ensemble members: {len(pred.ensemble_highs)}")
            print(f"Prob above 40°F: {pred.prob_above(40):.1%}")
            print(f"Prob above 50°F: {pred.prob_above(50):.1%}")
            print(f"Confidence: {pred.confidence():.2f}")

    asyncio.run(test())
