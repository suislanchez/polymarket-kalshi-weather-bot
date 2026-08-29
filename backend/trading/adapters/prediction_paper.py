"""Deterministic, credential-free simulation of binary prediction-market venues.

This module is a *simulation*, not a venue client. It has no network surface, no
credentials, and no order-signing or CLOB machinery, and it never mutates account
state: the append-only event ledger remains the single source of truth for
positions and cash. Both weather venues are simulated by the same engine because
they price the same instrument -- a binary outcome share quoted in (0, 1).

Sizing is notional-only. The weather lane this preserves has always sized in
dollars, and refusing contract-count sizing keeps the simulation from inventing a
share count the legacy path never had.

The decimal helpers below intentionally duplicate the ones in ``fake.py``: the
adapter import policy confines these modules to the adapter package, and a
production adapter must not take a runtime dependency on a test double.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from decimal import (
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    Rounded,
    localcontext,
)

from backend.trading.adapters.base import (
    BrokerAdapterError,
    DuplicateClientOrderIdError,
    OrderNotCancelableError,
    OrderNotFoundError,
)
from backend.trading.domain import (
    AccountSnapshot,
    AssetClass,
    ExecutionReport,
    NormalizedOrder,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    Venue,
)
from backend.trading.execution_mode import require_paper_mode

MONITOR_ONLY_REASON = "venue_monitor_only"

PREDICTION_VENUES = frozenset({Venue.POLYMARKET_PAPER, Venue.KALSHI_PAPER})

_DENIED_METADATA_KEYS = frozenset(
    {
        "api_key",
        "api_secret",
        "secret_key",
        "access_token",
        "password",
        "credential",
        "credentials",
    }
)
_VALIDATION_TIME = datetime(1970, 1, 1, tzinfo=timezone.utc)
# Deterministic division runs at >= 28 significant digits, so any real drift is
# many orders of magnitude below this; the bound exists to catch a broken quotient.
_RECONCILIATION_TOLERANCE = Decimal("0.00000001")


def _decimal_context(*, precision: int = 28, exact: bool = False) -> Context:
    """Return a fresh arithmetic context independent of ambient process state."""

    context = Context(
        prec=precision,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
    )
    for trap in context.traps:
        context.traps[trap] = False
    for trap in (InvalidOperation, DivisionByZero, Overflow):
        context.traps[trap] = True
    if exact:
        context.traps[Inexact] = True
        context.traps[Rounded] = True
    context.clear_flags()
    return context


def _coefficient_digits(value: Decimal) -> int:
    return len(value.as_tuple().digits)


def _exact_multiply(left: Decimal, right: Decimal) -> Decimal:
    precision = max(28, _coefficient_digits(left) + _coefficient_digits(right))
    with localcontext(_decimal_context(precision=precision, exact=True)):
        return left * right


def _digit_span(value: Decimal) -> int:
    """Digits needed to write a finite Decimal out in full, including its scale."""
    digits, exponent = value.as_tuple().digits, value.as_tuple().exponent
    return len(digits) + (abs(exponent) if type(exponent) is int else 0)


def _exact_absolute_difference(left: Decimal, right: Decimal) -> Decimal:
    """Absolute difference in a context wide enough to hold both operands exactly.

    The reconciliation check below is the guard that makes an inexact quotient
    safe to book, so it must not inherit the caller's ambient decimal context: a
    process running at low precision could otherwise round real drift down to
    zero and the check would approve the fill it exists to refuse.
    """

    precision = max(28, _digit_span(left) + _digit_span(right))
    with localcontext(_decimal_context(precision=precision, exact=True)):
        return abs(left - right)


def _deterministic_divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Divide exactly when the quotient terminates, otherwise deterministically."""

    if denominator == Decimal("1"):
        return numerator

    digit_budget = _coefficient_digits(numerator) + _coefficient_digits(denominator)
    precision = max(28, 4 * digit_budget)
    try:
        with localcontext(_decimal_context(precision=precision, exact=True)):
            return numerator / denominator
    except (Inexact, Rounded):
        with localcontext(_decimal_context(precision=precision)):
            return numerator / denominator


