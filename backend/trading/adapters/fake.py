"""Credential-free deterministic paper broker simulation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import (
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    ROUND_HALF_EVEN,
    Rounded,
    localcontext,
)
from typing import cast

from backend.trading.adapters.base import (
    BrokerAdapterError,
    DuplicateClientOrderIdError,
    OrderNotCancelableError,
    OrderNotFoundError,
)
from backend.trading.domain import (
    AccountSnapshot,
    ExecutionReport,
    NormalizedOrder,
    OrderStatus,
    PositionSnapshot,
    Venue,
)
from backend.trading.execution_mode import require_paper_mode


_REPORT_METADATA = {"adapter": "fake-paper", "simulation": True}
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
    for signal in context.traps:
        context.traps[signal] = False
    for signal in (InvalidOperation, DivisionByZero, Overflow):
        context.traps[signal] = True
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


def _deterministic_divide(numerator: Decimal, denominator: Decimal) -> Decimal:
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


@dataclass(frozen=True, slots=True)
class FakeOrderScenario:
    """One deterministic result selected by a client's order identifier."""

    status: OrderStatus = OrderStatus.SUBMITTED
    fill_fraction: Decimal = Decimal("0")
    average_fill_price: Decimal | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not OrderStatus:
            raise ValueError("invalid fake order scenario")
        if not isinstance(self.fill_fraction, Decimal):
            raise TypeError("fill_fraction must be a Decimal")
        if self.average_fill_price is not None and not isinstance(
            self.average_fill_price, Decimal
        ):
            raise TypeError("average_fill_price must be a Decimal")
        if not self.fill_fraction.is_finite() or (
            self.average_fill_price is not None
            and not self.average_fill_price.is_finite()
        ):
            raise ValueError("invalid fake order scenario")

        empty = self.fill_fraction == 0 and self.average_fill_price is None
        if self.status in {OrderStatus.SUBMITTED, OrderStatus.REJECTED}:
            valid = empty
        elif self.status is OrderStatus.PARTIALLY_FILLED:
            valid = (
                Decimal("0") < self.fill_fraction < Decimal("1")
                and self.average_fill_price is not None
                and self.average_fill_price > 0
            )
        elif self.status is OrderStatus.FILLED:
            valid = (
                self.fill_fraction == Decimal("1")
                and self.average_fill_price is not None
                and self.average_fill_price > 0
            )
        else:
            valid = False
        if not valid:
            raise ValueError("invalid fake order scenario")


