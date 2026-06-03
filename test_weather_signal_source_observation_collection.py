from datetime import date, datetime, timezone

from backend.core import weather_signals as ws
from backend.core.weather_source_benchmark import SourceObservation


def test_collect_source_observations_keeps_authority_and_comparators(monkeypatch):
    authority = ws.WeatherObservation(
        source="aviationweather_metar",
        station_id="KJFK",
        observed_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc),
        temp_f=86.0,
        raw={"rawOb": "KJFK 031551Z AUTO"},
        raw_hash="metar-hash",
        source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
    )

    def fake_nws(station_id, lat, lon):
        return SourceObservation(
            source="nws_latest_observation",
            station_id=station_id,
            observed_at=datetime(2026, 6, 3, 15, 50, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 6, 3, 15, 51, 30, tzinfo=timezone.utc),
            temp_f=86.2,
            source_url=f"nws:{lat}:{lon}",
            raw_hash="nws-hash",
        )

    def fake_open_meteo(_station_id, _lat, _lon):
        raise TimeoutError("open meteo timeout")

    observations, failures = ws.collect_source_observations_for_station(
        "KJFK",
        lat=40.6413,
        lon=-73.7781,
        authority_observation=authority,
        comparator_providers=[fake_nws, fake_open_meteo],
    )

    assert [observation.source for observation in observations] == [
        "aviationweather_metar",
        "nws_latest_observation",
    ]
    assert failures == {"fake_open_meteo": "TimeoutError: open meteo timeout"}


def test_same_day_signal_attaches_comparator_source_observations_for_fusion(monkeypatch):
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
    authority = ws.WeatherObservation(
        source="aviationweather_metar",
        station_id="KJFK",
        observed_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc),
        temp_f=84.0,
        raw={"rawOb": "KJFK 031551Z AUTO"},
        raw_hash="metar-hash",
        source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
    )
    comparator = SourceObservation(
        source="nws_latest_observation",
        station_id="KJFK",
        observed_at=datetime(2026, 6, 3, 15, 50, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
        temp_f=86.0,
        source_url="https://api.weather.gov/stations/KJFK/observations/latest",
        raw_hash="nws-hash",
    )

    monkeypatch.setattr(ws, "date", type("FakeDate", (), {"today": staticmethod(lambda: today)}))
    monkeypatch.setattr(ws, "fetch_kalshi_weather_markets", lambda: [raw_market])
    monkeypatch.setattr(ws, "fetch_ensemble", lambda *_args: {"2026-06-03": {"temp_max_c": [30.0], "temp_min_c": [20.0], "precip_total_mm": [0.0], "snow_total_cm": [0.0], "n_members": 1}})
    monkeypatch.setattr(ws, "get_metar_temps", lambda *_args: {
        "icao": "KJFK",
        "status": "fresh",
        "current_temp_f": 84.0,
        "max_temp_f": 84.0,
        "local_hour": 15,
        "observation": authority,
    })
    monkeypatch.setattr(ws, "metar_high_probability", lambda *_args: (0.05, "high", "authority below"))
    monkeypatch.setattr(ws, "collect_source_observations_for_station", lambda *_args, **_kwargs: ([
        SourceObservation(
            source="aviationweather_metar",
            station_id="KJFK",
            observed_at=authority.observed_at,
            fetched_at=authority.fetched_at,
            temp_f=authority.temp_f,
            source_url=authority.source_url,
            raw_hash=authority.raw_hash,
        ),
        comparator,
    ], {}))
    monkeypatch.setattr(ws, "load_live_source_fusion_policy", lambda: {
        "aviationweather_metar": {"role": "lock_authority"},
        "nws_latest_observation": {"role": "watch_only"},
    })

    signal = ws._build_signals_sync()[0]

    assert [observation.source for observation in signal.source_observations] == [
        "aviationweather_metar",
        "nws_latest_observation",
    ]
    assert signal.source_fusion_policy["nws_latest_observation"]["role"] == "watch_only"
