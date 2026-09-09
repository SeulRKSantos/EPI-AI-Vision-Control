"""Access log queries.

Read-only by design: the log is the audit trail, written by the decision
path and never edited through the API.
"""

from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.db.models import AccessDecision, AccessLog, Gate
from app.schemas.entities import AccessLogPage

router = APIRouter(prefix="/access-logs", tags=["access logs"])


@router.get("", response_model=AccessLogPage, summary="Query access history")
async def list_access_logs(
    db: DbSession,
    badge_id: str | None = Query(default=None),
    gate_code: str | None = Query(default=None),
    decision: AccessDecision | None = Query(default=None),
    granted: bool | None = Query(
        default=None, description="Shortcut filter: true for granted, false for any denial"
    ),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AccessLogPage:
    """Most recent first, since that is what an operator looks for."""
    filters = []

    if badge_id:
        filters.append(AccessLog.badge_id == badge_id)
    if decision:
        filters.append(AccessLog.decision == decision)
    if granted is not None:
        if granted:
            filters.append(AccessLog.decision == AccessDecision.GRANTED)
        else:
            filters.append(AccessLog.decision != AccessDecision.GRANTED)
    if since:
        filters.append(AccessLog.created_at >= since)
    if until:
        filters.append(AccessLog.created_at <= until)
    if gate_code:
        gate_id = (
            await db.execute(select(Gate.id).where(Gate.code == gate_code))
        ).scalar_one_or_none()
        # An unknown gate matches nothing rather than everything.
        filters.append(AccessLog.gate_id == gate_id)

    count_stmt = select(func.count()).select_from(AccessLog)
    page_stmt = select(AccessLog).order_by(AccessLog.created_at.desc(), AccessLog.id.desc())

    for condition in filters:
        count_stmt = count_stmt.where(condition)
        page_stmt = page_stmt.where(condition)

    total = (await db.execute(count_stmt)).scalar_one()
    items = list((await db.execute(page_stmt.limit(limit).offset(offset))).scalars())

    return AccessLogPage(total=total, limit=limit, offset=offset, items=items)
