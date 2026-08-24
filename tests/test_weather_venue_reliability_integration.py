"""Integration: per-venue reliability is fed into weather probability calibration."""
import asyncio
from datetime import date

from backend.core import weather_signals
from backend.data.weather import EnsembleForecast
from backend.data.weather_markets import WeatherMarket


class _AllowGate:
    def __init__(self):
        self.allowed = True
        self.reasons = []
        self.execution_spread = 0.02
        self.top_ask_size = 500.0


def _market(platform: str) -> WeatherMarket:
    return WeatherMarket(
        slug=f"{platform}-wx-cal-test",
        market_id=f"{platform}-wx-cal-test-1",
        platform=platform,
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


def _decisive_forecast() -> EnsembleForecast:
    # Enough threshold separation that calibration is confident; venue reliability
    # should be the thing that changes probability/edge.
    return EnsembleForecast(
        city_key="nyc",
        city_name="New York City",
        target_date=date.today(),
        member_highs=[83.0] * 31,
        member_lows=[60.0] * 31,
    )


def test_generate_weather_signal_uses_platform_reliability_to_shrink_edge(monkeypatch):
    monkeypatch.setattr(weather_signals, "evaluate_weather_trade_gate", lambda *_a, **_k: _AllowGate())
    monkeypatch.setattr(weather_signals.settings, "WEATHER_COMPOSITE_MIN_SCORE", 0.0)
    monkeypatch.setattr(weather_signals.settings, "WEATHER_CALIBRATION_ENABLED", True)

    forecast = _decisive_forecast()
    polymarket = asyncio.run(
        weather_signals.generate_weather_signal(
            _market("polymarket"), forecast=forecast, venue_reliability=1.0
        )
    )
    kalshi = asyncio.run(
        weather_signals.generate_weather_signal(
            _market("kalshi"), forecast=forecast, venue_reliability=0.4
        )
    )

    assert polymarket is not None
    assert kalshi is not None
    assert polymarket.model_probability > kalshi.model_probability
    assert polymarket.edge > kalshi.edge
    assert any("venue_reliability=1.00" in source for source in polymarket.sources)
    assert any("venue_reliability=0.40" in source for source in kalshi.sources)
