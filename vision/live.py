"""Live view of the gate camera, with the model's boxes drawn on it.

Two sources feed the boxes:

* A throttled live loop, which runs the model every few seconds while at
  least one person is watching. Nobody watching means no calls: each
  inference is billed, and an unattended dashboard would otherwise spend the
  quota around the clock.
* Every badge scan. The boxes of the inference that decided an attempt are
  published here as soon as it returns, so the person at the panel sees
  exactly what the gate saw.

Boxes are drawn on the server and the frames sent as MJPEG. The browser then
needs nothing but an <img> tag, and the overlay can never drift out of step
with the frame underneath it.
"""

import asyncio
import logging
import threading
import time
import unicodedata
from dataclasses import dataclass, field

import cv2

from detector import Box, Detector

logger = logging.getLogger("vision.live")

# BGR
ACCEPTED = (60, 170, 50)
BELOW = (20, 165, 225)
IGNORED = (150, 150, 150)
TEXT_ON_DARK = (255, 255, 255)


def ascii_label(text: str) -> str:
    """OpenCV's Hershey fonts have no accented glyphs; fold them away."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


@dataclass
class Overlay:
    boxes: list[Box] = field(default_factory=list)
    source: str = "none"          # "live" or "scan"
    session_id: str | None = None
    updated_at: float = 0.0       # monotonic
    latency_ms: float = 0.0


class LiveView:
    # Calls still running past their timeout. Beyond this many, the service is
    # treated as unresponsive and no further calls are piled on top.
    MAX_STUCK_CALLS = 2

    def __init__(
        self,
        camera,
        detector: Detector,
        interval_s: float,
        threshold: float,
        timeout_s: float = 6.0,
    ) -> None:
        self._camera = camera
        # The live view should get a detector of its own (its own HTTP
        # client), so nothing it does can hold up the inference a badge scan
        # is waiting on.
        self._detector = detector
        self._interval_s = interval_s
        self._threshold = threshold
        self._timeout_s = timeout_s
        self._overlay = Overlay()
        self._viewers = 0
        self._last_error: str | None = None

        self._in_flight = 0
        self._in_flight_lock = threading.Lock()
        self._attempts = 0
        self._last_attempt_at = 0.0
        self._last_success_at = 0.0

    # --- viewers -----------------------------------------------------------

    @property
    def viewers(self) -> int:
        return self._viewers

    def viewer_joined(self) -> None:
        self._viewers += 1

    def viewer_left(self) -> None:
        self._viewers = max(0, self._viewers - 1)

    # --- overlay -----------------------------------------------------------

    def publish(self, boxes: list[Box], source: str, latency_ms: float,
                session_id: str | None = None) -> None:
        self._overlay = Overlay(
            boxes=boxes,
            source=source,
            session_id=session_id,
            updated_at=time.monotonic(),
            latency_ms=latency_ms,
        )

    def overlay_ttl(self) -> float:
        # Boxes outlive one cycle so they do not flicker, but not much longer:
        # a box hanging where someone stood five seconds ago is a lie.
        return max(3.0, self._interval_s * 2.5)

    def snapshot(self) -> dict:
        """The current overlay, for the panel's detection list."""
        now = time.monotonic()
        age = now - self._overlay.updated_at if self._overlay.updated_at else None
        fresh = age is not None and age <= self.overlay_ttl()

        def since(moment: float) -> float | None:
            return round(now - moment, 1) if moment else None

        return {
            "live_enabled": self._interval_s > 0,
            "interval_s": self._interval_s,
            "viewers": self._viewers,
            "source": self._overlay.source,
            "session_id": self._overlay.session_id,
            "age_s": round(age, 2) if age is not None else None,
            "fresh": fresh,
            "latency_ms": round(self._overlay.latency_ms, 1),
            "threshold": self._threshold,
            "error": self._last_error,
            # Health of the live loop itself, so "no boxes" can be told apart
            # from "the loop is not getting answers".
            "live_attempts": self._attempts,
            "last_attempt_age_s": since(self._last_attempt_at),
            "last_success_age_s": since(self._last_success_at),
            "stuck_calls": self._in_flight,
            "boxes": [
                {
                    "class_name": b.class_name,
                    "ppe_code": b.ppe_code,
                    "confidence": round(b.confidence, 4),
                    "accepted": b.ppe_code is not None and b.confidence >= self._threshold,
                }
                for b in (self._overlay.boxes if fresh else [])
            ],
        }

    # --- drawing -----------------------------------------------------------

    def annotate(self, frame):
        """Draws the current boxes onto a copy-safe frame in place."""
        overlay = self._overlay
        if time.monotonic() - overlay.updated_at > self.overlay_ttl():
            return frame

        for box in overlay.boxes:
            if box.ppe_code is None:
                color, thickness = IGNORED, 1
                label = f"{ascii_label(box.class_name)} {box.confidence:.2f} (ignorado)"
            elif box.confidence >= self._threshold:
                color, thickness = ACCEPTED, 3
                label = f"{ascii_label(box.class_name)} {box.confidence:.2f}"
            else:
                color, thickness = BELOW, 2
                label = f"{ascii_label(box.class_name)} {box.confidence:.2f} baixa"

            cv2.rectangle(frame, (box.x1, box.y1), (box.x2, box.y2), color, thickness)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            top = max(box.y1 - th - 8, 0)
            cv2.rectangle(frame, (box.x1, top), (box.x1 + tw + 8, top + th + 8), color, -1)
            cv2.putText(frame, label, (box.x1 + 4, top + th + 3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, TEXT_ON_DARK, 1, cv2.LINE_AA)

        if overlay.source == "scan":
            cv2.putText(frame, "LEITURA DE CRACHA", (14, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, TEXT_ON_DARK, 2, cv2.LINE_AA)
        return frame

    # --- live inference ----------------------------------------------------

    async def run(self) -> None:
        """Infers while watched; idles otherwise. Never stops on its own."""
        if self._interval_s <= 0:
            logger.info("Live boxes disabled; streaming plain video")
            return

        while True:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad cycle must not end the view
                logger.exception("Live loop error; continuing")
                await asyncio.sleep(1.0)

    async def _cycle(self) -> None:
        if self._viewers == 0:
            await asyncio.sleep(0.5)
            return

        frame = self._camera.grab()
        if frame is None:
            await asyncio.sleep(1.0)
            return

        if self._in_flight >= self.MAX_STUCK_CALLS:
            # Earlier calls are still hanging. Adding more would only leak
            # threads; wait for the service to come back.
            self._last_error = "O serviço de visão não está respondendo às análises ao vivo"
            await asyncio.sleep(self._interval_s)
            return

        started = time.monotonic()
        self._attempts += 1
        self._last_attempt_at = started
        try:
            predictions = await self._infer(frame)
            self.publish(
                self._detector.boxes(predictions),
                source="live",
                latency_ms=(time.monotonic() - started) * 1000.0,
            )
            if self._last_success_at == 0.0 or self._last_error:
                logger.info("Live inference answering")
            self._last_success_at = time.monotonic()
            self._last_error = None
        except asyncio.TimeoutError:
            self._last_error = f"Sem resposta do serviço de visão em {self._timeout_s:.0f} s"
            logger.warning("Live inference timed out", extra={"timeout_s": self._timeout_s})
        except Exception as exc:  # noqa: BLE001 - the view must keep going
            self._last_error = str(exc)[:200]
            logger.warning("Live inference failed", extra={"error": self._last_error})

        elapsed = time.monotonic() - started
        await asyncio.sleep(max(self._interval_s - elapsed, 0.1))

    async def _infer(self, frame):
        """Runs one inference on its own thread, bounded by the timeout.

        A plain executor would not do: an HTTP call that never returns keeps
        its worker forever, and every later call queues behind it — the live
        view goes quiet with no error to show for it. Here a hung call is
        abandoned at the timeout and the next cycle starts on a fresh thread.
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def deliver(setter, value):
            if not future.done():
                setter(value)

        def work():
            try:
                result = self._detector.predictions(frame)
                outcome = (future.set_result, result)
            except Exception as exc:  # noqa: BLE001 - handed to the awaiting side
                outcome = (future.set_exception, exc)
            finally:
                with self._in_flight_lock:
                    self._in_flight -= 1
            try:
                loop.call_soon_threadsafe(deliver, *outcome)
            except RuntimeError:
                pass  # the loop closed while this call was running

        with self._in_flight_lock:
            self._in_flight += 1
        threading.Thread(target=work, name="live-infer", daemon=True).start()
        return await asyncio.wait_for(future, self._timeout_s)

    def shutdown(self) -> None:
        """Nothing to release: inference threads are daemons."""
