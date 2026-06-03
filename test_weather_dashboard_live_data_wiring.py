from pathlib import Path

ROOT = Path(__file__).parent


def test_overview_weather_components_receive_live_weather_data_not_empty_arrays():
    app = (ROOT / "frontend/src/App.tsx").read_text()

    assert "const weatherSignals = liveData?.weather_signals ?? []" in app
    assert "const weatherForecasts = liveData?.weather_forecasts ?? []" in app
    assert "<EdgeDistribution btcSignals={[]} weatherSignals={weatherSignals}" in app
    assert "<GlobeView forecasts={weatherForecasts} signals={weatherSignals}" in app
    assert "<SignalsTable signals={[]} weatherSignals={weatherSignals}" in app
    assert "weatherSignals={[]}" not in app
    assert "forecasts={[]}" not in app
