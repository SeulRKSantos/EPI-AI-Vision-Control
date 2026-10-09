"""Liveness and readiness endpoints."""

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import settings
from app.core.mqtt_client import mqtt_client
from app.db.session import SessionFactory

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Returns as long as the process is running. Checks no dependencies."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }


@router.get("/health/ready", summary="Readiness probe")
async def readiness(response: Response) -> dict[str, object]:
    """Checks the dependencies the service needs to make a decision.

    Returns 503 when any dependency is down, so an orchestrator can hold
    traffic back instead of letting requests fail one by one.
    """
    checks: dict[str, str] = {}

    try:
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        logger.warning("Database readiness check failed", extra={"error": str(exc)})
        checks["database"] = "unavailable"

    checks["mqtt"] = "ok" if mqtt_client.is_connected else "unavailable"

    ready = all(value == "ok" for value in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"ready": ready, "checks": checks}
