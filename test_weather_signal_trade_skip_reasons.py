from datetime import date, datetime, timedelta, timezone

from backend.core.weather_source_benchmark import SourceObservation
from backend.core.weather_signals import KalshiWeatherMarket, WeatherObservation, WeatherTradingSignal


def _market(*, target_date=None, metric="high"):
    return KalshiWeatherMarket(
        market_id="KXHIGHTNY-26JUN03-T85",
        slug="KXHIGHTNY-26JUN03-T85",
        city_key="nyc",
        city_name="New York City",
        target_date=target_date or date.today(),
        threshold_f=85.0,
        metric=metric,
        yes_price=0.4,
        no_price=0.6,
    )


def _authority_observation(*, temp_f=86.0, stale=False):
    fetched_at = datetime.now(timezone.utc)
    observed_at = fetched_at - (timedelta(seconds=900) if stale else timedelta(seconds=30))
    return WeatherObservation(
        source="aviationweather_metar",
        station_id="KJFK",
        observed_at=observed_at,
        fetched_at=fetched_at,
        temp_f=temp_f,
        raw={"rawOb": "KJFK test"},
        raw_hash=f"hash-{temp_f}-{stale}",
        source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
    )


def _source_observation(source, temp_f):
    fetched_at = datetime.now(timezone.utc)
    return SourceObservation(
        source=source,
        station_id="KJFK",
        observed_at=fetched_at - timedelta(seconds=30),
        fetched_at=fetched_at,
        temp_f=temp_f,
        source_url=f"https://example.com/{source}",
        raw_hash=f"{source}-{temp_f}",
    )


def test_same_day_temperature_high_signal_fails_closed_without_observation():
    signal = WeatherTradingSignal(
        market=_market(),
        model_probability=0.95,
        market_probability=0.40,
        edge=0.55,
        net_edge=0.48,
        suggested_size=50.0,
    )

    assert signal.trade_skip_reason() == "weather_observation_missing"
    assert signal.passes_threshold is False


def test_same_day_temperature_low_signal_without_observation_keeps_forecast_path_eligible():
    signal = WeatherTradingSignal(
        market=_market(),
        model_probability=0.95,
        market_probability=0.40,
        edge=0.55,
        net_edge=0.48,
        suggested_size=50.0,
    )
    signal.market.metric = "low"

    assert signal.trade_skip_reason() is None
    assert signal.passes_threshold is True


def test_stale_weather_observation_blocks_otherwise_actionable_signal_with_exact_reason():
    signal = WeatherTradingSignal(
        market=_market(),
        model_probability=0.95,
        market_probability=0.40,
        edge=0.55,
        net_edge=0.48,
        suggested_size=50.0,
        weather_observation=_authority_observation(stale=True),
    )

    assert signal.passes_threshold is False
    skip_reason = signal.trade_skip_reason()
    assert skip_reason is not None
    assert skip_reason.startswith("aviationweather_metar.stale_observation_age_")
    assert skip_reason.endswith("s_gt_300s")


def test_source_fusion_conflict_blocks_otherwise_actionable_signal():
    signal = WeatherTradingSignal(
        market=_market(),
        model_probability=0.95,
        market_probability=0.40,
        edge=0.55,
        net_edge=0.48,
        suggested_size=50.0,
        weather_observation=_authority_observation(temp_f=84.0),
        source_observations=[
            _source_observation("nws_latest_observation", 86.0),
            _source_observation("aviationweather_metar", 84.0),
        ],
        source_fusion_policy={
            "aviationweather_metar": {"role": "lock_authority"},
            "nws_latest_observation": {"role": "watch_only"},
        },
    )

    assert signal.passes_threshold is False
    assert signal.trade_skip_reason() == "watch_source_crossed_but_authority_below:nws_latest_observation"


def test_fresh_authority_lock_can_pass_threshold():
    signal = WeatherTradingSignal(
        market=_market(),
        model_probability=0.95,
        market_probability=0.40,
        edge=0.55,
        net_edge=0.48,
        suggested_size=50.0,
        weather_observation=_authority_observation(temp_f=86.0),
        source_observations=[_source_observation("aviationweather_metar", 86.0)],
        source_fusion_policy={"aviationweather_metar": {"role": "lock_authority"}},
    )

    assert signal.trade_skip_reason() is None
    assert signal.passes_threshold is True


def test_same_day_low_temperature_signal_does_not_require_high_temp_authority_lock():
    signal = WeatherTradingSignal(
        market=_market(metric="low"),
        model_probability=0.95,
        market_probability=0.40,
        edge=0.55,
        net_edge=0.48,
        suggested_size=50.0,
    )

    assert signal.trade_skip_reason() is None
    assert signal.passes_threshold is True
