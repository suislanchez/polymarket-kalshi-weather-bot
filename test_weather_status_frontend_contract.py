from pathlib import Path

ROOT = Path(__file__).parent


def test_frontend_weather_status_type_includes_slo_fields():
    types = (ROOT / "frontend/src/types.ts").read_text()

    for field in [
        "export interface WeatherStatus",
        "enabled: boolean",
        "fast_loop_interval_seconds: number",
        "next_fast_scan_in_seconds: number | null",
        "cache_age_seconds: number | null",
        "last_observation_age_seconds: number | null",
        "last_observation?:",
        "last_change?:",
    ]:
        assert field in types


def test_frontend_fetches_and_renders_weather_status_panel():
    api = (ROOT / "frontend/src/api.ts").read_text()
    app = (ROOT / "frontend/src/App.tsx").read_text()

    assert "fetchWeatherStatus" in api
    assert "api.get<WeatherStatus>('/weather/status')" in api
    assert "queryKey: ['weatherStatus']" in app
    assert "fetchWeatherStatus" in app
    assert "Next fast" in app
    assert "Obs age" in app
    assert "Last change" in app
