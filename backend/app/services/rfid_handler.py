"""MQTT message handlers.

Thin layer between the broker and the flow: decode, validate, delegate. A
malformed payload is logged and dropped rather than raised — one bad message
from a device must not stop the ones that follow.
"""

import logging

from pydantic import ValidationError

from app.core import topics
from app.schemas.messages import BadgeScan, VisionResult
from app.services.access_flow import AccessFlow

logger = logging.getLogger(__name__)


class MessageHandlers:
    def __init__(self, flow: AccessFlow) -> None:
        self._flow = flow

    async def on_badge_scan(self, topic: str, payload: bytes) -> None:
        try:
            scan = BadgeScan.model_validate_json(payload)
        except ValidationError as exc:
            logger.warning(
                "Invalid badge scan payload discarded",
                extra={"topic": topic, "errors": exc.error_count()},
            )
            return

        # The topic is authoritative for the gate: a device must not be able
        # to claim it is at a different gate through the payload.
        gate_code = topics.extract_gate_code(topic)
        if gate_code and gate_code != scan.gate_code:
            scan = scan.model_copy(update={"gate_code": gate_code})

        logger.info(
            "Badge scan received",
            extra={
                "session_id": str(scan.session_id),
                "badge_id": scan.badge_id,
                "gate_code": scan.gate_code,
            },
        )
        await self._flow.handle_scan(scan)

    async def on_vision_result(self, topic: str, payload: bytes) -> None:
        try:
            result = VisionResult.model_validate_json(payload)
        except ValidationError as exc:
            logger.warning(
                "Invalid vision result payload discarded",
                extra={"topic": topic, "errors": exc.error_count()},
            )
            return

        logger.debug(
            "Vision result received",
            extra={
                "session_id": str(result.session_id),
                "detections": len(result.detections),
            },
        )
        await self._flow.handle_vision_result(result)

    async def on_gate_status(self, topic: str, payload: bytes) -> None:
        """Device availability, published as heartbeat and as Last Will.

        Recorded for observability only — an offline device simply stops
        sending scans, and the gate stays locked on its own.
        """
        gate_code = topics.extract_gate_code(topic)
        logger.info(
            "Gate status",
            extra={"gate_code": gate_code, "status": payload.decode(errors="replace")},
        )
