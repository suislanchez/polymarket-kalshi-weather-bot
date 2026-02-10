"""Signal generator - calculates edges and generates trading signals."""
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass, field
import asyncio

from backend.config import settings
from backend.data.weather import WeatherPrediction, fetch_weather_prediction
from backend.data.markets import MarketData, fetch_all_weather_markets


@dataclass
class TradingSignal:
    """A trading signal with all relevant data."""
    market: MarketData
    weather: WeatherPrediction

    # Core signal data
    model_probability: float  # Our calculated probability
    market_probability: float  # Implied by market price
    edge: float  # Difference
    direction: str  # "yes" or "no"

    # Confidence and sizing
    confidence: float
    kelly_fraction: float
    suggested_size: float

    # Metadata
    sources: List[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def passes_threshold(self) -> bool:
        """Check if signal passes minimum edge threshold."""
        return abs(self.edge) >= settings.MIN_EDGE_THRESHOLD


def calculate_edge(
    model_prob: float,
    market_price: float
) -> tuple[float, str]:
    """
    Calculate edge and determine direction.

    Returns:
        (edge, direction) where direction is "yes" or "no"
    """
    # Edge for YES bet
    yes_edge = model_prob - market_price

    # Edge for NO bet
    no_edge = (1 - model_prob) - (1 - market_price)

    # Take the more profitable direction
    if yes_edge >= no_edge:
        return yes_edge, "yes"
    else:
        return no_edge, "no"


def calculate_kelly_size(
    edge: float,
    probability: float,
    market_price: float,
    direction: str,
    bankroll: float
) -> float:
    """
    Calculate position size using fractional Kelly criterion.

    Kelly formula: f = (p * b - q) / b
    where:
        f = fraction of bankroll to bet
        p = probability of winning
        q = probability of losing (1 - p)
        b = odds (payout ratio)
    """
    if direction == "yes":
        win_prob = probability
        price = market_price
    else:
        win_prob = 1 - probability
        price = 1 - market_price

    # Avoid division by zero
    if price <= 0 or price >= 1:
        return 0

    # Odds: if you pay $0.30 and win $1.00, odds are (1-0.30)/0.30 = 2.33
    odds = (1 - price) / price

    # Kelly fraction
    lose_prob = 1 - win_prob
    kelly = (win_prob * odds - lose_prob) / odds

    # Apply fractional Kelly (quarter Kelly for safety)
    kelly *= settings.KELLY_FRACTION

    # Cap at maximum per-trade limit
    max_fraction = 0.05  # 5% max per trade
    kelly = min(kelly, max_fraction)

    # Don't bet negative
    kelly = max(kelly, 0)

    return kelly * bankroll


async def generate_signal(
    market: MarketData,
    weather: WeatherPrediction
) -> Optional[TradingSignal]:
    """
    Generate a trading signal for a weather market.

    Combines market price with weather prediction to find edge.
    """
    if not market.threshold:
        # Can't calculate probability without knowing the threshold
        return None

    # Calculate model probability
    # Most weather markets ask: "Will high temp exceed X?"
    if market.direction == "above" or market.direction is None:
        model_prob = weather.prob_above(market.threshold)
    else:
        model_prob = weather.prob_below(market.threshold)

    # Market implied probability
    market_prob = market.yes_price

    # Calculate edge and optimal direction
    edge, direction = calculate_edge(model_prob, market_prob)

    # Get confidence from ensemble
    confidence = weather.confidence()

    # Adjust edge threshold based on confidence
    effective_threshold = settings.MIN_EDGE_THRESHOLD
    if confidence < 0.5:
        effective_threshold *= 1.5  # Require more edge if less confident

    # Calculate Kelly sizing
    bankroll = settings.INITIAL_BANKROLL  # Would come from DB in production
    suggested_size = calculate_kelly_size(
        edge=abs(edge),
        probability=model_prob,
        market_price=market.yes_price,
        direction=direction,
        bankroll=bankroll
    )

    # Build reasoning
    sources = [weather.source]
    reasoning = (
        f"Model: {model_prob:.1%} (from {len(weather.ensemble_highs)} ensemble members), "
        f"Market: {market_prob:.1%}, "
        f"Edge: {edge:+.1%}, "
        f"Threshold: {market.threshold}°F"
    )

    return TradingSignal(
        market=market,
        weather=weather,
        model_probability=model_prob,
        market_probability=market_prob,
        edge=edge,
        direction=direction,
        confidence=confidence,
        kelly_fraction=suggested_size / bankroll if bankroll > 0 else 0,
        suggested_size=suggested_size,
        sources=sources,
        reasoning=reasoning
    )


async def scan_for_signals() -> List[TradingSignal]:
    """
    Scan all markets and generate signals.

    This is the main bot loop function.
    """
    signals = []

    # Fetch markets and weather data concurrently
    markets_task = fetch_all_weather_markets()
    weather_cache: Dict[str, WeatherPrediction] = {}

    markets = await markets_task

    # Group markets by city
    city_markets: Dict[str, List[MarketData]] = {}
    for market in markets:
        if market.subcategory:
            if market.subcategory not in city_markets:
                city_markets[market.subcategory] = []
            city_markets[market.subcategory].append(market)

    # Fetch weather for each city
    for city in city_markets.keys():
        weather = await fetch_weather_prediction(city)
        if weather:
            weather_cache[city] = weather

    # Generate signals for each market
    for market in markets:
        if not market.subcategory or market.subcategory not in weather_cache:
            continue

        weather = weather_cache[market.subcategory]
        signal = await generate_signal(market, weather)

        if signal:
            signals.append(signal)

    # Sort by absolute edge (best opportunities first)
    signals.sort(key=lambda s: abs(s.edge), reverse=True)

    return signals


async def get_actionable_signals() -> List[TradingSignal]:
    """Get only signals that pass the edge threshold."""
    all_signals = await scan_for_signals()
    return [s for s in all_signals if s.passes_threshold]


# Quick test
if __name__ == "__main__":
    async def test():
        print("Scanning for signals...")
        signals = await scan_for_signals()
        print(f"\nFound {len(signals)} total signals")

        actionable = [s for s in signals if s.passes_threshold]
        print(f"Actionable signals (>{settings.MIN_EDGE_THRESHOLD:.0%} edge): {len(actionable)}")

        for signal in actionable[:5]:
            print(f"\n{signal.market.platform.upper()}: {signal.market.title[:50]}...")
            print(f"  Model: {signal.model_probability:.1%} vs Market: {signal.market_probability:.1%}")
            print(f"  Edge: {signal.edge:+.1%} → {signal.direction.upper()}")
            print(f"  Suggested size: ${signal.suggested_size:.2f}")

    asyncio.run(test())
