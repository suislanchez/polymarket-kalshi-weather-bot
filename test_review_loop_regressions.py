"""Regression tests from the 2026-05-05 Weather Edge review loop."""

from datetime import datetime
import os

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api import main as api_main
from backend.api.main import app
from backend.config import Settings
from backend.core import scheduler as scheduler_mod
from backend.core.settlement import calculate_pnl
from backend.core.weather_signals import (
    KalshiWeatherMarket,
    WeatherTradingSignal,
    metar_high_probability,
)
from backend.models.database import Base, BotState, Signal, Trade, get_db


def test_backend_config_reads_documented_kalshi_env_vars(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID", "kalshi-key-id")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", "/tmp/kalshi.pem")
    monkeypatch.delenv("POLYMARKET_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    loaded = Settings()

    assert loaded.KALSHI_API_KEY_ID == "kalshi-key-id"
    assert loaded.KALSHI_PRIVATE_KEY_PATH == "/tmp/kalshi.pem"
    assert not hasattr(loaded, "POLYMARKET_API_KEY")
    assert not hasattr(loaded, "GROQ_API_KEY")


def test_settings_get_does_not_expose_full_kalshi_key_id_or_path(monkeypatch):
    monkeypatch.setattr(api_main.settings, "KALSHI_API_KEY_ID", "kalshi-full-secret-key-id")
    monkeypatch.setattr(api_main.settings, "KALSHI_PRIVATE_KEY_PATH", "/private/kalshi.pem")

    response = TestClient(app).get("/api/settings")

    assert response.status_code == 200
    body = response.json()
    assert "kalshi_key_id" not in body
    assert "kalshi-full-secret-key-id" not in response.text
    assert "/private/kalshi.pem" not in response.text
    assert body["kalshi_configured"] is True


def test_cors_rejects_non_localhost_origins():
    response = TestClient(app).options(
        "/api/status",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers.get("access-control-allow-origin") != "https://evil.example"
    assert response.headers.get("access-control-allow-origin") != "*"


def _isolated_client(tmp_path, monkeypatch):
    db_path = (tmp_path / "weather_edge_review.db").resolve()
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
    monkeypatch.setattr(api_main, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(api_main, "init_db", lambda: None)
    monkeypatch.setattr(api_main, "_log_event", lambda *args, **kwargs: None)
    return TestClient(app), TestingSessionLocal


def test_startup_initializes_paused_without_starting_scheduler(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("backend.core.scheduler.start_scheduler", lambda: calls.append("start"))
    monkeypatch.setattr("backend.core.scheduler.stop_scheduler", lambda: None)

    with _isolated_client(tmp_path, monkeypatch)[0]:
        pass

    _, Session = _isolated_client(tmp_path, monkeypatch)
    with Session() as db:
        state = db.query(BotState).first()
        assert state is not None
        assert state.is_running is False
    assert calls == []


def test_stop_bot_stops_scheduler(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("backend.core.scheduler.stop_scheduler", lambda: calls.append("stop"))
    client, _ = _isolated_client(tmp_path, monkeypatch)

    response = client.post("/api/bot/stop")

    assert response.status_code == 200
    assert response.json()["is_running"] is False
    assert calls == ["stop"]


def test_scheduler_weather_job_checks_paused_state_before_network_scan(monkeypatch):
    calls = []

    class FakeQuery:
        def first(self):
            return BotState(is_running=False)

    class FakeSession:
        def query(self, _model):
            return FakeQuery()
        def close(self):
            pass

    monkeypatch.setattr(scheduler_mod, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        "backend.core.weather_signals.scan_for_weather_signals",
        lambda: calls.append("scan"),
    )

    import asyncio
    asyncio.run(scheduler_mod.weather_scan_and_trade_job())

    assert calls == []


def test_metar_high_probability_waits_for_cooling_before_locking():
    probability, confidence, note = metar_high_probability(
        max_observed_temp_f=86.0,
        current_temp_f=86.0,
        threshold_f=85.0,
        local_hour=14,
    )

    assert probability == 0.90
    assert confidence == "medium"
    assert "waiting for cooling" in note.lower()


def test_metar_high_probability_locks_after_peak_on_way_down():
    probability, confidence, note = metar_high_probability(
        max_observed_temp_f=86.0,
        current_temp_f=83.5,
        threshold_f=85.0,
        local_hour=15,
    )

    assert probability >= 0.95
    assert confidence == "high"
    assert "cooling" in note.lower()


def test_metar_early_signals_never_pass_threshold(monkeypatch):
    monkeypatch.setattr("backend.core.weather_signals.settings.WEATHER_MIN_EDGE_THRESHOLD", 0.08)
    signal = WeatherTradingSignal(
        market=KalshiWeatherMarket(market_id="KXTEST", slug="kx-test"),
        net_edge=0.40,
        signal_source="METAR-early",
        suggested_size=0.0,
    )

    assert signal.passes_threshold is False


def test_pnl_treats_size_as_dollar_stake():
    trade = Trade(direction="yes", entry_price=0.70, size=100.0)

    assert calculate_pnl(trade, 0.0) == -100.0
    assert calculate_pnl(trade, 1.0) == 42.86


def test_weather_signal_calibration_uses_yes_no_outcomes(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'settle.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    with Session() as db:
        sig = Signal(
            market_ticker="KXTEST",
            platform="kalshi",
            market_type="weather",
            direction="yes",
            model_probability=0.9,
            market_price=0.7,
            edge=0.2,
            confidence=0.95,
            kelly_fraction=0.1,
            suggested_size=100,
            sources=[],
            reasoning="test",
        )
        db.add(sig)
        db.flush()
        trade = Trade(
            signal_id=sig.id,
            market_ticker="KXTEST",
            platform="kalshi",
            market_type="weather",
            direction="yes",
            entry_price=0.70,
            size=100,
        )
        db.add(trade)
        db.commit()

        settlement_value = 1.0
        actual_outcome = "yes" if trade.market_type == "weather" and settlement_value == 1.0 else "no"
        sig.actual_outcome = actual_outcome
        sig.outcome_correct = sig.direction == actual_outcome

        assert sig.actual_outcome == "yes"
        assert sig.outcome_correct is True


def test_weather_direction_uses_selected_side_net_edge_after_fees(monkeypatch):
    monkeypatch.setattr("backend.core.weather_signals.settings.WEATHER_MIN_EDGE_THRESHOLD", 0.08)

    fair_no_signal = WeatherTradingSignal(
        market=KalshiWeatherMarket(market_id="KXFAIR", slug="kx-fair"),
        model_probability=0.48,
        market_probability=0.50,
        edge=0.02,
        net_edge=-0.05,
        direction="no",
        suggested_size=100.0,
    )
    real_no_signal = WeatherTradingSignal(
        market=KalshiWeatherMarket(market_id="KXEDGE", slug="kx-edge"),
        model_probability=0.30,
        market_probability=0.50,
        edge=0.20,
        net_edge=0.13,
        direction="no",
        suggested_size=100.0,
    )

    assert fair_no_signal.passes_threshold is False
    assert real_no_signal.passes_threshold is True


def test_remote_client_cannot_change_noncredential_settings(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    api_dir = tmp_path / "backend" / "api"
    api_dir.mkdir(parents=True)
    fake_main = api_dir / "main.py"
    fake_main.write_text("# fake module path for settings tests\n")
    monkeypatch.setattr(api_main, "__file__", str(fake_main))
    env_path.write_text("WEATHER_MIN_EDGE_THRESHOLD=0.08\n")

    client = TestClient(app, client=("203.0.113.10", 4321))
    response = client.post("/api/settings", json={"min_edge": 0.01})

    assert response.status_code == 403
    assert env_path.read_text() == "WEATHER_MIN_EDGE_THRESHOLD=0.08\n"


def test_run_py_requires_explicit_host_override_for_public_bind():
    text = open(os.path.join(os.path.dirname(__file__), "run.py")).read()

    assert 'os.environ.get("HOST", "127.0.0.1")' in text
    assert 'host="0.0.0.0"' not in text


def test_remote_client_cannot_call_admin_mutation_endpoints(tmp_path, monkeypatch):
    client, _ = _isolated_client(tmp_path, monkeypatch)
    client._transport.client = ("203.0.113.10", 4321)

    for method, path in [
        ("post", "/api/bot/start"),
        ("post", "/api/bot/stop"),
        ("post", "/api/bot/reset"),
        ("post", "/api/run-scan"),
        ("post", "/api/settle-trades"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 403, path


def test_metar_cache_respects_ttl(monkeypatch):
    from backend.core import weather_signals as ws
    calls = []

    class FakeResponse:
        status_code = 200
        def json(self):
            return [{"temp": 20.0, "obsTime": "2026-05-06T10:00:00Z"}]

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()

    ws._metar_cache.clear()
    monkeypatch.setattr(ws.requests, "get", fake_get)
    monkeypatch.setattr(ws.time, "time", lambda: 1000.0)
    assert ws.fetch_metar("KJFK")
    assert ws.fetch_metar("KJFK")
    assert len(calls) == 1

    monkeypatch.setattr(ws.time, "time", lambda: 1000.0 + ws._METAR_CACHE_TTL + 1)
    assert ws.fetch_metar("KJFK")
    assert len(calls) == 2


def test_gfs_cache_key_includes_forecast_horizon(monkeypatch):
    from backend.core import weather_signals as ws
    calls = []

    class FakeResponse:
        status_code = 200
        def json(self):
            return {
                "hourly": {
                    "time": ["2026-05-06T00:00"],
                    "temperature_2m": [20.0],
                    "precipitation": [0.0],
                    "snowfall": [0.0],
                }
            }

    def fake_get(url, params=None, timeout=None):
        calls.append(params["forecast_days"])
        return FakeResponse()

    ws._ensemble_cache.clear()
    monkeypatch.setattr(ws.requests, "get", fake_get)
    monkeypatch.setattr(ws.time, "time", lambda: 1000.0)
    monkeypatch.setattr(ws.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(ws, "date", type("FakeDate", (), {"today": staticmethod(lambda: ws.datetime(2026, 5, 6).date())}))

    ws.fetch_ensemble(40.0, -73.0, ws.datetime(2026, 5, 6).date())
    ws.fetch_ensemble(40.0, -73.0, ws.datetime(2026, 5, 16).date())

    assert len(calls) == 2
    assert calls[0] != calls[1]


def test_remote_client_cannot_read_authenticated_kalshi_status(monkeypatch):
    class FakeClient:
        async def get_balance(self):
            return {"balance": 12345}

    monkeypatch.setattr("backend.data.kalshi_client.kalshi_credentials_present", lambda: True)
    monkeypatch.setattr("backend.data.kalshi_client.KalshiClient", FakeClient)
    client = TestClient(app, client=("203.0.113.10", 4321))

    assert client.get("/api/kalshi/status").status_code == 403
    assert client.post("/api/settings/test-connection").status_code == 403


def test_metar_lock_panel_filters_to_metar_lock_sources_only():
    app_text = open(os.path.join(os.path.dirname(__file__), "frontend/src/App.tsx")).read()

    assert "s.actionable && s.signal_source === 'METAR-lock'" in app_text


def test_hostile_origin_cannot_trigger_local_admin_mutations(tmp_path, monkeypatch):
    client, _ = _isolated_client(tmp_path, monkeypatch)
    hostile = {"Origin": "https://evil.example"}

    for path, kwargs in [
        ("/api/bot/start", {}),
        ("/api/bot/stop", {}),
        ("/api/bot/reset", {}),
        ("/api/run-scan", {}),
        ("/api/settings", {"json": {"simulation_mode": False}}),
        ("/api/settings/test-connection", {}),
    ]:
        response = client.post(path, headers=hostile, **kwargs)
        assert response.status_code == 403, path


def test_negative_net_edge_never_passes_actionable_threshold(monkeypatch):
    monkeypatch.setattr("backend.core.weather_signals.settings.WEATHER_MIN_EDGE_THRESHOLD", 0.01)
    signal = WeatherTradingSignal(
        market=KalshiWeatherMarket(market_id="KXNEG", slug="kx-neg"),
        net_edge=-0.07,
        suggested_size=50.0,
    )

    assert signal.passes_threshold is False


def test_scheduler_defensively_skips_non_positive_edge(monkeypatch):
    from backend.core.weather_signals import WeatherTradingSignal, KalshiWeatherMarket

    events = []
    added = []

    signal = WeatherTradingSignal(
        market=KalshiWeatherMarket(market_id="KXNEG", slug="kx-neg"),
        net_edge=-0.07,
        direction="yes",
        suggested_size=50.0,
    )

    class FakeQuery:
        def __init__(self, model):
            self.model = model
        def first(self):
            if self.model is BotState:
                return BotState(is_running=True, bankroll=100.0)
            return None
        def filter(self, *args, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def scalar(self):
            return 0.0

    class FakeSession:
        def query(self, model):
            return FakeQuery(model)
        def add(self, obj):
            added.append(obj)
        def flush(self):
            pass
        def commit(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(scheduler_mod, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        "backend.core.weather_signals.scan_for_weather_signals",
        lambda: [signal],
    )
    monkeypatch.setattr(scheduler_mod, "log_event", lambda *args, **kwargs: events.append(args))

    import asyncio
    asyncio.run(scheduler_mod.weather_scan_and_trade_job())

    assert added == []


def test_settings_reject_invalid_numeric_values(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    api_dir = tmp_path / "backend" / "api"
    api_dir.mkdir(parents=True)
    fake_main = api_dir / "main.py"
    fake_main.write_text("# fake module path for settings tests\n")
    monkeypatch.setattr(api_main, "__file__", str(fake_main))
    env_path.write_text("UNCHANGED=value\n")

    client = TestClient(app, client=("127.0.0.1", 12345))
    for payload in [
        {"max_trade_size": 0},
        {"max_trade_size": -1},
        {"initial_bankroll": -1},
        {"min_edge": -0.01},
        {"min_edge": 1.5},
    ]:
        response = client.post("/api/settings", json=payload)
        assert response.status_code == 422, payload
        assert env_path.read_text() == "UNCHANGED=value\n"


def test_settings_invalid_numeric_payload_is_atomic(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    api_dir = tmp_path / "backend" / "api"
    api_dir.mkdir(parents=True)
    fake_main = api_dir / "main.py"
    fake_main.write_text("# fake module path for settings tests\n")
    monkeypatch.setattr(api_main, "__file__", str(fake_main))
    env_path.write_text("UNCHANGED=value\n")

    old_sim = api_main.settings.SIMULATION_MODE
    old_key = api_main.settings.KALSHI_API_KEY_ID
    old_path = api_main.settings.KALSHI_PRIVATE_KEY_PATH
    monkeypatch.setenv("SIMULATION_MODE", str(old_sim))
    monkeypatch.setenv("KALSHI_API_KEY_ID", "old-key-env")

    client = TestClient(app, client=("127.0.0.1", 12345))
    response = client.post(
        "/api/settings",
        json={
            "simulation_mode": not old_sim,
            "key_id": "new-key",
            "private_key_pem": "PRIVATE KEY DATA",
            "min_edge": -0.01,
        },
    )

    assert response.status_code == 422
    assert env_path.read_text() == "UNCHANGED=value\n"
    assert not (tmp_path / "kalshi_private_key.pem").exists()
    assert api_main.settings.SIMULATION_MODE == old_sim
    assert api_main.settings.KALSHI_API_KEY_ID == old_key
    assert api_main.settings.KALSHI_PRIVATE_KEY_PATH == old_path
    assert os.environ["KALSHI_API_KEY_ID"] == "old-key-env"


def test_scheduler_caps_new_weather_trades_against_remaining_allocation(monkeypatch):
    from backend.core.weather_signals import WeatherTradingSignal, KalshiWeatherMarket

    added = []
    events = []
    signals = [
        WeatherTradingSignal(
            market=KalshiWeatherMarket(market_id=f"KXCAP{i}", slug=f"kx-cap-{i}", yes_price=0.50),
            net_edge=0.20,
            direction="yes",
            suggested_size=100.0,
        )
        for i in range(3)
    ]

    class FakeQuery:
        def __init__(self, model):
            self.model = model
        def first(self):
            if self.model is BotState:
                return BotState(is_running=True, bankroll=1000.0)
            return None
        def filter(self, *args, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def scalar(self):
            return 450.0

    class FakeSession:
        def query(self, model):
            return FakeQuery(model)
        def add(self, obj):
            added.append(obj)
        def flush(self):
            pass
        def commit(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(scheduler_mod, "SessionLocal", lambda: FakeSession())
    async def _fake_scan():
        return signals
    monkeypatch.setattr(
        "backend.core.weather_signals.scan_for_weather_signals",
        _fake_scan,
    )
    monkeypatch.setattr(scheduler_mod, "log_event", lambda *args, **kwargs: events.append(args))

    import asyncio
    asyncio.run(scheduler_mod.weather_scan_and_trade_job())

    trades = [obj for obj in added if isinstance(obj, Trade)]
    assert len(trades) == 1
    assert sum(t.size for t in trades) <= 50.0
    assert trades[0].size == 50.0


def test_backend_rejects_unsupported_live_trading_mode(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    api_dir = tmp_path / "backend" / "api"
    api_dir.mkdir(parents=True)
    fake_main = api_dir / "main.py"
    fake_main.write_text("# fake module path for settings tests\n")
    monkeypatch.setattr(api_main, "__file__", str(fake_main))
    env_path.write_text("SIMULATION_MODE=True\n")

    old_sim = api_main.settings.SIMULATION_MODE
    client = TestClient(app, client=("127.0.0.1", 12345))

    response = client.post("/api/settings", json={"simulation_mode": False})

    assert response.status_code == 422
    assert "paper-only" in response.json()["detail"]
    assert env_path.read_text() == "SIMULATION_MODE=True\n"
    assert api_main.settings.SIMULATION_MODE == old_sim


def test_settings_endpoint_advertises_no_live_trading_support():
    body = TestClient(app).get("/api/settings").json()

    assert body["live_trading_supported"] is False


def test_scheduler_skips_weather_signal_above_max_entry_price(monkeypatch):
    from backend.core.weather_signals import WeatherTradingSignal, KalshiWeatherMarket

    added = []
    events = []
    signal = WeatherTradingSignal(
        market=KalshiWeatherMarket(market_id="KXPRICE", slug="kx-price", yes_price=0.95),
        net_edge=0.30,
        direction="yes",
        suggested_size=50.0,
    )

    class FakeQuery:
        def __init__(self, model):
            self.model = model
        def first(self):
            if self.model is BotState:
                return BotState(is_running=True, bankroll=1000.0)
            return None
        def filter(self, *args, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def scalar(self):
            return 0.0

    class FakeSession:
        def query(self, model):
            return FakeQuery(model)
        def add(self, obj):
            added.append(obj)
        def flush(self):
            pass
        def commit(self):
            pass
        def close(self):
            pass

    async def _fake_scan():
        return [signal]

    monkeypatch.setattr(scheduler_mod, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        "backend.core.weather_signals.scan_for_weather_signals",
        _fake_scan,
    )
    monkeypatch.setattr(scheduler_mod.settings, "WEATHER_MAX_ENTRY_PRICE", 0.70)
    monkeypatch.setattr(scheduler_mod, "log_event", lambda *args, **kwargs: events.append(args))

    import asyncio
    asyncio.run(scheduler_mod.weather_scan_and_trade_job())

    assert [obj for obj in added if isinstance(obj, Trade)] == []
    assert any("entry price above max" in str(args) for args in events)
