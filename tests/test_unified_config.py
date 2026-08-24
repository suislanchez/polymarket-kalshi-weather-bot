"""Deterministic defaults for the unified paper-trading runtime."""

import pytest

from backend.config import Settings


def test_unified_paper_runtime_defaults():
    settings = Settings(_env_file=None)

    assert settings.EXECUTION_MODE == "paper"
    assert settings.LIVE_TRADING_ENABLED is False
    assert settings.ACTIVE_PRODUCT_SCOPE == "unified_paper"
    assert settings.STOCK_CRYPTO_LANE_ENABLED is False
    assert settings.DATABASE_URL == (
        "sqlite:////Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/"
        "data/ledgers/tradingbot.db"
    )
    assert settings.DATABASE_URL.startswith("sqlite:////Volumes/Archives/")
    assert "sqlite:///./" not in settings.DATABASE_URL
    assert settings.TRADING_SYSTEM_ROOT == (
        "/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/"
        "unified-trading-system"
    )
    assert settings.TRADING_DATA_ROOT == (
        "/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/data"
    )
    assert settings.TRADING_ARTIFACTS_ROOT == (
        "/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/artifacts"
    )
    assert settings.TRADING_LOG_ROOT == (
        "/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/logs"
    )
    assert settings.TRADING_SYMBOL_ALLOWLIST == "SPY,QQQ,BTC/USD,ETH/USD"


@pytest.mark.parametrize(
    ("setting_name", "expected"),
    [
        ("MAX_ORDER_NOTIONAL_USD", 250.0),
        ("MAX_ORDER_EQUITY_FRACTION", 0.01),
        ("MAX_SYMBOL_EXPOSURE_FRACTION", 0.05),
        ("MAX_GROSS_EXPOSURE_FRACTION", 0.25),
        ("MAX_CRYPTO_EXPOSURE_FRACTION", 0.10),
        ("MAX_DAILY_LOSS_FRACTION", 0.01),
        ("MAX_MARKET_DATA_AGE_SECONDS", 30),
    ],
)
def test_unified_risk_defaults(setting_name, expected):
    settings = Settings(_env_file=None)

    assert getattr(settings, setting_name) == expected


def test_global_trading_kill_switch_defaults_to_off():
    settings = Settings(_env_file=None)

    assert settings.GLOBAL_TRADING_KILL_SWITCH is False


def test_alpaca_defaults_are_paper_only_and_credential_free():
    settings = Settings(_env_file=None)

    assert settings.ALPACA_PAPER_BASE_URL == "https://paper-api.alpaca.markets"
    assert settings.ALPACA_API_KEY == ""
    assert settings.ALPACA_API_SECRET == ""


def test_existing_safe_lifecycle_and_weather_defaults_are_preserved():
    settings = Settings(_env_file=None)

    assert settings.SIMULATION_MODE is True
    assert settings.SCHEDULER_AUTOSTART is True
    assert settings.BTC_LANE_ENABLED is False
    assert settings.WEATHER_ENABLED is True
    assert settings.WEATHER_RESEARCH_ENABLED is True
