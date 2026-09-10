"""Auditable record of every access attempt."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AccessDecision(str, enum.Enum):
    """Outcome of an access attempt.

    Everything other than GRANTED keeps the gate locked. The distinct values
    exist so the audit log explains *why* access was refused.
    """

    GRANTED = "granted"
    DENIED_MISSING_PPE = "denied_missing_ppe"
    DENIED_UNKNOWN_BADGE = "denied_unknown_badge"
    DENIED_INACTIVE_EMPLOYEE = "denied_inactive_employee"
    DENIED_VISION_TIMEOUT = "denied_vision_timeout"
    DENIED_INTERNAL_ERROR = "denied_internal_error"


class AccessLog(Base):
    """One row per access attempt, written after the decision is made."""

    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Correlates the badge scan, the inference request and the decision.
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True
    )

    gate_id: Mapped[int | None] = mapped_column(ForeignKey("gates.id", ondelete="SET NULL"))
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL")
    )

    # Kept denormalized on purpose: the log must stay readable even if the
    # employee record is later edited or removed.
    badge_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role_code: Mapped[str | None] = mapped_column(String(50))

    decision: Mapped[AccessDecision] = mapped_column(
        SAEnum(AccessDecision, name="access_decision", native_enum=False, length=40),
        nullable=False,
        index=True,
    )

    required_ppe: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    detected_ppe: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    missing_ppe: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    latency_ms: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<AccessLog {self.badge_id} {self.decision.value}>"
