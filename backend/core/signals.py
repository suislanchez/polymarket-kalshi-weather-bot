"""Signal generator for BTC 5-minute Up/Down markets."""
import logging
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, field
import asyncio

from backend.config import settings
from backend.data.btc_markets import BtcMarket, fetch_active_btc_markets
from backend.data.crypto import fetch_crypto_price

logger = logging.getLogger("trading_bot")


@dataclass
class TradingSignal:
    """A trading signal for a BTC 5-min market."""
    market: BtcMarket

    # Core signal data
    model_probability: float = 0.5  # Our estimated probability of UP
    market_probability: float = 0.5  # Market's implied UP probability
    edge: float = 0.0
    direction: str = "up"  # "up" or "down"

    # Confidence and sizing
    confidence: float = 0.5
    kelly_fraction: float = 0.0
    suggested_size: float = 0.0

    # Metadata
    sources: List[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # BTC price context
    btc_price: float = 0.0
    btc_change_1h: float = 0.0
    btc_change_24h: float = 0.0

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

    For BTC 5-min markets:
    - "up" is equivalent to "yes" (outcomePrices[0])
    - "down" is equivalent to "no" (outcomePrices[1])

    Returns:
        (edge, direction) where direction is "up" or "down"
    """
    # Edge for UP bet
    up_edge = model_prob - market_price

    # Edge for DOWN bet
    down_edge = (1 - model_prob) - (1 - market_price)

    if up_edge >= down_edge:
        return up_edge, "up"
    else:
        return down_edge, "down"


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
    if direction == "up":
        win_prob = probability
        price = market_price
    else:
        win_prob = 1 - probability
        price = 1 - market_price

    if price <= 0 or price >= 1:
        return 0

    odds = (1 - price) / price

    lose_prob = 1 - win_prob
    kelly = (win_prob * odds - lose_prob) / odds

    # Apply fractional Kelly
    kelly *= settings.KELLY_FRACTION

    # Cap at maximum per-trade limit
    max_fraction = 0.10  # 10% max per trade - aggressive
    kelly = min(kelly, max_fraction)

    kelly = max(kelly, 0)

    return kelly * bankroll


async def generate_btc_signal(market: BtcMarket) -> Optional[TradingSignal]:
    """
    Generate a trading signal for a BTC 5-min Up/Down market.

    AGGRESSIVE strategy:
    - Momentum from 24h price trend
    - Exploit any market price deviation from 50/50
    - Contrarian when market is skewed without strong momentum
    """
    # Fetch BTC price data
    try:
        btc = await fetch_crypto_price("BTC")
    except Exception as e:
        logger.warning(f"Failed to fetch BTC price: {e}")
        return None

    if not btc:
        return None

    market_up_prob = market.up_price

    # Skip only truly resolved markets
    if market_up_prob < 0.02 or market_up_prob > 0.98:
        return None

    change_24h = btc.change_24h

    # --- AGGRESSIVE MOMENTUM MODEL ---
    # Start at 50/50, then layer on biases

    # 1) Momentum bias from recent price action (bigger effect)
    momentum_bias = 0.0
    if abs(change_24h) > 5:
        momentum_bias = 0.08 if change_24h > 0 else -0.08
    elif abs(change_24h) > 3:
        momentum_bias = 0.06 if change_24h > 0 else -0.06
    elif abs(change_24h) > 1.5:
        momentum_bias = 0.04 if change_24h > 0 else -0.04
    elif abs(change_24h) > 0.5:
        momentum_bias = 0.03 if change_24h > 0 else -0.03
    else:
        momentum_bias = 0.01 if change_24h > 0 else -0.01

    # 2) Market mispricing - if market deviates from 50/50, lean contrarian
    #    These 5-min markets should be ~50/50, so any skew is opportunity
    market_skew = market_up_prob - 0.50
    contrarian_bias = -market_skew * 0.5  # Fade the skew

    # 3) Combine biases
    model_up_prob = 0.50 + momentum_bias + contrarian_bias

    # Clamp to wide range (be aggressive)
    model_up_prob = max(0.25, min(0.75, model_up_prob))

    # Calculate edge
    edge, direction = calculate_edge(model_up_prob, market_up_prob)

    # Confidence: higher when momentum is strong or market is skewed
    signal_strength = abs(momentum_bias) + abs(market_skew)
    confidence = min(0.8, 0.4 + signal_strength * 3)

    # Kelly sizing
    bankroll = settings.INITIAL_BANKROLL
    suggested_size = calculate_kelly_size(
        edge=abs(edge),
        probability=model_up_prob,
        market_price=market_up_prob,
        direction=direction,
        bankroll=bankroll
    )

    # Build reasoning
    reasoning = (
        f"BTC ${btc.current_price:,.0f} ({btc.change_24h:+.2f}% 24h) | "
        f"Model UP: {model_up_prob:.0%} vs Market UP: {market_up_prob:.0%} | "
        f"Edge: {edge:+.1%} -> {direction.upper()} | "
        f"Window ends: {market.window_end.strftime('%H:%M UTC')}"
    )

    return TradingSignal(
        market=market,
        model_probability=model_up_prob,
        market_probability=market_up_prob,
        edge=edge,
        direction=direction,
        confidence=confidence,
        kelly_fraction=suggested_size / bankroll if bankroll > 0 else 0,
        suggested_size=suggested_size,
        sources=["coingecko_momentum"],
        reasoning=reasoning,
        btc_price=btc.current_price,
        btc_change_1h=0,  # CoinGecko free doesn't give 1h easily
        btc_change_24h=btc.change_24h,
    )


async def scan_for_signals() -> List[TradingSignal]:
    """
    Scan BTC 5-min markets and generate signals.
    """
    signals = []

    logger.info("=" * 50)
    logger.info("BTC 5-MIN SCAN: Fetching markets from Polymarket...")

    try:
        markets = await fetch_active_btc_markets()
    except Exception as e:
        logger.error(f"Failed to fetch BTC markets: {e}")
        markets = []

    logger.info(f"Found {len(markets)} active BTC 5-min markets")

    for market in markets:
        try:
            signal = await generate_btc_signal(market)
            if signal:
                signals.append(signal)
        except Exception as e:
            logger.debug(f"Signal generation failed for {market.slug}: {e}")

        # Small delay to avoid CoinGecko rate limits
        # (only needed if we're making multiple calls - reuse first result)
        await asyncio.sleep(0.1)

    # Sort by absolute edge (best opportunities first)
    signals.sort(key=lambda s: abs(s.edge), reverse=True)

    actionable = [s for s in signals if s.passes_threshold]
    logger.info(f"=" * 50)
    logger.info(f"SCAN COMPLETE: {len(signals)} signals, {len(actionable)} actionable")

    for signal in actionable[:5]:
        logger.info(f"  {signal.market.slug}")
        logger.info(f"    Edge: {signal.edge:+.1%} -> {signal.direction.upper()} @ ${signal.suggested_size:.2f}")

    return signals


async def get_actionable_signals() -> List[TradingSignal]:
    """Get only signals that pass the edge threshold."""
    all_signals = await scan_for_signals()
    return [s for s in all_signals if s.passes_threshold]


if __name__ == "__main__":
    async def test():
        print("Scanning BTC 5-min markets for signals...")
        signals = await scan_for_signals()
        print(f"\nFound {len(signals)} total signals")

        actionable = [s for s in signals if s.passes_threshold]
        print(f"Actionable signals (>{settings.MIN_EDGE_THRESHOLD:.0%} edge): {len(actionable)}")

        for signal in actionable[:5]:
            print(f"\n{signal.market.slug}")
            print(f"  BTC: ${signal.btc_price:,.0f} ({signal.btc_change_24h:+.2f}%)")
            print(f"  Model UP: {signal.model_probability:.1%} vs Market UP: {signal.market_probability:.1%}")
            print(f"  Edge: {signal.edge:+.1%} -> {signal.direction.upper()}")
            print(f"  Size: ${signal.suggested_size:.2f}")

    asyncio.run(test())
