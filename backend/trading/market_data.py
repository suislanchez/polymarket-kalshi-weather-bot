"""Typed, validated OHLCV market data for deterministic strategies.

Bars are exact Decimals parsed from strings. A series is refused outright if it is
unordered, has duplicate timestamps, carries a non-positive price, or is missing a
field: a strategy must never have to decide whether its own inputs are trustworthy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from pydantic import Field, model_validator

from backend.trading.domain import (
    AssetClass,
    DomainModel,
    NonBlankString,
    PositiveDecimal,
    UtcDatetime,
)

_REQUIRED_BAR_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")


class MarketDataError(ValueError):
    """Raised when market data is missing, malformed, or internally inconsistent."""


class MarketBar(DomainModel):
    """One immutable OHLCV bar at a UTC instant."""

    timestamp: UtcDatetime
    open: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    close: PositiveDecimal
    volume: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> MarketBar:
        if self.high < self.low:
            raise ValueError("bar high must not be below bar low")
        if not (self.low <= self.open <= self.high):
            raise ValueError("bar open must lie within the bar range")
        if not (self.low <= self.close <= self.high):
            raise ValueError("bar close must lie within the bar range")
        return self


class BarSeries(DomainModel):
    """A strictly increasing run of bars for one symbol."""

    symbol: NonBlankString
    asset_class: AssetClass
    bars: tuple[MarketBar, ...]

    @model_validator(mode="after")
    def validate_ordering(self) -> BarSeries:
        if not self.bars:
            raise ValueError("a bar series requires at least one bar")
        previous: datetime | None = None
        for bar in self.bars:
            if previous is not None and bar.timestamp <= previous:
                raise ValueError("bars must be strictly increasing in time")
            previous = bar.timestamp
        return self

    @property
    def latest(self) -> MarketBar:
        return self.bars[-1]

    def closes(self) -> tuple[Decimal, ...]:
        return tuple(bar.close for bar in self.bars)


def _decimal(raw: object, field: str) -> Decimal:
    """Parse an exact finite decimal from a string, refusing floats."""
    failed = False
    value: Decimal | None = None
    try:
        if type(raw) is Decimal:
            value = raw
        elif type(raw) is str and raw.strip():
            value = Decimal(raw)
        elif type(raw) is int and not isinstance(raw, bool):
            value = Decimal(raw)
        else:
            failed = True
        if value is not None and not value.is_finite():
            failed = True
    except (InvalidOperation, ValueError, ArithmeticError):
        failed = True
    if failed or value is None:
        raise MarketDataError(f"market data field {field} was not an exact finite decimal")
    return value


def _timestamp(raw: object) -> datetime:
    failed = False
    parsed: datetime | None = None
    try:
        if type(raw) is datetime:
            parsed = raw
        elif type(raw) is str and raw.strip():
            parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        else:
            failed = True
        if parsed is not None and parsed.tzinfo is None:
            failed = True
        elif parsed is not None and parsed.utcoffset() != timedelta(0):
            parsed = parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        failed = True
    if failed or parsed is None:
        raise MarketDataError("market data timestamp was not a UTC instant")
    return parsed


def load_bar_series(payload: Mapping[str, object]) -> BarSeries:
    """Build a validated BarSeries from a plain mapping, or raise MarketDataError."""
    if not isinstance(payload, Mapping):
        raise MarketDataError("bar series payload must be a mapping")

    symbol = payload.get("symbol")
    if type(symbol) is not str or not symbol.strip():
        raise MarketDataError("bar series requires a non-blank symbol")

    raw_class = payload.get("asset_class")
    try:
        asset_class = AssetClass(raw_class)
    except ValueError:
        raise MarketDataError("bar series asset class is unrecognized") from None
    if asset_class is AssetClass.PREDICTION_WEATHER:
        # Spot strategies and prediction-market weather signals stay separate.
        raise MarketDataError("prediction-weather series are not spot market data")

    raw_bars = payload.get("bars")
    if not isinstance(raw_bars, Sequence) or isinstance(raw_bars, (str, bytes)) or not raw_bars:
        raise MarketDataError("bar series requires a non-empty sequence of bars")

    bars: list[MarketBar] = []
    for raw in raw_bars:
        if not isinstance(raw, Mapping):
            raise MarketDataError("each bar must be a mapping")
        missing = [f for f in _REQUIRED_BAR_FIELDS if f not in raw]
        if missing:
            raise MarketDataError(f"bar is missing required fields: {sorted(missing)}")
        unknown = [f for f in raw if f not in _REQUIRED_BAR_FIELDS]
        if unknown:
            # Refuse silently-ignored fields: an unexpected key usually means the
            # feed shape changed, which is exactly when guessing is unsafe.
            raise MarketDataError(f"bar has unexpected fields: {sorted(unknown)}")
        try:
            bars.append(
                MarketBar(
                    timestamp=_timestamp(raw["timestamp"]),
                    open=_decimal(raw["open"], "open"),
                    high=_decimal(raw["high"], "high"),
                    low=_decimal(raw["low"], "low"),
                    close=_decimal(raw["close"], "close"),
                    volume=_decimal(raw["volume"], "volume"),
                )
            )
        except MarketDataError:
            raise
        except Exception:
            raise MarketDataError("bar failed validation") from None

    try:
        return BarSeries(symbol=symbol, asset_class=asset_class, bars=tuple(bars))
    except Exception:
        raise MarketDataError("bar series failed validation") from None


__all__ = ["BarSeries", "MarketBar", "MarketDataError", "load_bar_series"]
