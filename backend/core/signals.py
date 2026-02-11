"""Signal generator - calculates edges and generates trading signals."""
import logging
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass, field
import asyncio

from backend.config import settings
from backend.data.weather import WeatherPrediction, fetch_weather_prediction
from backend.data.markets import MarketData, fetch_all_weather_markets, fetch_all_markets

logger = logging.getLogger("trading_bot")

# Track AI usage for this scan
_ai_calls_this_scan = 0
_max_ai_calls_per_scan = 5  # Limit AI calls to control costs


@dataclass
class TradingSignal:
    """A trading signal with all relevant data."""
    market: MarketData
    weather: Optional[WeatherPrediction] = None

    # Core signal data
    model_probability: float = 0.5  # Our calculated probability
    market_probability: float = 0.5  # Implied by market price
    edge: float = 0.0  # Difference
    direction: str = "yes"  # "yes" or "no"

    # Confidence and sizing
    confidence: float = 0.5
    kelly_fraction: float = 0.0
    suggested_size: float = 0.0

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


async def generate_price_signal(market: MarketData, use_ai: bool = False) -> Optional[TradingSignal]:
    """
    Generate a trading signal for non-weather markets based on price analysis.

    Uses contrarian logic: extreme prices often revert.
    - Markets at < 0.15 or > 0.85 are considered extreme
    - We bet against the crowd with a small edge assumption
    """
    global _ai_calls_this_scan

    yes_price = market.yes_price

    # Skip markets at very extreme prices (likely to resolve soon)
    if yes_price < 0.03 or yes_price > 0.97:
        return None

    # Skip markets with middle prices (no clear signal)
    if 0.30 <= yes_price <= 0.70:
        return None

    # Contrarian signal: bet against extreme prices
    # If market says 85% YES, we estimate maybe 75% (10% edge for NO)
    # If market says 15% YES, we estimate maybe 25% (10% edge for YES)

    if yes_price > 0.70:
        # Market is very confident YES - contrarian NO bet
        model_prob = yes_price - 0.10  # Our estimate is lower
        direction = "no"
        edge = (1 - model_prob) - (1 - yes_price)  # NO edge
    elif yes_price < 0.30:
        # Market is very confident NO - contrarian YES bet
        model_prob = yes_price + 0.10  # Our estimate is higher
        direction = "yes"
        edge = model_prob - yes_price  # YES edge
    else:
        return None

    # Confidence based on how extreme the price is
    extremeness = abs(yes_price - 0.5) * 2  # 0 at 0.5, 1 at 0 or 1
    confidence = 0.4 + (extremeness * 0.3)  # 0.4 to 0.7

    # Optional: Use Groq for quick analysis on best signals
    ai_reasoning = None
    if use_ai and _ai_calls_this_scan < _max_ai_calls_per_scan and settings.GROQ_API_KEY:
        try:
            from backend.ai.groq import GroqClassifier
            groq = GroqClassifier()
            analysis = await groq.analyze_signal({
                'market_title': market.title,
                'market_ticker': market.ticker,
                'direction': direction,
                'edge': edge,
                'yes_price': yes_price
            })
            if analysis:
                ai_reasoning = analysis.reasoning
                confidence = max(confidence, analysis.confidence)
                _ai_calls_this_scan += 1
                logger.info(f"Groq analysis for {market.ticker}: {ai_reasoning[:50]}...")
        except Exception as e:
            logger.debug(f"Groq analysis skipped: {e}")

    # Kelly sizing
    bankroll = settings.INITIAL_BANKROLL
    suggested_size = calculate_kelly_size(
        edge=abs(edge),
        probability=model_prob,
        market_price=yes_price,
        direction=direction,
        bankroll=bankroll
    )

    # Build reasoning
    reasoning = (
        f"Price signal: Market at {yes_price:.0%} {direction.upper()}, "
        f"contrarian estimate {model_prob:.0%}, "
        f"Edge: {edge:+.1%}"
    )
    if ai_reasoning:
        reasoning += f" | AI: {ai_reasoning[:100]}"

    return TradingSignal(
        market=market,
        weather=None,
        model_probability=model_prob,
        market_probability=yes_price,
        edge=edge,
        direction=direction,
        confidence=confidence,
        kelly_fraction=suggested_size / bankroll if bankroll > 0 else 0,
        suggested_size=suggested_size,
        sources=["price_analysis"] + (["groq"] if ai_reasoning else []),
        reasoning=reasoning
    )


async def scan_for_signals() -> List[TradingSignal]:
    """
    Scan all markets and generate signals.

    This is the main bot loop function.
    """
    signals = []

    logger.info("=" * 50)
    logger.info("Fetching ALL markets from Polymarket...")

    # Fetch ALL markets (not just weather)
    try:
        markets = await fetch_all_markets(exclude_sports=True)
    except Exception as e:
        logger.error(f"Failed to fetch markets: {e}")
        markets = []

    logger.info(f"Found {len(markets)} total markets")

    # Group by category
    by_category: Dict[str, List[MarketData]] = {}
    for market in markets:
        cat = market.category or "other"
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(market)

    for cat, cat_markets in by_category.items():
        logger.info(f"  {cat.upper()}: {len(cat_markets)} markets")

    # Weather markets - use weather data for signals
    weather_cache: Dict[str, WeatherPrediction] = {}
    weather_markets = by_category.get("weather", [])

    if weather_markets:
        # Get unique cities
        cities = set(m.subcategory for m in weather_markets if m.subcategory)
        logger.info(f"Fetching weather for {len(cities)} cities...")

        for city in cities:
            try:
                weather = await fetch_weather_prediction(city)
                if weather:
                    weather_cache[city] = weather
                await asyncio.sleep(0.3)  # Rate limit
            except Exception as e:
                logger.warning(f"Weather fetch failed for {city}: {e}")

        # Generate weather signals
        for market in weather_markets:
            if market.subcategory and market.subcategory in weather_cache:
                weather = weather_cache[market.subcategory]
                signal = await generate_signal(market, weather)
                if signal:
                    signals.append(signal)

    # Non-weather markets - use price-based signals
    non_weather_markets = [m for m in markets if m.category != "weather"]
    logger.info(f"Analyzing {len(non_weather_markets)} non-weather markets for price signals...")

    # Reset AI call counter for this scan
    global _ai_calls_this_scan
    _ai_calls_this_scan = 0

    # Sort by price extremeness to prioritize best opportunities for AI analysis
    non_weather_markets.sort(key=lambda m: abs(m.yes_price - 0.5), reverse=True)

    for i, market in enumerate(non_weather_markets):
        try:
            # Use AI for top 5 most extreme-priced markets
            use_ai = i < 5
            signal = await generate_price_signal(market, use_ai=use_ai)
            if signal:
                signals.append(signal)
        except Exception as e:
            logger.debug(f"Signal generation failed for {market.ticker}: {e}")

    # Sort by absolute edge (best opportunities first)
    signals.sort(key=lambda s: abs(s.edge), reverse=True)

    # Log actionable signals
    actionable = [s for s in signals if s.passes_threshold]
    logger.info(f"=" * 50)
    logger.info(f"SCAN COMPLETE: {len(signals)} signals, {len(actionable)} actionable")

    for signal in actionable[:10]:
        logger.info(f"  [{signal.market.category.upper()}] {signal.market.title[:40]}...")
        logger.info(f"    Edge: {signal.edge:+.1%} -> {signal.direction.upper()} @ ${signal.suggested_size:.2f}")

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
