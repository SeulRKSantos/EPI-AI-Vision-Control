"""Shared test fixtures.

Integration tests run against a real PostgreSQL instance: the schema uses
JSONB and UUID columns, so SQLite would not exercise the same behaviour.

Point TEST_DATABASE_URL at a disposable database. When it is unset, the
integration tests are skipped and only the pure-logic tests run.
"""

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Employee, Gate, PPEType, Role

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set",
)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """A session against a freshly created schema, rolled back afterwards."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s

    await engine.dispose()


@pytest_asyncio.fixture
async def seeded(session: AsyncSession) -> AsyncSession:
    """Minimal fixture data: one gate, PPE types, roles and employees."""
    helmet = PPEType(code="helmet", label="Capacete")
    goggles = PPEType(code="goggles", label="Óculos")
    gloves = PPEType(code="gloves", label="Luvas")
    retired = PPEType(code="retired_item", label="Item desativado", is_active=False)
    session.add_all([helmet, goggles, gloves, retired])
    await session.flush()

    operator = Role(code="operator", name="Operador")
    operator.required_ppe = [helmet, goggles]

    # Includes an inactive PPE type, which must not be required.
    legacy = Role(code="legacy", name="Função legada")
    legacy.required_ppe = [helmet, retired]

    unrestricted = Role(code="unrestricted", name="Sem exigência")

    disabled_role = Role(code="disabled_role", name="Função inativa", is_active=False)
    disabled_role.required_ppe = [helmet]

    session.add_all([operator, legacy, unrestricted, disabled_role])
    await session.flush()

    session.add(Gate(code="gate-01", name="Portão principal"))
    session.add_all([
        Employee(badge_id="ACTIVE01", name="Ativo", role_id=operator.id),
        Employee(badge_id="INACTIVE1", name="Inativo", role_id=operator.id, is_active=False),
        Employee(badge_id="LEGACY01", name="Legado", role_id=legacy.id),
        Employee(badge_id="FREE01", name="Sem exigência", role_id=unrestricted.id),
        Employee(badge_id="BADROLE01", name="Função inativa", role_id=disabled_role.id),
    ])
    await session.commit()

    return session
