from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.scheduler import (
    _open_weather_positions_by_city,
    _weather_daily_settled_pnl,
    _weather_paper_execution_blockers,
)
from backend.models.database import Base, Trade


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'weather_risk_controls.sqlite'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_weather_daily_settled_pnl_counts_weather_only(tmp_path):
    db = _session(tmp_path)
    now = datetime(2099, 1, 1, 12, 0, 0)
    marker = "test-weather-pnl"
    try:
        db.add_all(
            [
                Trade(
                    market_ticker=f"{marker}-wx-1",
                    platform="polymarket",
                    market_type="weather",
                    direction="yes",
                    entry_price=0.5,
                    size=10,
                    settled=True,
                    settlement_time=now,
                    pnl=-25.0,
                    model_probability=0.6,
                    market_price_at_entry=0.5,
                    edge_at_entry=0.1,
                ),
                Trade(
                    market_ticker=f"{marker}-btc-1",
                    platform="polymarket",
                    market_type="btc",
                    direction="up",
                    entry_price=0.5,
                    size=10,
                    settled=True,
                    settlement_time=now,
                    pnl=-999.0,
                    model_probability=0.6,
                    market_price_at_entry=0.5,
                    edge_at_entry=0.1,
                ),
            ]
        )
        db.commit()

        pnl = _weather_daily_settled_pnl(db, now.replace(hour=0, minute=0, second=0, microsecond=0))
        assert pnl <= -25.0
        assert pnl > -200.0
    finally:
        db.query(Trade).filter(Trade.market_ticker.like(f"{marker}%")).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_open_weather_positions_by_city_maps_from_signals(tmp_path):
    db = _session(tmp_path)
    marker = "test-city-cap"
    try:
        db.add_all(
            [
                Trade(
                    market_ticker=f"{marker}-chi-1",
                    platform="polymarket",
                    market_type="weather",
                    direction="yes",
                    entry_price=0.5,
                    size=10,
                    settled=False,
                    model_probability=0.6,
                    market_price_at_entry=0.5,
                    edge_at_entry=0.1,
                ),
                Trade(
                    market_ticker=f"{marker}-chi-2",
                    platform="polymarket",
                    market_type="weather",
                    direction="yes",
                    entry_price=0.5,
                    size=10,
                    settled=False,
                    model_probability=0.6,
                    market_price_at_entry=0.5,
                    edge_at_entry=0.1,
                ),
                Trade(
                    market_ticker=f"{marker}-nyc-1",
                    platform="polymarket",
                    market_type="weather",
                    direction="yes",
                    entry_price=0.5,
                    size=10,
                    settled=False,
                    model_probability=0.6,
                    market_price_at_entry=0.5,
                    edge_at_entry=0.1,
                ),
            ]
        )
        db.commit()

        signals = [
            SimpleNamespace(market=SimpleNamespace(market_id=f"{marker}-chi-1", city_key="chicago")),
            SimpleNamespace(market=SimpleNamespace(market_id=f"{marker}-chi-2", city_key="chicago")),
            SimpleNamespace(market=SimpleNamespace(market_id=f"{marker}-nyc-1", city_key="nyc")),
        ]

        counts = _open_weather_positions_by_city(db, signals)
        assert counts["chicago"] == 2
        assert counts["nyc"] == 1
    finally:
        db.query(Trade).filter(Trade.market_ticker.like(f"{marker}%")).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_weather_paper_execution_blocks_kalshi_by_default_and_preserves_polymarket(monkeypatch):
    kalshi_signal = SimpleNamespace(
        suggested_size=75.0,
        no_trade_reasons=[],
        market=SimpleNamespace(platform="kalshi", market_id="KXHIGHTBOS-26JUN08-T79"),
    )
    polymarket_signal = SimpleNamespace(
        suggested_size=75.0,
        no_trade_reasons=[],
        market=SimpleNamespace(platform="polymarket", market_id="pm-weather"),
    )

    monkeypatch.setattr(
        "backend.core.scheduler.settings.WEATHER_KALSHI_PAPER_EXECUTION_ENABLED",
        False,
        raising=False,
    )

    assert _weather_paper_execution_blockers(kalshi_signal) == [
        "Kalshi weather paper execution is monitor-only until venue calibration improves"
    ]
    assert _weather_paper_execution_blockers(polymarket_signal) == []

    monkeypatch.setattr(
        "backend.core.scheduler.settings.WEATHER_KALSHI_PAPER_EXECUTION_ENABLED",
        True,
        raising=False,
    )
    assert _weather_paper_execution_blockers(kalshi_signal) == []
