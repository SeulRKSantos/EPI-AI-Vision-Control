"""Stage 1 and 2 tests: configuration, schema definition and health endpoints.

These run without a database or broker — they cover what can be verified
before any infrastructure exists.
"""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.base import Base
from app.db.models import AccessDecision, Employee, Gate, PPEType, Role
from app.main import app

client = TestClient(app)


# --- Configuration ---------------------------------------------------------

def test_database_url_is_built_from_parts():
    settings = Settings(
        postgres_user="u", postgres_password="p",
        postgres_host="h", postgres_port=5432, postgres_db="d",
    )
    assert settings.database_url == "postgresql+asyncpg://u:p@h:5432/d"


def test_defaults_are_fail_safe():
    """A short timeout denies legitimate access; the default must be generous."""
    settings = Settings()
    assert settings.session_timeout_seconds > 0
    assert 0 < settings.detection_confidence_threshold <= 1


# --- Schema ----------------------------------------------------------------

def test_every_expected_table_is_registered():
    expected = {
        "gates", "roles", "ppe_types",
        "role_ppe_requirements", "employees", "access_logs",
    }
    assert expected <= set(Base.metadata.tables)


def test_badge_id_is_unique_and_indexed():
    """The badge lookup happens on every scan and must not allow duplicates."""
    employees = Base.metadata.tables["employees"]
    assert any(
        c.name == "uq_employees_badge_id" for c in employees.constraints
        if hasattr(c, "name")
    )
    assert any("badge_id" in ix.columns for ix in employees.indexes)


def test_session_id_is_unique_on_access_logs():
    """One log row per session — a repeated result must not create a second."""
    logs = Base.metadata.tables["access_logs"]
    session_index = next(ix for ix in logs.indexes if "session_id" in ix.columns)
    assert session_index.unique


def test_only_one_decision_value_grants_access():
    granting = [d for d in AccessDecision if not d.value.startswith("denied")]
    assert granting == [AccessDecision.GRANTED]


def test_access_log_keeps_denormalized_badge_and_role():
    """The audit trail must survive edits to the employee record."""
    logs = Base.metadata.tables["access_logs"]
    assert not logs.c.badge_id.nullable
    assert "role_code" in logs.c


def test_models_expose_expected_relationships():
    assert hasattr(Role, "required_ppe")
    assert hasattr(PPEType, "roles")
    assert hasattr(Employee, "role")
    assert Gate.__tablename__ == "gates"


# --- Health endpoints ------------------------------------------------------

def test_health_responds_without_dependencies():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_reports_unavailable_database():
    """With no database reachable, readiness must fail rather than lie."""
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["checks"]["database"] == "unavailable"


def test_openapi_document_is_generated():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
def test_readiness_reports_unavailable_database(monkeypatch):
    """When the database cannot be reached, readiness must fail rather than lie."""
    import app.api.v1.health as health_module

    class BrokenSession:
        async def __aenter__(self):
            raise ConnectionError("simulated outage")
        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(health_module, "SessionFactory", lambda: BrokenSession())

    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["checks"]["database"] == "unavailable"


def test_readiness_succeeds_when_database_is_reachable():
    """Complements the test above: with a live database, readiness passes."""
    import os
    if not os.getenv("TEST_DATABASE_URL"):
        import pytest
        pytest.skip("no database configured")
    response = client.get("/health/ready")
    assert response.status_code == 200
