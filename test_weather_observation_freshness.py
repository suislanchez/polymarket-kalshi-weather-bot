from datetime import datetime, timezone

from backend.core import weather_signals as ws


def test_fetch_latest_metar_observation_preserves_provenance_and_hash(monkeypatch):
    ws._metar_cache.clear()

    class FakeResponse:
        status_code = 200

        def json(self):
            return [
                {
                    "icaoId": "KJFK",
                    "temp": 20.0,
                    "obsTime": "2026-06-03T15:51:00Z",
                    "receiptTime": "2026-06-03T15:53:04Z",
                    "rawOb": "KJFK 031551Z 18008KT 10SM CLR 20/10 A3001",
                }
            ]

    monkeypatch.setattr(ws.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(ws, "_utcnow", lambda: datetime(2026, 6, 3, 15, 53, 10, tzinfo=timezone.utc))
    monkeypatch.setattr(ws.time, "time", lambda: 1000.0)

    observation = ws.fetch_latest_metar_observation("KJFK")

    assert observation is not None
    assert observation.source == "aviationweather_metar"
    assert observation.station_id == "KJFK"
    assert observation.temp_f == 68.0
    assert observation.observed_at == datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    assert observation.fetched_at == datetime(2026, 6, 3, 15, 53, 10, tzinfo=timezone.utc)
    assert observation.source_url.startswith("https://aviationweather.gov/api/data/metar")
    assert observation.raw_hash
    assert observation.freshness_seconds == 130.0
    assert observation.is_fresh(max_age_seconds=300)


def test_stale_metar_observation_is_not_used_as_fresh_lock_input(monkeypatch):
    stale_observation = ws.WeatherObservation(
        source="aviationweather_metar",
        station_id="KJFK",
        observed_at=datetime(2026, 6, 3, 14, 0, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 0, tzinfo=timezone.utc),
        temp_f=86.0,
        raw={"temp": 30.0},
        raw_hash="abc123",
        source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
    )

    monkeypatch.setattr(ws, "fetch_latest_metar_observation", lambda _icao: stale_observation)

    result = ws.get_metar_temps("NYC", datetime(2026, 6, 3, tzinfo=timezone.utc).date())

    assert result is not None
    assert result["status"] == "stale"
    assert result["stale_reason"] == "aviationweather_metar.stale_observation_age_3600s_gt_300s"
    assert result["current_temp_f"] is None
    assert result["max_temp_f"] is None
