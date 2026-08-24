"""Dependency-light, immutable contracts for normalized paper trading."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Annotated, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    model_validator,
)


class AssetClass(str, Enum):
    """Asset families supported by the unified paper-trading runtime."""

    STOCK = "stock"
    CRYPTO = "crypto"
    PREDICTION_WEATHER = "prediction_weather"


class Venue(str, Enum):
    """Approved paper or simulation venues."""

    ALPACA_PAPER = "alpaca_paper"
    POLYMARKET_PAPER = "polymarket_paper"
    KALSHI_PAPER = "kalshi_paper"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PROPOSED = "proposed"
    RISK_REJECTED = "risk_rejected"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must be a nonblank stable string")
    return value


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware UTC")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


def _freeze_json(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _freeze_json_object(value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    frozen = MappingProxyType(
        {key: _freeze_json(item) for key, item in value.items()}
    )
    return cast(Mapping[str, JsonValue], frozen)


def _thaw_json(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return cast(JsonValue, value)


NonBlankString = Annotated[str, AfterValidator(_require_nonblank)]
UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
FrozenJsonObject = Annotated[
    Mapping[str, JsonValue],
    AfterValidator(_freeze_json_object),
    PlainSerializer(_thaw_json, return_type=dict[str, JsonValue]),
]


class DomainModel(BaseModel):
    """Shared strictness for all values crossing trading boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class SizedOrderModel(DomainModel):
    """Shared normalized size and order-price invariants."""

    quantity: PositiveDecimal | None = None
    notional: PositiveDecimal | None = None
    order_type: OrderType = OrderType.MARKET
    limit_price: PositiveDecimal | None = None

    @model_validator(mode="after")
    def validate_size_and_limit(self) -> SizedOrderModel:
        if self.quantity is None and self.notional is None:
            raise ValueError("positive quantity or notional is required")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        return self


class TradeProposal(SizedOrderModel):
    """A strategy proposal that has not yet passed deterministic risk checks."""

    proposal_id: NonBlankString
    strategy_id: NonBlankString
    venue: Venue
    asset_class: AssetClass
    symbol: NonBlankString
    side: Side
    reference_price: PositiveDecimal
    market_data_at: UtcDatetime
    created_at: UtcDatetime
    rationale: NonBlankString
    metadata: FrozenJsonObject = Field(default_factory=dict)


class RiskDecision(DomainModel):
    """Deterministic risk result plus the limits active at decision time."""

    proposal_id: NonBlankString
    approved: bool
    reason_codes: tuple[NonBlankString, ...] = ()
    approved_quantity: PositiveDecimal | None = None
    approved_notional: PositiveDecimal | None = None
    decided_at: UtcDatetime
    limit_snapshot: FrozenJsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_decision_size(self) -> RiskDecision:
        has_quantity = self.approved_quantity is not None
        has_notional = self.approved_notional is not None
        if self.approved:
            if has_quantity == has_notional:
                raise ValueError(
                    "approved decisions require exactly one approved sizing field"
                )
        else:
            if has_quantity or has_notional:
                raise ValueError("rejected decisions prohibit approved sizing fields")
            if not self.reason_codes:
                raise ValueError("rejected decisions require at least one reason code")
        return self


class NormalizedOrder(SizedOrderModel):
    """Risk-normalized paper order passed to a venue adapter."""

    client_order_id: NonBlankString
    proposal_id: NonBlankString
    venue: Venue
    asset_class: AssetClass
    symbol: NonBlankString
    side: Side
    status: OrderStatus
    created_at: UtcDatetime
    metadata: FrozenJsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unambiguous_size(self) -> NormalizedOrder:
        if (self.quantity is None) == (self.notional is None):
            raise ValueError("normalized orders require exactly one sizing field")
        return self


class ExecutionReport(DomainModel):
    """Normalized adapter report for an order lifecycle transition."""

    client_order_id: NonBlankString
    venue: Venue
    status: OrderStatus
    broker_order_id: NonBlankString | None = None
    filled_quantity: NonNegativeDecimal = Decimal("0")
    filled_notional: NonNegativeDecimal = Decimal("0")
    average_fill_price: PositiveDecimal | None = None
    rejection_reason: NonBlankString | None = None
    occurred_at: UtcDatetime
    metadata: FrozenJsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_lifecycle_values(self) -> ExecutionReport:
        rejection_statuses = {OrderStatus.RISK_REJECTED, OrderStatus.REJECTED}
        fill_statuses = {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED}
        has_fill = self.filled_quantity > 0 or self.filled_notional > 0

        if self.status in rejection_statuses:
            if self.rejection_reason is None:
                raise ValueError("rejection statuses require rejection_reason")
            if has_fill or self.average_fill_price is not None:
                raise ValueError("rejection statuses prohibit fills and average_fill_price")
            return self

        if self.rejection_reason is not None:
            raise ValueError("non-rejection statuses prohibit rejection_reason")
        if self.status in fill_statuses and not has_fill:
            raise ValueError("fill statuses require a positive fill basis")
        if has_fill and self.average_fill_price is None:
            raise ValueError("positive fills require average_fill_price")
        if self.average_fill_price is not None and not has_fill:
            raise ValueError("average_fill_price requires a positive fill basis")
        return self


class PositionSnapshot(DomainModel):
    """Normalized long-only position state from a paper venue."""

    venue: Venue
    asset_class: AssetClass
    symbol: NonBlankString
    quantity: PositiveDecimal
    cost_basis: NonNegativeDecimal
    market_value: NonNegativeDecimal
    average_entry_price: PositiveDecimal
    current_price: PositiveDecimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    captured_at: UtcDatetime
    metadata: FrozenJsonObject = Field(default_factory=dict)


class AccountSnapshot(DomainModel):
    """Normalized account balances and positions at one UTC instant."""

    venue: Venue
    cash: NonNegativeDecimal
    equity: PositiveDecimal
    buying_power: NonNegativeDecimal
    captured_at: UtcDatetime
    positions: tuple[PositionSnapshot, ...] = ()
    metadata: FrozenJsonObject = Field(default_factory=dict)


__all__ = [
    "AccountSnapshot",
    "AssetClass",
    "ExecutionReport",
    "NormalizedOrder",
    "OrderStatus",
    "OrderType",
    "PositionSnapshot",
    "RiskDecision",
    "Side",
    "TradeProposal",
    "Venue",
]
