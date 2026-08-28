"""Access flow orchestration.

Ties together the pieces built in earlier stages: a badge scan arrives, the
vision service is asked for a detection, the compliance rule runs, and a
decision goes back to the gate.

The flow is written so that every exit path publishes a decision. A scan that
produced no message at all would leave the firmware waiting on its own
timeout, which is a worse failure than an explicit denial.
"""

import logging
import time

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import topics
from app.core.config import settings
from app.core.mqtt_client import MQTTClient
from app.db.models import AccessDecision
from app.schemas.messages import (
    AccessDecisionMessage,
    BadgeScan,
    VisionRequest,
    VisionResult,
)
from app.services.access_control import AccessControlService
from app.services.session_manager import SessionManager

logger = logging.getLogger(__name__)

_DENIAL_REASONS = {
    AccessDecision.GRANTED: "compliant",
    AccessDecision.DENIED_MISSING_PPE: "missing_ppe",
    AccessDecision.DENIED_UNKNOWN_BADGE: "unknown_badge",
    AccessDecision.DENIED_INACTIVE_EMPLOYEE: "inactive_employee",
    AccessDecision.DENIED_VISION_TIMEOUT: "vision_timeout",
    AccessDecision.DENIED_INTERNAL_ERROR: "internal_error",
}


class AccessFlow:
    """Handles one badge scan from arrival to published decision."""

    def __init__(
        self,
        mqtt: MQTTClient,
        sessions: SessionManager,
        session_factory: async_sessionmaker,
    ) -> None:
        self._mqtt = mqtt
        self._sessions = sessions
        self._session_factory = session_factory

    async def handle_scan(self, scan: BadgeScan) -> None:
        """Full path for one scan. Never raises to the caller."""
        if self._sessions.is_in_cooldown(scan.badge_id):
            logger.info(
                "Scan ignored, badge in cooldown",
                extra={"badge_id": scan.badge_id, "gate_code": scan.gate_code},
            )
            return

        session = self._sessions.open(scan.session_id, scan.badge_id, scan.gate_code)
        started = time.monotonic()

        try:
            await self._mqtt.publish(
                topics.vision_request(scan.gate_code),
                VisionRequest(session_id=scan.session_id, gate_code=scan.gate_code),
            )

            result = await self._sessions.wait_for_result(
                session, settings.session_timeout_seconds
            )
            latency_ms = (time.monotonic() - started) * 1000.0

            if result is None:
                await self._decide_failure(
                    scan, AccessDecision.DENIED_VISION_TIMEOUT, latency_ms
                )
                return

            await self._decide_from_result(scan, result, latency_ms)

        except Exception:
            logger.exception(
                "Access flow failed",
                extra={
                    "session_id": str(scan.session_id),
                    "badge_id": scan.badge_id,
                },
            )
            latency_ms = (time.monotonic() - started) * 1000.0
            await self._decide_failure(
                scan, AccessDecision.DENIED_INTERNAL_ERROR, latency_ms
            )
        finally:
            self._sessions.close(scan.session_id)

    async def handle_vision_result(self, result: VisionResult) -> None:
        """Route an inference result to the session that is waiting for it."""
        self._sessions.resolve(result)

    # --- internals ---------------------------------------------------------

    async def _decide_from_result(
        self, scan: BadgeScan, result: VisionResult, latency_ms: float
    ) -> None:
        async with self._session_factory() as db:
            service = AccessControlService(db)
            outcome = await service.decide(
                session_id=scan.session_id,
                badge_id=scan.badge_id,
                gate_code=scan.gate_code,
                detections=result.detections,
                latency_ms=latency_ms,
            )
            await db.commit()

        await self._publish_decision(
            scan,
            granted=outcome.granted,
            reason=_DENIAL_REASONS[outcome.decision],
            missing_ppe=outcome.missing_ppe,
        )

    async def _decide_failure(
        self, scan: BadgeScan, decision: AccessDecision, latency_ms: float
    ) -> None:
        """Record and publish a denial that no comparison produced."""
        try:
            async with self._session_factory() as db:
                service = AccessControlService(db)
                await service.deny_on_failure(
                    session_id=scan.session_id,
                    badge_id=scan.badge_id,
                    gate_code=scan.gate_code,
                    decision=decision,
                    latency_ms=latency_ms,
                )
                await db.commit()
        except Exception:
            # Persisting the audit record failed. The denial still has to
            # reach the gate, so the publish below is attempted regardless.
            logger.exception(
                "Could not record failure decision",
                extra={"session_id": str(scan.session_id)},
            )

        await self._publish_decision(
            scan, granted=False, reason=_DENIAL_REASONS[decision], missing_ppe=[]
        )

    async def _publish_decision(
        self, scan: BadgeScan, *, granted: bool, reason: str, missing_ppe: list[str]
    ) -> None:
        message = AccessDecisionMessage(
            session_id=scan.session_id,
            gate_code=scan.gate_code,
            granted=granted,
            reason=reason,
            missing_ppe=missing_ppe,
        )
        try:
            await self._mqtt.publish(topics.access_decision(scan.gate_code), message)
        except Exception:
            # Nothing further can be done: the firmware will fall back to its
            # own timeout, which keeps the gate locked.
            logger.exception(
                "Could not publish decision",
                extra={"session_id": str(scan.session_id), "granted": granted},
            )
