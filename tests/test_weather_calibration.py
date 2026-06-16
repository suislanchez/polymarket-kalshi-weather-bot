"""Tests for the weather probability-calibration / anti-overconfidence layer.

The model counts ensemble members above/below a threshold, which is dangerously
overconfident near thresholds and for tight/underdispersed ensembles. This layer
re-estimates the probability with a variance-inflated Gaussian and emits a
confidence flag so clipped 95%/5% unanimity cannot, on its own, drive an
actionable trade.
"""
import math

import pytest

from backend.core.weather_calibration import (
    CalibrationConfig,
    CalibrationResult,
    calibrate_weather_probability,
    config_from_settings,
    normal_cdf,
    reliability_weight_from_brier,
)


def test_normal_cdf_basic_properties():
    assert normal_cdf(0.0) == pytest.approx(0.5, abs=1e-9)
    assert normal_cdf(-10.0) < 1e-6
    assert normal_cdf(10.0) > 1.0 - 1e-6
    # Monotonic increasing
    assert normal_cdf(-1.0) < normal_cdf(0.0) < normal_cdf(1.0)
    assert normal_cdf(1.0) == pytest.approx(0.8413447, abs=1e-5)


def test_far_threshold_stays_confident_and_high():
    result = calibrate_weather_probability(
        metric="high",
        direction="above",
        threshold_f=75.0,
        bucket_low_f=None,
        bucket_high_f=None,
        ensemble_mean=82.0,
        ensemble_std=2.0,
        ensemble_members=31,
        raw_probability=1.0,  # unanimous, clipped upstream
        exact_source=True,
    )
    assert isinstance(result, CalibrationResult)
    assert result.confident is True
    assert result.calibrated_probability >= 0.9
    assert result.threshold_z is not None and result.threshold_z > 1.0


def test_unanimous_near_threshold_is_not_confident_and_is_shrunk():
    # Tight ensemble (std 0.3) all sitting just above the threshold: the raw
    # member-count says ~100% (clipped 95%) but the mean is only 0.5F away.
    result = calibrate_weather_probability(
        metric="high",
        direction="above",
        threshold_f=75.0,
        bucket_low_f=None,
        bucket_high_f=None,
        ensemble_mean=75.5,
        ensemble_std=0.3,
        ensemble_members=31,
        raw_probability=1.0,
        exact_source=True,
    )
    assert result.confident is False
    # Must be pulled well below the clipped 0.95 it would otherwise be.
    assert result.calibrated_probability < 0.80
    assert result.calibrated_probability > 0.5  # still leans the right way
    assert result.raw_probability == pytest.approx(1.0)
    assert any("σ" in r or "confiden" in r.lower() for r in result.reasons)


def test_inexact_source_widens_uncertainty_and_blocks_confidence():
    exact = calibrate_weather_probability(
        metric="high", direction="above", threshold_f=75.0,
        bucket_low_f=None, bucket_high_f=None,
        ensemble_mean=80.0, ensemble_std=2.0, ensemble_members=31,
        raw_probability=1.0, exact_source=True,
    )
    inexact = calibrate_weather_probability(
        metric="high", direction="above", threshold_f=75.0,
        bucket_low_f=None, bucket_high_f=None,
        ensemble_mean=80.0, ensemble_std=2.0, ensemble_members=31,
        raw_probability=1.0, exact_source=False,
    )
    # Inexact source must be at least as cautious (closer to 0.5) and not confident.
    assert inexact.calibrated_probability <= exact.calibrated_probability
    assert inexact.confident is False
    assert inexact.inflated_std > exact.inflated_std


def test_fewer_members_shrinks_toward_half():
    many = calibrate_weather_probability(
        metric="low", direction="below", threshold_f=60.0,
        bucket_low_f=None, bucket_high_f=None,
        ensemble_mean=55.0, ensemble_std=2.0, ensemble_members=31,
        raw_probability=1.0, exact_source=True,
    )
    few = calibrate_weather_probability(
        metric="low", direction="below", threshold_f=60.0,
        bucket_low_f=None, bucket_high_f=None,
        ensemble_mean=55.0, ensemble_std=2.0, ensemble_members=4,
        raw_probability=1.0, exact_source=True,
    )
    assert abs(few.calibrated_probability - 0.5) < abs(many.calibrated_probability - 0.5)
    assert few.confident is False


def test_below_direction_orientation():
    # mean well below threshold => P(value below threshold) should be high.
    result = calibrate_weather_probability(
        metric="low", direction="below", threshold_f=60.0,
        bucket_low_f=None, bucket_high_f=None,
        ensemble_mean=52.0, ensemble_std=2.0, ensemble_members=31,
        raw_probability=1.0, exact_source=True,
    )
    assert result.calibrated_probability >= 0.9


def test_bucket_uses_gaussian_band():
    result = calibrate_weather_probability(
        metric="high", direction="bucket", threshold_f=None,
        bucket_low_f=74.0, bucket_high_f=76.0,
        ensemble_mean=75.0, ensemble_std=1.0, ensemble_members=31,
        raw_probability=0.68, exact_source=True,
    )
    # A narrow 2F band is genuinely uncertain once the spread floor inflates the
    # sigma, so the calibrated mass is pulled below the naive 0.68 estimate.
    assert 0.25 < result.calibrated_probability < 0.70
    assert result.calibrated_probability < result.raw_probability
    assert result.threshold_z is None
    assert result.method == "gaussian"


def test_calibrated_probability_always_in_clip_range():
    cfg = CalibrationConfig()
    for mean in (40.0, 75.0, 120.0):
        r = calibrate_weather_probability(
            metric="high", direction="above", threshold_f=75.0,
            bucket_low_f=None, bucket_high_f=None,
            ensemble_mean=mean, ensemble_std=1.0, ensemble_members=31,
            raw_probability=1.0, exact_source=True, config=cfg,
        )
        assert cfg.prob_floor <= r.calibrated_probability <= cfg.prob_ceil


def test_reliability_weight_from_brier():
    # Perfect calibration -> high weight; coin-flip Brier (0.25) -> low weight.
    strong = reliability_weight_from_brier(brier=0.05, sample_size=100)
    weak = reliability_weight_from_brier(brier=0.25, sample_size=100)
    assert strong > weak
    assert 0.0 <= weak <= strong <= 1.0
    # Tiny samples are not trusted to move the weight far from neutral.
    tiny = reliability_weight_from_brier(brier=0.05, sample_size=1)
    assert abs(tiny - 1.0) < abs(strong - 1.0) or tiny == pytest.approx(1.0)


def test_config_from_settings_reads_overrides(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "WEATHER_CALIBRATION_MIN_MEMBERS", 12, raising=False)
    monkeypatch.setattr(settings, "WEATHER_CALIBRATION_MIN_CONFIDENT_Z", 2.0, raising=False)
    cfg = config_from_settings()
    assert cfg.min_members == 12
    assert cfg.min_confident_z == 2.0
