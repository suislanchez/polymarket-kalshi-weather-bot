"""Configuration settings for the BTC 5-min trading bot."""
import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database (SQLite for Phase 1, PostgreSQL for production)
    DATABASE_URL: str = "sqlite:///./tradingbot.db"

    # Polymarket APIs
    POLYMARKET_GAMMA_API: str = "https://gamma-api.polymarket.com"
    POLYMARKET_DATA_API: str = "https://data-api.polymarket.com"
    POLYMARKET_CLOB_API: str = "https://clob.polymarket.com"

    # Legacy/short key field kept for compatibility with older local config.
    POLYMARKET_API_KEY: Optional[str] = None

    # CLOB L2 API credentials. These enable authenticated CLOB reads/order
    # management only when the full L2 tuple is present. Order creation still
    # requires a local signer/private key and remains disabled by default.
    POLYMARKET_API_KEY_ID: Optional[str] = None
    POLYMARKET_API_SECRET: Optional[str] = None
    POLYMARKET_API_PASSPHRASE: Optional[str] = None
    POLYMARKET_ADDRESS: Optional[str] = None
    POLYMARKET_FUNDER_ADDRESS: Optional[str] = None
    POLYMARKET_SIGNATURE_TYPE: int = 3
    POLYMARKET_ENABLE_AUTHENTICATED_CLOB: bool = False

    # Polymarket relayer credentials, if using the separate relayer path.
    RELAYER_API_KEY: Optional[str] = None
    RELAYER_API_KEY_ADDRESS: Optional[str] = None

    # Kalshi API
    KALSHI_API_KEY_ID: Optional[str] = None
    KALSHI_PRIVATE_KEY_PATH: Optional[str] = None
    KALSHI_ENABLED: bool = True

    # AI API Keys
    GROQ_API_KEY: Optional[str] = None

    # AI Model Configuration
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # AI Feature Flags
    AI_LOG_ALL_CALLS: bool = True
    AI_DAILY_BUDGET_USD: float = 1.0

    # Unified paper-trading runtime. Live trading is rejected during app startup.
    EXECUTION_MODE: str = "paper"
    LIVE_TRADING_ENABLED: bool = False
    ACTIVE_PRODUCT_SCOPE: str = "unified_paper"
    STOCK_CRYPTO_LANE_ENABLED: bool = False
    TRADING_SYSTEM_ROOT: str = "/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/unified-trading-system"
    TRADING_DATA_ROOT: str = "/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/data"
    TRADING_ARTIFACTS_ROOT: str = "/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/artifacts"
    TRADING_LOG_ROOT: str = "/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/logs"
    TRADING_SYMBOL_ALLOWLIST: str = "SPY,QQQ,BTC/USD,ETH/USD"

    # Unified risk controls
    MAX_ORDER_NOTIONAL_USD: float = 250.0
    MAX_ORDER_EQUITY_FRACTION: float = 0.01
    MAX_SYMBOL_EXPOSURE_FRACTION: float = 0.05
    MAX_GROSS_EXPOSURE_FRACTION: float = 0.25
    MAX_CRYPTO_EXPOSURE_FRACTION: float = 0.10
    MAX_DAILY_LOSS_FRACTION: float = 0.01
    MAX_MARKET_DATA_AGE_SECONDS: int = 30
    GLOBAL_TRADING_KILL_SWITCH: bool = False

    # Alpaca paper API only. Credentials are blank by default.
    ALPACA_PAPER_BASE_URL: str = "https://paper-api.alpaca.markets"
    ALPACA_API_KEY: str = ""
    ALPACA_API_SECRET: str = ""

    # Legacy dashboard sections remain hidden unless explicitly requested.
    DASHBOARD_LEGACY_SECTIONS_ENABLED: bool = False

    # Scheduler / app lifecycle
    # When False, FastAPI startup constructs the app WITHOUT launching any
    # background scan/settlement/heartbeat jobs. Read-only API smokes and the
    # FastAPI TestClient should set SCHEDULER_AUTOSTART=false so importing or
    # constructing the app never triggers market scans or paper trades.
    SCHEDULER_AUTOSTART: bool = True
    # Legacy BTC 5-min prediction-market lane. Disabled by default under the
    # unified-paper product scope. This is the canonical off-switch for BTC
    # scanning — do not rely on MIN_EDGE_THRESHOLD=999 to suppress actionability.
    BTC_LANE_ENABLED: bool = False

    # Bot settings - BTC 5-MIN TRADING
    SIMULATION_MODE: bool = True
    INITIAL_BANKROLL: float = 10000.0
    KELLY_FRACTION: float = 0.15  # Fractional Kelly

    # BTC 5-min specific settings
    SCAN_INTERVAL_SECONDS: int = 60  # Scan every minute
    SETTLEMENT_INTERVAL_SECONDS: int = 120  # Check settlements every 2 min
    BTC_PRICE_SOURCE: str = "coinbase"
    MIN_EDGE_THRESHOLD: float = 0.02  # 2% edge required — these are 50/50 markets
    MAX_ENTRY_PRICE: float = 0.55  # Enter up to 55c
    MAX_TRADES_PER_WINDOW: int = 1
    MAX_TOTAL_PENDING_TRADES: int = 20

    # Risk management
    DAILY_LOSS_LIMIT: float = 300.0
    MAX_TRADE_SIZE: float = 75.0
    MIN_TIME_REMAINING: int = 60  # Don't trade windows closing in < 60s
    MAX_TIME_REMAINING: int = 1800  # Trade windows up to 30min out

    # Indicator weights for composite signal (must sum to ~1.0)
    WEIGHT_RSI: float = 0.20
    WEIGHT_MOMENTUM: float = 0.35
    WEIGHT_VWAP: float = 0.20
    WEIGHT_SMA: float = 0.15
    WEIGHT_MARKET_SKEW: float = 0.10

    # Volume filter
    MIN_MARKET_VOLUME: float = 100.0  # Low volume for 5-min markets

    # Weather trading settings
    WEATHER_ENABLED: bool = True
    # Read-only weather research/dashboard mode. This may remain enabled even
    # when WEATHER_ENABLED/KALSHI_ENABLED are false in .env to avoid starting
    # schedulers or private-account features while still allowing public market
    # data discovery, signal review, and paper/simulation analysis.
    WEATHER_RESEARCH_ENABLED: bool = True
    WEATHER_SCAN_INTERVAL_SECONDS: int = 300  # 5 min
    # Bounded concurrency for per-scan forecast prefetch and signal generation.
    WEATHER_SCAN_CONCURRENCY: int = 8
    WEATHER_SETTLEMENT_INTERVAL_SECONDS: int = 1800  # 30 min
    WEATHER_MIN_EDGE_THRESHOLD: float = 0.08  # 8% — weather has more signal than 5-min BTC
    WEATHER_MAX_ENTRY_PRICE: float = 0.70
    WEATHER_MAX_TRADE_SIZE: float = 100.0
    WEATHER_CITIES: str = "nyc,chicago,miami,los_angeles,denver,seattle,boston,seoul,tokyo,beijing,shanghai,london,paris,singapore,hong_kong,austin,houston"
    # Kalshi weather paper execution is deliberately monitor-only by default
    # while the venue-specific paper ledger is underperforming; public Kalshi
    # discovery/signals/calibration remain enabled.
    WEATHER_KALSHI_PAPER_EXECUTION_ENABLED: bool = False

    # Weather risk controls + scoring
    WEATHER_DAILY_LOSS_LIMIT: float = 200.0
    WEATHER_MAX_OPEN_POSITIONS_PER_CITY: int = 2

    # Open-position risk manager (paper/simulation only)
    PAPER_POSITION_RISK_ENABLED: bool = True
    PAPER_AUTO_EXIT_ENABLED: bool = False
    POSITION_RISK_SCAN_INTERVAL_SECONDS: int = 120
    EXIT_HARD_MODEL_PROB_THRESHOLD: float = 0.15
    EXIT_HARD_MARKET_PROB_THRESHOLD: float = 0.10
    EXIT_MIN_SELL_PRICE: float = 0.03
    EXIT_MAX_SPREAD: float = 0.20
    EXIT_MIN_TOP_BID_SIZE: float = 5.0
    EXIT_HOLD_EV_MARGIN: float = 0.02
    WEATHER_EXIT_MODEL_PROB_THRESHOLD: float = 0.15
    WEATHER_EXIT_FINAL_SOURCE_CONFIDENCE_REQUIRED: bool = True
    WEATHER_EXIT_NEAR_FINAL_HOURS: float = 2.0
    WEATHER_EXIT_MIN_SOURCE_ALIGNMENT: int = 2
    BTC_EXIT_MODEL_PROB_THRESHOLD: float = 0.20
    BTC_EXIT_NEAR_CLOSE_SECONDS: int = 90
    BTC_EXIT_STRONG_FLIP_EDGE: float = 0.08
    ENTERTAINMENT_EXIT_MODEL_PROB_THRESHOLD: float = 0.15
    ENTERTAINMENT_EXIT_MIN_REVIEW_COUNT: int = 30

    # Composite score tuning for weather execution
    WEATHER_COMPOSITE_MIN_SCORE: float = 0.10
    WEATHER_WEIGHT_MISPRICING: float = 0.60
    WEATHER_WEIGHT_SPREAD: float = 0.20
    WEATHER_WEIGHT_LIQUIDITY: float = 0.15
    WEATHER_WEIGHT_IMBALANCE: float = 0.05

    # Probability calibration / anti-overconfidence (weather)
    # Re-estimates P(YES) with a variance-inflated Gaussian and gates actionability
    # on a confidence flag so clipped 95%/5% unanimity near a threshold cannot,
    # by itself, drive a paper trade. See backend/core/weather_calibration.py.
    WEATHER_CALIBRATION_ENABLED: bool = True
    WEATHER_CALIBRATION_MIN_STD_F: float = 1.5
    WEATHER_CALIBRATION_STD_INFLATION: float = 1.5
    WEATHER_CALIBRATION_MIN_CONFIDENT_Z: float = 1.0
    WEATHER_CALIBRATION_MIN_MEMBERS: int = 20

    # Optional secondary forecast provider (NOAA AIGEFS)
    WEATHER_USE_AIGEFS: bool = False
    WEATHER_AIGEFS_WEIGHT: float = 0.50
    WEATHER_AIGEFS_ENDPOINT_TEMPLATE: str = "https://noaa-hwp-pds.s3.amazonaws.com/aigefs/{date}/{city}.json"

    class Config:
        env_file = ".env"


settings = Settings()
