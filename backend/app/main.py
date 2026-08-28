"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.api.v1.health import router as health_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Owns the lifecycle of every long-lived resource.

    The MQTT client and its consumer task join this block in stage 5. Keeping
    them here — rather than at import time — is what lets the REST API and the
    message consumer share one event loop without blocking each other.
    """
    logger.info(
        "Starting service",
        extra={"environment": settings.environment, "app": settings.app_name},
    )

    yield

    logger.info("Shutting down service")
    await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Access control backend for EPI-AI-Vision-Control",
    lifespan=lifespan,
)

# Health lives at the root so probes don't depend on the API version prefix.
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_v1_prefix)
