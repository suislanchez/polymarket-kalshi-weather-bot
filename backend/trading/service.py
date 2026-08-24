"""Synchronous fail-closed orchestration for deterministic paper orders."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.trading.domain import (
    ExecutionReport,
    NormalizedOrder,
    OrderStatus,
    RiskDecision,
    TradeProposal,
    Venue,
)
from backend.trading.ledger import (
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
UpsertProjection = Callable[[Session, ExecutionReport], object]
Clock = Callable[[], datetime]
KillSwitch = Callable[[], bool]


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
        self._append_event = append_event_fn
        self._upsert_projection = upsert_order_projection_fn
        self._completed: dict[str, tuple[str, PaperExecutionResult]] = {}
        self._completed_idempotency: dict[str, str] = {}
        self._rollback_listener_registered = False
        self._rollback_listener = self._handle_rollback

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
        self._ensure_rollback_listener()
        prior = self._completed.get(proposal.proposal_id)
        if prior is not None:
            if prior[0] != identity:
                raise PaperExecutionServiceError("proposal identity conflict")
            return prior[1]
        prior_proposal_id = self._completed_idempotency.get(context.idempotency_key)
        if prior_proposal_id is not None and prior_proposal_id != proposal.proposal_id:
            raise PaperExecutionServiceError("proposal identity conflict")

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

        def record(event_type: str, occurred_at: datetime, payload: dict[str, object]) -> None:
            nonlocal sequence
            next_sequence = sequence + 1
            event_id = self._event_id(
                proposal.proposal_id, next_sequence, event_type
            )
            self._append_event(
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

        record(
            "proposal_created",
            proposal.created_at,
            self._proposal_payload(proposal),
        )
        decision = self._evaluate_risk(proposal, portfolio, risk_context, limits)
        record(
            "risk_approved" if decision.approved else "risk_rejected",
            decision.decided_at,
            self._risk_payload(decision),
        )

        if not decision.approved:
            result = PaperExecutionResult(proposal, decision, None, None)
            self._completed[proposal.proposal_id] = (identity, result)
            self._completed_idempotency[context.idempotency_key] = proposal.proposal_id
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
            self._completed[proposal.proposal_id] = (identity, result)
            self._completed_idempotency[context.idempotency_key] = proposal.proposal_id
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
            self._completed[proposal.proposal_id] = (identity, result)
            self._completed_idempotency[context.idempotency_key] = proposal.proposal_id
            return result

        record("order_submitted", now, self._order_payload(order))
        report = self._submit(adapter, order, now)
        for event_type in self._report_event_types(report.status):
            record(event_type, report.occurred_at, self._report_payload(report, event_type))
        self._upsert_projection(self._session, report)

        result = PaperExecutionResult(proposal, decision, order, report)
        self._completed[proposal.proposal_id] = (identity, result)
        self._completed_idempotency[context.idempotency_key] = proposal.proposal_id
        return result

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

    def _ensure_rollback_listener(self) -> None:
        if self._rollback_listener_registered:
            return
        failed = False
        after_rollback_added = False
        try:
            event.listen(self._session, "after_rollback", self._rollback_listener)
            after_rollback_added = True
            event.listen(self._session, "after_soft_rollback", self._rollback_listener)
        except Exception:
            failed = True
        if failed:
            if after_rollback_added:
                try:
                    event.remove(
                        self._session, "after_rollback", self._rollback_listener
                    )
                except Exception:
                    pass
            raise PaperExecutionServiceError("transaction listener failed") from None
        self._rollback_listener_registered = True

    def _handle_rollback(self, *unused: object) -> None:
        self._completed.clear()
        self._completed_idempotency.clear()

    @staticmethod
    def _event_id(aggregate_id: str, sequence: int, event_type: str) -> str:
        encoded = f"{aggregate_id}\x1f{sequence}\x1f{event_type}".encode("utf-8")
        return f"paper-event-{hashlib.sha256(encoded).hexdigest()}"

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
            decision = self._risk_evaluator(proposal, portfolio, context, limits)
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
            ):
                raise ValueError
        except Exception:
            invalid = True
        if invalid or normalized is None:
            raise PaperExecutionServiceError("risk decision invalid") from None
        return normalized

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
        try:
            report = adapter.submit_order(
                order, execution_mode=self._settings.execution_mode
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
        self._upsert_projection(self._session, report)
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
    def _report_event_types(status: OrderStatus) -> tuple[str, ...]:
        if status is OrderStatus.REJECTED:
            return ("order_rejected",)
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
    def _proposal_payload(cls, proposal: TradeProposal) -> dict[str, object]:
        return {
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
