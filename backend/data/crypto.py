"""Crypto price data fetcher using CoinGecko API."""
import httpx
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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
