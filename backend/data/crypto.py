"""Crypto price data fetcher using CoinGecko + Binance APIs."""
import httpx
import logging
import math
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Binance 1-min kline fetcher + technical indicators for BTC 5-min trading
# ---------------------------------------------------------------------------

BINANCE_API = "https://api.binance.com/api/v3"
BYBIT_API = "https://api.bybit.com/v5/market"
COINBASE_API = "https://api.exchange.coinbase.com"
KRAKEN_API = "https://api.kraken.com/0/public"

# 30-second cache to avoid hammering Binance during a single scan cycle
_kline_cache: Dict[str, Any] = {"data": None, "ts": 0.0}
_CACHE_TTL = 30.0


@dataclass
class BtcMicrostructure:
    """Real-time BTC technical indicators computed from 1-min candles."""
    # RSI (14-period Wilder smoothing)
    rsi: float = 50.0
    # Momentum: % change over various lookbacks
    momentum_1m: float = 0.0
    momentum_5m: float = 0.0
    momentum_15m: float = 0.0
    # VWAP deviation (positive = price above VWAP)
    vwap: float = 0.0
    vwap_deviation: float = 0.0
    # SMA crossover: sma5 - sma15 as fraction of price
    sma_crossover: float = 0.0
    # Volatility: stdev of 1-min returns
    volatility: float = 0.0
    # Current price
    price: float = 0.0
    # Source exchange
    source: str = "binance"


