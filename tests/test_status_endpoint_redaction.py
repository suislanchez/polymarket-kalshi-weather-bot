"""Status endpoints must never leak raw private-account data.

`/api/kalshi/status` must not return the raw balance payload (cents/value), and
`/api/polymarket/relayer/status` must not return the full relayer address. Both
should return summarized/redacted status by default per the weather-only safety
rules.
"""
import asyncio
import json

from backend.api import main
from backend.config import settings


class _FakeKalshiClient:
    def __init__(self, *args, **kwargs):
        pass

    async def get_balance(self):
        # Realistic Kalshi payload shape: integer cents.
        return {"balance": 1234567, "payout": 42}


class _FakeRelayerClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def validate_credentials(self):
        return True


def test_kalshi_status_does_not_leak_raw_balance(monkeypatch):
    monkeypatch.setattr("backend.data.kalshi_client.kalshi_credentials_present", lambda: True)
    monkeypatch.setattr("backend.data.kalshi_client.KalshiClient", _FakeKalshiClient)

    result = asyncio.run(main.get_kalshi_status())
    blob = json.dumps(result)

    assert result["connected"] is True
    # Presence flag is fine; raw value/cents must be gone.
    assert result.get("balance_available") is True
    assert "balance" not in result
    assert "1234567" not in blob
    assert "1234567" not in str(result.get("balance_available"))


def test_relayer_status_redacts_full_address(monkeypatch):
    full_address = "0x1111111111111111111111111111111111111111"
    monkeypatch.setattr(settings, "RELAYER_API_KEY_ADDRESS", full_address)
    monkeypatch.setattr(settings, "RELAYER_API_KEY", "secret-key")
    monkeypatch.setattr("backend.data.polymarket_relayer.relayer_credentials_present", lambda: True)
    monkeypatch.setattr("backend.data.polymarket_relayer.PolymarketRelayerClient", _FakeRelayerClient)

    result = asyncio.run(main.get_polymarket_relayer_status())
    blob = json.dumps(result)

    assert result["configured"] is True
    assert result["connected"] is True
    assert result.get("address_present") is True
    # The full address must never appear; only a shortened preview is allowed.
    assert "address" not in result
    assert full_address not in blob
    preview = result.get("address_preview")
    assert preview is not None
    assert preview != full_address
    assert full_address[:6] in preview  # short prefix is acceptable


def test_relayer_status_not_configured_is_safe(monkeypatch):
    monkeypatch.setattr("backend.data.polymarket_relayer.relayer_credentials_present", lambda: False)

    result = asyncio.run(main.get_polymarket_relayer_status())

    assert result["configured"] is False
    assert result["connected"] is False
    assert "address" not in result
