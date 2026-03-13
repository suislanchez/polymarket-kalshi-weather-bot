"""Polymarket CLOB API client for real order placement.

Authentication flow:
  Level 1 (L1): private key + chain_id — used to sign orders and derive API keys
  Level 2 (L2): L1 + API credentials (key/secret/passphrase) — used to POST orders

Setup:
  1. Set POLYMARKET_PRIVATE_KEY (hex, no 0x prefix needed) to your MetaMask private key
  2. Set POLYMARKET_FUNDER_ADDRESS to your wallet's Polygon address
  3. On first run, API credentials are derived automatically and logged — copy them to .env

Required: pip install py-clob-client
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger("trading_bot")

# Module-level singleton (initialized lazily)
_clob_client = None


def _init_clob_client():
    """Initialize CLOB client synchronously (called once on first use)."""
    global _clob_client
    if _clob_client is not None:
        return _clob_client

    from backend.config import settings

    if not settings.POLYMARKET_PRIVATE_KEY:
        raise ValueError(
            "POLYMARKET_PRIVATE_KEY not set. Add your MetaMask private key to .env"
        )
    if not settings.POLYMARKET_FUNDER_ADDRESS:
        raise ValueError(
            "POLYMARKET_FUNDER_ADDRESS not set. Add your Polygon wallet address to .env"
        )

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds
    except ImportError:
        raise ImportError(
            "py-clob-client not installed. Run: pip install py-clob-client"
        )

    client = ClobClient(
        host="https://clob.polymarket.com",
        key=settings.POLYMARKET_PRIVATE_KEY,
        chain_id=137,  # Polygon mainnet
        signature_type=0,  # Standard EOA — MetaMask / hardware wallet
        funder=settings.POLYMARKET_FUNDER_ADDRESS,
    )

    # Use existing credentials if provided, otherwise derive from private key
    if (
        settings.POLYMARKET_API_KEY
        and settings.POLYMARKET_API_SECRET
        and settings.POLYMARKET_API_PASSPHRASE
    ):
        creds = ApiCreds(
            api_key=settings.POLYMARKET_API_KEY,
            api_secret=settings.POLYMARKET_API_SECRET,
            api_passphrase=settings.POLYMARKET_API_PASSPHRASE,
        )
        client.set_api_creds(creds)
        logger.info(
            f"Polymarket CLOB: using stored API key {settings.POLYMARKET_API_KEY[:8]}..."
        )
    else:
        logger.info("Polymarket CLOB: deriving API credentials from private key...")
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        logger.info(
            f"Polymarket CLOB: derived credentials. "
            f"Add to .env to avoid re-derivation:\n"
            f"  POLYMARKET_API_KEY={creds.api_key}\n"
            f"  POLYMARKET_API_SECRET={creds.api_secret}\n"
            f"  POLYMARKET_API_PASSPHRASE={creds.api_passphrase}"
        )

    _clob_client = client
    return _clob_client


def polymarket_credentials_present() -> bool:
    """True if trading credentials are configured."""
    from backend.config import settings
    return bool(
        settings.POLYMARKET_PRIVATE_KEY and settings.POLYMARKET_FUNDER_ADDRESS
    )


async def get_usdc_balance() -> float:
    """Return current USDC balance available for trading on Polymarket."""
    loop = asyncio.get_event_loop()
    client = _init_clob_client()

    def _fetch():
        return float(client.get_balance())

    return await loop.run_in_executor(None, _fetch)


async def place_limit_order(
    token_id: str,
    price: float,
    size_usd: float,
    side: str = "buy",
    neg_risk: bool = False,
) -> dict:
    """Place a GTC limit order on the Polymarket CLOB.

    Args:
        token_id: Outcome token ID (YES or NO token from clobTokenIds)
        price:    Limit price in USDC, e.g. 0.62 for 62¢
        size_usd: Dollar amount to spend (converted to shares internally)
        side:     "buy" or "sell"
        neg_risk: True for neg-risk multi-outcome markets (rare for weather)

    Returns:
        dict with "orderID", "status", "takingAmount", "makingAmount", etc.
    """
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL
    except ImportError:
        raise ImportError("py-clob-client not installed. Run: pip install py-clob-client")

    # Clamp price to valid range and align to tick size (0.01)
    price = round(max(0.01, min(0.99, price)), 2)

    # Convert dollar amount to shares: spend $size_usd at $price/share
    shares = round(size_usd / price, 2)
    if shares < 1.0:
        raise ValueError(
            f"Order too small: ${size_usd:.2f} at {price:.2f} = {shares:.2f} shares (min 1)"
        )

    order_args = OrderArgs(
        token_id=token_id,
        price=price,
        size=shares,
        side=BUY if side == "buy" else SELL,
    )

    loop = asyncio.get_event_loop()
    client = _init_clob_client()

    def _create_and_post():
        signed = client.create_order(
            order_args,
            options={"neg_risk": neg_risk},
        )
        return client.post_order(signed, OrderType.GTC)

    response = await loop.run_in_executor(None, _create_and_post)
    return response if isinstance(response, dict) else {}


async def cancel_order(order_id: str) -> dict:
    """Cancel an open order by its ID."""
    loop = asyncio.get_event_loop()
    client = _init_clob_client()

    def _cancel():
        return client.cancel(order_id)

    return await loop.run_in_executor(None, _cancel)


async def get_open_orders(market_id: Optional[str] = None) -> list:
    """Return list of open orders, optionally filtered by market token_id."""
    loop = asyncio.get_event_loop()
    client = _init_clob_client()

    def _fetch():
        try:
            from py_clob_client.clob_types import OpenOrderParams
            params = OpenOrderParams(market=market_id) if market_id else OpenOrderParams()
            return client.get_orders(params)
        except Exception:
            return client.get_orders()

    result = await loop.run_in_executor(None, _fetch)
    return result if isinstance(result, list) else []
