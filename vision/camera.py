"""Camera capture.

OpenCV keeps an internal buffer, so calling `read()` only when a badge is
scanned returns a frame from seconds ago — the person who just walked up
would be judged on whoever stood there before. A background thread therefore
keeps grabbing and discarding frames, and the capture takes the most recent
one.
"""

import logging
import threading
import time

import cv2

logger = logging.getLogger(__name__)


class Camera:
    def __init__(self, index: int, width: int, height: int) -> None:
        self._index = index
        self._width = width
        self._height = height
        self._capture: cv2.VideoCapture | None = None
        self._frame = None
        self._frame_at = 0.0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> bool:
        self._capture = cv2.VideoCapture(self._index)
        if not self._capture.isOpened():
            logger.error("Could not open camera", extra={"index": self._index})
            return False

        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        # Ask the driver for the shallowest buffer it will give us. Not every
        # backend honours it, which is why the draining thread exists anyway.
        self._capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._running = True
        self._thread = threading.Thread(target=self._drain, name="camera", daemon=True)
        self._thread.start()
        logger.info("Camera started", extra={"index": self._index})
        return True

    def _drain(self) -> None:
        while self._running:
            ok, frame = self._capture.read()
            if not ok:
                # A camera that was unplugged should not spin the CPU.
                time.sleep(0.1)
                continue
            with self._lock:
                self._frame = frame
                self._frame_at = time.monotonic()

    def grab(self, max_age_s: float = 2.0):
        """Returns the most recent frame, or None if it is stale or absent.

        A stale frame is refused rather than used: deciding access from an old
        image is worse than not deciding at all, because the backend's timeout
        turns silence into a refusal while a wrong frame could open the gate.
        """
        with self._lock:
            if self._frame is None:
                return None
            if time.monotonic() - self._frame_at > max_age_s:
                logger.warning("Latest frame is stale, refusing to use it")
                return None
            return self._frame.copy()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._capture is not None:
            self._capture.release()
        logger.info("Camera stopped")
