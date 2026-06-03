from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from pathlib import Path

from backend.core.forecast_convergence import compute_convergence_score
from backend.core import forecast_convergence as fc
from backend.core import weather_signals as ws


def test_single_forecast_run_reports_one_run_available():
    result = compute_convergence_score([(datetime.now(timezone.utc), 72.0)])

    assert result["runs_available"] == 1
    assert result["confidence_multiplier"] == 0.75
    assert "only 1 run" in result["note"]


def test_short_gap_pair_does_not_count_as_full_convergence():
    now = datetime.now(timezone.utc)
    result = compute_convergence_score([
        (now - timedelta(hours=2), 74.0),
        (now, 74.2),
    ])

    assert result["converged"] is None
    assert result["shift_24h"] is None
    assert result["confidence_multiplier"] == 0.75
    assert "no 24h convergence reference" in result["note"]


def test_default_history_path_stays_inside_weather_edge_repo():
    history_path = Path(fc._HISTORY_PATH).resolve()
    repo_root = Path(__file__).resolve().parent

    assert history_path == repo_root / "data" / "forecast_run_history.json"


def test_forecast_history_quarantines_corrupt_json_and_recovers(tmp_path, monkeypatch):
    history_path = tmp_path / "forecast_run_history.json"
    history_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(fc, "_HISTORY_PATH", str(history_path))

    assert fc.load_forecast_series("nyc", "2026-05-24") == []
    assert not history_path.exists()
    assert list(tmp_path.glob("forecast_run_history.json.corrupt-*"))

    fc.record_forecast_run("nyc", "2026-05-24", 74.2)
    assert history_path.exists()
    assert not list(tmp_path.glob(".forecast_run_history.*.tmp"))
    series = fc.load_forecast_series("nyc", "2026-05-24")
    assert len(series) == 1
    assert series[0][1] == 74.2


def test_forecast_history_ignores_malformed_per_key_rows_and_normalizes_city(tmp_path, monkeypatch):
    history_path = tmp_path / "forecast_run_history.json"
    now_ts = datetime.now(timezone.utc).timestamp()
    history_path.write_text(
        '{"NYC:2026-05-24": "bad", "nyc:2026-05-24": [[%s, 74.2], ["bad", 75], [123]], "other": {}}'
        % now_ts,
        encoding="utf-8",
    )
    monkeypatch.setattr(fc, "_HISTORY_PATH", str(history_path))

    series = fc.load_forecast_series(" NYC ", "2026-05-24")

    assert len(series) == 1
    assert series[0][1] == 74.2


