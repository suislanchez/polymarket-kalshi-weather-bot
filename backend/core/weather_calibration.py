"""Probability calibration / anti-overconfidence layer for weather signals.

The base model estimates P(YES) by counting ensemble members above/below a
threshold. That estimator is badly overconfident in exactly the situations that
hurt the paper ledger most:

* **Near a threshold.** A tight ensemble can be unanimous (raw prob 0/1, clipped
  to 5%/95%) while the mean is only a fraction of a degree from the line. One
  warm afternoon flips the outcome.
* **Underdispersed ensembles.** Raw GFS ensemble spread for daily temperature is
  known to be too narrow, so member-count probabilities are too sharp.
* **Source/station mismatch.** When the settlement station/source is not an exact
  match, observation noise adds real uncertainty the ensemble never sees.

This module re-estimates the probability with a **variance-inflated Gaussian**
(a standard ensemble post-processing / "dressing" technique) and returns a
``confident`` flag derived from the threshold's distance in inflated sigmas.
Callers (the weather signal generator) use ``confident`` as a complementary
no-trade gate so a clipped 95% unanimity cannot, by itself, drive a trade.

Pure and dependency-light (only ``math`` + ``settings`` for defaults) so it is
fully unit-testable without network or DB.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from backend.config import settings


def normal_cdf(x: float) -> float:
    """Standard normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clamp01(value: float) -> float:
    return _clamp(value, 0.0, 1.0)


@dataclass(frozen=True)
class CalibrationConfig:
    """Tuning for the calibration layer.

    Defaults are conservative on purpose; operationally meaningful values are
    overridable from settings via :func:`config_from_settings`.
    """

    # Floor on the per-member spread (deg F). Raw ensemble spread for daily temps
    # is frequently <1F, which is not believable for a settlement outcome.
    min_std_f: float = 1.5
    # Multiplicative inflation to correct ensemble underdispersion.
    std_inflation: float = 1.5
    # Extra observation/station uncertainty (deg F) added in quadrature when the
    # settlement source/station is not an exact match.
    obs_std_f: float = 2.0
    # Member count considered "full"; fewer members widen the distribution.
    full_members: int = 31
    max_member_factor: float = 2.5
    # Weight on the Gaussian estimate vs the raw member-count estimate.
    gaussian_weight: float = 0.7
    # Probability clip range (never claim certainty).
    prob_floor: float = 0.05
    prob_ceil: float = 0.95
    # Confidence gate: threshold must be at least this many inflated sigmas from
    # the ensemble mean, with at least this many members and an exact source.
    min_confident_z: float = 1.0
    min_members: int = 20
    # Shrinkage multiplier applied to the YES-0.5 deviation when the source is
    # inexact (belt-and-suspenders on top of the variance inflation).
    inexact_source_shrink: float = 0.6


DEFAULT_CONFIG = CalibrationConfig()


def config_from_settings() -> CalibrationConfig:
    """Build a :class:`CalibrationConfig` from operational settings overrides."""
    return CalibrationConfig(
        min_std_f=float(getattr(settings, "WEATHER_CALIBRATION_MIN_STD_F", DEFAULT_CONFIG.min_std_f)),
        std_inflation=float(getattr(settings, "WEATHER_CALIBRATION_STD_INFLATION", DEFAULT_CONFIG.std_inflation)),
        min_confident_z=float(getattr(settings, "WEATHER_CALIBRATION_MIN_CONFIDENT_Z", DEFAULT_CONFIG.min_confident_z)),
        min_members=int(getattr(settings, "WEATHER_CALIBRATION_MIN_MEMBERS", DEFAULT_CONFIG.min_members)),
    )


@dataclass(frozen=True)
class CalibrationResult:
    calibrated_probability: float
    raw_probability: float
    inflated_std: float
    threshold_z: Optional[float]
    shrink_weight: float
    method: str
    confident: bool
    reasons: list[str] = field(default_factory=list)


def reliability_weight_from_brier(
    *,
    brier: Optional[float],
    sample_size: int,
    neutral: float = 1.0,
    floor: float = 0.4,
) -> float:
    """Map a venue's recent Brier score to a [floor, 1] reliability multiplier.

    A Brier of 0 is perfect; 0.25 is a coin flip for binary outcomes. We map
    [0, 0.25] -> [1, floor] and shrink toward ``neutral`` for small samples so a
    handful of trades cannot swing confidence. Returns ``neutral`` when no Brier
    is available.
    """
    if brier is None or sample_size <= 0:
        return neutral
    raw = 1.0 - _clamp01(brier / 0.25) * (1.0 - floor)
    # Confidence in the estimate grows with sample size (full trust ~30 samples).
    trust = _clamp01(sample_size / 30.0)
    return _clamp01(neutral + trust * (raw - neutral))


