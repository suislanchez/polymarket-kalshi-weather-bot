from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.api import main as api_main
from backend.api.main import app
from backend.core.weather_source_benchmark import SourceBenchmarkResult, SourceBenchmarkRow


def _row(source, lead=0.0, delta=0.0):
    ts = datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    return SourceBenchmarkRow(
        source=source,
        station_id="KJFK",
        authority_source="aviationweather_metar",
        observed_at=ts,
        fetched_at=ts,
        temp_f=68.0 + delta,
        freshness_seconds=90.0,
        source_lead_seconds_vs_authority=lead,
        temp_delta_f_vs_authority=delta,
        raw_hash=f"{source}-hash",
        source_url=f"https://example.com/{source}",
        quality_flags=[],
    )


def test_source_benchmark_run_endpoint_persists_result_and_returns_policy(tmp_path, monkeypatch):
    history_path = tmp_path / "benchmark_history.jsonl"
    monkeypatch.setattr(api_main.settings, "WEATHER_SOURCE_BENCHMARK_HISTORY_PATH", str(history_path), raising=False)

    def fake_benchmark_observation_sources(**kwargs):
        assert kwargs["station_id"] == "KJFK"
        assert kwargs["lat"] == 40.6413
        assert kwargs["lon"] == -73.7781
        return SourceBenchmarkResult(
            station_id="KJFK",
            rows=[
                _row("aviationweather_metar", lead=0.0, delta=0.0),
                _row("nws_latest_observation", lead=45.0, delta=0.2),
            ],
            failures={},
        )

    monkeypatch.setattr("backend.core.weather_source_benchmark.benchmark_observation_sources", fake_benchmark_observation_sources)
    monkeypatch.setattr("backend.core.weather_source_benchmark.default_benchmark_providers", lambda: [lambda *_args: None])
    monkeypatch.setattr("backend.api.main.datetime", type("FakeDateTime", (), {
        "utcnow": staticmethod(lambda: datetime(2026, 6, 3, 16, 0, tzinfo=timezone.utc))
    }))

    response = TestClient(app).post(
        "/api/weather/source-benchmark/run",
        json={"station_id": "KJFK", "lat": 40.6413, "lon": -73.7781},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["station_id"] == "KJFK"
    assert body["rows"][0]["source"] == "aviationweather_metar"
    assert body["policy"]["aviationweather_metar"]["role"] == "lock_authority"
    assert history_path.exists()
    assert "nws_latest_observation" in history_path.read_text()
