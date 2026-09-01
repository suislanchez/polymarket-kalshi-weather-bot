"""Signal generator for weather temperature markets using ensemble forecasts."""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from backend.config import settings
from backend.core.signals import calculate_edge, calculate_kelly_size
from backend.data.weather import (
    fetch_ensemble_forecast,
    EnsembleForecast,
    integer_temp_meets,
)
from backend.data.weather_markets import WeatherMarket, fetch_polymarket_weather_markets
from backend.models.database import SessionLocal, Signal

logger = logging.getLogger("trading_bot")


@dataclass
class WeatherTradingSignal:
    """A trading signal for a weather temperature market."""
    market: WeatherMarket

    # Core signal data
    model_probability: float = 0.5   # Ensemble probability of YES outcome
    market_probability: float = 0.5  # Market's implied YES probability
    edge: float = 0.0
    direction: str = "yes"           # "yes" or "no"

    # Confidence and sizing
    confidence: float = 0.5
    kelly_fraction: float = 0.0
    suggested_size: float = 0.0

    # Metadata
    sources: List[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Forecast context
    ensemble_mean: float = 0.0
    ensemble_std: float = 0.0
    ensemble_members: int = 0

    @property
    def passes_threshold(self) -> bool:
        """Check if signal passes minimum edge threshold."""
        return abs(self.edge) >= settings.WEATHER_MIN_EDGE_THRESHOLD


def _ensemble_members_for_market(forecast: EnsembleForecast, market: WeatherMarket) -> List[float]:
    return forecast.member_highs if market.metric == "high" else forecast.member_lows


def model_yes_probability(forecast: EnsembleForecast, market: WeatherMarket) -> Optional[float]:
    """YES probability using the same integer-high definition as settlement.

    Open-Meteo members are floats; NOAA/official highs are whole degrees.
    '80-81°F' is P(round(h) in [80, 81]), not a mix of strict float cuts.
    Returns None (with a warning) if a between-bracket is missing its high.
    """
    members = _ensemble_members_for_market(forecast, market)
    if not members:
        return None

    if market.direction == "between" and market.threshold_high_f is None:
        logger.warning(
            "Skipping %s: between-bracket missing threshold_high_f",
            getattr(market, "title", None) or market.slug,
        )
        return None

    try:
        yes_count = sum(
            1 for m in members
            if integer_temp_meets(
                m, market.direction, market.threshold_f, market.threshold_high_f
            )
        )
    except ValueError as e:
        logger.warning(
            "Skipping %s: %s",
            getattr(market, "title", None) or market.slug,
            e,
        )
        return None

    return yes_count / len(members)


def ensemble_yes_agreement(forecast: EnsembleForecast, market: WeatherMarket) -> Optional[float]:
    """Ensemble agreement on YES vs NO (same integer definition as probability)."""
    members = _ensemble_members_for_market(forecast, market)
    if not members:
        return None

    if market.direction == "between" and market.threshold_high_f is None:
        logger.warning(
            "Skipping confidence for %s: between-bracket missing threshold_high_f",
            getattr(market, "title", None) or market.slug,
        )
        return None

    try:
        yes_count = sum(
            1 for m in members
            if integer_temp_meets(
                m, market.direction, market.threshold_f, market.threshold_high_f
            )
        )
    except ValueError as e:
        logger.warning(
            "Skipping confidence for %s: %s",
            getattr(market, "title", None) or market.slug,
            e,
        )
        return None

    n = len(members)
    agreement_frac = max(yes_count, n - yes_count) / n
    return min(0.9, agreement_frac)


async def generate_weather_signal(market: WeatherMarket) -> Optional[WeatherTradingSignal]:
    """
    Generate a trading signal for a weather temperature market.

    Uses ensemble forecast to estimate probability:
    - Count fraction of ensemble members above/below the threshold
    - Compare to market price to find edge
    - Size using Kelly criterion
    """
    forecast = await fetch_ensemble_forecast(market.city_key, market.target_date)
    if not forecast or not forecast.member_highs:
        return None

    model_yes_prob = model_yes_probability(forecast, market)
    if model_yes_prob is None:
        return None

    agreement_frac = ensemble_yes_agreement(forecast, market)
    if agreement_frac is None:
        return None

    # Clip extreme probabilities (ensemble can be unanimous but don't bet 100%)
    model_yes_prob = max(0.05, min(0.95, model_yes_prob))

    market_yes_prob = market.yes_price

    # Use existing edge calculation (treats yes=up, no=down)
    edge, direction_raw = calculate_edge(model_yes_prob, market_yes_prob)
    direction = "yes" if direction_raw == "up" else "no"

    # Entry price filter
    entry_price = market.yes_price if direction == "yes" else market.no_price
    if entry_price > settings.WEATHER_MAX_ENTRY_PRICE:
        edge = 0.0  # Zero out but still return for UI visibility

    confidence = agreement_frac

    # Kelly sizing
    bankroll = settings.INITIAL_BANKROLL
    suggested_size = calculate_kelly_size(
        edge=abs(edge),
        probability=model_yes_prob,
        market_price=market_yes_prob,
        direction=direction_raw,  # calculate_kelly_size expects "up"/"down"
        bankroll=bankroll,
    )
    suggested_size = min(suggested_size, settings.WEATHER_MAX_TRADE_SIZE)

    # Ensemble stats for display
    mean_val = forecast.mean_high if market.metric == "high" else forecast.mean_low
    std_val = forecast.std_high if market.metric == "high" else forecast.std_low

    # Build reasoning
    filter_status = "ACTIONABLE" if abs(edge) >= settings.WEATHER_MIN_EDGE_THRESHOLD else "FILTERED"
    filter_notes = []
    if entry_price > settings.WEATHER_MAX_ENTRY_PRICE:
        filter_notes.append(f"entry {entry_price:.0%} > {settings.WEATHER_MAX_ENTRY_PRICE:.0%}")
    filter_note = f" [{', '.join(filter_notes)}]" if filter_notes else ""

    bracket_desc = (
        f"{market.threshold_f:.0f}-{market.threshold_high_f:.0f}F"
        if market.direction == "between" and market.threshold_high_f is not None
        else f"{market.direction} {market.threshold_f:.0f}F"
    )
    reasoning = (
        f"[{filter_status}]{filter_note} "
        f"{market.city_name} {market.metric} {bracket_desc} on {market.target_date} | "
        f"Ensemble: {mean_val:.1f}F +/- {std_val:.1f}F ({forecast.num_members} members) | "
        f"Model YES: {model_yes_prob:.0%} vs Market: {market_yes_prob:.0%} | "
        f"Edge: {edge:+.1%} -> {direction.upper()} @ {entry_price:.0%} | "
        f"Agreement: {agreement_frac:.0%}"
    )

    return WeatherTradingSignal(
        market=market,
        model_probability=model_yes_prob,
        market_probability=market_yes_prob,
        edge=edge,
        direction=direction,
        confidence=confidence,
        kelly_fraction=suggested_size / bankroll if bankroll > 0 else 0,
        suggested_size=suggested_size,
        sources=[f"open_meteo_ensemble_{forecast.num_members}m"],
        reasoning=reasoning,
        ensemble_mean=mean_val,
        ensemble_std=std_val,
        ensemble_members=forecast.num_members,
    )


async def scan_for_weather_signals() -> List[WeatherTradingSignal]:
    """
    Scan weather markets and generate ensemble-based signals.
    """
    signals = []

    city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]

    logger.info("=" * 50)
    logger.info("WEATHER SCAN: Fetching temperature markets...")

    markets = []

    # Polymarket
    try:
        poly_markets = await fetch_polymarket_weather_markets(city_keys)
        markets.extend(poly_markets)
        logger.info(f"Polymarket: {len(poly_markets)} weather markets")
    except Exception as e:
        logger.error(f"Failed to fetch Polymarket weather markets: {e}")

    # Kalshi
    if settings.KALSHI_ENABLED:
        try:
            from backend.data.kalshi_client import kalshi_credentials_present
            from backend.data.kalshi_markets import fetch_kalshi_weather_markets
            if kalshi_credentials_present():
                kalshi_markets = await fetch_kalshi_weather_markets(city_keys)
                markets.extend(kalshi_markets)
                logger.info(f"Kalshi: {len(kalshi_markets)} weather markets")
        except Exception as e:
            logger.error(f"Failed to fetch Kalshi weather markets: {e}")

    logger.info(f"Found {len(markets)} total weather temperature markets")

    for market in markets:
        try:
            signal = await generate_weather_signal(market)
            if signal:
                signals.append(signal)
        except Exception as e:
            logger.debug(f"Weather signal generation failed for {market.title}: {e}")

    # Sort by absolute edge
    signals.sort(key=lambda s: abs(s.edge), reverse=True)

    actionable = [s for s in signals if s.passes_threshold]
    logger.info(f"WEATHER SCAN COMPLETE: {len(signals)} signals, {len(actionable)} actionable")

    for signal in actionable[:5]:
        logger.info(f"  {signal.market.city_name}: {signal.market.metric} {signal.market.direction} "
                     f"{signal.market.threshold_f:.0f}F | Edge: {signal.edge:+.1%}")

    # Persist signals to DB
    _persist_weather_signals(signals)

    return signals


def _persist_weather_signals(signals: list):
    """Save weather signals to DB for calibration tracking."""
    to_save = [s for s in signals if abs(s.edge) > 0]
    if not to_save:
        return

    db = SessionLocal()
    try:
        for signal in to_save:
            # Dedup: skip if already logged for this market
            existing = db.query(Signal).filter(
                Signal.market_ticker == signal.market.market_id,
                Signal.timestamp >= signal.timestamp.replace(second=0, microsecond=0),
            ).first()
            if existing:
                continue

            db_signal = Signal(
                market_ticker=signal.market.market_id,
                platform=signal.market.platform,
                market_type="weather",
                timestamp=signal.timestamp,
                direction=signal.direction,
                model_probability=signal.model_probability,
                market_price=signal.market_probability,
                edge=signal.edge,
                confidence=signal.confidence,
                kelly_fraction=signal.kelly_fraction,
                suggested_size=signal.suggested_size,
                sources=signal.sources,
                reasoning=signal.reasoning,
                executed=False,
            )
            db.add(db_signal)

        db.commit()
    except Exception as e:
        logger.warning(f"Failed to persist weather signals: {e}")
        db.rollback()
    finally:
        db.close()
