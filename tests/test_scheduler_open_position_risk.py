import asyncio

from backend.core import scheduler
from backend.core.open_position_monitor import OpenPositionRiskSummary


def test_open_position_risk_job_wires_public_weather_exit_quote_provider(monkeypatch):
    class DummyDB:
        closed = False

        def close(self):
            self.closed = True

    class FakeWeatherQuoteProvider:
        pass

    dummy_db = DummyDB()
    seen = {}

    def fake_run_open_position_risk_scan(db, *, weather_quote_provider=None, **kwargs):
        seen["db"] = db
        seen["weather_quote_provider"] = weather_quote_provider
        seen["kwargs"] = kwargs
        return OpenPositionRiskSummary(total_open_positions=0)

    monkeypatch.setattr(scheduler.settings, "PAPER_POSITION_RISK_ENABLED", True)
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: dummy_db)
    monkeypatch.setattr(
        "backend.core.open_position_monitor.run_open_position_risk_scan",
        fake_run_open_position_risk_scan,
    )
    monkeypatch.setattr(
        "backend.core.weather_exit_quotes.PublicWeatherExitQuoteProvider",
        FakeWeatherQuoteProvider,
    )

    result = asyncio.run(scheduler.open_position_risk_job())

    assert result.total_open_positions == 0
    assert seen["db"] is dummy_db
    assert isinstance(seen["weather_quote_provider"], FakeWeatherQuoteProvider)
    assert seen["kwargs"] == {}
    assert dummy_db.closed is True
