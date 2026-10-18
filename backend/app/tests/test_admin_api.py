"""Stage 3 tests: the administration API.

Run against a real database through the ASGI transport, so routing,
validation, serialization and persistence are all exercised together.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

PREFIX = "/api/v1"


@pytest_asyncio.fixture
async def client(monkeypatch):
    """An HTTP client bound to the app, with a clean schema behind it."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import app.api.deps as deps
    monkeypatch.setattr(deps, "SessionFactory", factory)

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await engine.dispose()


async def make_ppe(client, code: str, label: str = "Item") -> dict:
    response = await client.post(f"{PREFIX}/ppe-types", json={"code": code, "label": label})
    assert response.status_code == 201, response.text
    return response.json()


async def make_role(client, code: str, required: list[str] | None = None) -> dict:
    response = await client.post(
        f"{PREFIX}/roles",
        json={"code": code, "name": code.title(), "required_ppe": required or []},
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- PPE types -------------------------------------------------------------

async def test_create_and_read_ppe_type(client):
    created = await make_ppe(client, "helmet", "Capacete")
    assert created["code"] == "helmet"
    assert created["is_active"] is True

    response = await client.get(f"{PREFIX}/ppe-types/helmet")
    assert response.status_code == 200
    assert response.json()["label"] == "Capacete"


async def test_duplicate_ppe_code_is_rejected(client):
    await make_ppe(client, "helmet")
    response = await client.post(
        f"{PREFIX}/ppe-types", json={"code": "helmet", "label": "Outro"}
    )
    assert response.status_code == 409


async def test_unknown_ppe_type_returns_404(client):
    response = await client.get(f"{PREFIX}/ppe-types/nonexistent")
    assert response.status_code == 404


async def test_deactivated_ppe_is_hidden_but_retrievable(client):
    """Deactivation must not erase the record: logs still reference the code."""
    await make_ppe(client, "helmet")
    assert (await client.delete(f"{PREFIX}/ppe-types/helmet")).status_code == 204

    listed = (await client.get(f"{PREFIX}/ppe-types")).json()
    assert listed == []

    with_inactive = (
        await client.get(f"{PREFIX}/ppe-types", params={"include_inactive": True})
    ).json()
    assert len(with_inactive) == 1
    assert with_inactive[0]["is_active"] is False


# --- Roles and the requirement matrix --------------------------------------

async def test_create_role_with_requirements(client):
    await make_ppe(client, "helmet")
    await make_ppe(client, "goggles")

    role = await make_role(client, "operator", ["helmet", "goggles"])

    assert {p["code"] for p in role["required_ppe"]} == {"helmet", "goggles"}


async def test_role_with_unknown_ppe_code_is_rejected(client):
    """Silently dropping a code would leave a role requiring less than intended."""
    await make_ppe(client, "helmet")

    response = await client.post(
        f"{PREFIX}/roles",
        json={"code": "operator", "name": "Operador", "required_ppe": ["helmet", "ghost"]},
    )
    assert response.status_code == 422
    assert "ghost" in response.text


async def test_requirements_are_replaced_not_merged(client):
    await make_ppe(client, "helmet")
    await make_ppe(client, "goggles")
    await make_ppe(client, "gloves")
    await make_role(client, "operator", ["helmet", "goggles"])

    response = await client.put(
        f"{PREFIX}/roles/operator/requirements", json={"required_ppe": ["gloves"]}
    )
    assert response.status_code == 200
    assert {p["code"] for p in response.json()["required_ppe"]} == {"gloves"}


async def test_requirements_can_be_cleared(client):
    """An office role legitimately requires nothing."""
    await make_ppe(client, "helmet")
    await make_role(client, "office", ["helmet"])

    response = await client.put(
        f"{PREFIX}/roles/office/requirements", json={"required_ppe": []}
    )
    assert response.status_code == 200
    assert response.json()["required_ppe"] == []


# --- Employees -------------------------------------------------------------

async def test_register_and_read_employee(client):
    await make_ppe(client, "helmet")
    await make_role(client, "operator", ["helmet"])

    response = await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "B001", "name": "Fulano", "role_code": "operator"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["badge_id"] == "B001"
    assert body["role"]["code"] == "operator"
    assert body["role"]["required_ppe"][0]["code"] == "helmet"


async def test_duplicate_badge_is_rejected(client):
    await make_role(client, "operator")
    await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "B001", "name": "A", "role_code": "operator"},
    )
    response = await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "B001", "name": "B", "role_code": "operator"},
    )
    assert response.status_code == 409


async def test_employee_with_unknown_role_is_rejected(client):
    response = await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "B001", "name": "A", "role_code": "ghost"},
    )
    assert response.status_code == 422


