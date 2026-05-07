"""Configuration settings for the Weather Edge signal dashboard."""
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes")


def _float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except Exception:
        return default


def _int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except Exception:
        return default


def _str(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key) or default


class Settings:
    def __init__(self):
        self.reload_from_env()

    def reload_from_env(self):
        self.DATABASE_URL = _str("DATABASE_URL", "sqlite:///./tradingbot.db")
        self.KALSHI_API_KEY_ID = _str("KALSHI_API_KEY_ID")
        self.KALSHI_PRIVATE_KEY_PATH = _str("KALSHI_PRIVATE_KEY_PATH")
        self.KALSHI_ENABLED = _bool("KALSHI_ENABLED", True)
        self.SIMULATION_MODE = _bool("SIMULATION_MODE", True)
        self.INITIAL_BANKROLL = _float("INITIAL_BANKROLL", 10000.0)
        self.KELLY_FRACTION = _float("KELLY_FRACTION", 0.15)
        self.DAILY_LOSS_LIMIT = _float("DAILY_LOSS_LIMIT", 300.0)
        self.WEATHER_ENABLED = _bool("WEATHER_ENABLED", True)
        self.WEATHER_SCAN_INTERVAL_SECONDS = _int("WEATHER_SCAN_INTERVAL_SECONDS", 300)
        self.WEATHER_SETTLEMENT_INTERVAL_SECONDS = _int("WEATHER_SETTLEMENT_INTERVAL_SECONDS", 1800)
        self.WEATHER_MIN_EDGE_THRESHOLD = _float("WEATHER_MIN_EDGE_THRESHOLD", 0.08)
        self.WEATHER_MAX_ENTRY_PRICE = _float("WEATHER_MAX_ENTRY_PRICE", 0.70)
        self.WEATHER_MAX_TRADE_SIZE = _float("WEATHER_MAX_TRADE_SIZE", 100.0)
        self.WEATHER_CITIES = _str("WEATHER_CITIES", "nyc,chicago,miami,los_angeles,denver")


settings = Settings()
