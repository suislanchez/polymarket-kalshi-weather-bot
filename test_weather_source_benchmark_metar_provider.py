from datetime import datetime, timezone

from backend.core import weather_source_benchmark as bench
from backend.core.weather_signals import WeatherObservation


def test_aviationweather_metar_provider_converts_authority_observation(monkeypatch):
    observed = datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    fetched = datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc)
    weather_observation = WeatherObservation(
        source="aviationweather_metar",
        station_id="KJFK",
        observed_at=observed,
        fetched_at=fetched,
        temp_f=68.0,
        raw={"rawOb": "KJFK 031551Z AUTO"},
        raw_hash="metar-hash",
        source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
        qc="V",
    )

    monkeypatch.setattr(
        "backend.core.weather_signals.fetch_latest_metar_observation",
        lambda station_id: weather_observation,
    )

    observation = bench.fetch_aviationweather_metar("KJFK", None, None)

    assert observation is not None
    assert observation.source == "aviationweather_metar"
    assert observation.station_id == "KJFK"
    assert observation.observed_at == observed
    assert observation.fetched_at == fetched
    assert observation.temp_f == 68.0
    assert observation.raw_hash == "metar-hash"
    assert observation.qc == "V"


def test_default_benchmark_providers_include_authority_and_free_comparators():
    provider_names = [provider.__name__ for provider in bench.default_benchmark_providers()]

    assert provider_names == [
        "fetch_aviationweather_metar",
        "fetch_nws_latest_observation",
        "fetch_iem_mesonet_current",
        "fetch_open_meteo_current",
    ]
