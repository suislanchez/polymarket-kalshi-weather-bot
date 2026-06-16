"""Integration: calibration confidence gate is wired into signal generation.

Acceptance criterion from the handoff: a unanimous ensemble sitting just above a
threshold must NOT produce an actionable signal on the strength of its clipped
95% probability alone — even if every other gate (source, spread, depth, buffer)
were to pass.
"""
import asyncio
from datetime import date

from backend.core import weather_signals
from backend.data.weather import EnsembleForecast
from backend.data.weather_markets import WeatherMarket


class _AllowGate:
    """A gate that always allows, so calibration is the only possible blocker."""

    def __init__(self):
        self.allowed = True
        self.reasons = []
        self.execution_spread = 0.02
        self.top_ask_size = 500.0


def _near_threshold_market() -> WeatherMarket:
    return WeatherMarket(
        slug="wx-cal-test",
        market_id="wx-cal-test-1",
        platform="polymarket",
        title="High temp above 75F",
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
        settlement_source="NWS_CLI",
        settlement_station="KNYC",
    )


def test_unanimous_near_threshold_signal_is_blocked_by_calibration(monkeypatch):
    # 31 members all at 75.5F: raw member-count says 100% above 75F (clipped 95%),
    # but the mean is only 0.5F above the line.
    forecast = EnsembleForecast(
        city_key="nyc",
        city_name="New York City",
        target_date=date.today(),
        member_highs=[75.5] * 31,
        member_lows=[60.0] * 31,
    )

    async def _forecast(*_args, **_kwargs):
        return forecast

    monkeypatch.setattr(weather_signals, "fetch_ensemble_forecast", _forecast)
    monkeypatch.setattr(weather_signals, "evaluate_weather_trade_gate", lambda *_a, **_k: _AllowGate())
    monkeypatch.setattr(weather_signals.settings, "WEATHER_COMPOSITE_MIN_SCORE", 0.0)
    monkeypatch.setattr(weather_signals.settings, "WEATHER_CALIBRATION_ENABLED", True)

    signal = asyncio.run(weather_signals.generate_weather_signal(_near_threshold_market()))

    assert signal is not None
    # Calibration shrank the clipped 95% well down.
    assert signal.model_probability < 0.80
    # And flagged it non-actionable via a calibration reason.
    assert any("calibration not confident" in r for r in signal.no_trade_reasons)
    assert signal.edge == 0.0
    assert signal.suggested_size == 0.0
    assert signal.passes_threshold is False
    assert any(s.startswith("calibration:") for s in signal.sources)
