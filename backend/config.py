"""Configuration settings for the Weather Edge signal dashboard."""
import os
from typing import Optional
try:
    from dotenv import load_dotenv
except ImportError:  # optional in lightweight test/runtime environments
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False

load_dotenv()

def _bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None: return default
    return val.strip().lower() in ("1", "true", "yes")

def _float(key: str, default: float) -> float:
    try: return float(os.environ.get(key, default))
    except: return default

def _int(key: str, default: int) -> int:
    try: return int(os.environ.get(key, default))
    except: return default

def _str(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key) or default


class Settings:
    def __init__(self):
        self.reload_from_env()

    def reload_from_env(self):
        self.DATABASE_URL = _str("DATABASE_URL", "sqlite:///./tradingbot.db")
        self.POLYMARKET_API_KEY = _str("POLYMARKET_API_KEY")
        self.KALSHI_API_KEY_ID = _str("KALSHI_API_KEY_ID")
        self.KALSHI_PRIVATE_KEY_PATH = _str("KALSHI_PRIVATE_KEY_PATH")
        self.KALSHI_ENABLED = _bool("KALSHI_ENABLED", True)
        self.GROQ_API_KEY = _str("GROQ_API_KEY")
        self.GROQ_MODEL = _str("GROQ_MODEL", "llama-3.1-8b-instant")
        self.AI_LOG_ALL_CALLS = _bool("AI_LOG_ALL_CALLS", True)
        self.AI_DAILY_BUDGET_USD = _float("AI_DAILY_BUDGET_USD", 1.0)
        self.SIMULATION_MODE = _bool("SIMULATION_MODE", True)
        self.INITIAL_BANKROLL = _float("INITIAL_BANKROLL", 10000.0)
        self.KELLY_FRACTION = _float("KELLY_FRACTION", 0.15)
        self.SCAN_INTERVAL_SECONDS = _int("SCAN_INTERVAL_SECONDS", 60)
        self.SETTLEMENT_INTERVAL_SECONDS = _int("SETTLEMENT_INTERVAL_SECONDS", 120)
        self.BTC_PRICE_SOURCE = _str("BTC_PRICE_SOURCE", "coinbase")
        self.MIN_EDGE_THRESHOLD = _float("MIN_EDGE_THRESHOLD", 0.02)
        self.MAX_ENTRY_PRICE = _float("MAX_ENTRY_PRICE", 0.55)
        self.MAX_TRADES_PER_WINDOW = _int("MAX_TRADES_PER_WINDOW", 1)
        self.MAX_TOTAL_PENDING_TRADES = _int("MAX_TOTAL_PENDING_TRADES", 20)
        self.DAILY_LOSS_LIMIT = _float("DAILY_LOSS_LIMIT", 300.0)
        self.MAX_TRADE_SIZE = _float("MAX_TRADE_SIZE", 75.0)
        self.MIN_TIME_REMAINING = _int("MIN_TIME_REMAINING", 60)
        self.MAX_TIME_REMAINING = _int("MAX_TIME_REMAINING", 1800)
        self.WEIGHT_RSI = _float("WEIGHT_RSI", 0.20)
        self.WEIGHT_MOMENTUM = _float("WEIGHT_MOMENTUM", 0.35)
        self.WEIGHT_VWAP = _float("WEIGHT_VWAP", 0.20)
        self.WEIGHT_SMA = _float("WEIGHT_SMA", 0.15)
        self.WEIGHT_MARKET_SKEW = _float("WEIGHT_MARKET_SKEW", 0.10)
        self.MIN_MARKET_VOLUME = _float("MIN_MARKET_VOLUME", 100.0)
        self.BTC_ENABLED = _bool("BTC_ENABLED", False)
        self.WEATHER_ENABLED = _bool("WEATHER_ENABLED", True)
        self.WEATHER_SCAN_INTERVAL_SECONDS = _int("WEATHER_SCAN_INTERVAL_SECONDS", 300)
        self.WEATHER_NOWCAST_INTERVAL_SECONDS = _int("WEATHER_NOWCAST_INTERVAL_SECONDS", 60)
        self.WEATHER_SETTLEMENT_INTERVAL_SECONDS = _int("WEATHER_SETTLEMENT_INTERVAL_SECONDS", 1800)
        self.WEATHER_MIN_EDGE_THRESHOLD = _float("WEATHER_MIN_EDGE_THRESHOLD", 0.08)
        self.WEATHER_MAX_ENTRY_PRICE = _float("WEATHER_MAX_ENTRY_PRICE", 0.70)
        self.WEATHER_MAX_TRADE_SIZE = _float("WEATHER_MAX_TRADE_SIZE", 100.0)
        self.WEATHER_CITIES = _str("WEATHER_CITIES", "nyc,chicago,miami,los_angeles,denver")
        self.WEATHER_SOURCE_BENCHMARK_HISTORY_PATH = _str("WEATHER_SOURCE_BENCHMARK_HISTORY_PATH", "data/weather_source_benchmark_history.jsonl")


settings = Settings()
