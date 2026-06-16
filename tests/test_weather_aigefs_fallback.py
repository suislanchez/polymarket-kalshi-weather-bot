import asyncio
from datetime import date

from backend.core import weather_signals
from backend.data.weather import EnsembleForecast
from backend.data.weather_markets import WeatherMarket


class _Gate:
    def __init__(self):
        self.allowed = True
        self.reasons = []
        self.execution_spread = 0.02
        self.top_ask_size = 500.0


def _make_market() -> WeatherMarket:
    return WeatherMarket(
        slug="wx-test",
        market_id="wx-test-1",
        platform="polymarket",
        title="Test Weather Market",
        city_key="nyc",
        city_name="New York City",
        target_date=date.today(),
        threshold_f=75.0,
        metric="high",
        direction="above",
        yes_price=0.55,
        no_price=0.45,
        volume=5000.0,
        best_bid=0.54,
        best_ask=0.56,
        top_ask_size=500.0,
        yes_last_price=0.55,
    )


def test_aigefs_fallback_tag_when_unavailable(monkeypatch):
    base = EnsembleForecast(
        city_key="nyc",
        city_name="New York City",
        target_date=date.today(),
        member_highs=[80.0] * 20 + [70.0] * 10,
        member_lows=[60.0] * 30,
    )

    async def _base(*_args, **_kwargs):
        return base

    monkeypatch.setattr(weather_signals, "fetch_ensemble_forecast", _base)

    async def _none(*_args, **_kwargs):
        return None

    monkeypatch.setattr(weather_signals, "fetch_aigefs_forecast", _none)
    monkeypatch.setattr(weather_signals, "evaluate_weather_trade_gate", lambda *_args, **_kwargs: _Gate())

    monkeypatch.setattr(weather_signals.settings, "WEATHER_USE_AIGEFS", True)
    monkeypatch.setattr(weather_signals.settings, "WEATHER_COMPOSITE_MIN_SCORE", 0.0)

    signal = asyncio.run(weather_signals.generate_weather_signal(_make_market()))
    assert signal is not None
    assert "aigefs_fallback_open_meteo" in signal.sources


def test_aigefs_blends_probability_when_available(monkeypatch):
    base = EnsembleForecast(
        city_key="nyc",
        city_name="New York City",
        target_date=date.today(),
        member_highs=[80.0] * 20 + [70.0] * 10,
        member_lows=[60.0] * 30,
    )
    # Much more bullish alternative provider
    alt = EnsembleForecast(
        city_key="nyc",
        city_name="New York City",
        target_date=date.today(),
        member_highs=[82.0] * 30,
        member_lows=[62.0] * 30,
    )

    async def _base(*_args, **_kwargs):
        return base

    async def _alt(*_args, **_kwargs):
        return alt

    monkeypatch.setattr(weather_signals, "fetch_ensemble_forecast", _base)
    monkeypatch.setattr(weather_signals, "fetch_aigefs_forecast", _alt)
    monkeypatch.setattr(weather_signals, "evaluate_weather_trade_gate", lambda *_args, **_kwargs: _Gate())

    monkeypatch.setattr(weather_signals.settings, "WEATHER_USE_AIGEFS", True)
    monkeypatch.setattr(weather_signals.settings, "WEATHER_AIGEFS_WEIGHT", 0.5)
    monkeypatch.setattr(weather_signals.settings, "WEATHER_COMPOSITE_MIN_SCORE", 0.0)
    # This test isolates the raw AIGEFS blend math. The calibration layer is a
    # deliberate, separately-tested transform (test_weather_calibration.py) that
    # would otherwise shrink this overconfident blended estimate.
    monkeypatch.setattr(weather_signals.settings, "WEATHER_CALIBRATION_ENABLED", False)

    signal = asyncio.run(weather_signals.generate_weather_signal(_make_market()))
    assert signal is not None
    assert any(s.startswith("aigefs_ensemble_") for s in signal.sources)
    # base prob = 20/30 = 0.666..., alt prob = 1.0, blended around 0.833
    assert signal.model_probability > 0.80
