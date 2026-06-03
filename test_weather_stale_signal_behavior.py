from datetime import date

from backend.core import weather_signals as ws


def test_stale_metar_data_does_not_enter_lock_probability_path(monkeypatch):
    today = date(2026, 6, 3)
    raw_market = {
        "ticker": "KXHIGHTNY-26JUN03-T85",
        "title": "NYC high temperature 85 F",
        "rules_primary": "Will the high temperature in New York be 85 F or above on June 3, 2026?",
        "yes_bid_dollars": 0.40,
        "yes_ask_dollars": 0.42,
        "last_price_dollars": 0.41,
        "open_interest_fp": 100,
    }

    monkeypatch.setattr(ws, "date", type("FakeDate", (), {"today": staticmethod(lambda: today)}))
    monkeypatch.setattr(ws, "fetch_kalshi_weather_markets", lambda: [raw_market])
    monkeypatch.setattr(ws, "fetch_ensemble", lambda *_args: {"2026-06-03": {"temp_max_c": [30.0], "temp_min_c": [20.0], "precip_total_mm": [0.0], "snow_total_cm": [0.0], "n_members": 1}})
    monkeypatch.setattr(ws, "get_metar_temps", lambda *_args: {
        "icao": "KJFK",
        "status": "stale",
        "stale_reason": "aviationweather_metar.stale_observation_age_3600s_gt_300s",
        "current_temp_f": None,
        "max_temp_f": None,
        "local_hour": None,
    })

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("stale METAR data must not be passed into lock probability")

    monkeypatch.setattr(ws, "metar_high_probability", fail_if_called)

    signals = ws._build_signals_sync()

    assert len(signals) == 1
    assert signals[0].signal_source == "GFS-ensemble"
    assert "stale_observation_age_3600s_gt_300s" in signals[0].metar_note
