"""Pure, deterministic risk authorization for unified paper-trading proposals."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Annotated, Any, Self, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    field_validator,
)

from backend.trading.domain import (
    AssetClass,
    RiskDecision,
    Side,
    TradeProposal,
    Venue,
)


class _ImmutableMapping(Mapping[str, Decimal]):
    """Small recursively-safe immutable mapping for injected portfolio state."""

    __slots__ = ("_data",)

    def __init__(self, values: Mapping[str, Decimal]) -> None:
        self._data = MappingProxyType(dict(values))

    def __getitem__(self, key: str) -> Decimal:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        memo[id(self)] = self
        return self

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Mapping) and self._data == other

    def __repr__(self) -> str:
        return repr(self._data)


def _positive_finite(value: Decimal) -> Decimal:
    if not value.is_finite() or value <= 0:
        raise ValueError("value must be finite and positive")
    return value


def _nonnegative_finite(value: Decimal) -> Decimal:
    if not value.is_finite() or value < 0:
        raise ValueError("value must be finite and nonnegative")
    return value


def _finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("value must be finite")
    return value


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must be nonblank")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware UTC")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


def _freeze_decimal_mapping(value: Mapping[str, Decimal]) -> Mapping[str, Decimal]:
    return _ImmutableMapping(value)


def _dump_decimal_mapping(value: Mapping[str, Decimal]) -> dict[str, Decimal]:
    return dict(value)


PositiveFiniteDecimal = Annotated[Decimal, AfterValidator(_positive_finite)]
NonnegativeFiniteDecimal = Annotated[Decimal, AfterValidator(_nonnegative_finite)]
FiniteDecimal = Annotated[Decimal, AfterValidator(_finite)]
NonblankString = Annotated[str, AfterValidator(_nonblank)]
UtcDatetime = Annotated[datetime, AfterValidator(_utc)]
FrozenDecimalMapping = Annotated[
    Mapping[NonblankString, NonnegativeFiniteDecimal],
    AfterValidator(_freeze_decimal_mapping),
    PlainSerializer(_dump_decimal_mapping, return_type=dict[str, Decimal]),
]


class _RiskModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        if not update:
            return super().model_copy(update=update, deep=deep)
        candidate = {
            field_name: getattr(self, field_name)
            for field_name in type(self).model_fields
        }
        candidate.update(update)
        validated = type(self).model_validate(candidate)
        validated_update = {
            field_name: getattr(validated, field_name) for field_name in update
        }
        return super().model_copy(update=validated_update, deep=deep)


class RiskLimits(_RiskModel):
    """Versioned risk policy injected into each deterministic evaluation."""

    max_order_notional: PositiveFiniteDecimal
    max_order_equity_fraction: PositiveFiniteDecimal
    max_symbol_exposure_fraction: PositiveFiniteDecimal
    max_gross_exposure_fraction: PositiveFiniteDecimal
    max_crypto_exposure_fraction: PositiveFiniteDecimal
    daily_loss_fraction: PositiveFiniteDecimal
    stock_crypto_max_quote_age_seconds: PositiveFiniteDecimal
    weather_max_quote_age_seconds: PositiveFiniteDecimal
    allowed_symbols: frozenset[NonblankString]
    allowed_venues: frozenset[Venue]

    @field_validator("allowed_symbols", "allowed_venues")
    @classmethod
    def require_nonempty_allowlist(cls, value: frozenset[object]) -> frozenset[object]:
        if not value:
            raise ValueError("allowlist must not be empty")
        return value

    def snapshot(self) -> dict[str, JsonValue]:
        """Return a detached, stable, JSON-compatible view of active limits."""

        return cast(
            dict[str, JsonValue],
            {
                "max_order_notional": str(self.max_order_notional),
                "max_order_equity_fraction": str(
                    self.max_order_equity_fraction
                ),
                "max_symbol_exposure_fraction": str(
                    self.max_symbol_exposure_fraction
                ),
                "max_gross_exposure_fraction": str(
                    self.max_gross_exposure_fraction
                ),
                "max_crypto_exposure_fraction": str(
                    self.max_crypto_exposure_fraction
                ),
                "daily_loss_fraction": str(self.daily_loss_fraction),
                "stock_crypto_max_quote_age_seconds": str(
                    self.stock_crypto_max_quote_age_seconds
                ),
                "weather_max_quote_age_seconds": str(
                    self.weather_max_quote_age_seconds
                ),
                "allowed_symbols": sorted(self.allowed_symbols),
                "allowed_venues": sorted(
                    venue.value for venue in self.allowed_venues
                ),
            },
        )


class PortfolioState(_RiskModel):
    """Injected account state required for deterministic limit arithmetic."""

    equity: PositiveFiniteDecimal
    start_of_day_nlv: PositiveFiniteDecimal
    daily_realized_pnl: FiniteDecimal
    symbol_exposures: FrozenDecimalMapping = Field(default_factory=dict)
    gross_exposure: NonnegativeFiniteDecimal
    crypto_exposure: NonnegativeFiniteDecimal
    held_quantities: FrozenDecimalMapping = Field(default_factory=dict)


class RiskContext(_RiskModel):
    """Injected clock, mode, idempotency, and upstream authorization evidence."""

    now: UtcDatetime
    execution_mode: NonblankString
    idempotency_key: NonblankString
    seen_idempotency_keys: frozenset[NonblankString] = Field(default_factory=frozenset)
    global_kill_switch: bool = False
    weather_upstream_approved: bool = False
    weather_approval_evidence: tuple[NonblankString, ...] = ()


def _effective_notional(proposal: TradeProposal) -> Decimal:
    candidates: list[Decimal] = []
    if proposal.notional is not None:
        candidates.append(proposal.notional)
    if proposal.quantity is not None:
        candidates.append(proposal.quantity * proposal.reference_price)
    return min(candidates)


def _largest_implied_quantity(proposal: TradeProposal) -> Decimal:
    candidates: list[Decimal] = []
    if proposal.quantity is not None:
        candidates.append(proposal.quantity)
    if proposal.notional is not None:
        candidates.append(proposal.notional / proposal.reference_price)
    return max(candidates)


def _project(current: Decimal, change: Decimal, side: Side) -> Decimal:
    if side is Side.BUY:
        return current + change
    return max(Decimal("0"), current - change)


def evaluate_proposal(
    proposal: TradeProposal | None,
    portfolio: PortfolioState,
    context: RiskContext,
    limits: RiskLimits,
) -> RiskDecision | None:
    """Evaluate every applicable hard gate in stable order without side effects."""

    if proposal is None:
        return None

    reasons: list[str] = []
    effective_notional = _effective_notional(proposal)

    if context.execution_mode != "paper":
        reasons.append("execution_mode_not_paper")
    if context.global_kill_switch:
        reasons.append("global_kill_switch")
    if context.idempotency_key in context.seen_idempotency_keys:
        reasons.append("duplicate_idempotency_key")
    if proposal.venue not in limits.allowed_venues:
        reasons.append("venue_not_allowed")

    coherent_venue = (
        proposal.venue is Venue.ALPACA_PAPER
        if proposal.asset_class in {AssetClass.STOCK, AssetClass.CRYPTO}
        else proposal.venue in {Venue.POLYMARKET_PAPER, Venue.KALSHI_PAPER}
    )
    if not coherent_venue:
        reasons.append("asset_venue_mismatch")

    if (
        proposal.asset_class in {AssetClass.STOCK, AssetClass.CRYPTO}
        and proposal.symbol not in limits.allowed_symbols
    ):
        reasons.append("symbol_not_allowed")

    if proposal.asset_class is AssetClass.PREDICTION_WEATHER and not (
        context.weather_upstream_approved and context.weather_approval_evidence
    ):
        reasons.append("weather_upstream_not_approved")

    if proposal.side is Side.SELL:
        held = portfolio.held_quantities.get(proposal.symbol, Decimal("0"))
        if _largest_implied_quantity(proposal) > held:
            reasons.append("opening_short_not_allowed")

    order_cap = min(
        limits.max_order_notional,
        portfolio.equity * limits.max_order_equity_fraction,
    )
    if effective_notional > order_cap:
        reasons.append("order_notional_limit")

    symbol_exposure = portfolio.symbol_exposures.get(proposal.symbol, Decimal("0"))
    projected_symbol = _project(symbol_exposure, effective_notional, proposal.side)
    if projected_symbol > portfolio.equity * limits.max_symbol_exposure_fraction:
        reasons.append("symbol_exposure_limit")

    projected_gross = _project(
        portfolio.gross_exposure, effective_notional, proposal.side
    )
    if projected_gross > portfolio.equity * limits.max_gross_exposure_fraction:
        reasons.append("gross_exposure_limit")

    if proposal.asset_class is AssetClass.CRYPTO:
        projected_crypto = _project(
            portfolio.crypto_exposure, effective_notional, proposal.side
        )
        if projected_crypto > portfolio.equity * limits.max_crypto_exposure_fraction:
            reasons.append("crypto_exposure_limit")

    daily_loss_threshold = -(portfolio.start_of_day_nlv * limits.daily_loss_fraction)
    if portfolio.daily_realized_pnl <= daily_loss_threshold:
        reasons.append("daily_loss_limit")

    quote_age = context.now - proposal.market_data_at
    quote_age_seconds = Decimal(quote_age.days * 86_400 + quote_age.seconds) + (
        Decimal(quote_age.microseconds) / Decimal("1000000")
    )
    if quote_age_seconds < 0:
        reasons.append("future_market_data")
    else:
        max_age = (
            limits.weather_max_quote_age_seconds
            if proposal.asset_class is AssetClass.PREDICTION_WEATHER
            else limits.stock_crypto_max_quote_age_seconds
        )
        if quote_age_seconds > max_age:
            reasons.append("stale_market_data")

    if reasons:
        return RiskDecision(
            proposal_id=proposal.proposal_id,
            approved=False,
            reason_codes=tuple(reasons),
            decided_at=context.now,
            limit_snapshot=limits.snapshot(),
        )
    return RiskDecision(
        proposal_id=proposal.proposal_id,
        approved=True,
        reason_codes=(),
        approved_notional=effective_notional,
        decided_at=context.now,
        limit_snapshot=limits.snapshot(),
    )


__all__ = ["PortfolioState", "RiskContext", "RiskLimits", "evaluate_proposal"]