class FakePaperAdapter:
    """In-memory deterministic adapter with no credentials or external effects.

    Client order identifiers are returned in execution reports; callers must never
    place secrets in identifiers.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        venue: Venue = Venue.ALPACA_PAPER,
        cash: Decimal = Decimal("100000.00"),
        equity: Decimal = Decimal("100000.00"),
        buying_power: Decimal = Decimal("100000.00"),
        positions: Iterable[PositionSnapshot] = (),
        scenarios: Mapping[str, FakeOrderScenario] | None = None,
    ) -> None:
        if not isinstance(venue, Venue):
            raise BrokerAdapterError("adapter venue must be a Venue")
        fixtures = tuple(position.model_copy(deep=True) for position in positions)
        if any(position.venue is not venue for position in fixtures):
            raise BrokerAdapterError("position fixture venue must match adapter venue")

        validated = AccountSnapshot(
            venue=venue,
            cash=cash,
            equity=equity,
            buying_power=buying_power,
            captured_at=_VALIDATION_TIME,
            positions=fixtures,
            metadata=_REPORT_METADATA,
        )
        scenario_items = tuple(scenarios.items()) if scenarios is not None else ()
        if not all(type(key) is str and bool(key.strip()) for key, _ in scenario_items):
            raise BrokerAdapterError("scenario keys must be nonblank strings")
        if not all(isinstance(value, FakeOrderScenario) for _, value in scenario_items):
            raise TypeError("scenarios must contain FakeOrderScenario values")
        scenario_map = dict(scenario_items)

        self._clock = clock
        self._venue = venue
        self._cash = validated.cash
        self._equity = validated.equity
        self._buying_power = validated.buying_power
        self._positions = fixtures
        self._scenarios = scenario_map
        self._reports: dict[str, ExecutionReport] = {}
        self._fingerprints: dict[str, str] = {}
        self._transition_sequences: dict[str, int] = {}
        self._broker_counter = 0
        self._transition_counter = 0

    @property
    def name(self) -> str:
        return "fake-paper"

    @property
    def paper_only(self) -> bool:
        return True

    def __repr__(self) -> str:
        return (
            "FakePaperAdapter(name='fake-paper', "
            f"venue='{self._venue.value}', paper_only=True)"
        )

    def _captured_positions(self, captured_at: datetime) -> tuple[PositionSnapshot, ...]:
        return tuple(
            position.model_copy(update={"captured_at": captured_at}, deep=True)
            for position in self._positions
        )

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

    def get_account_snapshot(self) -> AccountSnapshot:
        captured_at = self._read_clock()
        return AccountSnapshot(
            venue=self._venue,
            cash=self._cash,
            equity=self._equity,
            buying_power=self._buying_power,
            captured_at=captured_at,
            positions=self._captured_positions(captured_at),
            metadata=_REPORT_METADATA,
        )

    def list_positions(self) -> tuple[PositionSnapshot, ...]:
        return self._captured_positions(self._read_clock())

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
        return "".join(result)

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
            order.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _record_transition(self, client_order_id: str, report: ExecutionReport) -> None:
        self._transition_counter += 1
        self._reports[client_order_id] = report
        self._transition_sequences[client_order_id] = self._transition_counter

    @staticmethod
    def _fill_values(
        order: NormalizedOrder, scenario: FakeOrderScenario
    ) -> tuple[Decimal, Decimal, Decimal | None, str | None]:
        filled_quantity = Decimal("0")
        filled_notional = Decimal("0")
        average_fill_price = None
        rejection_reason = None
        if scenario.status in {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED}:
            average_fill_price = cast(Decimal, scenario.average_fill_price)
            try:
                if order.quantity is not None:
                    filled_quantity = _exact_multiply(
                        order.quantity, scenario.fill_fraction
                    )
                    filled_notional = _exact_multiply(
                        filled_quantity, average_fill_price
                    )
                else:
                    filled_notional = _exact_multiply(
                        cast(Decimal, order.notional), scenario.fill_fraction
                    )
                    filled_quantity = _deterministic_divide(
                        filled_notional, average_fill_price
                    )
            except DecimalException:
                raise BrokerAdapterError("simulated fill arithmetic failed") from None
            if (
                not filled_quantity.is_finite()
                or not filled_notional.is_finite()
                or filled_quantity <= 0
                or filled_notional <= 0
            ):
                raise BrokerAdapterError("simulated fill arithmetic failed")
        elif scenario.status is OrderStatus.REJECTED:
            rejection_reason = "simulated_rejection"
        return (
            filled_quantity,
            filled_notional,
            average_fill_price,
            rejection_reason,
        )

    def submit_order(
        self, order: NormalizedOrder, *, execution_mode: str
    ) -> ExecutionReport:
        require_paper_mode(execution_mode)
        if order.status is not OrderStatus.APPROVED:
            raise BrokerAdapterError("adapter accepts approved orders only")
        if order.venue is not self._venue:
            raise BrokerAdapterError("order venue must match adapter venue")
        if self._contains_denied_metadata_key(order.metadata):
            raise BrokerAdapterError("order contains a prohibited metadata key")

        fingerprint = self._fingerprint(order)
        prior = self._reports.get(order.client_order_id)
        if prior is not None:
            if self._fingerprints[order.client_order_id] != fingerprint:
                raise DuplicateClientOrderIdError(
                    "client order payload conflicts with an existing order"
                )
            return prior

        scenario = self._scenarios.get(order.client_order_id, FakeOrderScenario())
        next_broker_counter = self._broker_counter + 1
        broker_order_id = f"fake-paper-{next_broker_counter:06d}"
        (
            filled_quantity,
            filled_notional,
            average_fill_price,
            rejection_reason,
        ) = self._fill_values(order, scenario)
        occurred_at = self._read_clock()

        report = ExecutionReport(
            client_order_id=order.client_order_id,
            venue=self._venue,
            status=scenario.status,
            broker_order_id=broker_order_id,
            filled_quantity=filled_quantity,
            filled_notional=filled_notional,
            average_fill_price=average_fill_price,
            rejection_reason=rejection_reason,
            occurred_at=occurred_at,
            metadata=_REPORT_METADATA,
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


__all__ = ["FakeOrderScenario", "FakePaperAdapter"]
