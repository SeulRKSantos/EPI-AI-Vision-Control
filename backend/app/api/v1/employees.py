"""Employee administration."""

import logging

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.core.badges import normalize_badge
from app.db.models import Employee, Role
from app.schemas.entities import EmployeeCreate, EmployeeRead, EmployeeUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=list[EmployeeRead], summary="List employees")
async def list_employees(
    db: DbSession,
    include_inactive: bool = Query(default=False),
    role_code: str | None = Query(default=None),
) -> list[Employee]:
    stmt = select(Employee).order_by(Employee.name)
    if not include_inactive:
        stmt = stmt.where(Employee.is_active.is_(True))
    if role_code:
        stmt = stmt.join(Role).where(Role.code == role_code)
    return list((await db.execute(stmt)).scalars())


@router.post(
    "",
    response_model=EmployeeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register an employee",
)
async def create_employee(body: EmployeeCreate, db: DbSession) -> Employee:
    role = await _role_or_422(body.role_code, db)

    employee = Employee(
        **body.model_dump(exclude={"role_code"}),
        role_id=role.id,
    )
    db.add(employee)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Badge '{body.badge_id}' is already registered",
        ) from None

    await db.refresh(employee)
    return employee


@router.get(
    "/{badge_id}",
    response_model=EmployeeRead,
    summary="Get an employee by badge",
)
async def get_employee(badge_id: str, db: DbSession) -> Employee:
    return await _get_or_404(badge_id, db)


@router.patch(
    "/{badge_id}",
    response_model=EmployeeRead,
    summary="Update an employee",
)
async def update_employee(
    badge_id: str, body: EmployeeUpdate, db: DbSession
) -> Employee:
    """Updates an employee, including handing them a different card.

    Changing the badge keeps the person's access history: records are linked
    to the employee, and each one keeps the badge that was used at the time.
    The old card stops working at once, and a card registered to someone
    else is refused rather than silently taken over.
    """
    employee = await _get_or_404(badge_id, db)
    data = body.model_dump(exclude_unset=True)

    new_badge = data.pop("badge_id", None)
    if new_badge is not None and new_badge != employee.badge_id:
        holder = (
            await db.execute(select(Employee).where(Employee.badge_id == new_badge))
        ).scalar_one_or_none()
        if holder is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Badge '{new_badge}' is already registered to {holder.name}",
            )
        logger.info(
            "Badge reassigned",
            extra={"employee_id": employee.id, "old_badge": employee.badge_id,
                   "new_badge": new_badge},
        )
        employee.badge_id = new_badge

    if "role_code" in data:
        role = await _role_or_422(data.pop("role_code"), db)
        employee.role_id = role.id

    for field, value in data.items():
        setattr(employee, field, value)

    try:
        await db.flush()
    except IntegrityError:
        # Another request took the badge between the check and the write.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Badge '{new_badge}' is already registered",
        ) from None
    await db.refresh(employee)
    return employee


@router.delete(
    "/{badge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate an employee",
)
async def deactivate_employee(badge_id: str, db: DbSession) -> None:
    """Deactivates rather than deletes.

    A deactivated badge is denied at the gate and the reason is recorded,
    which is the auditable outcome. Deleting the row would erase the link
    from past access logs to the person they refer to.
    """
    employee = await _get_or_404(badge_id, db)
    employee.is_active = False
    await db.flush()


async def _get_or_404(badge_id: str, db: DbSession) -> Employee:
    # Exact match first covers rows registered before ids were normalized.
    stmt = select(Employee).where(
        Employee.badge_id.in_({badge_id, normalize_badge(badge_id)})
    )
    employee = (await db.execute(stmt)).scalar_one_or_none()
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Badge '{badge_id}' not found",
        )
    return employee


async def _role_or_422(code: str, db: DbSession) -> Role:
    stmt = select(Role).where(Role.code == code)
    role = (await db.execute(stmt)).scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=422,  # named constant differs across Starlette versions
            detail=f"Unknown role code '{code}'",
        )
    return role
