from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core import weather_signals as ws
from backend.models import database as db_models
from backend.models.database import Base


def test_weather_observation_store_persists_unique_raw_observations(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'observations.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(ws, "SessionLocal", Session)

    observed = datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    fetched = datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc)
    observation = ws.WeatherObservation(
        source="aviationweather_metar",
        station_id="KJFK",
        observed_at=observed,
        fetched_at=fetched,
        temp_f=86.0,
        raw={"temp": 30.0, "rawOb": "KJFK 031551Z AUTO"},
        raw_hash="same-hash",
        source_url="https://aviationweather.gov/api/data/metar?ids=KJFK&format=json&hours=12",
    )
    signal = ws.WeatherTradingSignal(
        market=ws.KalshiWeatherMarket(
            market_id="KXHIGHTNY-26JUN03-T85",
            slug="KXHIGHTNY-26JUN03-T85",
            city_key="nyc",
            city_name="New York City",
            target_date=date(2026, 6, 3),
            threshold_f=85.0,
        ),
        edge=0.22,
        weather_observation=observation,
        signal_at=datetime(2026, 6, 3, 15, 52, 5, tzinfo=timezone.utc),
    )

    ws._persist_weather_signals([signal, signal])

    with Session() as session:
        rows = session.query(db_models.WeatherObservationRecord).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.source == "aviationweather_metar"
        assert row.station_id == "KJFK"
        assert row.market_ticker == "KXHIGHTNY-26JUN03-T85"
        assert row.raw_hash == "same-hash"
        assert row.temp_f == 86.0
        assert row.observation_latency_seconds == 60.0
        assert row.signal_latency_seconds == 5.0
        assert row.raw_payload["rawOb"] == "KJFK 031551Z AUTO"
