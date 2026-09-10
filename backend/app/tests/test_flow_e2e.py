"""Stage 5 end-to-end tests.

Exercise the real path: a scan is published to a real broker, the backend
consumes it, asks for inference, a stand-in vision service answers, and the
decision comes back on the decision topic.

The vision service here is a few lines of test code, not the real worker —
which is the point: the backend is verified on its own, before the other
frontline exists.

Requires TEST_DATABASE_URL and TEST_MQTT_HOST; skipped otherwise.
"""

import asyncio
import json
import os
import uuid

import aiomqtt
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import topics
from app.core.mqtt_client import MQTTClient
from app.db.base import Base
from app.db.models import AccessDecision, AccessLog, Employee, Gate, PPEType, Role
from app.schemas.messages import AccessDecisionMessage, BadgeScan, VisionResult
from app.services.access_flow import AccessFlow
from app.services.rfid_handler import MessageHandlers
from app.services.session_manager import SessionManager

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
TEST_MQTT_HOST = os.getenv("TEST_MQTT_HOST")
TEST_MQTT_PORT = int(os.getenv("TEST_MQTT_PORT", "1883"))

pytestmark = pytest.mark.skipif(
    not (TEST_DATABASE_URL and TEST_MQTT_HOST),
    reason="TEST_DATABASE_URL and TEST_MQTT_HOST are required",
)

GATE = "gate-e2e"


