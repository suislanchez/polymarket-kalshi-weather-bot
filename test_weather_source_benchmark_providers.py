from datetime import datetime, timezone

from backend.core import weather_source_benchmark as bench


def test_nws_latest_provider_parses_weather_gov_payload(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "properties": {
                    "station": "https://api.weather.gov/stations/KJFK",
                    "timestamp": "2026-06-03T15:50:00+00:00",
                    "temperature": {"value": 20.0, "qualityControl": "V"},
                    "rawMessage": "KJFK NWS latest obs",
                }
            }

        def raise_for_status(self):
            return None

    monkeypatch.setattr(bench.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(bench, "_utcnow", lambda: datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc))

    observation = bench.fetch_nws_latest_observation("KJFK", None, None)

    assert observation is not None
    assert observation.source == "nws_latest_observation"
    assert observation.station_id == "KJFK"
    assert observation.observed_at == datetime(2026, 6, 3, 15, 50, tzinfo=timezone.utc)
    assert observation.fetched_at == datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    assert observation.temp_f == 68.0
    assert observation.qc == "V"
    assert observation.raw_hash
    assert observation.source_url == "https://api.weather.gov/stations/KJFK/observations/latest"


def test_open_meteo_current_provider_parses_current_payload(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "current": {
                    "time": "2026-06-03T15:45",
                    "temperature_2m": 19.5,
                    "interval": 900,
                }
            }

        def raise_for_status(self):
            return None

    monkeypatch.setattr(bench.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(bench, "_utcnow", lambda: datetime(2026, 6, 3, 15, 53, tzinfo=timezone.utc))

    observation = bench.fetch_open_meteo_current("KJFK", 40.6413, -73.7781)

    assert observation is not None
    assert observation.source == "open_meteo_current"
    assert observation.station_id == "KJFK"
    assert observation.observed_at == datetime(2026, 6, 3, 15, 45, tzinfo=timezone.utc)
    assert observation.fetched_at == datetime(2026, 6, 3, 15, 53, tzinfo=timezone.utc)
    assert observation.temp_f == 67.1
    assert observation.qc == "interval_900s"
    assert "latitude=40.6413" in observation.source_url
    assert observation.raw_hash


def test_open_meteo_provider_requires_coordinates():
    assert bench.fetch_open_meteo_current("KJFK", None, None) is None


def test_iem_mesonet_provider_parses_current_asos_payload_and_strips_icao_prefix(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "generated_at": "2026-06-03T15:52:00Z",
                "id": "JFK",
                "network": "NY_ASOS",
                "last_ob": {
                    "utc_valid": "2026-06-03T15:51:00Z",
                    "airtemp[F]": 62.0,
                    "raw": "KJFK 031551Z AUTO",
                },
            }

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(bench.requests, "get", fake_get)
    monkeypatch.setattr(bench, "_utcnow", lambda: datetime(2026, 6, 3, 15, 53, tzinfo=timezone.utc))

    observation = bench.fetch_iem_mesonet_current("KJFK", None, None)

    assert observation is not None
    assert calls[0][0] == "https://mesonet.agron.iastate.edu/json/current.py"
    assert calls[0][1]["params"] == {"station": "JFK", "network": "NY_ASOS"}
    assert observation.source == "iem_mesonet_current"
    assert observation.station_id == "KJFK"
    assert observation.observed_at == datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    assert observation.fetched_at == datetime(2026, 6, 3, 15, 53, tzinfo=timezone.utc)
    assert observation.temp_f == 62.0
    assert observation.qc == "network_NY_ASOS"
    assert "station=JFK" in observation.source_url
    assert "network=NY_ASOS" in observation.source_url
    assert observation.raw_hash


def test_iem_mesonet_provider_skips_unmapped_stations_without_network_call(monkeypatch):
    def fail_get(*_args, **_kwargs):
        raise AssertionError("unexpected network call")

    monkeypatch.setattr(bench.requests, "get", fail_get)

    assert bench.fetch_iem_mesonet_current("CYVR", None, None) is None


def test_default_benchmark_providers_include_mesonet_comparator():
    names = [provider.__name__ for provider in bench.default_benchmark_providers()]

    assert names == [
        "fetch_aviationweather_metar",
        "fetch_nws_latest_observation",
        "fetch_iem_mesonet_current",
        "fetch_open_meteo_current",
    ]