def calibrate_weather_probability(
    *,
    metric: str,
    direction: str,
    threshold_f: Optional[float],
    bucket_low_f: Optional[float],
    bucket_high_f: Optional[float],
    ensemble_mean: Optional[float],
    ensemble_std: Optional[float],
    ensemble_members: int,
    raw_probability: float,
    exact_source: bool = True,
    venue_reliability: float = 1.0,
    config: Optional[CalibrationConfig] = None,
) -> CalibrationResult:
    """Re-estimate P(YES) with a variance-inflated Gaussian + shrinkage.

    Returns the calibrated probability plus diagnostics and a ``confident`` flag.
    ``confident`` is True only when the threshold is comfortably far (in inflated
    sigmas) from the ensemble mean, the ensemble is large enough, and the
    settlement source is exact.
    """
    cfg = config or DEFAULT_CONFIG
    reasons: list[str] = []
    raw = _clamp01(float(raw_probability))

    # --- Inflated spread -------------------------------------------------
    base_std = max(float(ensemble_std or 0.0), cfg.min_std_f)
    inflated = base_std * cfg.std_inflation
    if not exact_source:
        inflated = math.sqrt(inflated ** 2 + cfg.obs_std_f ** 2)
        reasons.append("inexact settlement source/station widens forecast uncertainty")
    members = max(int(ensemble_members or 0), 0)
    if 0 < members < cfg.full_members:
        member_factor = min(math.sqrt(cfg.full_members / members), cfg.max_member_factor)
        inflated *= member_factor
    inflated = max(inflated, cfg.min_std_f)

    # --- Gaussian YES probability ---------------------------------------
    threshold_z: Optional[float] = None
    method = "gaussian"
    if direction in ("above", "below") and threshold_f is not None and ensemble_mean is not None:
        z_signed = (float(threshold_f) - float(ensemble_mean)) / inflated
        cdf_below = normal_cdf(z_signed)
        gaussian = (1.0 - cdf_below) if direction == "above" else cdf_below
        threshold_z = abs(float(ensemble_mean) - float(threshold_f)) / inflated
    elif direction == "bucket" and bucket_low_f is not None and bucket_high_f is not None and ensemble_mean is not None:
        lo = normal_cdf((float(bucket_low_f) - float(ensemble_mean)) / inflated)
        hi = normal_cdf((float(bucket_high_f) - float(ensemble_mean)) / inflated)
        gaussian = max(0.0, hi - lo)
    else:
        gaussian = raw
        method = "raw_fallback"
        reasons.append("no usable threshold geometry; falling back to raw ensemble probability")

    gaussian = _clamp(gaussian, cfg.prob_floor, cfg.prob_ceil)

    # Blend the Gaussian (primary) with the raw member-count estimate so gross
    # non-Gaussianity (e.g. bimodal forecasts) is not entirely ignored.
    core = cfg.gaussian_weight * gaussian + (1.0 - cfg.gaussian_weight) * raw

    # --- Shrinkage toward 0.5 for degraded inputs -----------------------
    member_adequacy = _clamp01(members / cfg.min_members) if cfg.min_members > 0 else 1.0
    source_w = 1.0 if exact_source else cfg.inexact_source_shrink
    shrink_weight = _clamp01(member_adequacy * source_w * _clamp01(venue_reliability))
    calibrated = 0.5 + shrink_weight * (core - 0.5)
    calibrated = _clamp(calibrated, cfg.prob_floor, cfg.prob_ceil)

    # --- Confidence gate -------------------------------------------------
    confident = (
        members >= cfg.min_members
        and exact_source
        and threshold_z is not None
        and threshold_z >= cfg.min_confident_z
    )
    if not confident:
        if threshold_z is not None and threshold_z < cfg.min_confident_z:
            reasons.append(
                f"threshold within {cfg.min_confident_z:.1f}σ of inflated forecast "
                f"(z={threshold_z:.2f}); not confident"
            )
        if members < cfg.min_members:
            reasons.append(f"ensemble has {members} members (<{cfg.min_members} required for confidence)")
        if direction == "bucket":
            reasons.append("bucket markets require mutually-exclusive set sanity, not a single-threshold confidence")

    return CalibrationResult(
        calibrated_probability=round(calibrated, 6),
        raw_probability=round(raw, 6),
        inflated_std=round(inflated, 4),
        threshold_z=None if threshold_z is None else round(threshold_z, 4),
        shrink_weight=round(shrink_weight, 4),
        method=method,
        confident=confident,
        reasons=reasons,
    )
