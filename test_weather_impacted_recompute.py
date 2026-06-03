from datetime import date, datetime, timezone

from backend.core import weather_signals as ws


def _signal(market_id, city_key, target_date):
    return ws.WeatherTradingSignal(
        market=ws.KalshiWeatherMarket(
            market_id=market_id,
            slug=market_id,
            city_key=city_key,
            city_name=city_key.upper(),
            target_date=target_date,
            threshold_f=85.0,
            metric="high",
        ),
        edge=0.1,
    )


def test_recompute_plan_scopes_changed_station_observation_to_impacted_same_day_tickers():
    observation = ws.WeatherObservation(
        source="aviationweather_metar",
        station_id="KJFK",
        observed_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc),
        temp_f=86.0,
        raw={"rawOb": "KJFK 031551Z AUTO"},
        raw_hash="new-hash",
        source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
    )
    signals = [
        _signal("KXHIGHTNY-26JUN03-T85", "nyc", date(2026, 6, 3)),
        _signal("KXHIGHTLA-26JUN03-T85", "los angeles", date(2026, 6, 3)),
        _signal("KXHIGHTNY-26JUN04-T85", "nyc", date(2026, 6, 4)),
    ]

    plan = ws.plan_impacted_weather_recompute(
        observation,
        signals,
        as_of_date=date(2026, 6, 3),
        previous_hash_by_station={},
    )

    assert plan.changed is True
    assert plan.station_id == "KJFK"
    assert plan.city_keys == ["nyc"]
    assert plan.market_ids == ["KXHIGHTNY-26JUN03-T85"]
    assert plan.skip_reason is None


def test_recompute_plan_suppresses_unchanged_observation_hash_with_exact_reason():
    observation = ws.WeatherObservation(
        source="aviationweather_metar",
        station_id="KJFK",
        observed_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc),
        temp_f=86.0,
        raw={"rawOb": "KJFK 031551Z AUTO"},
        raw_hash="same-hash",
        source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
    )

    plan = ws.plan_impacted_weather_recompute(
        observation,
        [_signal("KXHIGHTNY-26JUN03-T85", "nyc", date(2026, 6, 3))],
        as_of_date=date(2026, 6, 3),
        previous_hash_by_station={"KJFK": "same-hash"},
    )

    assert plan.changed is False
    assert plan.market_ids == []
    assert plan.skip_reason == "observation_hash_unchanged"
