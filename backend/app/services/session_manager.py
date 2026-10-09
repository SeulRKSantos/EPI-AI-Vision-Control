"""Session lifecycle for access attempts.

One session spans a single badge scan: it is opened when the scan arrives,
resolved when the matching vision result comes back, and closed once a
decision is published.

Two behaviours here exist specifically to keep the gate safe:

* A session that is never resolved expires. Waiting forever would leave the
  attempt hanging with no decision, and the firmware would be left guessing.
* A result whose session is unknown or already closed is refused. A late
  inference must not open a gate for an attempt that was already decided.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from app.schemas.messages import VisionResult

logger = logging.getLogger(__name__)


@dataclass
class PendingSession:
    """An access attempt awaiting its vision result."""

    session_id: uuid.UUID
    badge_id: str
    gate_code: str
    started_at: float = field(default_factory=time.monotonic)
    future: asyncio.Future[VisionResult] = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
    )

    def elapsed_ms(self) -> float:
        return (time.monotonic() - self.started_at) * 1000.0


class SessionManager:
    """Tracks in-flight sessions and enforces the badge cooldown."""

    def __init__(self, cooldown_seconds: float) -> None:
        self._cooldown_seconds = cooldown_seconds
        self._sessions: dict[uuid.UUID, PendingSession] = {}
        self._last_scan_at: dict[str, float] = {}

    # --- cooldown ----------------------------------------------------------

    def is_in_cooldown(self, badge_id: str) -> bool:
        """True when this badge was scanned too recently.

        Stops a card held against the reader, or a bouncing read, from
        starting a second verification while the first is still running.
        """
        last = self._last_scan_at.get(badge_id)
        if last is None:
            return False
        return (time.monotonic() - last) < self._cooldown_seconds

    def mark_scanned(self, badge_id: str) -> None:
        self._last_scan_at[badge_id] = time.monotonic()

    # --- session lifecycle -------------------------------------------------

    def open(
        self, session_id: uuid.UUID, badge_id: str, gate_code: str
    ) -> PendingSession:
        session = PendingSession(
            session_id=session_id, badge_id=badge_id, gate_code=gate_code
        )
        self._sessions[session_id] = session
        self.mark_scanned(badge_id)
        logger.debug("Session opened", extra={"session_id": str(session_id)})
        return session

    def resolve(self, result: VisionResult) -> bool:
        """Deliver a vision result to the session waiting for it.

        Returns False when there is no such session — the attempt already
        timed out, was already decided, or the identifier is unknown. The
        caller logs the discard; nothing else happens.
        """
        session = self._sessions.get(result.session_id)
        if session is None or session.future.done():
            logger.info(
                "Discarded vision result for unknown or closed session",
                extra={"session_id": str(result.session_id)},
            )
            return False

        session.future.set_result(result)
        return True

    async def wait_for_result(
        self, session: PendingSession, timeout: float
    ) -> VisionResult | None:
        """Await the vision result, or None when the wait times out."""
        try:
            return await asyncio.wait_for(asyncio.shield(session.future), timeout)
        except TimeoutError:
            logger.warning(
                "Vision result timed out",
                extra={
                    "session_id": str(session.session_id),
                    "timeout_seconds": timeout,
                },
            )
            return None

    def close(self, session_id: uuid.UUID) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None and not session.future.done():
            session.future.cancel()

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    def clear(self) -> None:
        """Drop every tracked session. Used on shutdown and in tests."""
        for session_id in list(self._sessions):
            self.close(session_id)
        self._last_scan_at.clear()
