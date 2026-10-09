"""Stage 5 tests: session correlation, timeouts and cooldown.

These run without a broker or a database — the session manager is pure
asyncio state.
"""

import asyncio
import uuid

import pytest

from app.schemas.messages import Detection, VisionResult
from app.services.session_manager import SessionManager


def result_for(session_id: uuid.UUID, *codes: str) -> VisionResult:
    return VisionResult(
        session_id=session_id,
        detections=[Detection(ppe_code=c, confidence=0.9) for c in codes],
    )


# --- Correlation -----------------------------------------------------------

async def test_result_reaches_the_session_that_waits_for_it():
    manager = SessionManager(cooldown_seconds=0)
    session_id = uuid.uuid4()
    session = manager.open(session_id, "BADGE1", "gate-01")

    manager.resolve(result_for(session_id, "helmet"))
    result = await manager.wait_for_result(session, timeout=1.0)

    assert result is not None
    assert result.detections[0].ppe_code == "helmet"


async def test_concurrent_sessions_do_not_cross_results():
    """Two gates scanning at once must not receive each other's detections."""
    manager = SessionManager(cooldown_seconds=0)
    id_a, id_b = uuid.uuid4(), uuid.uuid4()
    session_a = manager.open(id_a, "BADGE_A", "gate-01")
    session_b = manager.open(id_b, "BADGE_B", "gate-02")

    # Resolved out of order, on purpose.
    manager.resolve(result_for(id_b, "vest"))
    manager.resolve(result_for(id_a, "helmet"))

    result_a = await manager.wait_for_result(session_a, timeout=1.0)
    result_b = await manager.wait_for_result(session_b, timeout=1.0)

    assert result_a.detections[0].ppe_code == "helmet"
    assert result_b.detections[0].ppe_code == "vest"


# --- Timeout ---------------------------------------------------------------

async def test_wait_returns_none_when_no_result_arrives():
    """A silent vision service must produce a timeout, not a hang."""
    manager = SessionManager(cooldown_seconds=0)
    session = manager.open(uuid.uuid4(), "BADGE1", "gate-01")

    result = await manager.wait_for_result(session, timeout=0.05)

    assert result is None


async def test_result_arriving_before_the_deadline_is_accepted():
    manager = SessionManager(cooldown_seconds=0)
    session_id = uuid.uuid4()
    session = manager.open(session_id, "BADGE1", "gate-01")

    async def respond_late():
        await asyncio.sleep(0.02)
        manager.resolve(result_for(session_id, "helmet"))

    asyncio.create_task(respond_late())
    result = await manager.wait_for_result(session, timeout=1.0)

    assert result is not None


# --- Late and unknown results ----------------------------------------------

async def test_result_for_unknown_session_is_refused():
    """An identifier the backend never issued must not be honoured."""
    manager = SessionManager(cooldown_seconds=0)
    assert manager.resolve(result_for(uuid.uuid4(), "helmet")) is False


async def test_result_after_session_closed_is_refused():
    """A late inference must not decide an attempt that already ended."""
    manager = SessionManager(cooldown_seconds=0)
    session_id = uuid.uuid4()
    session = manager.open(session_id, "BADGE1", "gate-01")

    await manager.wait_for_result(session, timeout=0.01)  # times out
    manager.close(session_id)

    assert manager.resolve(result_for(session_id, "helmet")) is False


async def test_duplicate_result_is_refused():
    """Two publishes of the same result must not resolve twice."""
    manager = SessionManager(cooldown_seconds=0)
    session_id = uuid.uuid4()
    manager.open(session_id, "BADGE1", "gate-01")

    assert manager.resolve(result_for(session_id, "helmet")) is True
    assert manager.resolve(result_for(session_id, "vest")) is False


# --- Cooldown --------------------------------------------------------------

async def test_badge_enters_cooldown_after_a_scan():
    """A card held against the reader must not start a second verification."""
    manager = SessionManager(cooldown_seconds=5.0)
    assert manager.is_in_cooldown("BADGE1") is False

    manager.open(uuid.uuid4(), "BADGE1", "gate-01")

    assert manager.is_in_cooldown("BADGE1") is True


async def test_cooldown_is_per_badge():
    """One employee's scan must not block the next person in line."""
    manager = SessionManager(cooldown_seconds=5.0)
    manager.open(uuid.uuid4(), "BADGE1", "gate-01")

    assert manager.is_in_cooldown("BADGE1") is True
    assert manager.is_in_cooldown("BADGE2") is False


async def test_cooldown_expires():
    manager = SessionManager(cooldown_seconds=0.05)
    manager.open(uuid.uuid4(), "BADGE1", "gate-01")
    assert manager.is_in_cooldown("BADGE1") is True

    await asyncio.sleep(0.06)

    assert manager.is_in_cooldown("BADGE1") is False


# --- Bookkeeping -----------------------------------------------------------

async def test_sessions_are_released_on_close():
    """Sessions must not accumulate: a busy gate would leak memory."""
    manager = SessionManager(cooldown_seconds=0)
    ids = [uuid.uuid4() for _ in range(5)]
    for session_id in ids:
        manager.open(session_id, f"B{session_id}", "gate-01")
    assert manager.active_count == 5

    for session_id in ids:
        manager.close(session_id)

    assert manager.active_count == 0


async def test_closing_an_unknown_session_is_harmless():
    manager = SessionManager(cooldown_seconds=0)
    manager.close(uuid.uuid4())  # must not raise


async def test_clear_drops_everything():
    manager = SessionManager(cooldown_seconds=5.0)
    manager.open(uuid.uuid4(), "BADGE1", "gate-01")

    manager.clear()

    assert manager.active_count == 0
    assert manager.is_in_cooldown("BADGE1") is False
