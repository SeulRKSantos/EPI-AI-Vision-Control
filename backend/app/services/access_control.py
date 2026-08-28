"""Access control decision logic.

Split in two layers on purpose:

* `evaluate_compliance` is a pure function — no database, no clock, no I/O.
  It is the rule that decides whether someone may pass, and it is fully
  testable in isolation.
* `AccessControlService` orchestrates: it looks the employee up, applies the
  rule, and writes the audit record.

Every path that is not an explicit approval returns a denial. There is no
code path where an error or a missing piece of information results in the
gate opening.
"""

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AccessDecision, AccessLog, Employee, Gate
from app.schemas.messages import Detection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComplianceResult:
    """Outcome of comparing required PPE against what was detected."""

    decision: AccessDecision
    missing_ppe: list[str] = field(default_factory=list)
    accepted_ppe: list[str] = field(default_factory=list)

    @property
    def granted(self) -> bool:
        return self.decision is AccessDecision.GRANTED


def evaluate_compliance(
    required_ppe: set[str],
    detections: list[Detection],
    confidence_threshold: float | None = None,
) -> ComplianceResult:
    """Decide whether the detected PPE satisfies what the role requires.

    Detections below the confidence threshold are treated as absent: a
    low-confidence guess must never be the reason a gate opens.

    A role with no required PPE is granted — the employee was identified and
    nothing is demanded of them. That is a configuration decision, not an
    error, and it keeps roles like unrestricted staff working.
    """
    threshold = (
        confidence_threshold
        if confidence_threshold is not None
        else settings.detection_confidence_threshold
    )

    accepted = {d.ppe_code for d in detections if d.confidence >= threshold}
    missing = sorted(required_ppe - accepted)

    if missing:
        return ComplianceResult(
            decision=AccessDecision.DENIED_MISSING_PPE,
            missing_ppe=missing,
            accepted_ppe=sorted(accepted),
        )

    return ComplianceResult(
        decision=AccessDecision.GRANTED,
        missing_ppe=[],
        accepted_ppe=sorted(accepted),
    )


class AccessControlService:
    """Resolves a badge scan into a decision and records the attempt."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def decide(
        self,
        *,
        session_id: uuid.UUID,
        badge_id: str,
        gate_code: str,
        detections: list[Detection],
        latency_ms: float | None = None,
    ) -> ComplianceResult:
        """Full decision path for one access attempt.

        The audit record is written for every outcome, including denials and
        unknown badges — an attempt that leaves no trace is worse than a
        denied one.
        """
        employee = await self._find_employee(badge_id)

        if employee is None:
            return await self._record(
                session_id=session_id,
                badge_id=badge_id,
                gate_code=gate_code,
                employee=None,
                result=ComplianceResult(decision=AccessDecision.DENIED_UNKNOWN_BADGE),
                required_ppe=[],
                detections=detections,
                latency_ms=latency_ms,
            )

        if not employee.is_active or not employee.role.is_active:
            return await self._record(
                session_id=session_id,
                badge_id=badge_id,
                gate_code=gate_code,
                employee=employee,
                result=ComplianceResult(
                    decision=AccessDecision.DENIED_INACTIVE_EMPLOYEE
                ),
                required_ppe=[],
                detections=detections,
                latency_ms=latency_ms,
            )

        required = {
            ppe.code for ppe in employee.role.required_ppe if ppe.is_active
        }
        result = evaluate_compliance(required, detections)

        return await self._record(
            session_id=session_id,
            badge_id=badge_id,
            gate_code=gate_code,
            employee=employee,
            result=result,
            required_ppe=sorted(required),
            detections=detections,
            latency_ms=latency_ms,
        )

    async def deny_on_failure(
        self,
        *,
        session_id: uuid.UUID,
        badge_id: str,
        gate_code: str,
        decision: AccessDecision,
        latency_ms: float | None = None,
    ) -> ComplianceResult:
        """Record a denial caused by a failure rather than by missing PPE.

        Used when the vision service times out or an internal error occurs —
        cases where no comparison was possible at all.
        """
        employee = await self._find_employee(badge_id)
        result = ComplianceResult(decision=decision)
        return await self._record(
            session_id=session_id,
            badge_id=badge_id,
            gate_code=gate_code,
            employee=employee,
            result=result,
            required_ppe=[],
            detections=[],
            latency_ms=latency_ms,
        )

    # --- internals ---------------------------------------------------------

    async def _find_employee(self, badge_id: str) -> Employee | None:
        stmt = select(Employee).where(Employee.badge_id == badge_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _resolve_gate_id(self, gate_code: str) -> int | None:
        stmt = select(Gate.id).where(Gate.code == gate_code)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _record(
        self,
        *,
        session_id: uuid.UUID,
        badge_id: str,
        gate_code: str,
        employee: Employee | None,
        result: ComplianceResult,
        required_ppe: list[str],
        detections: list[Detection],
        latency_ms: float | None,
    ) -> ComplianceResult:
        log = AccessLog(
            session_id=session_id,
            gate_id=await self._resolve_gate_id(gate_code),
            employee_id=employee.id if employee else None,
            badge_id=badge_id,
            role_code=employee.role.code if employee else None,
            decision=result.decision,
            required_ppe=required_ppe,
            detected_ppe=[d.model_dump() for d in detections],
            missing_ppe=result.missing_ppe,
            latency_ms=latency_ms,
        )
        self._session.add(log)
        await self._session.flush()

        logger.info(
            "Access decision",
            extra={
                "session_id": str(session_id),
                "gate_code": gate_code,
                "badge_id": badge_id,
                "decision": result.decision.value,
                "missing_ppe": result.missing_ppe,
                "latency_ms": latency_ms,
            },
        )
        return result
