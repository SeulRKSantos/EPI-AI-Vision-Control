"""Gate operations.

The simulation endpoint publishes a badge scan exactly as the ESP32 would,
so the whole path — broker, handler, vision request, decision — runs without
any hardware attached. It stays useful after the firmware exists, as the
entry point for automated end-to-end tests.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core import topics
from app.schemas.messages import BadgeScan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gates", tags=["gates"])


class SimulateScanRequest(BaseModel):
    badge_id: str = Field(min_length=1, max_length=64)


class SimulateScanResponse(BaseModel):
    session_id: uuid.UUID
    gate_code: str
    badge_id: str
    published_to: str


@router.post(
    "/{gate_code}/simulate-scan",
    response_model=SimulateScanResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Publish a badge scan as if it came from the gate device",
)
async def simulate_scan(
    gate_code: str, body: SimulateScanRequest, request: Request
) -> SimulateScanResponse:
    """Emit a scan and return immediately.

    The decision is not part of this response: it travels over MQTT to the
    gate, as it does in production. Read the access log or subscribe to the
    decision topic to observe the outcome.
    """
    mqtt = request.app.state.mqtt
    if not mqtt.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MQTT broker is unavailable",
        )

    scan = BadgeScan(gate_code=gate_code, badge_id=body.badge_id)
    topic = topics.badge_scan(gate_code)
    await mqtt.publish(topic, scan)

    logger.info(
        "Simulated scan published",
        extra={
            "session_id": str(scan.session_id),
            "gate_code": gate_code,
            "badge_id": body.badge_id,
        },
    )

    return SimulateScanResponse(
        session_id=scan.session_id,
        gate_code=gate_code,
        badge_id=body.badge_id,
        published_to=topic,
    )
