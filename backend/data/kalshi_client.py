"""Kalshi API client with RSA-PSS signature authentication."""
import asyncio
import base64
import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization

# Kalshi rate-limits per key. Callers of this client catch their own exceptions
# and carry on, so an un-retried 429 does not fail a run -- it silently removes
# whatever that request was fetching. Retrying here protects every caller.
#
# Bounded, because retrying forever would hang a request instead of degrading
# it, and the dashboard is already the slowest thing in the app.
RATE_LIMIT_MAX_ATTEMPTS = 4
RATE_LIMIT_BACKOFF_SECONDS = 0.5
from cryptography.hazmat.primitives.asymmetric import padding

from backend.config import settings

logger = logging.getLogger("trading_bot")

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiClient:
    """Async Kalshi API client.

    Public market-data endpoints such as ``/markets`` and
    ``/markets/{ticker}/orderbook`` can be queried without credentials.  Keep
    signing optional so simulation-only weather research can refresh public
    orderbooks without touching portfolio/trading credentials.
    """

    def __init__(self):
        self._private_key = None

    def _load_private_key(self):
        """Load RSA private key from file (lazy, cached)."""
        if self._private_key is not None:
            return self._private_key

        key_path = settings.KALSHI_PRIVATE_KEY_PATH
        if not key_path:
            raise ValueError("KALSHI_PRIVATE_KEY_PATH not configured")

        pem_data = Path(key_path).expanduser().read_bytes()
        self._private_key = serialization.load_pem_private_key(pem_data, password=None)
        return self._private_key

    def _sign_request(self, method: str, path: str) -> Dict[str, str]:
        """
        Generate auth headers for a Kalshi API request.

        Signature = RSA-PSS-sign(timestamp_ms + METHOD + path)
        where path = /trade-api/v2/... (no query params).
        """
        timestamp_ms = str(int(time.time() * 1000))
        message = f"{timestamp_ms}{method.upper()}{path}"

        private_key = self._load_private_key()
        signature = private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        return {
            "KALSHI-ACCESS-KEY": settings.KALSHI_API_KEY_ID,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "Content-Type": "application/json",
        }

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> dict:
        """
        Authenticated GET request to Kalshi API.

        Args:
            path: API path after /trade-api/v2 (e.g., "/markets")
            params: Query parameters (not included in signature)
        """
        full_path = f"/trade-api/v2{path}"
        url = f"{BASE_URL}{path}"
        headers = {"Content-Type": "application/json"}
        if kalshi_credentials_present():
            headers = self._sign_request("GET", full_path)

        for attempt in range(1, RATE_LIMIT_MAX_ATTEMPTS + 1):
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=headers, params=params)
                if (
                    response.status_code == 429
                    and attempt < RATE_LIMIT_MAX_ATTEMPTS
                ):
                    # Exponential, and honouring Retry-After when the server
                    # bothers to send one.
                    delay = RATE_LIMIT_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after))
                        except (TypeError, ValueError):
                            pass
                    logger.debug(
                        f"Kalshi rate limited on {path}; retrying in {delay}s "
                        f"(attempt {attempt}/{RATE_LIMIT_MAX_ATTEMPTS})"
                    )
                    await asyncio.sleep(delay)
                    continue
                # Every other status, and the final 429, raise as before.
                response.raise_for_status()
                return response.json()

    async def get_markets(self, params: Optional[Dict[str, Any]] = None) -> dict:
        """Fetch markets with optional filters."""
        return await self.get("/markets", params=params)

    async def get_market(self, ticker: str) -> dict:
        """Fetch a single market by ticker."""
        return await self.get(f"/markets/{ticker}")

    async def get_orderbook(self, ticker: str) -> dict:
        """Fetch a market orderbook by ticker."""
        return await self.get(f"/markets/{ticker}/orderbook")

    async def get_balance(self) -> dict:
        """Get portfolio balance (useful for auth test)."""
        return await self.get("/portfolio/balance")


def kalshi_credentials_present() -> bool:
    """Check if Kalshi API credentials are configured."""
    return bool(settings.KALSHI_API_KEY_ID and settings.KALSHI_PRIVATE_KEY_PATH)
