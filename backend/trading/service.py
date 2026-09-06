"""Synchronous fail-closed orchestration for deterministic paper orders."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import (
    Clamped,
    Context,
    Decimal,
    Inexact,
    InvalidOperation,
    MAX_EMAX,
    MIN_EMIN,
    Overflow,
    Rounded,
    Underflow,
    localcontext,
)
from typing import Protocol

from sqlalchemy import event, select
from sqlalchemy.orm import Session, SessionTransaction

from backend.models.database import TradingEvent

from backend.trading.domain import (
    ExecutionReport,
    NormalizedOrder,
    OrderStatus,
    RiskDecision,
    TradeProposal,
    Venue,
)
from backend.trading.execution_mode import ArchivesRuntimeError
from backend.trading.ledger import (
    LedgerConflictError,
    LedgerEventInput,
    append_event,
    upsert_order_projection,
)
from backend.trading.risk import (
    PortfolioState,
    RiskContext,
    RiskLimits,
    evaluate_proposal,
)


_ALLOWED_RISK_REASON_CODES = frozenset(
    {
        "execution_mode_not_paper",
        "global_kill_switch",
        "duplicate_idempotency_key",
        "venue_not_allowed",
        "asset_venue_mismatch",
        "asset_symbol_mismatch",
        "symbol_not_allowed",
        "weather_upstream_not_approved",
        "risk_arithmetic_invalid",
        "opening_short_not_allowed",
        "order_notional_limit",
        "symbol_exposure_limit",
        "gross_exposure_limit",
        "crypto_exposure_limit",
        "daily_loss_limit",
        "future_market_data",
        "stale_market_data",
    }
)
_EXACT_PRODUCT_TRAPS = (
    Clamped,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Underflow,
)


def _exact_product(left: Decimal, right: Decimal) -> Decimal:
    precision = max(1, len(left.as_tuple().digits) + len(right.as_tuple().digits))
    context = Context(prec=precision, Emin=MIN_EMIN, Emax=MAX_EMAX)
    for signal in _EXACT_PRODUCT_TRAPS:
        context.traps[signal] = True
    with localcontext(context):
        product = left * right
    if not product.is_finite():
        raise ArithmeticError
    return product


class PaperExecutionServiceError(RuntimeError):
    """Fixed, caller-safe failure at an execution-service boundary."""


@dataclass(frozen=True, slots=True)
class PaperExecutionSettings:
    """Immutable settings used by one paper execution service instance."""

    execution_mode: str = "paper"

    def __post_init__(self) -> None:
        if type(self.execution_mode) is not str or self.execution_mode != "paper":
            raise PaperExecutionServiceError("paper execution settings invalid")


@dataclass(frozen=True, slots=True)
class PaperExecutionResult:
    """Immutable completed result retained for in-process duplicate replay."""

    proposal: TradeProposal
    decision: RiskDecision
    order: NormalizedOrder | None
    report: ExecutionReport | None


class _RiskEvaluator(Protocol):
    def __call__(
        self,
        proposal: TradeProposal | None,
        portfolio: PortfolioState,
        context: RiskContext,
        limits: RiskLimits,
    ) -> RiskDecision | None: ...


class _Adapter(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def paper_only(self) -> bool: ...

    def submit_order(
        self, order: NormalizedOrder, *, execution_mode: str
    ) -> ExecutionReport: ...


AppendEvent = Callable[[Session, LedgerEventInput], object]
UpsertProjection = Callable[[Session, ExecutionReport, NormalizedOrder], object]
Clock = Callable[[], datetime]
KillSwitch = Callable[[], bool]
ArchivesGuard = Callable[[], None]


class PaperExecutionService:
    """Route paper proposals with rollback-aware in-process duplicate replay."""

    def __init__(
        self,
        *,
        session: Session,
        adapters: Mapping[Venue, _Adapter],
        risk_evaluator: _RiskEvaluator = evaluate_proposal,
        settings: PaperExecutionSettings,
        clock: Clock,
        kill_switch: KillSwitch,
        archives_guard: ArchivesGuard | None = None,
        append_event_fn: AppendEvent = append_event,
        upsert_order_projection_fn: UpsertProjection = upsert_order_projection,
    ) -> None:
        invalid_settings = False
        settings_snapshot: PaperExecutionSettings | None = None
        try:
            if type(settings) is not PaperExecutionSettings:
                raise ValueError
            execution_mode = settings.execution_mode
            if type(execution_mode) is not str or execution_mode != "paper":
                raise ValueError
            settings_snapshot = PaperExecutionSettings(execution_mode=execution_mode)
        except Exception:
            invalid_settings = True
        if invalid_settings or settings_snapshot is None:
            raise PaperExecutionServiceError("paper execution settings invalid") from None
        self._session = session
        self._adapters = adapters
        self._risk_evaluator = risk_evaluator
        self._settings = settings_snapshot
        self._clock = clock
        self._kill_switch = kill_switch
        self._archives_guard = archives_guard
        self._append_event = append_event_fn
        self._upsert_projection = upsert_order_projection_fn
        self._pending_completed: dict[
            str,
            tuple[
                str,
                PaperExecutionResult,
                tuple[str, int, str, str, str] | None,
                SessionTransaction,
            ],
        ] = {}
        self._pending_idempotency: dict[str, tuple[str, SessionTransaction]] = {}
        self._committed_completed: dict[
            str,
            tuple[str, PaperExecutionResult, tuple[str, int, str, str, str] | None],
        ] = {}
        self._committed_idempotency: dict[str, str] = {}
        self._transaction_listeners_registered = False
        self._commit_listener = self._handle_commit
        self._rollback_listener = self._handle_rollback
        self._transaction_end_listener = self._handle_transaction_end

    def execute(
        self,
        proposal: TradeProposal | None,
        *,
        portfolio: PortfolioState,
        context: RiskContext,
        limits: RiskLimits,
    ) -> PaperExecutionResult | None:
        """Execute one proposal without committing or rolling back the caller transaction."""

        if proposal is None:
            return None
        proposal = self._normalize_request_model(proposal, TradeProposal)
        portfolio = self._normalize_request_model(portfolio, PortfolioState)
        context = self._normalize_request_model(context, RiskContext)
        limits = self._normalize_request_model(limits, RiskLimits)

        identity = self._identity(proposal, context.idempotency_key)
        self._ensure_transaction_listeners()
        stale_replay_dropped = False
        prior = self._pending_completed.get(proposal.proposal_id)
        if prior is None:
            prior = self._committed_completed.get(proposal.proposal_id)
        if prior is not None:
            if prior[0] != identity:
                raise PaperExecutionServiceError("proposal identity conflict")
            durability = self._verify_replay_durability(prior[2])
            if durability == "found":
                return self._detach_result(prior[1])
            if durability != "absent":
                raise PaperExecutionServiceError(
                    "replay durability unverifiable"
                ) from None
            self._pending_completed.pop(proposal.proposal_id, None)
            self._committed_completed.pop(proposal.proposal_id, None)
            stale_replay_dropped = True
        pending_proposal = self._pending_idempotency.get(context.idempotency_key)
        prior_proposal_id = (
            None if pending_proposal is None else pending_proposal[0]
        )
        if prior_proposal_id is None:
            prior_proposal_id = self._committed_idempotency.get(
                context.idempotency_key
            )
        if prior_proposal_id is not None and prior_proposal_id != proposal.proposal_id:
            raise PaperExecutionServiceError("proposal identity conflict")

        self._require_archives()
        now = self._read_clock()
        initial_kill_switch = self._read_kill_switch()
        risk_context = RiskContext(
            now=now,
            execution_mode=self._settings.execution_mode,
            idempotency_key=context.idempotency_key,
            seen_idempotency_keys=context.seen_idempotency_keys,
            global_kill_switch=initial_kill_switch,
            weather_upstream_approved=context.weather_upstream_approved,
            weather_approval_evidence=context.weather_approval_evidence,
        )

        sequence = 0
        terminal_row: dict[str, object] = {"key": None}

        def record(event_type: str, occurred_at: datetime, payload: dict[str, object]) -> None:
            nonlocal sequence
            next_sequence = sequence + 1
            event_id = self._event_id(
                proposal.proposal_id, next_sequence, event_type
            )
            stored = self._append_event(
                self._session,
                LedgerEventInput(
                    event_id=event_id,
                    aggregate_id=proposal.proposal_id,
                    sequence=next_sequence,
                    event_type=event_type,
                    occurred_at=occurred_at,
                    payload=payload,
                ),
            )
            sequence = next_sequence
            try:
                stored_hash = stored.event_hash
                if type(stored_hash) is not str or len(stored_hash) != 64:
                    raise ValueError
                terminal_row["key"] = (
                    proposal.proposal_id,
                    next_sequence,
                    event_type,
                    event_id,
                    stored_hash,
                )
            except Exception:
                terminal_row["key"] = None

        replay_conflict = False
        try:
            record(
                "proposal_created",
                proposal.created_at,
                self._proposal_payload(proposal, identity),
            )
        except LedgerConflictError:
            if not stale_replay_dropped:
                raise
            replay_conflict = True
        if replay_conflict:
            raise PaperExecutionServiceError("ledger replay conflict") from None
        decision = self._evaluate_risk(proposal, portfolio, risk_context, limits)
        record(
            "risk_approved" if decision.approved else "risk_rejected",
            decision.decided_at,
            self._risk_payload(decision),
        )

        if not decision.approved:
            result = PaperExecutionResult(proposal, decision, None, None)
            self._cache_pending_result(
                proposal.proposal_id,
                context.idempotency_key,
                identity,
                result,
                terminal_row["key"],
            )
            return result

        order = self._build_order(proposal, decision, context.idempotency_key, now)
        adapter = self._resolve_adapter(proposal.venue)
        if adapter is None:
            result = self._reject_before_submit(
                proposal,
                decision,
                order,
                "adapter_unavailable",
                now,
                record,
            )
            self._cache_pending_result(
                proposal.proposal_id,
                context.idempotency_key,
                identity,
                result,
                terminal_row["key"],
            )
            return result

        if self._read_kill_switch():
            result = self._reject_before_submit(
                proposal,
                decision,
                order,
                "kill_switch_active",
                now,
                record,
            )
            self._cache_pending_result(
                proposal.proposal_id,
                context.idempotency_key,
                identity,
                result,
                terminal_row["key"],
            )
            return result

        self._require_archives()
        record("order_submitted", now, self._order_payload(order))
        report = self._submit(adapter, order, now)
        for event_type in self._report_event_types(report):
            record(event_type, report.occurred_at, self._report_payload(report, event_type))
        self._upsert_projection(self._session, report, order)

        result = PaperExecutionResult(proposal, decision, order, report)
        self._cache_pending_result(
            proposal.proposal_id,
            context.idempotency_key,
            identity,
            result,
            terminal_row["key"],
        )
        return result

    def _cache_pending_result(
        self,
        proposal_id: str,
        idempotency_key: str,
        identity: str,
        result: PaperExecutionResult,
        terminal_key: tuple[str, int, str, str, str] | None,
    ) -> None:
        cached_result = self._detach_result(result)
        failed = False
        transaction: SessionTransaction | None = None
        try:
            transaction = self._session.get_nested_transaction()
            if transaction is None:
                transaction = self._session.get_transaction()
        except Exception:
            failed = True
        if failed or transaction is None:
            raise PaperExecutionServiceError("transaction state invalid") from None
        self._pending_completed[proposal_id] = (
            identity,
            cached_result,
            terminal_key,
            transaction,
        )
        self._pending_idempotency[idempotency_key] = (proposal_id, transaction)

    @classmethod
    def _detach_result(cls, result: object) -> PaperExecutionResult:
        failed = False
        detached: PaperExecutionResult | None = None
        try:
            if type(result) is not PaperExecutionResult:
                raise ValueError
            proposal = cls._normalize_request_model(result.proposal, TradeProposal)
            decision = cls._normalize_request_model(result.decision, RiskDecision)
            order = (
                None
                if result.order is None
                else cls._normalize_request_model(result.order, NormalizedOrder)
            )
            report = (
                None
                if result.report is None
                else cls._normalize_request_model(result.report, ExecutionReport)
            )
            detached = PaperExecutionResult(proposal, decision, order, report)
        except Exception:
            failed = True
        if failed or detached is None:
            raise PaperExecutionServiceError("execution result invalid") from None
        return detached

    @staticmethod
    def _normalize_request_model(value: object, model_type):
        failed = False
        normalized = None
        try:
            if type(value) is not model_type:
                raise ValueError
            fields = {
                field_name: getattr(value, field_name)
                for field_name in model_type.model_fields
            }
            candidate = model_type(**fields)
            encoded = model_type.model_dump_json(candidate)
            normalized = model_type.model_validate_json(encoded)
            if type(normalized) is not model_type:
                raise ValueError
        except Exception:
            failed = True
        if failed or normalized is None:
            raise PaperExecutionServiceError("invalid execution request") from None
        return normalized

    @staticmethod
    def _identity(proposal: TradeProposal, idempotency_key: str) -> str:
        failed = False
        digest: str | None = None
        try:
            document = {
                "proposal": TradeProposal.model_dump(proposal, mode="json"),
                "idempotency_key": idempotency_key,
            }
            encoded = json.dumps(
                document,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
            digest = hashlib.sha256(encoded).hexdigest()
        except Exception:
            failed = True
        if failed or digest is None:
            raise PaperExecutionServiceError("invalid execution request") from None
        return digest

    def _ensure_transaction_listeners(self) -> None:
        if self._transaction_listeners_registered:
            return
        failed = False
        added: list[tuple[str, Callable[..., object]]] = []
        listeners = (
            ("after_commit", self._commit_listener),
            ("after_soft_rollback", self._rollback_listener),
            ("after_transaction_end", self._transaction_end_listener),
        )
        try:
            for event_name, listener in listeners:
                event.listen(self._session, event_name, listener)
                added.append((event_name, listener))
        except Exception:
            failed = True
        if failed:
            for event_name, listener in reversed(added):
                try:
                    event.remove(self._session, event_name, listener)
                except Exception:
                    pass
            raise PaperExecutionServiceError("transaction listener failed") from None
        self._transaction_listeners_registered = True

    def _handle_commit(self, *unused: object) -> None:
        try:
            if self._session.in_nested_transaction():
                return
        except Exception:
            return
        for proposal_id, (
            identity,
            result,
            terminal_key,
            _,
        ) in self._pending_completed.items():
            self._committed_completed[proposal_id] = (identity, result, terminal_key)
        for idempotency_key, (
            proposal_id,
            _,
        ) in self._pending_idempotency.items():
            self._committed_idempotency[idempotency_key] = proposal_id
        self._pending_completed.clear()
        self._pending_idempotency.clear()

    def _handle_rollback(self, *event_arguments: object) -> None:
        rolled_back = event_arguments[-1] if event_arguments else None
        if not isinstance(rolled_back, SessionTransaction):
            self._pending_completed.clear()
            self._pending_idempotency.clear()
            return
        for proposal_id, (_, _, _, transaction) in tuple(
            self._pending_completed.items()
        ):
            if self._transaction_is_within(transaction, rolled_back):
                self._pending_completed.pop(proposal_id, None)
        for idempotency_key, (_, transaction) in tuple(
            self._pending_idempotency.items()
        ):
            if self._transaction_is_within(transaction, rolled_back):
                self._pending_idempotency.pop(idempotency_key, None)

    def _handle_transaction_end(self, *event_arguments: object) -> None:
        """Invalidate pending replay state when a root transaction is discarded.

        ``after_commit`` promotes pending results before this event fires, and
        ``after_soft_rollback`` clears a rolled-back subtree. Neither is emitted by
        ``Session.close()`` or ``Session.reset()``, which discard the transaction
        outright. Anything still pending once the root transaction ends therefore has
        no durable ledger behind it and must never be replayed.
        """

        ended = event_arguments[-1] if event_arguments else None
        discarded = False
        if not isinstance(ended, SessionTransaction):
            discarded = True
        else:
            try:
                discarded = ended.nested is False and ended.parent is None
            except Exception:
                discarded = True
        if not discarded:
            return
        self._pending_completed.clear()
        self._pending_idempotency.clear()

    def _verify_replay_durability(
        self, terminal_key: tuple[str, int, str, str, str] | None
    ) -> str:
        """Check that the cached result's own terminal ledger row is still visible.

        Session and transaction state cannot answer whether a write set survived:
        SQLAlchemy discards work on paths that emit no session event and leave every
        state flag untouched (a failed flush subtransaction, ``Connection.invalidate``
        behind the session, a closed savepoint). Instead of inferring, look for the
        exact terminal event this cached result produced -- its aggregate, sequence,
        type, deterministic event id, and chain hash, remembered at write time. The
        hash folds the whole prior chain including the request identity digest, so a
        different execution of the same proposal can never satisfy the probe.

        The query selects columns only, never entities: after a discard the identity
        map still holds the stale rows and an entity get would serve them without
        touching the database. ``no_autoflush`` keeps a caller's unrelated dirty
        state from turning a read into a failed flush.

        Returns "found", "absent", or "unverifiable"; on "unverifiable" the caches
        are left untouched and the caller must fail closed.
        """

        if type(terminal_key) is not tuple or len(terminal_key) != 5:
            return "unverifiable"
        aggregate_id, sequence, event_type, event_id, event_hash = terminal_key
        try:
            with self._session.no_autoflush:
                found = self._session.execute(
                    select(TradingEvent.id)
                    .where(
                        TradingEvent.aggregate_id == aggregate_id,
                        TradingEvent.sequence == sequence,
                        TradingEvent.event_type == event_type,
                        TradingEvent.event_id == event_id,
                        TradingEvent.event_hash == event_hash,
                    )
                    .limit(1)
                ).first()
        except Exception:
            return "unverifiable"
        return "found" if found is not None else "absent"

    @staticmethod
    def _transaction_is_within(
        transaction: SessionTransaction, ancestor: SessionTransaction
    ) -> bool:
        seen: set[int] = set()
        current: SessionTransaction | None = transaction
        try:
            while current is not None:
                if current is ancestor:
                    return True
                marker = id(current)
                if marker in seen:
                    return True
                seen.add(marker)
                current = current.parent
        except Exception:
            return True
        return False

    @staticmethod
    def _event_id(aggregate_id: str, sequence: int, event_type: str) -> str:
        encoded = f"{aggregate_id}\x1f{sequence}\x1f{event_type}".encode("utf-8")
        return f"paper-event-{hashlib.sha256(encoded).hexdigest()}"

    def _require_archives(self) -> None:
        """Reject execution whenever Archives-backed runtime state is unavailable.

        Checked before any risk evaluation or ledger mutation, and again immediately
        before adapter submission so a mount lost mid-execution is not written
        through. Any failure from the injected guard is treated as unavailable.
        """

        guard = self._archives_guard
        if guard is None:
            return
        failed = False
        try:
            guard()
        except Exception:
            failed = True
        if failed:
            raise PaperExecutionServiceError("archives runtime unavailable") from None

    def _read_clock(self) -> datetime:
        failed = False
        normalized: datetime | None = None
        try:
            value = self._clock()
            if (
                type(value) is not datetime
                or value.tzinfo is None
                or value.utcoffset() != timedelta(0)
            ):
                raise ValueError
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
            raise PaperExecutionServiceError("service clock failed") from None
        return normalized

    def _read_kill_switch(self) -> bool:
        failed = False
        normalized: bool | None = None
        try:
            value = self._kill_switch()
            if type(value) is not bool:
                raise ValueError
            normalized = value
        except Exception:
            failed = True
        if failed or normalized is None:
            raise PaperExecutionServiceError("kill switch failed") from None
        return normalized

    def _evaluate_risk(
        self,
        proposal: TradeProposal,
        portfolio: PortfolioState,
        context: RiskContext,
        limits: RiskLimits,
    ) -> RiskDecision:
        failed = False
        decision: object = None
        try:
            evaluator_proposal = self._normalize_request_model(
                proposal, TradeProposal
            )
            evaluator_portfolio = self._normalize_request_model(
                portfolio, PortfolioState
            )
            evaluator_context = self._normalize_request_model(
                context, RiskContext
            )
            evaluator_limits = self._normalize_request_model(limits, RiskLimits)
            decision = self._risk_evaluator(
                evaluator_proposal,
                evaluator_portfolio,
                evaluator_context,
                evaluator_limits,
            )
        except Exception:
            failed = True
        if failed:
            raise PaperExecutionServiceError("risk evaluation failed") from None
        invalid = False
        normalized: RiskDecision | None = None
        try:
            if type(decision) is not RiskDecision:
                raise ValueError
            fields = {
                field_name: getattr(decision, field_name)
                for field_name in RiskDecision.model_fields
            }
            candidate = RiskDecision(**fields)
            encoded = RiskDecision.model_dump_json(candidate)
            normalized = RiskDecision.model_validate_json(encoded)
            if (
                type(normalized) is not RiskDecision
                or normalized.proposal_id != proposal.proposal_id
                or normalized.decided_at != context.now
                or (context.global_kill_switch and normalized.approved)
                or (normalized.approved and bool(normalized.reason_codes))
                or any(
                    reason not in _ALLOWED_RISK_REASON_CODES
                    for reason in normalized.reason_codes
                )
                or not self._approved_size_is_valid(
                    proposal, portfolio, limits, normalized
                )
            ):
                raise ValueError
            normalized = RiskDecision(
                proposal_id=normalized.proposal_id,
                approved=normalized.approved,
                reason_codes=normalized.reason_codes,
                approved_quantity=normalized.approved_quantity,
                approved_notional=normalized.approved_notional,
                decided_at=normalized.decided_at,
                limit_snapshot=limits.snapshot(),
            )
        except Exception:
            invalid = True
        if invalid or normalized is None:
            raise PaperExecutionServiceError("risk decision invalid") from None
        return normalized

    @staticmethod
    def _approved_size_is_valid(
        proposal: TradeProposal,
        portfolio: PortfolioState,
        limits: RiskLimits,
        decision: RiskDecision,
    ) -> bool:
        if not decision.approved:
            return True
        try:
            proposed_notional = proposal.notional
            if proposal.quantity is not None:
                quantity_notional = _exact_product(
                    proposal.quantity, proposal.reference_price
                )
                proposed_notional = (
                    quantity_notional
                    if proposed_notional is None
                    else min(proposed_notional, quantity_notional)
                )
            if proposed_notional is None:
                return False

            approved_notional = decision.approved_notional
            if approved_notional is None:
                if decision.approved_quantity is None:
                    return False
                approved_notional = _exact_product(
                    decision.approved_quantity, proposal.reference_price
                )

            order_cap = min(
                limits.max_order_notional,
                _exact_product(
                    portfolio.equity, limits.max_order_equity_fraction
                ),
            )
            return (
                proposed_notional.is_finite()
                and approved_notional.is_finite()
                and order_cap.is_finite()
                and approved_notional <= proposed_notional
                and approved_notional <= order_cap
            )
        except (ArithmeticError, ValueError):
            return False

    @staticmethod
    def _build_order(
        proposal: TradeProposal,
        decision: RiskDecision,
        client_order_id: str,
        created_at: datetime,
    ) -> NormalizedOrder:
        return NormalizedOrder(
            client_order_id=client_order_id,
            proposal_id=proposal.proposal_id,
            venue=proposal.venue,
            asset_class=proposal.asset_class,
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=decision.approved_quantity,
            notional=decision.approved_notional,
            order_type=proposal.order_type,
            limit_price=proposal.limit_price,
            status=OrderStatus.APPROVED,
            created_at=created_at,
            metadata={"strategy_id": proposal.strategy_id},
        )

    def _resolve_adapter(self, venue: Venue) -> _Adapter | None:
        failed = False
        adapter: object | None = None
        try:
            adapter = self._adapters[venue]
            name = adapter.name
            paper_only = adapter.paper_only
            submit_order = adapter.submit_order
            if (
                type(name) is not str
                or not name.strip()
                or type(paper_only) is not bool
                or paper_only is not True
                or not callable(submit_order)
            ):
                raise ValueError
        except Exception:
            failed = True
        if failed:
            return None
        return adapter  # type: ignore[return-value]

    def _submit(
        self, adapter: _Adapter, order: NormalizedOrder, occurred_at: datetime
    ) -> ExecutionReport:
        adapter_failed = False
        report: object = None
        adapter_order = self._normalize_request_model(order, NormalizedOrder)
        try:
            report = adapter.submit_order(
                adapter_order, execution_mode=self._settings.execution_mode
            )
        except Exception:
            adapter_failed = True
        if adapter_failed:
            return self._rejection_report(order, "adapter_error", occurred_at)
        invalid = False
        normalized: ExecutionReport | None = None
        try:
            if type(report) is not ExecutionReport:
                raise ValueError
            client_order_id = report.client_order_id
            venue = report.venue
            status = report.status
            if (
                type(client_order_id) is not str
                or type(venue) is not Venue
                or type(status) is not OrderStatus
                or client_order_id != order.client_order_id
                or venue is not order.venue
                or status
                not in {
                    OrderStatus.SUBMITTED,
                    OrderStatus.PARTIALLY_FILLED,
                    OrderStatus.FILLED,
                    OrderStatus.CANCELED,
                    OrderStatus.REJECTED,
                }
            ):
                raise ValueError
            boundary_candidate = ExecutionReport(
                client_order_id=client_order_id,
                venue=venue,
                status=status,
                broker_order_id=report.broker_order_id,
                filled_quantity=report.filled_quantity,
                filled_notional=report.filled_notional,
                average_fill_price=report.average_fill_price,
                rejection_reason=report.rejection_reason,
                occurred_at=report.occurred_at,
                metadata=report.metadata,
            )
            boundary_encoded = ExecutionReport.model_dump_json(boundary_candidate)
            boundary_report = ExecutionReport.model_validate_json(boundary_encoded)
            if not self._report_size_is_valid(order, boundary_report):
                raise ValueError
            normalized = ExecutionReport(
                client_order_id=boundary_report.client_order_id,
                venue=boundary_report.venue,
                status=boundary_report.status,
                broker_order_id=boundary_report.broker_order_id,
                filled_quantity=boundary_report.filled_quantity,
                filled_notional=boundary_report.filled_notional,
                average_fill_price=boundary_report.average_fill_price,
                rejection_reason=(
                    "adapter_rejected" if status is OrderStatus.REJECTED else None
                ),
                occurred_at=boundary_report.occurred_at,
                metadata={"service": "paper_execution"},
            )
            if type(normalized) is not ExecutionReport:
                raise ValueError
        except Exception:
            invalid = True
        if invalid or normalized is None:
            return self._rejection_report(
                order, "adapter_invalid_report", occurred_at
            )
        return normalized

    @staticmethod
    def _report_size_is_valid(
        order: NormalizedOrder, report: ExecutionReport
    ) -> bool:
        filled_quantity = report.filled_quantity
        filled_notional = report.filled_notional
        if filled_quantity == 0 and filled_notional == 0:
            return True
        average_fill_price = report.average_fill_price
        if average_fill_price is None:
            return False
        try:
            quantity_notional = _exact_product(
                filled_quantity, average_fill_price
            )
            if (
                filled_quantity > 0
                and filled_notional > 0
                and quantity_notional != filled_notional
            ):
                return False
            if order.notional is not None:
                return (
                    filled_notional <= order.notional
                    and quantity_notional <= order.notional
                )
            if order.quantity is None:
                return False
            maximum_notional = _exact_product(
                order.quantity, average_fill_price
            )
            return (
                filled_quantity <= order.quantity
                and filled_notional <= maximum_notional
            )
        except (ArithmeticError, ValueError):
            return False

    def _reject_before_submit(
        self,
        proposal: TradeProposal,
        decision: RiskDecision,
        order: NormalizedOrder,
        reason: str,
        occurred_at: datetime,
        record: Callable[[str, datetime, dict[str, object]], None],
    ) -> PaperExecutionResult:
        report = self._rejection_report(order, reason, occurred_at)
        record(
            "order_rejected",
            report.occurred_at,
            self._report_payload(report, "order_rejected"),
        )
        self._upsert_projection(self._session, report, order)
        return PaperExecutionResult(proposal, decision, order, report)

    @staticmethod
    def _rejection_report(
        order: NormalizedOrder, reason: str, occurred_at: datetime
    ) -> ExecutionReport:
        return ExecutionReport(
            client_order_id=order.client_order_id,
            venue=order.venue,
            status=OrderStatus.REJECTED,
            rejection_reason=reason,
            occurred_at=occurred_at,
            metadata={"service": "paper_execution"},
        )

    @staticmethod
    def _report_event_types(report: ExecutionReport) -> tuple[str, ...]:
        status = report.status
        if status is OrderStatus.REJECTED:
            return ("order_rejected",)
        if status is OrderStatus.CANCELED and (
            report.filled_quantity > 0 or report.filled_notional > 0
        ):
            return (
                "order_acknowledged",
                "order_partially_filled",
                "order_canceled",
            )
        final = {
            OrderStatus.SUBMITTED: None,
            OrderStatus.PARTIALLY_FILLED: "order_partially_filled",
            OrderStatus.FILLED: "order_filled",
            OrderStatus.CANCELED: "order_canceled",
        }[status]
        if final is None:
            return ("order_acknowledged",)
        return ("order_acknowledged", final)

    @staticmethod
    def _timestamp(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @classmethod
    def _proposal_payload(
        cls, proposal: TradeProposal, identity: str
    ) -> dict[str, object]:
        return {
            "identity": identity,
            "proposal_id": proposal.proposal_id,
            "strategy_id": proposal.strategy_id,
            "venue": proposal.venue.value,
            "asset_class": proposal.asset_class.value,
            "symbol": proposal.symbol,
            "side": proposal.side.value,
            "order_type": proposal.order_type.value,
            "quantity": None if proposal.quantity is None else str(proposal.quantity),
            "notional": None if proposal.notional is None else str(proposal.notional),
            "reference_price": str(proposal.reference_price),
            "created_at": cls._timestamp(proposal.created_at),
        }

    @classmethod
    def _risk_payload(cls, decision: RiskDecision) -> dict[str, object]:
        return {
            "proposal_id": decision.proposal_id,
            "approved": decision.approved,
            "reason_codes": list(decision.reason_codes),
            "approved_quantity": (
                None
                if decision.approved_quantity is None
                else str(decision.approved_quantity)
            ),
            "approved_notional": (
                None
                if decision.approved_notional is None
                else str(decision.approved_notional)
            ),
            "decided_at": cls._timestamp(decision.decided_at),
        }

    @classmethod
    def _order_payload(cls, order: NormalizedOrder) -> dict[str, object]:
        return {
            "client_order_id": order.client_order_id,
            "proposal_id": order.proposal_id,
            "venue": order.venue.value,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": None if order.quantity is None else str(order.quantity),
            "notional": None if order.notional is None else str(order.notional),
            "limit_price": (
                None if order.limit_price is None else str(order.limit_price)
            ),
            "created_at": cls._timestamp(order.created_at),
        }

    @classmethod
    def _report_payload(
        cls, report: ExecutionReport, event_type: str
    ) -> dict[str, object]:
        rejection_reason = report.rejection_reason
        if event_type == "order_rejected" and rejection_reason not in {
            "adapter_error",
            "adapter_invalid_report",
            "adapter_unavailable",
            "kill_switch_active",
        }:
            rejection_reason = "adapter_rejected"
        return {
            "client_order_id": report.client_order_id,
            "venue": report.venue.value,
            "status": report.status.value,
            "broker_order_id": report.broker_order_id,
            "filled_quantity": str(report.filled_quantity),
            "filled_notional": str(report.filled_notional),
            "average_fill_price": (
                None
                if report.average_fill_price is None
                else str(report.average_fill_price)
            ),
            "rejection_reason": rejection_reason,
            "occurred_at": cls._timestamp(report.occurred_at),
        }


__all__ = [
    "PaperExecutionResult",
    "PaperExecutionService",
    "PaperExecutionServiceError",
    "PaperExecutionSettings",
]