async def test_employee_role_can_be_changed(client):
    await make_role(client, "operator")
    await make_role(client, "chemist")
    await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "B001", "name": "A", "role_code": "operator"},
    )

    response = await client.patch(
        f"{PREFIX}/employees/B001", json={"role_code": "chemist"}
    )
    assert response.status_code == 200
    assert response.json()["role"]["code"] == "chemist"


async def test_deactivated_employee_is_hidden_but_retrievable(client):
    await make_role(client, "operator")
    await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "B001", "name": "A", "role_code": "operator"},
    )

    assert (await client.delete(f"{PREFIX}/employees/B001")).status_code == 204
    assert (await client.get(f"{PREFIX}/employees")).json() == []

    # Still reachable by badge, which is how the gate looks it up.
    response = await client.get(f"{PREFIX}/employees/B001")
    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_employees_can_be_filtered_by_role(client):
    await make_role(client, "operator")
    await make_role(client, "chemist")
    await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "B001", "name": "A", "role_code": "operator"},
    )
    await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "B002", "name": "B", "role_code": "chemist"},
    )

    listed = (
        await client.get(f"{PREFIX}/employees", params={"role_code": "chemist"})
    ).json()
    assert [e["badge_id"] for e in listed] == ["B002"]


async def test_badge_can_be_changed(client):
    await make_role(client, "operator")
    await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "B001", "name": "A", "role_code": "operator"},
    )

    response = await client.patch(f"{PREFIX}/employees/B001", json={"badge_id": "C9F2"})
    assert response.status_code == 200, response.text
    assert response.json()["badge_id"] == "C9F2"

    # The old card no longer identifies anyone; the new one does.
    assert (await client.get(f"{PREFIX}/employees/B001")).status_code == 404
    assert (await client.get(f"{PREFIX}/employees/C9F2")).json()["name"] == "A"


async def test_badge_change_to_a_card_in_use_is_refused(client):
    await make_role(client, "operator")
    for badge, name in (("B001", "A"), ("B002", "B")):
        await client.post(
            f"{PREFIX}/employees",
            json={"badge_id": badge, "name": name, "role_code": "operator"},
        )

    response = await client.patch(f"{PREFIX}/employees/B001", json={"badge_id": "B002"})
    assert response.status_code == 409
    assert "B" in response.json()["detail"]

    # Neither employee changed.
    assert (await client.get(f"{PREFIX}/employees/B001")).json()["name"] == "A"
    assert (await client.get(f"{PREFIX}/employees/B002")).json()["name"] == "B"


async def test_keeping_the_same_badge_is_not_a_conflict(client):
    await make_role(client, "operator")
    await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "B001", "name": "A", "role_code": "operator"},
    )
    response = await client.patch(
        f"{PREFIX}/employees/B001", json={"badge_id": "B001", "name": "A2"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "A2"


async def test_badges_are_stored_as_the_reader_reports_them(client):
    """The gate sends uppercase hex; a badge typed in lowercase must match it."""
    await make_role(client, "operator")
    response = await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": " 769f8205 ", "name": "A", "role_code": "operator"},
    )
    assert response.status_code == 201
    assert response.json()["badge_id"] == "769F8205"
    assert (await client.get(f"{PREFIX}/employees/769f8205")).status_code == 200

    response = await client.patch(f"{PREFIX}/employees/769F8205", json={"badge_id": "e2f48105"})
    assert response.json()["badge_id"] == "E2F48105"


async def test_blank_new_badge_is_rejected(client):
    await make_role(client, "operator")
    await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "B001", "name": "A", "role_code": "operator"},
    )
    response = await client.patch(f"{PREFIX}/employees/B001", json={"badge_id": "   "})
    assert response.status_code == 422


# --- Validation ------------------------------------------------------------

async def test_empty_badge_id_is_rejected(client):
    await make_role(client, "operator")
    response = await client.post(
        f"{PREFIX}/employees",
        json={"badge_id": "", "name": "A", "role_code": "operator"},
    )
    assert response.status_code == 422


# --- Access logs -----------------------------------------------------------

async def test_access_logs_start_empty_with_a_page_envelope(client):
    response = await client.get(f"{PREFIX}/access-logs")
    assert response.status_code == 200
    body = response.json()
    assert body == {"total": 0, "limit": 50, "offset": 0, "items": []}


async def test_access_log_limit_is_bounded(client):
    """An unbounded page size would let one request pull the whole history."""
    response = await client.get(f"{PREFIX}/access-logs", params={"limit": 10_000})
    assert response.status_code == 422


async def test_access_logs_are_read_only(client):
    """The audit trail must not be writable through the API."""
    response = await client.post(f"{PREFIX}/access-logs", json={})
    assert response.status_code == 405
