"""INV-374/INV-376 API contract regression tests."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api import main as api_main
from backend.api.main import app
from backend.config import settings
from backend.models.database import Base, BotState, get_db


class _FakeScheduler:
    running = False

    @classmethod
    def is_scheduler_running(cls):
        return cls.running

    @classmethod
    def start_scheduler(cls):
        cls.running = True

    @staticmethod
    def log_event(*args, **kwargs):
        return None


def _isolated_client(tmp_path, monkeypatch):
    """Return TestClient backed by tmp SQLite and fake scheduler/log hooks."""
    db_path = (tmp_path / "weather_edge_test.db").resolve()
    assert db_path.is_relative_to(tmp_path.resolve())
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides.clear()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(api_main, "_log_event", lambda *args, **kwargs: None)

    import sys
    monkeypatch.setitem(sys.modules, "backend.core.scheduler", _FakeScheduler)
    _FakeScheduler.running = False

    client = TestClient(app)
    return client, TestingSessionLocal


def test_frontend_live_data_contract_endpoint_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEATHER_ENABLED", False)
    monkeypatch.setattr(settings, "BTC_ENABLED", False)
    client, _ = _isolated_client(tmp_path, monkeypatch)

    response = client.get("/api/data")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) >= {
        "ts",
        "kalshi",
        "polymarket",
        "lifetime",
        "metar_lines",
        "metar_poly_lines",
        "metar_v2_signals",
        "system",
    }
    assert isinstance(payload["system"]["services"], list)
    assert isinstance(payload["system"]["socks_up"], bool)


def test_frontend_market_contract_endpoints_exist(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEATHER_ENABLED", False)

    client, _ = _isolated_client(tmp_path, monkeypatch)
    kalshi_response = client.get("/api/kalshi/markets")
    poly_response = client.get("/api/polymarket/markets")

    assert kalshi_response.status_code == 200
    assert kalshi_response.json() == {
        "markets": [],
        "count": 0,
        "traded_today_count": 0,
    }
    assert poly_response.status_code == 200
    assert poly_response.json() == {"markets": [], "count": 0}


def test_bot_start_stop_controls_toggle_state(monkeypatch, tmp_path):
    client, Session = _isolated_client(tmp_path, monkeypatch)

    stopped = client.post("/api/bot/stop")
    assert stopped.status_code == 200
    assert stopped.json()["is_running"] is False
    assert client.get("/api/data").json()["system"]["services"][0]["running"] is False

    started = client.post("/api/bot/start")
    assert started.status_code == 200
    assert started.json()["is_running"] is True
    assert client.get("/api/data").json()["system"]["services"][0]["running"] is True
    assert _FakeScheduler.running is True

    with Session() as db:
        assert db.query(BotState).first().is_running is True

    app.dependency_overrides.clear()
