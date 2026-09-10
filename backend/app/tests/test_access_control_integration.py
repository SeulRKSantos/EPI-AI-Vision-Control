"""Stage 4 integration tests: the orchestrating service.

These cover the paths the pure rule cannot: badge lookup, inactive records,
and the audit trail written for every outcome.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AccessDecision, AccessLog
from app.schemas.messages import Detection
from app.services.access_control import AccessControlService
from app.tests.conftest import requires_db

pytestmark = requires_db


def det(code: str, confidence: float = 0.95) -> Detection:
    return Detection(ppe_code=code, confidence=confidence)


async def _log_for(session: AsyncSession, session_id: uuid.UUID) -> AccessLog:
    stmt = select(AccessLog).where(AccessLog.session_id == session_id)
    return (await session.execute(stmt)).scalar_one()


# --- Decision paths --------------------------------------------------------

async def test_grants_compliant_employee(seeded: AsyncSession):
    service = AccessControlService(seeded)
    result = await service.decide(
        session_id=uuid.uuid4(),
        badge_id="ACTIVE01",
        gate_code="gate-01",
        detections=[det("helmet"), det("goggles")],
    )
    assert result.granted


async def test_denies_when_required_ppe_is_missing(seeded: AsyncSession):
    service = AccessControlService(seeded)
    result = await service.decide(
        session_id=uuid.uuid4(),
        badge_id="ACTIVE01",
        gate_code="gate-01",
        detections=[det("helmet")],
    )
    assert not result.granted
    assert result.decision is AccessDecision.DENIED_MISSING_PPE
    assert result.missing_ppe == ["goggles"]


async def test_denies_unknown_badge(seeded: AsyncSession):
    service = AccessControlService(seeded)
    result = await service.decide(
        session_id=uuid.uuid4(),
        badge_id="NOT_REGISTERED",
        gate_code="gate-01",
        detections=[det("helmet"), det("goggles")],
    )
    assert not result.granted
    assert result.decision is AccessDecision.DENIED_UNKNOWN_BADGE


async def test_denies_inactive_employee_even_when_fully_compliant(seeded: AsyncSession):
    """Wearing all the PPE does not reinstate a deactivated badge."""
    service = AccessControlService(seeded)
    result = await service.decide(
        session_id=uuid.uuid4(),
        badge_id="INACTIVE1",
        gate_code="gate-01",
        detections=[det("helmet"), det("goggles")],
    )
    assert not result.granted
    assert result.decision is AccessDecision.DENIED_INACTIVE_EMPLOYEE


async def test_denies_employee_whose_role_was_deactivated(seeded: AsyncSession):
    service = AccessControlService(seeded)
    result = await service.decide(
        session_id=uuid.uuid4(),
        badge_id="BADROLE01",
        gate_code="gate-01",
        detections=[det("helmet")],
    )
    assert not result.granted
    assert result.decision is AccessDecision.DENIED_INACTIVE_EMPLOYEE


async def test_inactive_ppe_type_is_not_required(seeded: AsyncSession):
    """Retiring a PPE type must stop it from blocking access."""
    service = AccessControlService(seeded)
    result = await service.decide(
        session_id=uuid.uuid4(),
        badge_id="LEGACY01",
        gate_code="gate-01",
        detections=[det("helmet")],
    )
    assert result.granted


async def test_role_without_requirements_is_granted(seeded: AsyncSession):
    service = AccessControlService(seeded)
    result = await service.decide(
        session_id=uuid.uuid4(),
        badge_id="FREE01",
        gate_code="gate-01",
        detections=[],
    )
    assert result.granted


# --- Failure paths ---------------------------------------------------------

async def test_vision_timeout_is_recorded_as_denial(seeded: AsyncSession):
    service = AccessControlService(seeded)
    session_id = uuid.uuid4()
    result = await service.deny_on_failure(
        session_id=session_id,
        badge_id="ACTIVE01",
        gate_code="gate-01",
        decision=AccessDecision.DENIED_VISION_TIMEOUT,
    )
    assert not result.granted

    log = await _log_for(seeded, session_id)
    assert log.decision is AccessDecision.DENIED_VISION_TIMEOUT
    assert log.employee_id is not None  # the employee was still identified


# --- Audit trail -----------------------------------------------------------

async def test_every_attempt_is_logged(seeded: AsyncSession):
    service = AccessControlService(seeded)
    session_id = uuid.uuid4()
    await service.decide(
        session_id=session_id,
        badge_id="ACTIVE01",
        gate_code="gate-01",
        detections=[det("helmet", 0.91)],
        latency_ms=412.5,
    )

    log = await _log_for(seeded, session_id)
    assert log.badge_id == "ACTIVE01"
    assert log.role_code == "operator"
    assert log.decision is AccessDecision.DENIED_MISSING_PPE
    assert log.missing_ppe == ["goggles"]
    assert sorted(log.required_ppe) == ["goggles", "helmet"]
    assert log.detected_ppe == [{"ppe_code": "helmet", "confidence": 0.91}]
    assert log.latency_ms == 412.5
    assert log.gate_id is not None


async def test_unknown_badge_is_logged_without_employee(seeded: AsyncSession):
    """An unregistered attempt must leave a trace, not vanish."""
    service = AccessControlService(seeded)
    session_id = uuid.uuid4()
    await service.decide(
        session_id=session_id,
        badge_id="INTRUDER",
        gate_code="gate-01",
        detections=[],
    )

    log = await _log_for(seeded, session_id)
    assert log.employee_id is None
    assert log.badge_id == "INTRUDER"
    assert log.role_code is None


async def test_unknown_gate_does_not_break_the_decision(seeded: AsyncSession):
    """A gate missing from the database must not stop the rule from running."""
    service = AccessControlService(seeded)
    session_id = uuid.uuid4()
    result = await service.decide(
        session_id=session_id,
        badge_id="ACTIVE01",
        gate_code="gate-unregistered",
        detections=[det("helmet"), det("goggles")],
    )
    assert result.granted

    log = await _log_for(seeded, session_id)
    assert log.gate_id is None
