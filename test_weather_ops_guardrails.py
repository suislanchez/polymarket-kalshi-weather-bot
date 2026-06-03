import math
from datetime import datetime, timedelta, timezone
import sys
import types

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api.main import app
from backend.models.database import Base, BotState, Trade, get_db
from backend.core import weather_signals as ws


def _isolated_client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ops_guardrails.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides.clear()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), Session


class FakeScheduler:
    running = False

    def add_job(self, *_args, **_kwargs):
        return None

    def start(self):
        self.running = True

    def shutdown(self, wait=False):
        self.running = False


class FakeIntervalTrigger:
    def __init__(self, seconds=None, minutes=None):
        self.seconds = seconds
        self.minutes = minutes


def _install_fake_apscheduler(monkeypatch):
    apscheduler = types.ModuleType("apscheduler")
    schedulers = types.ModuleType("apscheduler.schedulers")
    schedulers_asyncio = types.ModuleType("apscheduler.schedulers.asyncio")
    triggers = types.ModuleType("apscheduler.triggers")
    triggers_interval = types.ModuleType("apscheduler.triggers.interval")
    setattr(schedulers_asyncio, "AsyncIOScheduler", FakeScheduler)
    setattr(triggers_interval, "IntervalTrigger", FakeIntervalTrigger)
    monkeypatch.setitem(sys.modules, "apscheduler", apscheduler)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers", schedulers)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers.asyncio", schedulers_asyncio)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers", triggers)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.interval", triggers_interval)


def test_dashboard_sanitizes_nan_trade_and_state_values_without_crashing(tmp_path, monkeypatch):
    from backend.api import main as api_main

    monkeypatch.setattr(api_main.settings, "BTC_ENABLED", False)
    monkeypatch.setattr(api_main.settings, "WEATHER_ENABLED", False)
    client, Session = _isolated_client(tmp_path)

    with Session() as db:
        db.add(BotState(
            bankroll=float("nan"),
            total_trades=1,
            winning_trades=1,
            total_pnl=float("nan"),
            is_running=True,
        ))
        db.add(Trade(
            market_ticker="KXHIGHTNY-26JUN03-T85",
            platform="kalshi",
            event_slug="KXHIGHTNY-26JUN03-T85",
            market_type="weather",
            direction="yes",
            entry_price=float("nan"),
            size=float("inf"),
            timestamp=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc).replace(tzinfo=None),
            settled=True,
            result="win",
            pnl=float("nan"),
            model_probability=float("nan"),
            market_price_at_entry=float("nan"),
            edge_at_entry=float("nan"),
        ))
        db.commit()

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    assert "NaN" not in response.text
    assert "Infinity" not in response.text
    body = response.json()
    assert body["stats"]["bankroll"] == 0.0
    assert body["stats"]["total_pnl"] == 0.0
    assert body["recent_trades"][0]["entry_price"] == 0.0
    assert body["recent_trades"][0]["size"] == 0.0
    assert body["recent_trades"][0]["pnl"] is None
    app.dependency_overrides.clear()


def _stale_weather_signal():
    fetched_at = datetime.now(timezone.utc)
    observed_at = fetched_at - timedelta(seconds=900)
    return ws.WeatherTradingSignal(
        market=ws.KalshiWeatherMarket(
            market_id="KXHIGHTNY-26JUN03-T85",
            slug="KXHIGHTNY-26JUN03-T85",
            city_key="nyc",
            city_name="New York City",
            target_date=datetime.now(timezone.utc).date(),
            threshold_f=85.0,
            metric="high",
            yes_price=0.40,
            no_price=0.60,
        ),
        model_probability=0.95,
        market_probability=0.40,
        edge=0.55,
        net_edge=0.48,
        direction="yes",
        confidence=0.95,
        suggested_size=50.0,
        weather_observation=ws.WeatherObservation(
            source="aviationweather_metar",
            station_id="KJFK",
            observed_at=observed_at,
            fetched_at=fetched_at,
            temp_f=86.0,
            raw={"rawOb": "stale"},
            raw_hash="stale-hash",
            source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
        ),
    )


def test_weather_scan_job_vetoes_stale_observation_before_trade_insert(tmp_path, monkeypatch):
    _install_fake_apscheduler(monkeypatch)
    from backend.core import scheduler as scheduler_mod

    client, Session = _isolated_client(tmp_path)
    del client
    events = []
    stale_signal = _stale_weather_signal()

    with Session() as db:
        db.add(BotState(bankroll=10_000.0, total_trades=0, winning_trades=0, total_pnl=0.0, is_running=True))
        db.commit()

    async def fake_scan_for_weather_signals():
        return [stale_signal]

    monkeypatch.setattr("backend.core.weather_signals.scan_for_weather_signals", fake_scan_for_weather_signals)
    monkeypatch.setattr(scheduler_mod, "log_event", lambda typ, msg, data=None: events.append((typ, msg, data or {})))
    monkeypatch.setattr(scheduler_mod, "SessionLocal", Session)

    import asyncio
    asyncio.run(scheduler_mod.weather_scan_and_trade_job())

    with Session() as db:
        assert db.query(Trade).count() == 0
        state = db.query(BotState).first()
        assert state is not None
        assert state.total_trades == 0
    assert stale_signal.passes_threshold is False
    assert "stale_observation_age" in str(stale_signal.trade_skip_reason() or "")
    app.dependency_overrides.clear()
