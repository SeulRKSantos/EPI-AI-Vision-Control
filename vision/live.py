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
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
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
    def __init__(
        self,
        camera,
        detector: Detector,
        interval_s: float,
        threshold: float,
    ) -> None:
        self._camera = camera
        self._detector = detector
        self._interval_s = interval_s
        self._threshold = threshold
        self._overlay = Overlay()
        self._viewers = 0
        self._last_error: str | None = None
        # A dedicated worker, so a slow live call never delays the inference
        # a badge scan is waiting on.
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live")

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
        age = time.monotonic() - self._overlay.updated_at if self._overlay.updated_at else None
        fresh = age is not None and age <= self.overlay_ttl()
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
        """Infers while watched; idles otherwise."""
        if self._interval_s <= 0:
            logger.info("Live boxes disabled; streaming plain video")
            return

        loop = asyncio.get_running_loop()
        while True:
            if self._viewers == 0:
                await asyncio.sleep(0.5)
                continue

            frame = self._camera.grab()
            if frame is None:
                await asyncio.sleep(1.0)
                continue

            started = time.monotonic()
            try:
                predictions = await loop.run_in_executor(
                    self._pool, self._detector.predictions, frame
                )
                self.publish(
                    self._detector.boxes(predictions),
                    source="live",
                    latency_ms=(time.monotonic() - started) * 1000.0,
                )
                self._last_error = None
            except Exception as exc:  # noqa: BLE001 - the view must keep going
                self._last_error = str(exc)[:200]
                logger.warning("Live inference failed", extra={"error": self._last_error})

            elapsed = time.monotonic() - started
            await asyncio.sleep(max(self._interval_s - elapsed, 0.1))

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
