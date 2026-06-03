from datetime import date, datetime, timezone

from backend.core import weather_signals as ws


def test_same_day_signal_attaches_default_source_observations_and_fusion_policy(monkeypatch):
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
    observation = ws.WeatherObservation(
        source="aviationweather_metar",
        station_id="KJFK",
        observed_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc),
        temp_f=86.0,
        raw={"rawOb": "KJFK 031551Z AUTO"},
        raw_hash="metar-hash",
        source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
    )

    monkeypatch.setattr(ws, "date", type("FakeDate", (), {"today": staticmethod(lambda: today)}))
    monkeypatch.setattr(ws, "fetch_kalshi_weather_markets", lambda: [raw_market])
    monkeypatch.setattr(ws, "fetch_ensemble", lambda *_args: {"2026-06-03": {"temp_max_c": [30.0], "temp_min_c": [20.0], "precip_total_mm": [0.0], "snow_total_cm": [0.0], "n_members": 1}})
    monkeypatch.setattr(ws, "get_metar_temps", lambda *_args: {
        "icao": "KJFK",
        "status": "fresh",
        "current_temp_f": 86.0,
        "max_temp_f": 86.0,
        "local_hour": 15,
        "observation": observation,
    })
    monkeypatch.setattr(ws, "metar_high_probability", lambda *_args: (0.99, "high", "locked"))
    monkeypatch.setattr(ws, "load_live_source_fusion_policy", lambda: {
        "aviationweather_metar": {"role": "lock_authority"},
        "nws_latest_observation": {"role": "watch_only"},
    })

    signal = ws._build_signals_sync()[0]

    assert "aviationweather_metar" in [obs.source for obs in signal.source_observations]
    assert signal.source_fusion_policy["aviationweather_metar"]["role"] == "lock_authority"
