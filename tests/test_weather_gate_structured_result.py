from datetime import date

import pytest

from backend.core.weather_methodology import WeatherGateInput, evaluate_weather_trade_gate


def test_weather_gate_result_exposes_structured_depth_fields_for_api_display():
    gate = evaluate_weather_trade_gate(
        WeatherGateInput(
            settlement_source="nws_cli",
            station_code="KNYC",
            market_probability=0.42,
            best_bid=0.40,
            best_ask=0.44,
            top_ask_size=12.5,
            ensemble_mean=68.5,
            threshold_f=70.0,
            target_date=date(2026, 5, 21),
        )
    )

    assert gate.allowed is False
    assert gate.execution_spread == pytest.approx(0.04)
    assert gate.top_ask_size == 12.5
    assert gate.reasons == ["ensemble mean is only 1.5°F from threshold (<3.0°F buffer)"]