async def fetch_binance_klines(limit: int = 60) -> Optional[List[list]]:
    """
    Fetch recent 1-minute BTCUSDT candles from Binance.
    Falls back to Bybit if Binance fails (US geo-blocking).

    Returns list of [open_time, open, high, low, close, volume, ...] or None.
    """
    now = time.time()
    if _kline_cache["data"] is not None and (now - _kline_cache["ts"]) < _CACHE_TTL:
        return _kline_cache["data"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Try Binance first
        try:
            resp = await client.get(
                f"{BINANCE_API}/klines",
                params={"symbol": "BTCUSDT", "interval": "1m", "limit": limit},
            )
            resp.raise_for_status()
            candles = resp.json()
            _kline_cache["data"] = candles
            _kline_cache["ts"] = now
            _kline_cache["_source"] = "binance"
            return candles
        except Exception as e:
            logger.warning(f"Binance kline fetch failed, trying Bybit: {e}")

        # Fallback 1: Bybit
        try:
            resp = await client.get(
                f"{BYBIT_API}/kline",
                params={
                    "category": "spot",
                    "symbol": "BTCUSDT",
                    "interval": "1",
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("result", {}).get("list", [])
            rows = list(reversed(rows))
            candles = [
                [int(r[0]), r[1], r[2], r[3], r[4], r[5]]
                for r in rows
            ]
            _kline_cache["data"] = candles
            _kline_cache["ts"] = now
            _kline_cache["_source"] = "bybit"
            return candles
        except Exception as e:
            logger.warning(f"Bybit kline fetch failed, trying Coinbase: {e}")

        # Fallback 2: Coinbase (US-accessible, free)
        try:
            # Coinbase uses ISO time and granularity in seconds
            import datetime as _dt
            end = _dt.datetime.now(_dt.timezone.utc)
            start = end - _dt.timedelta(minutes=limit)
            resp = await client.get(
                f"{COINBASE_API}/products/BTC-USD/candles",
                params={
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "granularity": 60,  # 1-minute candles
                },
            )
            resp.raise_for_status()
            rows = resp.json()
            # Coinbase returns [time, low, high, open, close, volume] newest-first
            rows = list(reversed(rows))
            candles = [
                [int(r[0]) * 1000, str(r[3]), str(r[2]), str(r[1]), str(r[4]), str(r[5])]
                for r in rows
            ]
            _kline_cache["data"] = candles
            _kline_cache["ts"] = now
            _kline_cache["_source"] = "coinbase"
            return candles
        except Exception as e:
            logger.warning(f"Coinbase kline fetch failed, trying Kraken: {e}")

        # Fallback 3: Kraken (US-accessible, free)
        try:
            resp = await client.get(
                f"{KRAKEN_API}/OHLC",
                params={"pair": "XBTUSD", "interval": 1},
            )
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", {})
            # Kraken key is usually XXBTZUSD
            ohlc_key = [k for k in result if k != "last"]
            if ohlc_key:
                rows = result[ohlc_key[0]]
                # Kraken: [time, open, high, low, close, vwap, volume, count]
                # Take last `limit` candles
                rows = rows[-limit:]
                candles = [
                    [int(r[0]) * 1000, str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[6])]
                    for r in rows
                ]
                _kline_cache["data"] = candles
                _kline_cache["ts"] = now
                _kline_cache["_source"] = "kraken"
                return candles
        except Exception as e:
            logger.error(f"All kline sources failed (Binance/Bybit/Coinbase/Kraken): {e}")

        return None


def _compute_rsi(closes: List[float], period: int = 14) -> float:
    """Compute RSI using Wilder smoothing."""
    if len(closes) < period + 1:
        return 50.0

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [d if d > 0 else 0.0 for d in deltas[:period]]
    losses = [-d if d < 0 else 0.0 for d in deltas[:period]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for d in deltas[period:]:
        gain = d if d > 0 else 0.0
        loss = -d if d < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


async def compute_btc_microstructure() -> Optional[BtcMicrostructure]:
    """
    Fetch 60 one-minute candles and compute all technical indicators.
    Returns BtcMicrostructure or None on failure.
    """
    candles = await fetch_binance_klines(limit=60)
    if not candles or len(candles) < 20:
        logger.warning("Not enough candle data for microstructure")
        return None

    closes = [float(c[4]) for c in candles]
    volumes = [float(c[5]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]

    current_price = closes[-1]

    # RSI (14-period)
    rsi = _compute_rsi(closes, 14)

    # Momentum: % change over lookback periods
    def pct_change(lookback: int) -> float:
        if len(closes) > lookback and closes[-1 - lookback] > 0:
            return (closes[-1] - closes[-1 - lookback]) / closes[-1 - lookback] * 100
        return 0.0

    momentum_1m = pct_change(1)
    momentum_5m = pct_change(5)
    momentum_15m = pct_change(15)

    # VWAP (30-candle window)
    vwap_window = min(30, len(closes))
    typical_prices = [(highs[-i] + lows[-i] + closes[-i]) / 3 for i in range(1, vwap_window + 1)]
    vwap_volumes = [volumes[-i] for i in range(1, vwap_window + 1)]
    total_vol = sum(vwap_volumes)
    if total_vol > 0:
        vwap = sum(tp * v for tp, v in zip(typical_prices, vwap_volumes)) / total_vol
    else:
        vwap = current_price
    vwap_deviation = (current_price - vwap) / vwap * 100 if vwap > 0 else 0.0

    # SMA crossover: 5-period vs 15-period
    sma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else current_price
    sma15 = sum(closes[-15:]) / 15 if len(closes) >= 15 else current_price
    sma_crossover = (sma5 - sma15) / current_price * 100 if current_price > 0 else 0.0

    # Volatility: stdev of 1-min returns (last 30 candles)
    vol_window = min(30, len(closes) - 1)
    returns = [
        (closes[-i] - closes[-i - 1]) / closes[-i - 1]
        for i in range(1, vol_window + 1)
        if closes[-i - 1] > 0
    ]
    if returns:
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        volatility = math.sqrt(variance) * 100  # as percentage
    else:
        volatility = 0.0

    source = _kline_cache.get("_source", "unknown")

    return BtcMicrostructure(
        rsi=rsi,
        momentum_1m=momentum_1m,
        momentum_5m=momentum_5m,
        momentum_15m=momentum_15m,
        vwap=vwap,
        vwap_deviation=vwap_deviation,
        sma_crossover=sma_crossover,
        volatility=volatility,
        price=current_price,
        source=source,
    )

# CoinGecko API (free tier, no key needed)
COINGECKO_API = "https://api.coingecko.com/api/v3"


@dataclass
class CryptoPrice:
    """Current crypto price data."""
    symbol: str  # BTC, ETH, etc.
    name: str
    current_price: float
    price_24h_ago: float
    change_24h: float  # Percentage
    change_7d: float
    market_cap: float
    volume_24h: float
    last_updated: datetime


# Map common symbols to CoinGecko IDs
SYMBOL_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
}


async def fetch_crypto_price(symbol: str) -> Optional[CryptoPrice]:
    """
    Fetch current price data for a cryptocurrency.

    Args:
        symbol: Crypto symbol (BTC, ETH, etc.)

    Returns:
        CryptoPrice or None if not found
    """
    symbol_upper = symbol.upper()
    coin_id = SYMBOL_TO_ID.get(symbol_upper, symbol.lower())

    url = f"{COINGECKO_API}/coins/{coin_id}"
    params = {
        "localization": "false",
        "tickers": "false",
        "market_data": "true",
        "community_data": "false",
        "developer_data": "false"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            market_data = data.get("market_data", {})
            current_price = market_data.get("current_price", {}).get("usd", 0)
            change_24h = market_data.get("price_change_percentage_24h", 0)
            change_7d = market_data.get("price_change_percentage_7d", 0)

            # Calculate price 24h ago
            price_24h_ago = current_price / (1 + change_24h / 100) if change_24h else current_price

            return CryptoPrice(
                symbol=symbol_upper,
                name=data.get("name", symbol_upper),
                current_price=current_price,
                price_24h_ago=price_24h_ago,
                change_24h=change_24h or 0,
                change_7d=change_7d or 0,
                market_cap=market_data.get("market_cap", {}).get("usd", 0),
                volume_24h=market_data.get("total_volume", {}).get("usd", 0),
                last_updated=datetime.utcnow()
            )

        except httpx.HTTPStatusError as e:
            logger.warning(f"CoinGecko API error for {symbol}: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error fetching crypto price for {symbol}: {e}")
            return None


async def fetch_multiple_prices(symbols: List[str]) -> Dict[str, CryptoPrice]:
    """
    Fetch prices for multiple cryptocurrencies efficiently.

    Uses CoinGecko's markets endpoint for batch fetching.
    """
    # Map symbols to CoinGecko IDs
    coin_ids = [SYMBOL_TO_ID.get(s.upper(), s.lower()) for s in symbols]

    url = f"{COINGECKO_API}/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": ",".join(coin_ids),
        "order": "market_cap_desc",
        "sparkline": "false",
        "price_change_percentage": "24h,7d"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            data = response.json()

            results = {}
            for coin in data:
                symbol = coin.get("symbol", "").upper()
                current_price = coin.get("current_price", 0)
                change_24h = coin.get("price_change_percentage_24h", 0) or 0
                change_7d = coin.get("price_change_percentage_7d_in_currency", 0) or 0

                price_24h_ago = current_price / (1 + change_24h / 100) if change_24h else current_price

                results[symbol] = CryptoPrice(
                    symbol=symbol,
                    name=coin.get("name", symbol),
                    current_price=current_price,
                    price_24h_ago=price_24h_ago,
                    change_24h=change_24h,
                    change_7d=change_7d,
                    market_cap=coin.get("market_cap", 0) or 0,
                    volume_24h=coin.get("total_volume", 0) or 0,
                    last_updated=datetime.utcnow()
                )

            return results

        except Exception as e:
            logger.error(f"Error fetching multiple crypto prices: {e}")
            return {}


def estimate_price_probability(
    current_price: float,
    threshold: float,
    direction: str,
    volatility_24h: float = 0.05
) -> float:
    """
    Estimate probability of price hitting threshold.

    Simple model based on current distance and volatility.
    In production, you'd use options pricing or ML models.

    Args:
        current_price: Current asset price
        threshold: Target price threshold
        direction: "above" or "below"
        volatility_24h: Estimated daily volatility (default 5%)

    Returns:
        Probability estimate 0-1
    """
    if current_price <= 0:
        return 0.5

    # Calculate distance as percentage
    distance = (threshold - current_price) / current_price

    # Simple probability based on normal distribution
    # This is a rough approximation - real models are more complex
    import math

    # Standard deviations away
    std_devs = abs(distance) / volatility_24h

    if direction == "above":
        if current_price >= threshold:
            return 0.95  # Already above
        # Probability of going up by distance
        prob = 0.5 * (1 - math.erf(std_devs / math.sqrt(2)))
    else:  # below
        if current_price <= threshold:
            return 0.95  # Already below
        # Probability of going down by distance
        prob = 0.5 * (1 - math.erf(std_devs / math.sqrt(2)))

    return max(0.05, min(0.95, prob))


# Quick test
if __name__ == "__main__":
    import asyncio

    async def test():
        print("Fetching BTC price...")
        btc = await fetch_crypto_price("BTC")
        if btc:
            print(f"  {btc.name}: ${btc.current_price:,.2f}")
            print(f"  24h change: {btc.change_24h:+.2f}%")
            print(f"  Market cap: ${btc.market_cap:,.0f}")

        print("\nFetching multiple prices...")
        prices = await fetch_multiple_prices(["BTC", "ETH", "SOL"])
        for symbol, price in prices.items():
            print(f"  {symbol}: ${price.current_price:,.2f} ({price.change_24h:+.2f}%)")

    asyncio.run(test())