def test_weather_signal_size_is_scaled_by_forecast_convergence(monkeypatch):
    target = date.today() + timedelta(days=1)
    market = {
        "ticker": "KXHIGHNY-26MAY24-T70",
        "title": "New York high temperature above 70°F",
        "rules_primary": f"on {target.isoformat()} high above 70 F",
        "yes_bid_dollars": 0.39,
        "yes_ask_dollars": 0.41,
        "last_price_dollars": 0.40,
        "open_interest_fp": 1000,
    }

    monkeypatch.setattr(ws, "fetch_kalshi_weather_markets", lambda: [market])
    monkeypatch.setattr(ws, "parse_market_date", lambda m: target)
    monkeypatch.setattr(
        ws,
        "parse_market_type",
        lambda m: {
            "type": "temperature_high",
            "city": "nyc",
            "threshold_f": 70.0,
            "threshold_c": 21.1,
            "threshold_mm": 0.0,
        },
    )
    monkeypatch.setattr(ws, "fetch_ensemble", lambda lat, lon, target_date: {"ok": True})
    monkeypatch.setattr(
        ws,
        "compute_probability",
        lambda ensemble, target_date, market_info: {
            "prob": 0.80,
            "mean": 74.2,
            "std": 1.0,
            "n": 31,
        },
    )
    monkeypatch.setattr(ws, "get_metar_temps", lambda city, today: None)
    monkeypatch.setattr(ws.settings, "INITIAL_BANKROLL", 10_000.0)
    monkeypatch.setattr(ws.settings, "WEATHER_MAX_TRADE_SIZE", 100.0)
    monkeypatch.setattr(ws.settings, "WEATHER_MIN_EDGE_THRESHOLD", 0.01)
    monkeypatch.setattr(ws.settings, "WEATHER_MAX_ENTRY_PRICE", 0.99)

    recorded = []
    monkeypatch.setattr(
        ws,
        "record_forecast_run",
        lambda city, target_date_str, forecast_high_f: recorded.append(
            (city, target_date_str, forecast_high_f)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        ws,
        "load_forecast_series",
        lambda city, target_date_str: [
            (datetime.now(timezone.utc) - timedelta(hours=24), 72.0),
            (datetime.now(timezone.utc), 74.2),
        ],
        raising=False,
    )
    monkeypatch.setattr(
        ws,
        "compute_convergence_score",
        lambda series: {
            "shift_24h": 2.2,
            "converged": False,
            "confidence_multiplier": 0.5,
            "runs_available": 2,
            "comparison_age_hours": 24.0,
            "newest_value_f": 74.2,
            "reference_value_f": 72.0,
            "note": "24h shift=2.20°F → SHIFTING",
        },
        raising=False,
    )

    signals = ws._build_signals_sync()

    assert len(signals) == 1
    assert signals[0].suggested_size == 50.0
    assert recorded == [("nyc", target.isoformat(), 74.2)]
    assert "forecast_convergence" in signals[0].sources
    assert "Convergence: 24h shift=2.20°F" in signals[0].reasoning


def test_forecast_convergence_failure_scales_size_conservatively(monkeypatch):
    target = date.today() + timedelta(days=1)
    market = {
        "ticker": "KXHIGHNY-26MAY24-T70",
        "title": "New York high temperature above 70°F",
        "rules_primary": f"on {target.isoformat()} high above 70 F",
        "yes_bid_dollars": 0.39,
        "yes_ask_dollars": 0.41,
        "last_price_dollars": 0.40,
        "open_interest_fp": 1000,
    }

    monkeypatch.setattr(ws, "fetch_kalshi_weather_markets", lambda: [market])
    monkeypatch.setattr(ws, "parse_market_date", lambda m: target)
    monkeypatch.setattr(
        ws,
        "parse_market_type",
        lambda m: {
            "type": "temperature_high",
            "city": "nyc",
            "threshold_f": 70.0,
            "threshold_c": 21.1,
            "threshold_mm": 0.0,
        },
    )
    monkeypatch.setattr(ws, "fetch_ensemble", lambda lat, lon, target_date: {"ok": True})
    monkeypatch.setattr(
        ws,
        "compute_probability",
        lambda ensemble, target_date, market_info: {
            "prob": 0.80,
            "mean": 74.2,
            "std": 1.0,
            "n": 31,
        },
    )
    monkeypatch.setattr(ws, "get_metar_temps", lambda city, today: None)
    monkeypatch.setattr(ws.settings, "INITIAL_BANKROLL", 10_000.0)
    monkeypatch.setattr(ws.settings, "WEATHER_MAX_TRADE_SIZE", 100.0)
    monkeypatch.setattr(ws.settings, "WEATHER_MIN_EDGE_THRESHOLD", 0.01)
    monkeypatch.setattr(ws.settings, "WEATHER_MAX_ENTRY_PRICE", 0.99)
    monkeypatch.setattr(ws, "record_forecast_run", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(ws, "load_forecast_series", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(
        ws,
        "compute_convergence_score",
        lambda series: (_ for _ in ()).throw(RuntimeError("history corrupt")),
        raising=False,
    )

    signals = ws._build_signals_sync()

    assert len(signals) == 1
    assert signals[0].suggested_size == 75.0
    assert "forecast_convergence" in signals[0].sources
    assert "Convergence: unavailable" in signals[0].reasoning
    assert "size x0.75" in signals[0].reasoning


def test_forecast_convergence_does_not_scale_rain_markets(monkeypatch):
    target = date.today()
    market = {
        "ticker": "KXRAINNYC-26MAY24",
        "title": "Will it rain in New York?",
        "rules_primary": f"on {target.isoformat()} precipitation above 0.01 inch",
        "yes_bid_dollars": 0.39,
        "yes_ask_dollars": 0.41,
        "last_price_dollars": 0.40,
        "open_interest_fp": 1000,
    }

    monkeypatch.setattr(ws, "fetch_kalshi_weather_markets", lambda: [market])
    monkeypatch.setattr(ws, "parse_market_date", lambda m: target)
    monkeypatch.setattr(
        ws,
        "parse_market_type",
        lambda m: {
            "type": "rain",
            "city": "nyc",
            "threshold_f": None,
            "threshold_c": None,
            "threshold_mm": 0.25,
        },
    )
    monkeypatch.setattr(ws, "fetch_ensemble", lambda lat, lon, target_date: {"ok": True})
    monkeypatch.setattr(
        ws,
        "compute_probability",
        lambda ensemble, target_date, market_info: {
            "prob": 0.80,
            "mean": 0.40,
            "std": 0.10,
            "n": 31,
        },
    )
    monkeypatch.setattr(ws.settings, "INITIAL_BANKROLL", 10_000.0)
    monkeypatch.setattr(ws.settings, "WEATHER_MAX_TRADE_SIZE", 100.0)
    monkeypatch.setattr(ws.settings, "WEATHER_MIN_EDGE_THRESHOLD", 0.01)
    monkeypatch.setattr(ws.settings, "WEATHER_MAX_ENTRY_PRICE", 0.99)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("forecast convergence is high-temperature-only")

    monkeypatch.setattr(ws, "record_forecast_run", fail_if_called, raising=False)
    monkeypatch.setattr(ws, "load_forecast_series", fail_if_called, raising=False)
    monkeypatch.setattr(ws, "compute_convergence_score", fail_if_called, raising=False)

    signals = ws._build_signals_sync()

    assert len(signals) == 1
    assert signals[0].suggested_size == 100.0
    assert "forecast_convergence" not in signals[0].sources


def test_metar_lock_temperature_signal_bypasses_forecast_convergence(monkeypatch):
    target = date.today()
    market = {
        "ticker": "KXHIGHNY-26MAY24-T70",
        "title": "New York high temperature above 70°F",
        "rules_primary": f"on {target.isoformat()} high above 70 F",
        "yes_bid_dollars": 0.39,
        "yes_ask_dollars": 0.41,
        "last_price_dollars": 0.40,
        "open_interest_fp": 1000,
    }
    monkeypatch.setattr(ws, "fetch_kalshi_weather_markets", lambda: [market])
    monkeypatch.setattr(ws, "parse_market_date", lambda m: target)
    monkeypatch.setattr(
        ws,
        "parse_market_type",
        lambda m: {
            "type": "temperature_high",
            "city": "nyc",
            "threshold_f": 70.0,
            "threshold_c": 21.1,
            "threshold_mm": 0.0,
        },
    )
    monkeypatch.setattr(ws, "fetch_ensemble", lambda lat, lon, target_date: {"ok": True})
    monkeypatch.setattr(
        ws,
        "compute_probability",
        lambda ensemble, target_date, market_info: {"prob": 0.65, "mean": 74.2, "std": 1.0, "n": 31},
    )
    fetched_at = datetime.now(timezone.utc)
    observation = ws.WeatherObservation(
        source="aviationweather_metar",
        station_id="KJFK",
        observed_at=fetched_at - timedelta(seconds=30),
        fetched_at=fetched_at,
        temp_f=75.0,
        raw={"rawOb": "KJFK test"},
        raw_hash="metar-lock-hash",
        source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
    )
    monkeypatch.setattr(ws, "get_metar_temps", lambda city, today: {
        "max_temp_f": 75.0,
        "current_temp_f": 75.0,
        "local_hour": 16,
        "observation": observation,
    })
    monkeypatch.setattr(ws.settings, "INITIAL_BANKROLL", 10_000.0)
    monkeypatch.setattr(ws.settings, "WEATHER_MAX_TRADE_SIZE", 100.0)
    monkeypatch.setattr(ws.settings, "WEATHER_MIN_EDGE_THRESHOLD", 0.01)
    monkeypatch.setattr(ws.settings, "WEATHER_MAX_ENTRY_PRICE", 0.99)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("METAR-lock is already physical truth and must not use forecast convergence")

    monkeypatch.setattr(ws, "record_forecast_run", fail_if_called, raising=False)
    monkeypatch.setattr(ws, "load_forecast_series", fail_if_called, raising=False)
    monkeypatch.setattr(ws, "compute_convergence_score", fail_if_called, raising=False)

    signals = ws._build_signals_sync()

    assert len(signals) == 1
    assert signals[0].signal_source == "METAR-lock"
    assert signals[0].suggested_size == 100.0
    assert "forecast_convergence" not in signals[0].sources
