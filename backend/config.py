"""Configuration settings for the BTC 5-min trading bot."""
import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database (SQLite for Phase 1, PostgreSQL for production)
    DATABASE_URL: str = "sqlite:///./tradingbot.db"

    # API Keys (optional)
    POLYMARKET_API_KEY: Optional[str] = None

    # AI API Keys
    GROQ_API_KEY: Optional[str] = None

    # AI Model Configuration
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # AI Feature Flags
    AI_LOG_ALL_CALLS: bool = True
    AI_DAILY_BUDGET_USD: float = 1.0

    # Bot settings - BTC 5-MIN TRADING
    SIMULATION_MODE: bool = True
    INITIAL_BANKROLL: float = 10000.0
    KELLY_FRACTION: float = 0.10  # 1/3 Kelly — conservative for noisy edges

    # BTC 5-min specific settings
    SCAN_INTERVAL_SECONDS: int = 90  # Scan every 90s — slower = fewer trades
    SETTLEMENT_INTERVAL_SECONDS: int = 120  # Check settlements every 2 min
    BTC_PRICE_SOURCE: str = "binance"
    MIN_EDGE_THRESHOLD: float = 0.05  # 5% edge required
    MAX_ENTRY_PRICE: float = 0.48  # Need wider payout margin
    MAX_TRADES_PER_WINDOW: int = 1  # One trade per window max
    MAX_TOTAL_PENDING_TRADES: int = 8  # Hard cap on exposure

    # Risk management
    DAILY_LOSS_LIMIT: float = 200.0  # Stop trading after $200 daily loss
    MAX_TRADE_SIZE: float = 50.0  # Hard cap per trade in dollars
    MIN_TIME_REMAINING: int = 90  # Don't trade windows closing in < 90s
    MAX_TIME_REMAINING: int = 270  # Don't trade windows > 4.5min out

    # Indicator weights for composite signal (must sum to ~1.0)
    WEIGHT_RSI: float = 0.20
    WEIGHT_MOMENTUM: float = 0.35
    WEIGHT_VWAP: float = 0.20
    WEIGHT_SMA: float = 0.15
    WEIGHT_MARKET_SKEW: float = 0.10

    # Volume filter
    MIN_MARKET_VOLUME: float = 100.0  # Low volume for 5-min markets

    class Config:
        env_file = ".env"


settings = Settings()
