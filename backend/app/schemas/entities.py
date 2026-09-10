"""API request and response schemas.

Separate from the MQTT contracts in `messages.py`: these describe the REST
surface, which can evolve without touching what the devices speak.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AccessDecision


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- PPE types -------------------------------------------------------------

class PPETypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    is_active: bool = True


class PPETypeUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    is_active: bool | None = None


class PPETypeRead(ORMModel):
    id: int
    code: str
    label: str
    description: str | None
    is_active: bool


# --- Roles -----------------------------------------------------------------

class RoleCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    is_active: bool = True
    required_ppe: list[str] = Field(
        default_factory=list,
        description="PPE type codes required by this role",
    )


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    is_active: bool | None = None


class RoleRequirementsUpdate(BaseModel):
    """Replaces the whole requirement set for a role.

    Full replacement rather than add/remove: the matrix is small, and an
    operator editing it should see and confirm the complete list, not
    accumulate changes they cannot review.
    """

    required_ppe: list[str] = Field(description="PPE type codes, replacing the current set")


class RoleRead(ORMModel):
    id: int
    code: str
    name: str
    description: str | None
    is_active: bool
    required_ppe: list[PPETypeRead]


# --- Employees -------------------------------------------------------------

class EmployeeCreate(BaseModel):
    badge_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=150)
    registration: str | None = Field(default=None, max_length=50)
    role_code: str = Field(min_length=1, max_length=50)
    is_active: bool = True


class EmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    registration: str | None = Field(default=None, max_length=50)
    role_code: str | None = Field(default=None, min_length=1, max_length=50)
    is_active: bool | None = None


class EmployeeRead(ORMModel):
    id: int
    badge_id: str
    name: str
    registration: str | None
    is_active: bool
    role: RoleRead


# --- Gates -----------------------------------------------------------------

class GateRead(ORMModel):
    id: int
    code: str
    name: str
    location: str | None
    is_active: bool


# --- Access logs -----------------------------------------------------------

class AccessLogRead(ORMModel):
    id: int
    session_id: uuid.UUID
    badge_id: str
    role_code: str | None
    decision: AccessDecision
    required_ppe: list[str]
    detected_ppe: list[dict]
    missing_ppe: list[str]
    latency_ms: float | None
    created_at: datetime


class Page(BaseModel):
    """Envelope for list endpoints, so clients can page without guessing."""

    total: int
    limit: int
    offset: int


class AccessLogPage(Page):
    items: list[AccessLogRead]
