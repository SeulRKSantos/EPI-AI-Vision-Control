"""PPE type administration.

Each code here must match a class the vision model emits — the startup check
reports any mismatch, and the decision logic ignores codes it does not know.
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.db.models import PPEType
from app.schemas.entities import PPETypeCreate, PPETypeRead, PPETypeUpdate

router = APIRouter(prefix="/ppe-types", tags=["ppe types"])


@router.get("", response_model=list[PPETypeRead], summary="List PPE types")
async def list_ppe_types(
    db: DbSession,
    include_inactive: bool = Query(default=False),
) -> list[PPEType]:
    stmt = select(PPEType).order_by(PPEType.code)
    if not include_inactive:
        stmt = stmt.where(PPEType.is_active.is_(True))
    return list((await db.execute(stmt)).scalars())


@router.post(
    "",
    response_model=PPETypeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a PPE type",
)
async def create_ppe_type(body: PPETypeCreate, db: DbSession) -> PPEType:
    ppe = PPEType(**body.model_dump())
    db.add(ppe)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"PPE type '{body.code}' already exists",
        ) from None
    return ppe


@router.get("/{code}", response_model=PPETypeRead, summary="Get a PPE type")
async def get_ppe_type(code: str, db: DbSession) -> PPEType:
    return await _get_or_404(code, db)


@router.patch("/{code}", response_model=PPETypeRead, summary="Update a PPE type")
async def update_ppe_type(code: str, body: PPETypeUpdate, db: DbSession) -> PPEType:
    ppe = await _get_or_404(code, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(ppe, field, value)
    await db.flush()
    return ppe


@router.delete(
    "/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a PPE type",
)
async def deactivate_ppe_type(code: str, db: DbSession) -> None:
    """Deactivates rather than deletes.

    Access logs reference these codes by value; removing the row would leave
    historical records pointing at something that no longer exists.
    """
    ppe = await _get_or_404(code, db)
    ppe.is_active = False
    await db.flush()


async def _get_or_404(code: str, db: DbSession) -> PPEType:
    stmt = select(PPEType).where(PPEType.code == code)
    ppe = (await db.execute(stmt)).scalar_one_or_none()
    if ppe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PPE type '{code}' not found",
        )
    return ppe
