"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.core import topics
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.mqtt_client import mqtt_client
from app.db.session import SessionFactory, dispose_engine
from app.services.access_flow import AccessFlow
from app.services.rfid_handler import MessageHandlers
from app.services.session_manager import SessionManager

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Owns the lifecycle of every long-lived resource.

    The REST API and the MQTT consumer share this event loop. Neither blocks
    the other: the consumer awaits messages, and each scan awaits its vision
    result, so the API stays responsive throughout.
    """
    logger.info(
        "Starting service",
        extra={"environment": settings.environment, "app": settings.app_name},
    )

    sessions = SessionManager(cooldown_seconds=settings.badge_cooldown_seconds)
    flow = AccessFlow(mqtt_client, sessions, SessionFactory)
    handlers = MessageHandlers(flow)

    mqtt_client.register(topics.BADGE_SCAN_SUB, handlers.on_badge_scan)
    mqtt_client.register(topics.VISION_RESULT_SUB, handlers.on_vision_result)
    mqtt_client.register(topics.GATE_STATUS_SUB, handlers.on_gate_status)

    await mqtt_client.start()

    # Exposed for the API layer (the scan simulation endpoint).
    app.state.mqtt = mqtt_client
    app.state.sessions = sessions
    app.state.flow = flow

    yield

    logger.info("Shutting down service")
    await mqtt_client.stop()
    sessions.clear()
    await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Access control backend for EPI-AI-Vision-Control",
    lifespan=lifespan,
)

# The admin panel runs on its own origin, so the browser needs explicit
# permission to call this API. The allowed origins are configuration, not a
# constant: a deployment behind one hostname should not have to ship code.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health lives at the root so probes don't depend on the API version prefix.
app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_v1_prefix)