@pytest_asyncio.fixture
async def db_factory():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        helmet = PPEType(code="helmet", label="Capacete")
        goggles = PPEType(code="goggles", label="Óculos")
        s.add_all([helmet, goggles])
        await s.flush()

        role = Role(code="operator", name="Operador")
        role.required_ppe = [helmet, goggles]
        s.add(role)
        await s.flush()

        s.add(Gate(code=GATE, name="Portão de teste"))
        s.add(Employee(badge_id="E2E001", name="Teste", role_id=role.id))
        s.add(Employee(badge_id="E2E002", name="Teste 2", role_id=role.id))
        await s.commit()

    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def running_backend(db_factory, monkeypatch):
    """The backend's MQTT consumer, wired exactly as the lifespan wires it."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "mqtt_host", TEST_MQTT_HOST)
    monkeypatch.setattr(settings, "mqtt_port", TEST_MQTT_PORT)
    monkeypatch.setattr(settings, "session_timeout_seconds", 2.0)
    monkeypatch.setattr(settings, "badge_cooldown_seconds", 0.0)

    client = MQTTClient()
    sessions = SessionManager(cooldown_seconds=0.0)
    flow = AccessFlow(client, sessions, db_factory)
    handlers = MessageHandlers(flow)

    client.register(topics.BADGE_SCAN_SUB, handlers.on_badge_scan)
    client.register(topics.VISION_RESULT_SUB, handlers.on_vision_result)

    await client.start()
    assert await client.wait_until_connected(timeout=5.0), "broker unreachable"
    await asyncio.sleep(0.3)  # let subscriptions settle

    yield client, sessions, db_factory

    await client.stop()
    sessions.clear()


class FakeVisionService:
    """Stands in for the vision worker: answers requests with fixed detections."""

    def __init__(self, detections: list[dict], delay: float = 0.05, silent: bool = False):
        self._detections = detections
        self._delay = delay
        self._silent = silent
        self._task: asyncio.Task | None = None
        self.requests_seen = 0

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0.3)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        async with aiomqtt.Client(
            hostname=TEST_MQTT_HOST, port=TEST_MQTT_PORT, identifier="fake-vision"
        ) as client:
            await client.subscribe(topics.vision_request(GATE))
            async for message in client.messages:
                self.requests_seen += 1
                if self._silent:
                    continue
                payload = json.loads(message.payload)
                await asyncio.sleep(self._delay)
                result = VisionResult(
                    session_id=uuid.UUID(payload["session_id"]),
                    detections=self._detections,
                    inference_ms=self._delay * 1000,
                )
                await client.publish(topics.vision_result(GATE), result.model_dump_json())


async def collect_decision(timeout: float = 6.0) -> AccessDecisionMessage | None:
    """Subscribe to the decision topic and return the first message."""
    async with aiomqtt.Client(
        hostname=TEST_MQTT_HOST, port=TEST_MQTT_PORT, identifier=f"collector-{uuid.uuid4()}"
    ) as client:
        await client.subscribe(topics.access_decision(GATE))

        async def first():
            async for message in client.messages:
                return AccessDecisionMessage.model_validate_json(message.payload)

        try:
            return await asyncio.wait_for(first(), timeout)
        except TimeoutError:
            return None


async def publish_scan(badge_id: str, session_id: uuid.UUID | None = None) -> uuid.UUID:
    scan = BadgeScan(
        gate_code=GATE,
        badge_id=badge_id,
        **({"session_id": session_id} if session_id else {}),
    )
    async with aiomqtt.Client(
        hostname=TEST_MQTT_HOST, port=TEST_MQTT_PORT, identifier=f"esp32-{uuid.uuid4()}"
    ) as client:
        await client.publish(topics.badge_scan(GATE), scan.model_dump_json())
    return scan.session_id


async def log_for(factory, session_id: uuid.UUID) -> AccessLog | None:
    async with factory() as s:
        stmt = select(AccessLog).where(AccessLog.session_id == session_id)
        return (await s.execute(stmt)).scalar_one_or_none()


# --- Tests -----------------------------------------------------------------

async def test_compliant_scan_results_in_a_grant(running_backend):
    """The full path: scan in, inference requested and answered, gate opens."""
    _, _, factory = running_backend
    vision = FakeVisionService([
        {"ppe_code": "helmet", "confidence": 0.95},
        {"ppe_code": "goggles", "confidence": 0.91},
    ])
    await vision.start()
    try:
        collector = asyncio.create_task(collect_decision())
        await asyncio.sleep(0.3)
        session_id = await publish_scan("E2E001")

        decision = await collector
        assert decision is not None, "no decision was published"
        assert decision.granted is True
        assert decision.reason == "compliant"
        assert decision.session_id == session_id
        assert vision.requests_seen == 1

        log = await log_for(factory, session_id)
        assert log is not None
        assert log.decision is AccessDecision.GRANTED
        assert log.latency_ms is not None
    finally:
        await vision.stop()


async def test_missing_ppe_results_in_a_denial_naming_the_item(running_backend):
    _, _, factory = running_backend
    vision = FakeVisionService([{"ppe_code": "helmet", "confidence": 0.95}])
    await vision.start()
    try:
        collector = asyncio.create_task(collect_decision())
        await asyncio.sleep(0.3)
        session_id = await publish_scan("E2E001")

        decision = await collector
        assert decision is not None
        assert decision.granted is False
        assert decision.reason == "missing_ppe"
        assert decision.missing_ppe == ["goggles"]

        log = await log_for(factory, session_id)
        assert log.decision is AccessDecision.DENIED_MISSING_PPE
    finally:
        await vision.stop()


async def test_unknown_badge_is_denied_and_logged(running_backend):
    _, _, factory = running_backend
    vision = FakeVisionService([{"ppe_code": "helmet", "confidence": 0.95}])
    await vision.start()
    try:
        collector = asyncio.create_task(collect_decision())
        await asyncio.sleep(0.3)
        session_id = await publish_scan("NOT_REGISTERED")

        decision = await collector
        assert decision is not None
        assert decision.granted is False
        assert decision.reason == "unknown_badge"

        log = await log_for(factory, session_id)
        assert log.employee_id is None
    finally:
        await vision.stop()


async def test_silent_vision_service_times_out_into_a_denial(running_backend):
    """The critical fail-safe: no answer must produce an explicit denial."""
    _, _, factory = running_backend
    vision = FakeVisionService([], silent=True)
    await vision.start()
    try:
        collector = asyncio.create_task(collect_decision(timeout=8.0))
        await asyncio.sleep(0.3)
        session_id = await publish_scan("E2E001")

        decision = await collector
        assert decision is not None, "a timeout must still publish a decision"
        assert decision.granted is False
        assert decision.reason == "vision_timeout"

        log = await log_for(factory, session_id)
        assert log.decision is AccessDecision.DENIED_VISION_TIMEOUT
        assert vision.requests_seen == 1
    finally:
        await vision.stop()


async def test_late_result_does_not_open_the_gate(running_backend):
    """An inference arriving after the timeout must be discarded."""
    _, sessions, factory = running_backend
    # Answers well after the 2s timeout configured in the fixture.
    vision = FakeVisionService(
        [{"ppe_code": "helmet", "confidence": 0.95},
         {"ppe_code": "goggles", "confidence": 0.95}],
        delay=3.5,
    )
    await vision.start()
    try:
        collector = asyncio.create_task(collect_decision(timeout=8.0))
        await asyncio.sleep(0.3)
        session_id = await publish_scan("E2E001")

        decision = await collector
        assert decision.granted is False
        assert decision.reason == "vision_timeout"

        # Give the late result time to arrive and be refused.
        await asyncio.sleep(2.0)

        log = await log_for(factory, session_id)
        assert log.decision is AccessDecision.DENIED_VISION_TIMEOUT
        assert sessions.active_count == 0
    finally:
        await vision.stop()


async def test_malformed_payload_does_not_stop_the_consumer(running_backend):
    """A bad message from a device must not deafen the backend."""
    _, _, factory = running_backend
    vision = FakeVisionService([
        {"ppe_code": "helmet", "confidence": 0.95},
        {"ppe_code": "goggles", "confidence": 0.91},
    ])
    await vision.start()
    try:
        async with aiomqtt.Client(
            hostname=TEST_MQTT_HOST, port=TEST_MQTT_PORT, identifier="garbage"
        ) as client:
            await client.publish(topics.badge_scan(GATE), b"{not valid json")
        await asyncio.sleep(0.4)

        # A valid scan right after must still be served.
        collector = asyncio.create_task(collect_decision())
        await asyncio.sleep(0.3)
        session_id = await publish_scan("E2E001")

        decision = await collector
        assert decision is not None
        assert decision.granted is True
    finally:
        await vision.stop()


async def test_consumer_serves_a_second_scan_while_the_first_is_pending(
    running_backend,
):
    """Regression: the consumer must not block while a scan awaits inference.

    Handling a scan waits for a vision result, and that result arrives as a
    message on the same consumer loop. If handlers were awaited inline, the
    loop would be blocked against the very message it needs — and every scan
    would time out. This test pins that behaviour down.
    """
    _, _, factory = running_backend
    vision = FakeVisionService(
        [{"ppe_code": "helmet", "confidence": 0.95},
         {"ppe_code": "goggles", "confidence": 0.95}],
        delay=0.4,
    )
    await vision.start()
    try:
        decisions: list[AccessDecisionMessage] = []

        async def collect_two() -> None:
            async with aiomqtt.Client(
                hostname=TEST_MQTT_HOST,
                port=TEST_MQTT_PORT,
                identifier=f"collector2-{uuid.uuid4()}",
            ) as client:
                await client.subscribe(topics.access_decision(GATE))
                async for message in client.messages:
                    decisions.append(
                        AccessDecisionMessage.model_validate_json(message.payload)
                    )
                    if len(decisions) == 2:
                        return

        collector = asyncio.create_task(collect_two())
        await asyncio.sleep(0.3)

        # Two different badges, back to back, before the first can finish.
        first = await publish_scan("E2E001")
        second = await publish_scan("E2E002")

        await asyncio.wait_for(collector, timeout=8.0)

        assert len(decisions) == 2
        assert {d.session_id for d in decisions} == {first, second}
        # Neither attempt hit the timeout path.
        assert all(d.reason != "vision_timeout" for d in decisions)
    finally:
        await vision.stop()
