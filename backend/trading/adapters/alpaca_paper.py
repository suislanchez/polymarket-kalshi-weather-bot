"""Guarded Alpaca Paper broker adapter.

The paper endpoint and paper execution mode are both confirmed BEFORE a client is
ever constructed, so a misconfigured runtime cannot reach a live Alpaca host even
transiently. Credentials are held only to hand to the injected factory; they are
never rendered, logged, or allowed into an error message.

This adapter wraps the smallest stable broker surface it needs. API routes and
strategies must never instantiate an Alpaca client directly -- everything routes
through PaperExecutionService and the deterministic risk gate.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import (
    Clamped,
    Context,
    Decimal,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Underflow,
    localcontext,
)

from backend.trading.adapters.base import BrokerAdapterError
from backend.trading.domain import (
    AccountSnapshot,
    AssetClass,
    ExecutionReport,
    NormalizedOrder,
    OrderStatus,
    PositionSnapshot,
    Venue,
)

PAPER_BASE_URL = "https://paper-api.alpaca.markets"

_STATUS_MAP = {
    "new": OrderStatus.SUBMITTED,
    "accepted": OrderStatus.SUBMITTED,
    "pending_new": OrderStatus.SUBMITTED,
    "accepted_for_bidding": OrderStatus.SUBMITTED,
    # In-flight states map to SUBMITTED. Reporting a live order as terminal would let
    # the ledger close it while the broker still holds it, so these fail SAFE, not closed.
    "pending_cancel": OrderStatus.SUBMITTED,
    "pending_replace": OrderStatus.SUBMITTED,
    "pending_review": OrderStatus.SUBMITTED,
    "calculated": OrderStatus.SUBMITTED,
    "held": OrderStatus.SUBMITTED,
    "stopped": OrderStatus.SUBMITTED,
    "suspended": OrderStatus.SUBMITTED,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED,
    "cancelled": OrderStatus.CANCELED,
    "expired": OrderStatus.CANCELED,
    "done_for_day": OrderStatus.CANCELED,
    "replaced": OrderStatus.CANCELED,
    "rejected": OrderStatus.REJECTED,
}

_ASSET_CLASS_MAP = {
    "us_equity": AssetClass.STOCK,
    "equity": AssetClass.STOCK,
    "crypto": AssetClass.CRYPTO,
}


class AlpacaPaperAdapterError(BrokerAdapterError):
    """Sanitized, context-free Alpaca paper adapter failure."""


ClientFactory = Callable[..., object]


class AlpacaPaperAdapter:
    """Synchronous Alpaca Paper adapter built from an injected client factory."""

    name = "alpaca-paper"
    paper_only = True

    def __init__(
        self,
        *,
        client_factory: ClientFactory,
        base_url: object,
        execution_mode: object,
        api_key: object = "",
        api_secret: object = "",
        clock: Callable[[], datetime],
    ) -> None:
        # Endpoint and mode are validated BEFORE the factory runs. An exact string
        # match is required: no normalization, no trailing slash, no case folding,
        # so a lookalike host can never satisfy the check.
        if type(base_url) is not str or base_url != PAPER_BASE_URL:
            raise AlpacaPaperAdapterError(
                "Alpaca adapter accepts only the paper endpoint."
            ) from None
        if type(execution_mode) is not str or execution_mode != "paper":
            raise AlpacaPaperAdapterError(
                "Alpaca adapter requires paper execution mode."
            ) from None
        if type(api_key) is not str or type(api_secret) is not str:
            raise AlpacaPaperAdapterError(
                "Alpaca credentials must be strings."
            ) from None
        if not callable(client_factory) or not callable(clock):
            raise AlpacaPaperAdapterError(
                "Alpaca adapter requires callable dependencies."
            ) from None

        self._clock = clock
        failed = False
        client: object | None = None
        try:
            client = client_factory(
                base_url=PAPER_BASE_URL, api_key=api_key, api_secret=api_secret
            )
        except Exception:
            failed = True
        if failed or client is None:
            raise AlpacaPaperAdapterError(
                "Alpaca paper client could not be created."
            ) from None
        self._client = client

    # -- rendering must never expose credentials -------------------------------

    def __repr__(self) -> str:
        return f"<AlpacaPaperAdapter venue=alpaca_paper endpoint={PAPER_BASE_URL}>"

    __str__ = __repr__

    # -- internals -------------------------------------------------------------

    def _fail(self, message: str) -> AlpacaPaperAdapterError:
        """Raise a fixed message, never the broker's text, which may echo a key."""
        return AlpacaPaperAdapterError(message)

    def _now(self) -> datetime:
        failed = False
        value: object = None
        try:
            value = self._clock()
            if (
                type(value) is not datetime
                or value.tzinfo is None
                or value.utcoffset() != timedelta(0)
            ):
                raise ValueError
        except Exception:
            failed = True
        if failed or not isinstance(value, datetime):
            raise self._fail("Alpaca adapter clock failed.") from None
        return value.astimezone(timezone.utc)

    @staticmethod
    def _decimal(raw: object, field: str) -> Decimal:
        """Parse an exact decimal. Floats are refused: they cannot represent money.

        Non-finite values (NaN/Infinity) construct successfully as Decimals, so they are
        rejected explicitly here rather than escaping as a raw pydantic ValidationError
        that callers' BrokerAdapterError handlers would miss.
        """

        failed = False
        value: Decimal | None = None
        try:
            if type(raw) is Decimal:
                value = raw
            elif type(raw) is str and raw.strip():
                value = Decimal(raw)
            else:
                failed = True
            if value is not None and not value.is_finite():
                failed = True
        except (InvalidOperation, ValueError, ArithmeticError):
            failed = True
        if failed or value is None:
            raise AlpacaPaperAdapterError(
                f"Alpaca response field {field} was not an exact finite decimal."
            ) from None
        return value

    @staticmethod
    def _exact_product(left: Decimal, right: Decimal) -> Decimal:
        """Multiply in a context sized from both operands, trapping any inexactness.

        The ambient process context is not trusted: a caller running under reduced
        precision must never silently round a fill notional that reaches the ledger.
        """

        failed = False
        product: Decimal | None = None
        try:
            digits = len(left.as_tuple().digits) + len(right.as_tuple().digits) + 4
            with localcontext(
                Context(
                    prec=max(digits, 28),
                    traps=[Inexact, Rounded, Clamped, Overflow, Underflow, InvalidOperation],
                )
            ):
                product = left * right
        except Exception:
            failed = True
        if failed or product is None or not product.is_finite():
            raise AlpacaPaperAdapterError(
                "Alpaca fill notional could not be computed exactly."
            ) from None
        return product

    @classmethod
    def _status(cls, raw: object) -> OrderStatus:
        mapped = None
        if type(raw) is str:
            mapped = _STATUS_MAP.get(raw.strip().lower())
        if mapped is None:
            # Fail closed: an unrecognized status is never guessed into a terminal one.
            raise AlpacaPaperAdapterError("Alpaca order status is unrecognized.") from None
        return mapped

    @classmethod
    def _asset_class(cls, raw: object, symbol: str) -> AssetClass:
        if type(raw) is str:
            mapped = _ASSET_CLASS_MAP.get(raw.strip().lower())
            if mapped is not None:
                return mapped
        if "/" in symbol:
            return AssetClass.CRYPTO
        raise AlpacaPaperAdapterError("Alpaca asset class is unrecognized.") from None

    def _call(self, operation: Callable[[], object], message: str) -> object:
        failed = False
        result: object = None
        try:
            result = operation()
        except Exception:
            failed = True
        if failed:
            raise self._fail(message) from None
        return result

    def _report(self, raw: object, fallback_client_order_id: str | None = None) -> ExecutionReport:
        malformed = False
        client_order_id: object = None
        broker_order_id: object = None
        status_raw: object = None
        filled_qty_raw: object = None
        price_raw: object = None
        try:
            client_order_id = getattr(raw, "client_order_id", None) or fallback_client_order_id
            broker_order_id = getattr(raw, "id", None)
            status_raw = getattr(raw, "status", None)
            filled_qty_raw = getattr(raw, "filled_qty", None) or "0"
            price_raw = getattr(raw, "filled_avg_price", None)
        except Exception:
            malformed = True
        if malformed or type(client_order_id) is not str or not client_order_id.strip():
            raise self._fail("Alpaca order response was malformed.") from None

        status = self._status(status_raw)
        filled_quantity = self._decimal(filled_qty_raw, "filled_qty")
        average_fill_price = (
            None if price_raw in (None, "") else self._decimal(price_raw, "filled_avg_price")
        )
        filled_notional = (
            Decimal("0")
            if average_fill_price is None
            else self._exact_product(filled_quantity, average_fill_price)
        )
        return ExecutionReport(
            client_order_id=client_order_id,
            venue=Venue.ALPACA_PAPER,
            status=status,
            # Fixed code, never the broker's own text: Alpaca rejection messages can
            # echo request context and must not enter the ledger.
            rejection_reason="broker_rejected" if status is OrderStatus.REJECTED else None,
            broker_order_id=None if broker_order_id is None else str(broker_order_id),
            filled_quantity=filled_quantity,
            filled_notional=filled_notional,
            average_fill_price=average_fill_price,
            occurred_at=self._now(),
            metadata={"adapter": self.name},
        )

    # -- BrokerAdapter surface -------------------------------------------------

    def get_account_snapshot(self) -> AccountSnapshot:
        captured_at = self._now()
        account = self._call(
            lambda: self._client.get_account(), "Alpaca account could not be read."
        )
        failed = False
        fields: tuple[object, object, object] | None = None
        try:
            fields = (account.cash, account.equity, account.buying_power)
        except Exception:
            failed = True
        if failed or fields is None:
            raise self._fail("Alpaca account response was malformed.") from None
        return AccountSnapshot(
            venue=Venue.ALPACA_PAPER,
            cash=self._decimal(fields[0], "cash"),
            equity=self._decimal(fields[1], "equity"),
            buying_power=self._decimal(fields[2], "buying_power"),
            captured_at=captured_at,
            # One clock reading for the whole snapshot: positions must not carry a
            # different instant from the balances they accompany.
            positions=self._positions_at(captured_at),
            metadata={"adapter": self.name},
        )

    def list_positions(self) -> tuple[PositionSnapshot, ...]:
        return self._positions_at(self._now())

    def _positions_at(self, captured_at: datetime) -> tuple[PositionSnapshot, ...]:
        raw_positions = self._call(
            lambda: self._client.list_positions(),
            "Alpaca positions could not be read.",
        )
        snapshots: list[PositionSnapshot] = []
        failed = False
        iterator: list[object] = []
        try:
            iterator = list(raw_positions)  # type: ignore[arg-type]
        except Exception:
            failed = True
        if failed:
            raise self._fail("Alpaca positions response was malformed.") from None
        for raw in iterator:
            row_failed = False
            symbol: object = None
            asset_class_raw: object = None
            fields: tuple[object, ...] = ()
            try:
                symbol = raw.symbol
                asset_class_raw = getattr(raw, "asset_class", None)
                fields = (
                    raw.qty,
                    raw.cost_basis,
                    raw.market_value,
                    raw.avg_entry_price,
                    raw.current_price,
                    raw.realized_pl,
                    raw.unrealized_pl,
                )
            except Exception:
                row_failed = True
            if row_failed or type(symbol) is not str or not symbol.strip():
                raise self._fail("Alpaca position response was malformed.") from None
            snapshots.append(
                PositionSnapshot(
                    venue=Venue.ALPACA_PAPER,
                    asset_class=self._asset_class(asset_class_raw, symbol),
                    symbol=symbol,
                    quantity=self._decimal(fields[0], "qty"),
                    cost_basis=self._decimal(fields[1], "cost_basis"),
                    market_value=self._decimal(fields[2], "market_value"),
                    average_entry_price=self._decimal(fields[3], "avg_entry_price"),
                    current_price=self._decimal(fields[4], "current_price"),
                    realized_pnl=self._decimal(fields[5], "realized_pl"),
                    unrealized_pnl=self._decimal(fields[6], "unrealized_pl"),
                    captured_at=captured_at,
                    metadata={"adapter": self.name},
                )
            )
        return tuple(snapshots)

    def submit_order(
        self, order: NormalizedOrder, *, execution_mode: str
    ) -> ExecutionReport:
        if type(execution_mode) is not str or execution_mode != "paper":
            raise self._fail("Alpaca adapter requires paper execution mode.") from None
        if type(order) is not NormalizedOrder:
            raise self._fail("Alpaca adapter requires an exact normalized order.") from None
        if order.venue is not Venue.ALPACA_PAPER:
            raise self._fail("Alpaca adapter received another venue's order.") from None

        payload: dict[str, object] = {
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "type": order.order_type.value,
            # Alpaca rejects time_in_force='day' for crypto; crypto must be gtc.
            "time_in_force": "gtc" if order.asset_class is AssetClass.CRYPTO else "day",
        }
        if order.quantity is not None:
            payload["qty"] = str(order.quantity)
        if order.notional is not None:
            payload["notional"] = str(order.notional)
        if order.limit_price is not None:
            payload["limit_price"] = str(order.limit_price)

        raw = self._call(
            lambda: self._client.submit_order(**payload),
            "Alpaca order submission failed.",
        )
        return self._report(raw, order.client_order_id)

    def cancel_order(self, client_order_id: str) -> ExecutionReport:
        if type(client_order_id) is not str or not client_order_id.strip():
            raise self._fail("Alpaca adapter requires a client order id.") from None
        raw = self._call(
            lambda: self._client.cancel_order_by_client_id(client_order_id),
            "Alpaca order cancellation failed.",
        )
        return self._report(raw, client_order_id)

    def get_order(self, client_order_id: str) -> ExecutionReport | None:
        if type(client_order_id) is not str or not client_order_id.strip():
            raise self._fail("Alpaca adapter requires a client order id.") from None
        raw = self._call(
            lambda: self._client.get_order_by_client_id(client_order_id),
            "Alpaca order lookup failed.",
        )
        if raw is None:
            return None
        return self._report(raw, client_order_id)

    def list_recent_orders(self, *, limit: int = 100) -> tuple[ExecutionReport, ...]:
        if type(limit) is not int or isinstance(limit, bool) or limit <= 0:
            raise self._fail("Alpaca adapter requires a positive order limit.") from None
        raw_orders = self._call(
            lambda: self._client.list_orders(limit=limit),
            "Alpaca recent orders could not be read.",
        )
        try:
            iterator = list(raw_orders)  # type: ignore[arg-type]
        except Exception:
            raise self._fail("Alpaca orders response was malformed.") from None
        return tuple(self._report(raw) for raw in iterator)


__all__ = [
    "AlpacaPaperAdapter",
    "AlpacaPaperAdapterError",
    "PAPER_BASE_URL",
]
