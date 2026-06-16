#!/usr/bin/env python3
"""Validate Polymarket API setup without exposing secrets or placing orders."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--user-address",
        help="Optional Polymarket proxy/wallet address for read-only Data API positions check",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    env_path = Path.cwd() / ".env"
    repo_root = env_path.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if env_path.exists():
        load_dotenv(env_path, override=True)

    # Import after loading .env so pydantic settings see current values.
    from backend.data.polymarket_api_setup import validate_public_polymarket_apis

    result = validate_public_polymarket_apis(timeout=args.timeout, user_address=args.user_address)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("public_ok") else 1

    print("Polymarket API setup smoke test")
    print(f"public APIs ok: {result['public_ok']}")
    print(f"Gamma markets returned: {result['gamma_markets_count']}")
    print(f"Data trades returned: {result['data_trades_count']}")
    if result.get("data_positions_count") is not None:
        print(f"Data positions returned for supplied user: {result['data_positions_count']}")
    print(f"CLOB token discovered from Gamma: {result['clob_token_discovered']}")
    print("\nEndpoint checks:")
    for check in result["checks"]:
        status = check.get("status_code") or "n/a"
        suffix = "" if check["ok"] else f" -- {check.get('detail') or 'failed'}"
        print(f"- {check['name']}: {'OK' if check['ok'] else 'FAIL'} ({status}){suffix}")

    creds = result["credential_status"]
    print("\nCredential readiness (redacted):")
    for key in [
        "api_key_id_present",
        "api_secret_present",
        "api_passphrase_present",
        "address_present",
        "funder_address_present",
        "private_key_present",
        "authenticated_clob_enabled",
        "l2_credentials_ready",
        "order_signing_ready",
    ]:
        print(f"- {key}: {creds[key]}")
    if creds["missing_l2_fields"]:
        print("- missing_l2_fields: " + ", ".join(creds["missing_l2_fields"]))
    if creds["missing_order_signing_fields"]:
        print("- missing_order_signing_fields: " + ", ".join(creds["missing_order_signing_fields"]))

    return 0 if result.get("public_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
