import os
import stat
from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.api import main
from backend.api.main import app


def test_inv368_credentials_use_documented_env_var_names(monkeypatch):
    monkeypatch.setenv("POLYMARKET_API_KEY", "poly-secret")
    monkeypatch.setenv("KALSHI_API_KEY_ID", "kalshi-key-id")
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.delenv("...EY", raising=False)
    monkeypatch.delenv("...ID", raising=False)

    loaded = Settings()

    assert loaded.POLYMARKET_API_KEY == "poly-secret"
    assert loaded.KALSHI_API_KEY_ID == "kalshi-key-id"
    assert loaded.GROQ_API_KEY == "groq-secret"


def _point_settings_endpoint_at_tmp_env(monkeypatch, tmp_path: Path) -> Path:
    api_dir = tmp_path / "backend" / "api"
    api_dir.mkdir(parents=True)
    fake_main = api_dir / "main.py"
    fake_main.write_text("# fake module path for settings tests\n")
    monkeypatch.setattr(main, "__file__", str(fake_main))
    return tmp_path / ".env"


def _assert_settings_paths_are_tmp(env_path: Path, tmp_path: Path) -> None:
    """Fail closed before settings POSTs can write outside pytest tmp_path."""
    assert env_path.resolve().is_relative_to(tmp_path.resolve())
    pem_path = env_path.parent / "kalshi_private_key.pem"
    assert pem_path.resolve().is_relative_to(tmp_path.resolve())


def test_inv369_remote_client_cannot_write_kalshi_credentials(monkeypatch, tmp_path):
    env_path = _point_settings_endpoint_at_tmp_env(monkeypatch, tmp_path)
    _assert_settings_paths_are_tmp(env_path, tmp_path)
    env_path.write_text("UNCHANGED=value\n")

    previous_key_id = main.settings.KALSHI_API_KEY_ID
    previous_key_path = main.settings.KALSHI_PRIVATE_KEY_PATH
    assert not (tmp_path / "kalshi_private_key.pem").exists(), "pem must not exist before POST"
    client = TestClient(app, client=("203.0.113.10", 4321))

    response = client.post(
        "/api/settings",
        json={
            "key_id": "remote-key-id",
            "private_key_pem": "[REDACTED PRIVATE KEY]",
        },
    )

    assert response.status_code == 403
    assert env_path.read_text() == "UNCHANGED=value\n"
    assert not (tmp_path / "kalshi_private_key.pem").exists()
    assert main.settings.KALSHI_API_KEY_ID == previous_key_id
    assert main.settings.KALSHI_PRIVATE_KEY_PATH == previous_key_path


def test_inv369_remote_client_cannot_write_noncredential_settings(monkeypatch, tmp_path):
    env_path = _point_settings_endpoint_at_tmp_env(monkeypatch, tmp_path)
    _assert_settings_paths_are_tmp(env_path, tmp_path)
    env_path.write_text("UNCHANGED=value\n")
    previous_sim = main.settings.SIMULATION_MODE
    client = TestClient(app, client=("203.0.113.10", 4321))

    response = client.post("/api/settings", json={"simulation_mode": not previous_sim})

    assert response.status_code == 403
    assert env_path.read_text() == "UNCHANGED=value\n"
    assert main.settings.SIMULATION_MODE == previous_sim


def test_inv369_null_origin_is_rejected_for_settings_mutations(monkeypatch, tmp_path):
    env_path = _point_settings_endpoint_at_tmp_env(monkeypatch, tmp_path)
    _assert_settings_paths_are_tmp(env_path, tmp_path)
    env_path.write_text("UNCHANGED=value\n")
    client = TestClient(app, client=("127.0.0.1", 4321))

    response = client.post("/api/settings", headers={"Origin": "null"}, json={"simulation_mode": False})

    assert response.status_code == 403
    assert env_path.read_text() == "UNCHANGED=value\n"


def test_inv369_loopback_origin_with_port_can_update_settings(monkeypatch, tmp_path):
    env_path = _point_settings_endpoint_at_tmp_env(monkeypatch, tmp_path)
    _assert_settings_paths_are_tmp(env_path, tmp_path)
    env_path.write_text("UNCHANGED=value\n")
    client = TestClient(app, client=("127.0.0.1", 4321))

    response = client.post("/api/settings", headers={"Origin": "http://localhost:5173"}, json={"simulation_mode": True})

    assert response.status_code == 200
    assert "SIMULATION_MODE=True" in env_path.read_text()


def test_inv369_local_credential_write_preserves_env_content_uses_0600_and_redacts_response(monkeypatch, tmp_path):
    env_path = _point_settings_endpoint_at_tmp_env(monkeypatch, tmp_path)
    _assert_settings_paths_are_tmp(env_path, tmp_path)
    env_path.write_text(
        "# keep this comment\n"
        "UNRELATED=value with spaces\n"
        "KALSHI_API_KEY_ID=old-key\n"
        "KALSHI_PRIVATE_KEY_PATH=/old/key.pem\n"
        "TRAILING=still-here\n"
    )
    monkeypatch.setattr(main.settings, "KALSHI_API_KEY_ID", None)
    monkeypatch.setattr(main.settings, "KALSHI_PRIVATE_KEY_PATH", None)
    monkeypatch.setenv("KALSHI_API_KEY_ID", "")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", "")

    pem = "-----BEGIN PRIVATE KEY-----\nLOCAL-SECRET\n-----END PRIVATE KEY-----"
    client = TestClient(app, client=("127.0.0.1", 12345))

    response = client.post(
        "/api/settings",
        json={
            "key_id": "local-key-id",
            "private_key_pem": pem,
            "simulation_mode": False,
            "initial_bankroll": 12345,
            "min_edge": 0.12,
            "max_trade_size": 77,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "LOCAL-SECRET" not in response.text
    assert "private_key_pem" not in response.text
    assert "key_id" not in body

    pem_path = tmp_path / "kalshi_private_key.pem"
    assert pem_path.resolve().is_relative_to(tmp_path.resolve())
    assert pem_path.read_text() == pem + "\n"
    assert stat.S_IMODE(os.stat(pem_path).st_mode) == 0o600

    env_text = env_path.read_text()
    assert "# keep this comment\n" in env_text
    assert "UNRELATED=value with spaces\n" in env_text
    assert "TRAILING=still-here\n" in env_text
    assert "KALSHI_API_KEY_ID=local-key-id\n" in env_text
    assert f"KALSHI_PRIVATE_KEY_PATH={pem_path}\n" in env_text
    assert main.settings.KALSHI_API_KEY_ID == "local-key-id"
    assert main.settings.KALSHI_PRIVATE_KEY_PATH == str(pem_path)
