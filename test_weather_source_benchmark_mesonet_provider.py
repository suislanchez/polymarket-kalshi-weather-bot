from datetime import datetime, timezone

from backend.core import weather_source_benchmark as bench


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "generated_at": "2026-06-03T15:52:00Z",
            "id": "JFK",
            "network": "NY_ASOS",
            "last_ob": {
                "utc_valid": "2026-06-03T15:51:00Z",
                "airtemp[F]": 68.0,
                "dewpointtemp[F]": 42.0,
                "raw": "KJFK 031551Z AUTO 36008KT 10SM SCT250 20/06 A3018",
            },
        }

    def raise_for_status(self):
        return None


def test_iem_mesonet_current_provider_maps_icao_station_to_state_network_and_payload(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(bench.requests, "get", fake_get)
    monkeypatch.setattr(bench, "_utcnow", lambda: datetime(2026, 6, 3, 15, 52, 30, tzinfo=timezone.utc))

    observation = bench.fetch_iem_mesonet_current("KJFK", None, None)

    assert observation is not None
    assert observation.source == "iem_mesonet_current"
    assert observation.station_id == "KJFK"
    assert observation.observed_at == datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    assert observation.fetched_at == datetime(2026, 6, 3, 15, 52, 30, tzinfo=timezone.utc)
    assert observation.temp_f == 68.0
    assert observation.qc == "network_NY_ASOS"
    assert "station=JFK" in observation.source_url
    assert "network=NY_ASOS" in observation.source_url
    assert calls[0][0] == "https://mesonet.agron.iastate.edu/json/current.py"
    assert calls[0][1]["params"] == {"station": "JFK", "network": "NY_ASOS"}
    assert observation.raw_hash


def test_iem_mesonet_current_provider_requires_known_station_network():
    assert bench.fetch_iem_mesonet_current("KZZZ", None, None) is None


def test_default_benchmark_providers_include_iem_mesonet_comparator():
    provider_names = [provider.__name__ for provider in bench.default_benchmark_providers()]

    assert provider_names == [
        "fetch_aviationweather_metar",
        "fetch_nws_latest_observation",
        "fetch_iem_mesonet_current",
        "fetch_open_meteo_current",
    ]
