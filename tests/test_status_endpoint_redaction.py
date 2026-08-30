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
    # Distinctive so a preview sourced from the wrong secret is visible.
    api_key_sentinel = "RELAYERKEYSENTINEL-MUST-NOT-BE-PUBLISHED"
    monkeypatch.setattr(settings, "RELAYER_API_KEY_ADDRESS", full_address)
    monkeypatch.setattr(settings, "RELAYER_API_KEY", api_key_sentinel)
    monkeypatch.setattr("backend.data.polymarket_relayer.relayer_credentials_present", lambda: True)
    monkeypatch.setattr("backend.data.polymarket_relayer.PolymarketRelayerClient", _FakeRelayerClient)

    result = asyncio.run(main.get_polymarket_relayer_status())
    blob = json.dumps(result)

    assert result["configured"] is True
    assert result["connected"] is True
    assert result.get("address_present") is True

    # The full address must never appear, in any field.
    assert full_address not in blob
    assert full_address not in result.values()

    # Two independent properties, because dropping the old assertion dropped
    # both at once.
    #
    # It read `full_address[:6] in preview`, which required the disclosure it
    # exists to limit -- any future tightening of _redact_address would have
    # failed here and looked like a regression. But it was also the only thing
    # binding the preview to the address, and removing it alone let the preview
    # become a DIFFERENT secret published whole: a _redact_address returning
    # settings.RELAYER_API_KEY passed this test.
    #
    # So: an upper bound on how much may be published, and a sentinel on the
    # credential that must never be its source. Neither is a floor; a preview
    # reduced to a boolean still passes both.
    preview = result.get("address_preview")
    assert preview is not None
    assert preview != full_address
    assert len(preview) <= 12
    assert api_key_sentinel not in blob
    assert api_key_sentinel[:6] not in blob


def test_relayer_status_not_configured_is_safe(monkeypatch):
    monkeypatch.setattr("backend.data.polymarket_relayer.relayer_credentials_present", lambda: False)

    result = asyncio.run(main.get_polymarket_relayer_status())

    assert result["configured"] is False
    assert result["connected"] is False
    assert "address" not in result


def test_kalshi_status_does_not_leak_the_private_key_path(monkeypatch):
    """The failure path must not echo the exception message.

    A missing or unreadable key raises with the private key's absolute path in
    its message, and this route is unauthenticated, so returning str(e) published
    that path to anyone who asked. Reproduced before the fix; this pins it.
    """
    key_path = "/Volumes/Archives/SECRETS/kalshi_private_key.pem"

    class _ExplodingKalshiClient:
        def __init__(self, *args, **kwargs):
            raise FileNotFoundError(
                f"[Errno 2] No such file or directory: '{key_path}'"
            )

    monkeypatch.setattr("backend.data.kalshi_client.kalshi_credentials_present", lambda: True)
    monkeypatch.setattr("backend.data.kalshi_client.KalshiClient", _ExplodingKalshiClient)

    result = asyncio.run(main.get_kalshi_status())
    blob = json.dumps(result)

    assert result["connected"] is False
    assert key_path not in blob
    # No fragment either: a truncated path still names the directory.
    assert "SECRETS" not in blob
    assert "kalshi_private_key" not in blob
    # The exception type is enough for an operator, and carries no operand.
    assert result["error_type"] == "FileNotFoundError"
    assert "error" not in result