def _floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    """Largest whole multiple of ``increment`` not exceeding ``value``.

    Rounding down, never to nearest: a simulated fill must never claim more
    shares than the ordered notional pays for.
    """

    precision = max(28, _digit_span(value) + _digit_span(increment))
    with localcontext(_decimal_context(precision=precision)):
        return value.quantize(increment, rounding=ROUND_DOWN)


class PredictionMarketPaperAdapter:
    """Shared simulation engine for paper prediction-market venues.

    Client order identifiers are echoed back in execution reports; callers must
    never place secrets in identifiers.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        venue: Venue,
        adapter_name: str,
        execution_enabled: bool,
        share_increment: Decimal,
        cash: Decimal = Decimal("10000.00"),
        equity: Decimal = Decimal("10000.00"),
        buying_power: Decimal = Decimal("10000.00"),
        positions: Iterable[PositionSnapshot] = (),
    ) -> None:
        if type(venue) is not Venue or venue not in PREDICTION_VENUES:
            raise BrokerAdapterError("adapter venue must be a paper prediction venue")
        if type(adapter_name) is not str or not adapter_name.strip():
            raise BrokerAdapterError("adapter name must be a nonblank string")
        if type(execution_enabled) is not bool:
            raise BrokerAdapterError("execution_enabled must be an explicit bool")
        if (
            type(share_increment) is not Decimal
            or not share_increment.is_finite()
            or share_increment <= 0
        ):
            raise BrokerAdapterError("share increment must be a positive Decimal")

        position_materialization_failed = False
        position_items: tuple[PositionSnapshot, ...] = ()
        try:
            position_items = tuple(positions)
        except Exception:
            position_materialization_failed = True
        if position_materialization_failed:
            raise BrokerAdapterError("position fixtures failed") from None
        if not all(type(position) is PositionSnapshot for position in position_items):
            raise BrokerAdapterError("positions must contain PositionSnapshot values")
        fixtures = tuple(
            PositionSnapshot.model_copy(position, deep=True) for position in position_items
        )
        if any(position.venue is not venue for position in fixtures):
            raise BrokerAdapterError("position fixture venue must match adapter venue")

        report_metadata = {"adapter": adapter_name, "simulation": True}
        validated = AccountSnapshot(
            venue=venue,
            cash=cash,
            equity=equity,
            buying_power=buying_power,
            captured_at=_VALIDATION_TIME,
            positions=fixtures,
            metadata=report_metadata,
        )

        self._clock = clock
        self._venue = venue
        self._name = adapter_name
        self._execution_enabled = execution_enabled
        self._share_increment = share_increment
        self._report_metadata = report_metadata
        self._cash = validated.cash
        self._equity = validated.equity
        self._buying_power = validated.buying_power
        self._positions = fixtures
        self._reports: dict[str, ExecutionReport] = {}
        self._fingerprints: dict[str, str] = {}
        self._transition_sequences: dict[str, int] = {}
        self._broker_counter = 0
        self._transition_counter = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def paper_only(self) -> bool:
        return True

    @property
    def execution_enabled(self) -> bool:
        return self._execution_enabled

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(name='{self._name}', "
            f"venue='{self._venue.value}', paper_only=True)"
        )

    # -- clock and snapshots -------------------------------------------------

    def _read_clock(self) -> datetime:
        failed = False
        value: object = None
        normalized: datetime | None = None
        try:
            value = self._clock()
        except Exception:
            failed = True

        if not failed:
            try:
                if (
                    type(value) is not datetime
                    or value.tzinfo is None
                    or value.utcoffset() != timezone.utc.utcoffset(None)
                ):
                    failed = True
                else:
                    normalized = datetime(
                        value.year,
                        value.month,
                        value.day,
                        value.hour,
                        value.minute,
                        value.second,
                        value.microsecond,
                        tzinfo=timezone.utc,
                        fold=value.fold,
                    )
            except Exception:
                failed = True

        if failed or normalized is None:
            raise BrokerAdapterError("adapter clock failed") from None
        return normalized

    def _captured_positions(self, captured_at: datetime) -> tuple[PositionSnapshot, ...]:
        return tuple(
            PositionSnapshot.model_copy(
                position, update={"captured_at": captured_at}, deep=True
            )
            for position in self._positions
        )

    def get_account_snapshot(self) -> AccountSnapshot:
        captured_at = self._read_clock()
        return AccountSnapshot(
            venue=self._venue,
            cash=self._cash,
            equity=self._equity,
            buying_power=self._buying_power,
            captured_at=captured_at,
            positions=self._captured_positions(captured_at),
            metadata=self._report_metadata,
        )

    def list_positions(self) -> tuple[PositionSnapshot, ...]:
        return self._captured_positions(self._read_clock())

    # -- metadata hygiene ----------------------------------------------------

    @staticmethod
    def _normalize_metadata_key(key: object) -> str:
        normalized = str(key).strip().lower()
        result: list[str] = []
        in_separator = False
        for character in normalized:
            is_separator = character in "_-" or character.isspace()
            if is_separator:
                if not in_separator:
                    result.append("_")
            else:
                result.append(character)
            in_separator = is_separator
        return "".join(result).strip("_")

    @classmethod
    def _contains_denied_metadata_key(cls, value: object) -> bool:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if cls._normalize_metadata_key(key) in _DENIED_METADATA_KEYS:
                    return True
                if cls._contains_denied_metadata_key(item):
                    return True
            return False
        if isinstance(value, (tuple, list)):
            return any(cls._contains_denied_metadata_key(item) for item in value)
        return False

    @staticmethod
    def _fingerprint(order: NormalizedOrder) -> str:
        canonical = json.dumps(
            NormalizedOrder.model_dump(order, mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _record_transition(self, client_order_id: str, report: ExecutionReport) -> None:
        self._transition_counter += 1
        self._reports[client_order_id] = report
        self._transition_sequences[client_order_id] = self._transition_counter

    # -- order lifecycle -----------------------------------------------------

    def _validate_order(self, order: NormalizedOrder) -> Decimal:
        """Return the simulated fill price after rejecting anything unsupported."""

        if type(order) is not NormalizedOrder:
            raise BrokerAdapterError("order must be a NormalizedOrder")
        if order.status is not OrderStatus.APPROVED:
            raise BrokerAdapterError("adapter accepts approved orders only")
        if order.venue is not self._venue:
            raise BrokerAdapterError("order venue must match adapter venue")
        if order.asset_class is not AssetClass.PREDICTION_WEATHER:
            raise BrokerAdapterError("adapter accepts prediction weather orders only")
        if order.order_type is not OrderType.LIMIT:
            raise BrokerAdapterError(
                "binary outcome shares require a limit price; market orders are refused"
            )
        price = order.limit_price
        if price is None or not price.is_finite() or not (Decimal("0") < price < Decimal("1")):
            raise BrokerAdapterError(
                "limit price must fall inside the open probability interval"
            )
        if order.notional is None or order.quantity is not None:
            raise BrokerAdapterError("prediction paper orders must be sized by notional")
        if self._contains_denied_metadata_key(order.metadata):
            raise BrokerAdapterError("order contains a prohibited metadata key")
        return price

    def _simulated_fill(
        self, notional: Decimal, price: Decimal
    ) -> tuple[Decimal, Decimal] | None:
        """Fill whole share increments and report what those shares actually cost.

        The recorded notional is DERIVED from the share count rather than passed
        through from the order. That direction matters: the execution boundary
        requires filled_quantity * average_fill_price to equal filled_notional
        exactly, and a share count is a non-terminating quotient for most prices
        (50 / 0.56). Passing the ordered notional through would make the two
        disagree in the last digits for about six prices in seven, and every one
        of those fills would be discarded downstream as an invalid report.

        Sizing down to the venue's increment is also what a venue does -- shares
        are not infinitely divisible -- so the residual cash simply goes unspent.

        Returns None when the notional cannot buy even one increment.
        """

        try:
            raw_quantity = _deterministic_divide(notional, price)
            quantity = _floor_to_increment(raw_quantity, self._share_increment)
            if not quantity.is_finite():
                raise BrokerAdapterError("simulated fill arithmetic failed")
            if quantity <= 0:
                return None
            filled_notional = _exact_multiply(quantity, price)
            if not filled_notional.is_finite():
                raise BrokerAdapterError("simulated fill arithmetic failed")
            overspend = _exact_absolute_difference(filled_notional, notional)
        except DecimalException:
            raise BrokerAdapterError("simulated fill arithmetic failed") from None
        # Comparisons, not arithmetic: Decimal comparisons are exact and take no
        # rounding from the active context.
        if filled_notional > notional or overspend > notional:
            raise BrokerAdapterError("simulated fill exceeded the ordered notional")
        return quantity, filled_notional

    def submit_order(
        self, order: NormalizedOrder, *, execution_mode: str
    ) -> ExecutionReport:
        require_paper_mode(execution_mode)
        price = self._validate_order(order)

        fingerprint = self._fingerprint(order)
        prior = self._reports.get(order.client_order_id)
        if prior is not None:
            if self._fingerprints[order.client_order_id] != fingerprint:
                raise DuplicateClientOrderIdError(
                    "client order payload conflicts with an existing order"
                )
            return prior

        occurred_at = self._read_clock()
        if not self._execution_enabled:
            # Monitor-only venues observe and record, but never simulate a fill.
            report = ExecutionReport(
                client_order_id=order.client_order_id,
                venue=self._venue,
                status=OrderStatus.REJECTED,
                rejection_reason=MONITOR_ONLY_REASON,
                occurred_at=occurred_at,
                metadata=self._report_metadata,
            )
            self._fingerprints[order.client_order_id] = fingerprint
            self._record_transition(order.client_order_id, report)
            return report

        notional = order.notional
        if notional is None:  # pragma: no cover - _validate_order already required it
            raise BrokerAdapterError("prediction paper orders must be sized by notional")
        fill = self._simulated_fill(notional, price)
        if fill is None:
            report = ExecutionReport(
                client_order_id=order.client_order_id,
                venue=self._venue,
                status=OrderStatus.REJECTED,
                rejection_reason="notional_below_one_share_increment",
                occurred_at=occurred_at,
                metadata=self._report_metadata,
            )
            self._fingerprints[order.client_order_id] = fingerprint
            self._record_transition(order.client_order_id, report)
            return report

        filled_quantity, filled_notional = fill
        next_broker_counter = self._broker_counter + 1
        report = ExecutionReport(
            client_order_id=order.client_order_id,
            venue=self._venue,
            status=OrderStatus.FILLED,
            broker_order_id=f"{self._name}-{next_broker_counter:06d}",
            filled_quantity=filled_quantity,
            filled_notional=filled_notional,
            average_fill_price=price,
            occurred_at=occurred_at,
            metadata=self._report_metadata,
        )
        self._broker_counter = next_broker_counter
        self._fingerprints[order.client_order_id] = fingerprint
        self._record_transition(order.client_order_id, report)
        return report

    def cancel_order(self, client_order_id: str) -> ExecutionReport:
        report = self._reports.get(client_order_id)
        if report is None:
            raise OrderNotFoundError("order was not found")
        if report.status is OrderStatus.CANCELED:
            return report
        if report.status not in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}:
            raise OrderNotCancelableError("order is not cancelable")

        canceled = report.model_copy(
            update={"status": OrderStatus.CANCELED, "occurred_at": self._read_clock()}
        )
        self._record_transition(client_order_id, canceled)
        return canceled

    def get_order(self, client_order_id: str) -> ExecutionReport | None:
        return self._reports.get(client_order_id)

    def list_recent_orders(self, *, limit: int = 100) -> tuple[ExecutionReport, ...]:
        if type(limit) is not int:
            raise TypeError("limit must be an int")
        if limit < 0:
            raise ValueError("limit must be non-negative")
        ordered_ids = sorted(
            self._transition_sequences,
            key=self._transition_sequences.__getitem__,
            reverse=True,
        )
        return tuple(self._reports[client_order_id] for client_order_id in ordered_ids[:limit])


__all__ = [
    "MONITOR_ONLY_REASON",
    "PREDICTION_VENUES",
    "PredictionMarketPaperAdapter",
]
