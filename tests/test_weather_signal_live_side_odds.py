from datetime import date
import asyncio

from backend.core.weather_signals import generate_weather_signal
from backend.data.weather import EnsembleForecast
from backend.data.weather_markets import WeatherMarket


def test_no_side_signal_uses_live_no_ask_and_no_depth(monkeypatch):
    async def fake_forecast(city_key, target_date):
        return EnsembleForecast(
            city_key=city_key,
            city_name="Chicago",
            target_date=target_date,
            member_highs=[65.0] * 31,
            member_lows=[50.0] * 31,
        )

    monkeypatch.setattr("backend.core.weather_signals.fetch_ensemble_forecast", fake_forecast)

    market = WeatherMarket(
        slug="poly-weather-test",
        market_id="poly-weather-test-market",
        platform="polymarket",
        title="Will the high temperature in Chicago exceed 72°F on June 3, 2026?",
        city_key="chicago",
        city_name="Chicago",
        target_date=date(2026, 6, 3),
        threshold_f=72.0,
        metric="high",
        direction="above",
        yes_price=0.30,
        no_price=0.70,  # stale/derived; should not drive execution
        settlement_source="wunderground",
        settlement_station="KMDW",
        best_bid=0.29,
        best_ask=0.31,
        top_ask_size=200.0,
        no_best_bid=0.10,
        no_best_ask=0.95,
        no_top_ask_size=2.0,
    )

    signal = asyncio.run(generate_weather_signal(market))
    assert signal is not None

    assert signal.direction == "no"
    assert signal.edge == 0.0
    assert signal.suggested_size == 0.0
    assert signal.top_ask_size == 2.0
    assert "entry 95% > 70%" in signal.reasoning
    assert any("top ask size 2.0 below" in reason for reason in signal.no_trade_reasons)
