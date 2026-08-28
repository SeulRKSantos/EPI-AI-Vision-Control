"""Message contracts exchanged over MQTT.

These are the wire format between firmware, backend and vision service.
Changing a field here is a breaking change for the other two components.
"""

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class BadgeScan(BaseModel):
    """Published by the ESP32 when a badge is presented at a gate."""

    model_config = ConfigDict(extra="ignore")

    session_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    gate_code: str
    badge_id: str
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VisionRequest(BaseModel):
    """Published by the backend to ask the vision service for a detection."""

    session_id: uuid.UUID
    gate_code: str
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Detection(BaseModel):
    """A single PPE item detected in the frame.

    `ppe_code` must match a `ppe_types.code` row; unknown codes are ignored
    by the decision logic rather than causing a failure.
    """

    model_config = ConfigDict(extra="ignore")

    ppe_code: str
    confidence: float = Field(ge=0.0, le=1.0)


class VisionResult(BaseModel):
    """Published by the vision service with the outcome of an inference."""

    model_config = ConfigDict(extra="ignore")

    session_id: uuid.UUID
    detections: list[Detection] = Field(default_factory=list)
    inference_ms: float | None = None


class AccessDecisionMessage(BaseModel):
    """Published by the backend back to the ESP32.

    `granted` is the only field the firmware must act on. The remaining
    fields exist for display and diagnostics.
    """

    session_id: uuid.UUID
    gate_code: str
    granted: bool
    reason: str
    missing_ppe: list[str] = Field(default_factory=list)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
