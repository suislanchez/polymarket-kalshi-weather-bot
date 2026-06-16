from types import SimpleNamespace

from backend.data.polymarket_api_setup import polymarket_credential_status


def test_polymarket_credential_status_reports_missing_l2_fields(monkeypatch):
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY", raising=False)
    settings = SimpleNamespace(
        POLYMARKET_API_KEY_ID="key-id",
        POLYMARKET_API_KEY=None,
        POLYMARKET_API_SECRET="secret",
        POLYMARKET_API_PASSPHRASE=None,
        POLYMARKET_ADDRESS=None,
        POLYMARKET_FUNDER_ADDRESS=None,
        POLYMARKET_SIGNATURE_TYPE=3,
        POLYMARKET_ENABLE_AUTHENTICATED_CLOB=False,
    )

    status = polymarket_credential_status(settings)

    assert status["api_key_id_present"] is True
    assert status["api_secret_present"] is True
    assert status["l2_credentials_ready"] is False
    assert status["order_signing_ready"] is False
    assert status["missing_l2_fields"] == ["POLYMARKET_API_PASSPHRASE", "POLYMARKET_ADDRESS"]
    assert status["missing_order_signing_fields"] == [
        "PRIVATE_KEY or POLYMARKET_PRIVATE_KEY",
        "POLYMARKET_FUNDER_ADDRESS",
    ]


def test_polymarket_credential_status_accepts_legacy_api_key_and_private_key(monkeypatch):
    monkeypatch.setenv("PRIVATE_KEY", "present-but-not-read")
    settings = SimpleNamespace(
        POLYMARKET_API_KEY_ID=None,
        POLYMARKET_API_KEY="legacy-key",
        POLYMARKET_API_SECRET="secret",
        POLYMARKET_API_PASSPHRASE="passphrase",
        POLYMARKET_ADDRESS="0xabc",
        POLYMARKET_FUNDER_ADDRESS="0xdef",
        POLYMARKET_SIGNATURE_TYPE=3,
        POLYMARKET_ENABLE_AUTHENTICATED_CLOB=True,
    )

    status = polymarket_credential_status(settings)

    assert status["api_key_id_present"] is True
    assert status["l2_credentials_ready"] is True
    assert status["order_signing_ready"] is True
    assert status["authenticated_clob_enabled"] is True
    assert status["missing_l2_fields"] == []
    assert status["missing_order_signing_fields"] == []
