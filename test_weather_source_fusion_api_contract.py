from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.api import main as api_main
from backend.api.main import app
from backend.core.weather_source_benchmark import SourceObservation
from backend.core.weather_signals import KalshiWeatherMarket, WeatherTradingSignal


def _obs(source, temp_f):
    return SourceObservation(
        source=source,
        station_id="KJFK",
        observed_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc),
        temp_f=temp_f,
        source_url=f"https://example.com/{source}",
        raw_hash=f"{source}-{temp_f}",
    )


def test_weather_signal_api_surfaces_source_fusion_conflicts(monkeypatch):
    signal = WeatherTradingSignal(
        market=KalshiWeatherMarket(
            market_id="KXHIGHTNY-26JUN03-T85",
            slug="KXHIGHTNY-26JUN03-T85",
            city_key="nyc",
            city_name="New York City",
            target_date=datetime(2026, 6, 3, tzinfo=timezone.utc).date(),
            threshold_f=85.0,
            metric="high",
        ),
        model_probability=0.90,
        market_probability=0.55,
        edge=0.28,
        net_edge=0.21,
        direction="yes",
        confidence=0.8,
        suggested_size=50.0,
        reasoning="watch source crossed but METAR authority below",
    )
    signal.source_observations = [
        _obs("nws_latest_observation", 86.0),
        _obs("aviationweather_metar", 84.0),
    ]
    signal.source_fusion_policy = {
        "aviationweather_metar": {"role": "lock_authority"},
        "nws_latest_observation": {"role": "watch_only"},
    }

    monkeypatch.setattr(api_main.settings, "WEATHER_ENABLED", True)
    monkeypatch.setattr("backend.core.weather_signals.get_cached_signals", lambda: [signal])
    monkeypatch.setattr("backend.core.weather_signals.get_signal_cache_age_seconds", lambda: 1.0)

    response = TestClient(app).get("/api/weather/signals")

    assert response.status_code == 200
    body = response.json()[0]
    assert body["fusion_lock_state"] == "below"
    assert body["fusion_trade_allowed"] is False
    assert body["fusion_conflicts"] == ["watch_source_crossed_but_authority_below:nws_latest_observation"]
    assert body["fusion_authority_source"] == "aviationweather_metar"
    assert body["fusion_watch_sources"] == ["nws_latest_observation"]
