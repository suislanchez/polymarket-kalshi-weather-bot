from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.api import main as api_main
from backend.api.main import app
from backend.core.weather_source_benchmark import SourceBenchmarkResult, SourceBenchmarkRow


def _row(source, station_id, lead=0.0, delta=0.0):
    ts = datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    return SourceBenchmarkRow(
        source=source,
        station_id=station_id,
        authority_source="aviationweather_metar",
        observed_at=ts,
        fetched_at=ts,
        temp_f=68.0 + delta,
        freshness_seconds=90.0,
        source_lead_seconds_vs_authority=lead,
        temp_delta_f_vs_authority=delta,
        raw_hash=f"{source}-{station_id}",
        source_url=f"https://example.com/{source}",
        quality_flags=[],
    )


def test_source_benchmark_batch_endpoint_persists_multiple_station_results(tmp_path, monkeypatch):
    history_path = tmp_path / "benchmark_history.jsonl"
    monkeypatch.setattr(api_main.settings, "WEATHER_SOURCE_BENCHMARK_HISTORY_PATH", str(history_path), raising=False)

    def fake_benchmark_observation_sources(**kwargs):
        station_id = kwargs["station_id"]
        return SourceBenchmarkResult(
            station_id=station_id,
            rows=[_row("aviationweather_metar", station_id), _row("nws_latest_observation", station_id, lead=30.0, delta=0.2)],
            failures={},
        )

    monkeypatch.setattr("backend.core.weather_source_benchmark.benchmark_observation_sources", fake_benchmark_observation_sources)
    monkeypatch.setattr("backend.core.weather_source_benchmark.default_benchmark_providers", lambda: [lambda *_args: None])
    monkeypatch.setattr("backend.api.main.datetime", type("FakeDateTime", (), {
        "utcnow": staticmethod(lambda: datetime(2026, 6, 3, 16, 0, tzinfo=timezone.utc))
    }))

    response = TestClient(app).post(
        "/api/weather/source-benchmark/batch",
        json={
            "targets": [
                {"station_id": "KJFK", "lat": 40.6413, "lon": -73.7781},
                {"station_id": "KORD", "lat": 41.9742, "lon": -87.9073},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [result["station_id"] for result in body["results"]] == ["KJFK", "KORD"]
    assert body["summary"]["nws_latest_observation"]["sample_count"] == 2
    from backend.core.weather_source_benchmark import load_source_benchmark_history
    records = load_source_benchmark_history(history_path)
    assert sum(1 for record in records if record["source"] == "nws_latest_observation") == 2


def test_source_benchmark_batch_endpoint_rejects_unbounded_target_lists(monkeypatch):
    monkeypatch.setattr(api_main.settings, "WEATHER_SOURCE_BENCHMARK_HISTORY_PATH", "unused.jsonl", raising=False)
    response = TestClient(app).post(
        "/api/weather/source-benchmark/batch",
        json={
            "targets": [
                {"station_id": f"K{i:03d}", "lat": 40.0, "lon": -73.0}
                for i in range(api_main.MAX_WEATHER_SOURCE_BENCHMARK_BATCH_TARGETS + 1)
            ]
        },
    )

    assert response.status_code == 422
    assert "targets must contain 1-10 stations" in response.json()["detail"]
