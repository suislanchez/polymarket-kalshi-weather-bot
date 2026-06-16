import asyncio

from backend.config import settings
from backend.data.polymarket_relayer import (
    RELAYER_API,
    PolymarketRelayerClient,
    relayer_credentials_present,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def post(self, url, headers=None, json=None):
        self.calls.append((url, headers, json))
        return self.responses.pop(0)


async def _submit_with_fake_client():
    original_key = settings.RELAYER_API_KEY
    original_addr = settings.RELAYER_API_KEY_ADDRESS
    settings.RELAYER_API_KEY = "test-key"
    settings.RELAYER_API_KEY_ADDRESS = "0xabc"
    try:
        fake_client = FakeAsyncClient([FakeResponse({"ok": True})])
        client = PolymarketRelayerClient(client=fake_client)  # type: ignore[arg-type]
        payload = {"tx": "0xdeadbeef"}
        result = await client.submit_transaction(payload)
        return result, fake_client.calls
    finally:
        settings.RELAYER_API_KEY = original_key
        settings.RELAYER_API_KEY_ADDRESS = original_addr


def test_submit_transaction_includes_relayer_headers_and_payload():
    result, calls = asyncio.run(_submit_with_fake_client())

    assert result == {"ok": True}
    assert calls == [
        (
            f"{RELAYER_API}/submit",
            {
                "Content-Type": "application/json",
                "x-api-key": "test-key",
                "x-api-key-address": "0xabc",
            },
            {"tx": "0xdeadbeef"},
        )
    ]


def test_relayer_credentials_present_requires_both_key_and_address():
    original_key = settings.RELAYER_API_KEY
    original_addr = settings.RELAYER_API_KEY_ADDRESS
    try:
        settings.RELAYER_API_KEY = None
        settings.RELAYER_API_KEY_ADDRESS = "0xabc"
        assert relayer_credentials_present() is False

        settings.RELAYER_API_KEY = "test-key"
        settings.RELAYER_API_KEY_ADDRESS = None
        assert relayer_credentials_present() is False

        settings.RELAYER_API_KEY = "test-key"
        settings.RELAYER_API_KEY_ADDRESS = "0xabc"
        assert relayer_credentials_present() is True
    finally:
        settings.RELAYER_API_KEY = original_key
        settings.RELAYER_API_KEY_ADDRESS = original_addr


async def _validate_credentials_status_code(status_code: int):
    original_key = settings.RELAYER_API_KEY
    original_addr = settings.RELAYER_API_KEY_ADDRESS
    settings.RELAYER_API_KEY = "test-key"
    settings.RELAYER_API_KEY_ADDRESS = "0xabc"
    try:
        fake_client = FakeAsyncClient([FakeResponse({"ok": False}, status_code=status_code)])
        client = PolymarketRelayerClient(client=fake_client)  # type: ignore[arg-type]
        return await client.validate_credentials()
    finally:
        settings.RELAYER_API_KEY = original_key
        settings.RELAYER_API_KEY_ADDRESS = original_addr


def test_validate_credentials_treats_400_422_as_reachable_and_401_as_failure():
    assert asyncio.run(_validate_credentials_status_code(400)) is True
    assert asyncio.run(_validate_credentials_status_code(422)) is True
    assert asyncio.run(_validate_credentials_status_code(401)) is False
