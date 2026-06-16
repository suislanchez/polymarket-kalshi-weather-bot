"""Polymarket API setup and smoke-test helpers.

All network checks here are read-only.  The helper deliberately does not place,
cancel, or sign orders.  It reports credential presence without returning secret
values so setup checks are safe to run in logs/Slack.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from backend.config import settings

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "weather-paper-bot-polymarket-api-smoke/1.0",
}


@dataclass(frozen=True)
class EndpointCheck:
    name: str
    url: str
    ok: bool
    status_code: int | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "ok": self.ok,
            "status_code": self.status_code,
            "detail": self.detail,
        }


def _bool_env(name: str) -> bool:
    value = os.getenv(name)
    return bool(value and value.strip())


def polymarket_credential_status(settings_obj: Any = settings) -> dict[str, Any]:
    """Return redacted Polymarket credential readiness.

    CLOB L2 authentication requires api key id, secret, passphrase, and signer
    address.  Creating/posting orders also requires a local private key signer
    and funder/deposit-wallet metadata; those remain separate from public API
    smoke tests and are disabled by default in this bot.
    """
    api_key_id_present = bool(
        getattr(settings_obj, "POLYMARKET_API_KEY_ID", None)
        or getattr(settings_obj, "POLYMARKET_API_KEY", None)
    )
    api_secret_present = bool(getattr(settings_obj, "POLYMARKET_API_SECRET", None))
    api_passphrase_present = bool(getattr(settings_obj, "POLYMARKET_API_PASSPHRASE", None))
    address_present = bool(getattr(settings_obj, "POLYMARKET_ADDRESS", None))
    funder_present = bool(getattr(settings_obj, "POLYMARKET_FUNDER_ADDRESS", None))
    private_key_present = _bool_env("PRIVATE_KEY") or _bool_env("POLYMARKET_PRIVATE_KEY")
    authenticated_clob_enabled = bool(
        getattr(settings_obj, "POLYMARKET_ENABLE_AUTHENTICATED_CLOB", False)
    )

    missing_l2 = []
    if not api_key_id_present:
        missing_l2.append("POLYMARKET_API_KEY_ID")
    if not api_secret_present:
        missing_l2.append("POLYMARKET_API_SECRET")
    if not api_passphrase_present:
        missing_l2.append("POLYMARKET_API_PASSPHRASE")
    if not address_present:
        missing_l2.append("POLYMARKET_ADDRESS")

    l2_ready = not missing_l2
    missing_order_signing = []
    if not private_key_present:
        missing_order_signing.append("PRIVATE_KEY or POLYMARKET_PRIVATE_KEY")
    if not funder_present:
        missing_order_signing.append("POLYMARKET_FUNDER_ADDRESS")

    return {
        "api_key_id_present": api_key_id_present,
        "api_secret_present": api_secret_present,
        "api_passphrase_present": api_passphrase_present,
        "address_present": address_present,
        "funder_address_present": funder_present,
        "private_key_present": private_key_present,
        "signature_type": getattr(settings_obj, "POLYMARKET_SIGNATURE_TYPE", 3),
        "authenticated_clob_enabled": authenticated_clob_enabled,
        "l2_credentials_ready": l2_ready,
        "missing_l2_fields": missing_l2,
        "order_signing_ready": l2_ready and private_key_present and funder_present,
        "missing_order_signing_fields": missing_order_signing,
    }


def _get_json(client: httpx.Client, url: str, *, params: Mapping[str, Any] | None = None) -> tuple[EndpointCheck, Any]:
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = response.text
        return EndpointCheck(name=url, url=str(response.url), ok=True, status_code=response.status_code), payload
    except httpx.HTTPStatusError as exc:
        return (
            EndpointCheck(
                name=url,
                url=str(exc.response.url),
                ok=False,
                status_code=exc.response.status_code,
                detail=exc.response.text[:200],
            ),
            None,
        )
    except Exception as exc:  # pragma: no cover - network-dependent
        return EndpointCheck(name=url, url=url, ok=False, detail=f"{type(exc).__name__}: {exc}"), None


def _parse_first_clob_token(markets_payload: Any) -> str | None:
    markets = markets_payload if isinstance(markets_payload, list) else []
    for market in markets:
        if not isinstance(market, dict):
            continue
        token_ids_raw = market.get("clobTokenIds")
        if isinstance(token_ids_raw, str):
            try:
                token_ids = json.loads(token_ids_raw)
            except json.JSONDecodeError:
                token_ids = []
        elif isinstance(token_ids_raw, list):
            token_ids = token_ids_raw
        else:
            token_ids = []
        for token_id in token_ids:
            token_text = str(token_id or "").strip()
            if token_text:
                return token_text
    return None


def validate_public_polymarket_apis(
    *,
    timeout: float = 20.0,
    user_address: str | None = None,
    settings_obj: Any = settings,
) -> dict[str, Any]:
    """Read-only smoke test for Gamma, Data, and public CLOB APIs.

    Returns only counts/statuses and never includes credentials or private data.
    """
    checks: list[EndpointCheck] = []
    gamma_base = str(getattr(settings_obj, "POLYMARKET_GAMMA_API", "https://gamma-api.polymarket.com")).rstrip("/")
    data_base = str(getattr(settings_obj, "POLYMARKET_DATA_API", "https://data-api.polymarket.com")).rstrip("/")
    clob_base = str(getattr(settings_obj, "POLYMARKET_CLOB_API", "https://clob.polymarket.com")).rstrip("/")

    discovered_token_id: str | None = None
    gamma_markets_count = 0
    data_trades_count = 0
    data_positions_count: int | None = None

    with httpx.Client(timeout=timeout, headers=DEFAULT_HEADERS) as client:
        check, gamma_markets = _get_json(
            client,
            f"{gamma_base}/markets",
            params={"limit": 5, "closed": "false"},
        )
        checks.append(EndpointCheck("gamma_markets", check.url, check.ok, check.status_code, check.detail))
        if isinstance(gamma_markets, list):
            gamma_markets_count = len(gamma_markets)
            discovered_token_id = _parse_first_clob_token(gamma_markets)

        check, data_trades = _get_json(client, f"{data_base}/trades", params={"limit": 1})
        checks.append(EndpointCheck("data_trades", check.url, check.ok, check.status_code, check.detail))
        if isinstance(data_trades, list):
            data_trades_count = len(data_trades)

        if user_address:
            check, data_positions = _get_json(
                client,
                f"{data_base}/positions",
                params={"user": user_address, "limit": 1},
            )
            checks.append(EndpointCheck("data_positions_for_user", check.url, check.ok, check.status_code, check.detail))
            data_positions_count = len(data_positions) if isinstance(data_positions, list) else 0

        check, clob_time = _get_json(client, f"{clob_base}/time")
        checks.append(EndpointCheck("clob_time", check.url, check.ok, check.status_code, check.detail))

        if discovered_token_id:
            for name, path, params in [
                ("clob_book", "/book", {"token_id": discovered_token_id}),
                ("clob_midpoint", "/midpoint", {"token_id": discovered_token_id}),
                ("clob_price_buy", "/price", {"token_id": discovered_token_id, "side": "BUY"}),
                ("clob_price_sell", "/price", {"token_id": discovered_token_id, "side": "SELL"}),
            ]:
                check, _payload = _get_json(client, f"{clob_base}{path}", params=params)
                checks.append(EndpointCheck(name, check.url, check.ok, check.status_code, check.detail))

    public_ok = all(check.ok for check in checks)
    return {
        "public_ok": public_ok,
        "gamma_markets_count": gamma_markets_count,
        "data_trades_count": data_trades_count,
        "data_positions_count": data_positions_count,
        "clob_token_discovered": bool(discovered_token_id),
        "checks": [check.as_dict() for check in checks],
        "credential_status": polymarket_credential_status(settings_obj),
    }
