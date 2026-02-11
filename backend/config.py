"""Configuration settings for the trading bot."""
import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database (SQLite for Phase 1, PostgreSQL for production)
    DATABASE_URL: str = "sqlite:///./tradingbot.db"

    # API Keys (optional - most APIs are free without keys)
    KALSHI_API_KEY: Optional[str] = None
    KALSHI_API_SECRET: Optional[str] = None
    POLYMARKET_API_KEY: Optional[str] = None
    FRED_API_KEY: Optional[str] = None
    BLS_API_KEY: Optional[str] = None
    MAPBOX_TOKEN: Optional[str] = None

    # AI API Keys
    ANTHROPIC_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None

    # AI Model Configuration - USE GROQ ONLY (basically free)
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"  # Only for manual/critical analysis
    GROQ_MODEL: str = "llama-3.1-8b-instant"  # Fast & FREE - use this for everything

    # AI Feature Flags - COST OPTIMIZED
    AI_ENHANCED_SIGNALS: bool = False  # Disable Claude (expensive) - use Groq only
    AI_FAST_CLASSIFICATION: bool = True  # Use Groq for classification (free)
    AI_LOG_ALL_CALLS: bool = True  # Log all AI API calls
    AI_DAILY_BUDGET_USD: float = 1.0  # Low budget - rely on Groq (free)
    AI_MAX_CALLS_PER_SCAN: int = 3  # Limit AI calls per scan

    # Category Settings
    ENABLED_CATEGORIES: list = ["weather", "crypto", "politics", "economics"]
    EXCLUDE_SPORTS: bool = True  # Always exclude sports markets

    # Bot settings - AGGRESSIVE SHORT-TERM TRADING
    SIMULATION_MODE: bool = True  # Always True for Phase 1
    INITIAL_BANKROLL: float = 10000.0  # Virtual bankroll
    KELLY_FRACTION: float = 0.30  # Aggressive - 30% Kelly
    MIN_EDGE_THRESHOLD: float = 0.03  # Low threshold - 3% edge is enough

    # Aggressive filters - focus on SHORT-TERM
    MIN_MARKET_VOLUME: float = 1000.0  # Lower volume requirement
    MAX_DAYS_TO_RESOLUTION: int = 7  # Only markets resolving within 1 WEEK
    MAX_TRADES_PER_CATEGORY: int = 10  # More per category
    MAX_TOTAL_PENDING_TRADES: int = 50  # Lots of positions

    # Polling intervals (seconds)
    MARKET_SCAN_INTERVAL: int = 60
    WEATHER_UPDATE_INTERVAL: int = 300

    # NWS grid points for supported cities
    # Format: {city: (office, grid_x, grid_y)}
    NWS_GRID_POINTS: dict = {
        "nyc": ("OKX", 33, 37),
        "chicago": ("LOT", 65, 76),
        "miami": ("MFL", 110, 50),
        "austin": ("EWX", 52, 68),
        "los_angeles": ("LOX", 154, 44),
        "atlanta": ("FFC", 52, 88),
        "denver": ("BOU", 62, 60),
        "seattle": ("SEW", 124, 67),
        "dallas": ("FWD", 79, 108),
        "boston": ("BOX", 71, 90),
    }

    # City coordinates for map display
    CITY_COORDS: dict = {
        "nyc": (40.7128, -74.0060),
        "chicago": (41.8781, -87.6298),
        "miami": (25.7617, -80.1918),
        "austin": (30.2672, -97.7431),
        "los_angeles": (34.0522, -118.2437),
        "atlanta": (33.7490, -84.3880),
        "denver": (39.7392, -104.9903),
        "seattle": (47.6062, -122.3321),
        "dallas": (32.7767, -96.7970),
        "boston": (42.3601, -71.0589),
        "london": (51.5074, -0.1278),
        "seoul": (37.5665, 126.9780),
        "buenos_aires": (-34.6037, -58.3816),
    }

    class Config:
        env_file = ".env"


settings = Settings()
