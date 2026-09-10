"""Role administration and the PPE requirement matrix.

The requirement matrix is the configuration the whole system turns on: it is
what the decision logic reads on every scan.
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.db.models import PPEType, Role
from app.schemas.entities import (
    RoleCreate,
    RoleRead,
    RoleRequirementsUpdate,
    RoleUpdate,
)

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("", response_model=list[RoleRead], summary="List roles")
async def list_roles(
    db: DbSession,
    include_inactive: bool = Query(default=False),
) -> list[Role]:
    stmt = select(Role).order_by(Role.code)
    if not include_inactive:
        stmt = stmt.where(Role.is_active.is_(True))
    return list((await db.execute(stmt)).scalars())


@router.post(
    "",
    response_model=RoleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a role",
)
async def create_role(body: RoleCreate, db: DbSession) -> Role:
    payload = body.model_dump(exclude={"required_ppe"})
    role = Role(**payload)
    role.required_ppe = await _resolve_ppe(body.required_ppe, db)

    db.add(role)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Role '{body.code}' already exists",
        ) from None
    return role


@router.get("/{code}", response_model=RoleRead, summary="Get a role")
async def get_role(code: str, db: DbSession) -> Role:
    return await _get_or_404(code, db)


@router.patch("/{code}", response_model=RoleRead, summary="Update a role")
async def update_role(code: str, body: RoleUpdate, db: DbSession) -> Role:
    role = await _get_or_404(code, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(role, field, value)
    await db.flush()
    return role


@router.get(
    "/{code}/requirements",
    response_model=RoleRead,
    summary="Get the PPE required by a role",
)
async def get_requirements(code: str, db: DbSession) -> Role:
    return await _get_or_404(code, db)


@router.put(
    "/{code}/requirements",
    response_model=RoleRead,
    summary="Replace the PPE required by a role",
)
async def replace_requirements(
    code: str, body: RoleRequirementsUpdate, db: DbSession
) -> Role:
    """Sets the complete requirement list, replacing whatever was there.

    An unknown PPE code is rejected rather than ignored: a silent drop would
    leave a role requiring less than the operator believed.
    """
    role = await _get_or_404(code, db)
    role.required_ppe = await _resolve_ppe(body.required_ppe, db)
    await db.flush()
    return role


@router.delete(
    "/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a role",
)
async def deactivate_role(code: str, db: DbSession) -> None:
    """Deactivates rather than deletes.

    Employees reference roles, and access logs record the role code as it was
    at decision time; deleting would break both.
    """
    role = await _get_or_404(code, db)
    role.is_active = False
    await db.flush()


async def _get_or_404(code: str, db: DbSession) -> Role:
    stmt = select(Role).where(Role.code == code)
    role = (await db.execute(stmt)).scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Role '{code}' not found",
        )
    return role


async def _resolve_ppe(codes: list[str], db: DbSession) -> list[PPEType]:
    if not codes:
        return []

    stmt = select(PPEType).where(PPEType.code.in_(codes))
    found = list((await db.execute(stmt)).scalars())

    missing = set(codes) - {p.code for p in found}
    if missing:
        raise HTTPException(
            status_code=422,  # named constant differs across Starlette versions
            detail=f"Unknown PPE type codes: {sorted(missing)}",
        )
    return found
