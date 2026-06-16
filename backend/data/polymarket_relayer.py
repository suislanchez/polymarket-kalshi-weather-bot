"""Polymarket Relayer API helper.

This module intentionally does not auto-submit transactions anywhere in bot flows.
It only provides explicit helpers and a status check path.
"""

from __future__ import annotations

from typing import Optional

import httpx

from backend.config import settings

RELAYER_API = "https://relayer.polymarket.com"


def relayer_credentials_present() -> bool:
    return bool(settings.RELAYER_API_KEY and settings.RELAYER_API_KEY_ADDRESS)


class PolymarketRelayerClient:
    def __init__(self, client: Optional[httpx.AsyncClient] = None, timeout: float = 15.0):
        self._client = client
        self._timeout = timeout
        self._owns_client = False

    async def __aenter__(self) -> "PolymarketRelayerClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.RELAYER_API_KEY:
            headers["x-api-key"] = settings.RELAYER_API_KEY
        if settings.RELAYER_API_KEY_ADDRESS:
            headers["x-api-key-address"] = settings.RELAYER_API_KEY_ADDRESS
        return headers

    async def submit_transaction(self, payload: dict) -> Optional[dict]:
        """Submit a transaction to relayer.

        Explicit call only. Returns None on failure.
        """
        if not relayer_credentials_present():
            return None
        assert self._client is not None
        try:
            response = await self._client.post(
                f"{RELAYER_API}/submit", headers=self._headers(), json=payload
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    async def validate_credentials(self) -> bool:
        """Best-effort credential smoke test.

        Uses a deliberately invalid transaction body so we can verify the relayer
        acknowledges auth headers without executing any trade logic.
        """
        if not relayer_credentials_present():
            return False
        assert self._client is not None

        try:
            response = await self._client.post(
                f"{RELAYER_API}/submit",
                headers=self._headers(),
                json={"_ping": True},
            )
            # Expected outcomes:
            # - 400/422 validation error means request reached relayer with auth
            # - 401/403 means auth failed
            # - 5xx treated as inconclusive/false
            return response.status_code in (200, 400, 422)
        except Exception:
            return False
