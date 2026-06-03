from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.api import main as api_main
from backend.api.main import app
from backend.core.weather_signals import KalshiWeatherMarket, WeatherObservation, WeatherTradingSignal


def test_weather_signal_api_exposes_observation_latency_and_source(monkeypatch):
    observed = datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    fetched = datetime(2026, 6, 3, 15, 52, 15, tzinfo=timezone.utc)
    signal = WeatherTradingSignal(
        market=KalshiWeatherMarket(
            market_id="KXHIGHTNY-26JUN03-T85",
            slug="KXHIGHTNY-26JUN03-T85",
            city_key="nyc",
            city_name="New York City",
            target_date=observed.date(),
            threshold_f=85.0,
            metric="high",
        ),
        model_probability=0.99,
        market_probability=0.70,
        edge=0.22,
        net_edge=0.22,
        direction="yes",
        confidence=0.95,
        suggested_size=100.0,
        reasoning="METAR lock",
        ensemble_mean=86.0,
        ensemble_std=1.0,
        ensemble_members=31,
        signal_source="METAR-lock",
        metar_note="locked",
        threshold_state="locked",
        weather_observation=WeatherObservation(
            source="aviationweather_metar",
            station_id="KJFK",
            observed_at=observed,
            fetched_at=fetched,
            temp_f=86.0,
            raw={"temp": 30.0},
            raw_hash="hash123",
            source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
        ),
        signal_at=datetime(2026, 6, 3, 15, 52, 20, tzinfo=timezone.utc),
    )

    monkeypatch.setattr(api_main.settings, "WEATHER_ENABLED", True)
    monkeypatch.setattr("backend.core.weather_signals.get_cached_signals", lambda: [signal])
    monkeypatch.setattr("backend.core.weather_signals.get_signal_cache_age_seconds", lambda: 5.0)

    response = TestClient(app).get("/api/weather/signals")

    assert response.status_code == 200
    body = response.json()[0]
    assert body["signal_source"] == "METAR-lock"
    assert body["metar_note"] == "locked"
    assert body["observation_source"] == "aviationweather_metar"
    assert body["station_id"] == "KJFK"
    assert body["observed_at"] == "2026-06-03T15:51:00+00:00"
    assert body["fetched_at"] == "2026-06-03T15:52:15+00:00"
    assert body["signal_at"] == "2026-06-03T15:52:20+00:00"
    assert body["observation_latency_seconds"] == 75.0
    assert body["signal_latency_seconds"] == 5.0
    assert body["threshold_state"] == "locked"
    assert body["raw_hash"] == "hash123"
    assert body["source_url"].startswith("https://aviationweather.gov/api/data/metar")
