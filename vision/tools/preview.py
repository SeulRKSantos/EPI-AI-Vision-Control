"""Visual preview with bounding boxes.

A development tool, not part of the service: it runs the model against the
webcam and draws what it finds, which is how you check framing, lighting and
distance before trusting the gate to it.

Inference runs on a background thread. Each call is a round trip to the
cloud, and drawing only after it returns would freeze the video for a second
at a time. Here the video stays live and the boxes update whenever a fresh
answer arrives.

Classes the service would ignore are drawn in red and printed once, so a
missing mapping shows up while it can still be fixed.

    set -a && source ../.env && set +a
    python3 tools/preview.py
"""

import os
import sys
import threading
import time
from pathlib import Path

# OpenCV's Qt window paints black under Wayland. Forcing X11 (XWayland) is the
# standard workaround and is harmless on a plain X11 session.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import cv2  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from detector import Detector  # noqa: E402

WINDOW = "EPI preview"

# Drawn only to show where the backend's cut-off would land. The service
# itself publishes every detection and lets the backend decide.
PREVIEW_THRESHOLD = float(os.getenv("PREVIEW_THRESHOLD", "0.6"))

ACCEPTED = (54, 160, 47)    # BGR green
BELOW = (11, 160, 210)      # BGR amber
UNMAPPED = (42, 55, 200)    # BGR red


class BackgroundInference:
    """Keeps the latest predictions, refreshed from the newest frame."""

    def __init__(self, detector: Detector) -> None:
        self._detector = detector
        self._lock = threading.Lock()
        self._frame = None
        self._predictions: list[dict] = []
        self._latency_ms = 0.0
        self._error: str | None = None
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, frame) -> None:
        with self._lock:
            self._frame = frame.copy()

    def latest(self):
        with self._lock:
            return list(self._predictions), self._latency_ms, self._error

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            with self._lock:
                frame, self._frame = self._frame, None
            if frame is None:
                time.sleep(0.02)
                continue

            started = time.monotonic()
            try:
                raw = self._detector._client.run_workflow(
                    workspace_name=settings.roboflow_workspace,
                    workflow_id=settings.roboflow_workflow,
                    images={"image": frame},
                    use_cache=True,
                )
                predictions = list(self._detector._iter_predictions(raw))
                error = None
            except Exception as exc:  # noqa: BLE001 - a preview should not die
                predictions, error = [], str(exc)

            with self._lock:
                self._predictions = predictions
                self._latency_ms = (time.monotonic() - started) * 1000.0
                self._error = error


def draw(frame, predictions, detector: Detector, seen_unmapped: set[str]) -> None:
    for prediction in predictions:
        class_name = prediction.get("class") or prediction.get("class_name") or "?"
        confidence = float(prediction.get("confidence", 0.0))
        ppe_code = detector.map_class(class_name)

        if ppe_code is None:
            color = UNMAPPED
            label = f"{class_name} {confidence:.2f} SEM MAPEAMENTO"
            if class_name not in seen_unmapped:
                seen_unmapped.add(class_name)
                print(f"classe sem mapeamento em class_map.json: {class_name}")
        else:
            color = ACCEPTED if confidence >= PREVIEW_THRESHOLD else BELOW
            label = f"{class_name} -> {ppe_code} {confidence:.2f}"

        x, y = prediction.get("x"), prediction.get("y")
        w, h = prediction.get("width"), prediction.get("height")
        if None in (x, y, w, h):
            continue

        x1, y1 = int(x - w / 2), int(y - h / 2)
        x2, y2 = int(x + w / 2), int(y + h / 2)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, max(y1 - 8, 18)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def main() -> int:
    problems = settings.validate()
    if problems:
        for problem in problems:
            print(f"configuracao: {problem}")
        return 1

    detector = Detector(
        api_url=settings.roboflow_api_url,
        api_key=settings.roboflow_api_key,
        workspace=settings.roboflow_workspace,
        workflow=settings.roboflow_workflow,
        class_map=settings.class_map,
    )

    capture = cv2.VideoCapture(settings.camera_index)
    if not capture.isOpened():
        print("nao foi possivel abrir a camera")
        return 1

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, 1280, 720)

    inference = BackgroundInference(detector)
    seen_unmapped: set[str] = set()
    print("pressione 'q' na janela para sair")
    print(f"limiar exibido: {PREVIEW_THRESHOLD:.2f} (verde acima, ambar abaixo)")

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                print("falha ao capturar imagem")
                break

            inference.submit(frame)
            predictions, latency_ms, error = inference.latest()
            draw(frame, predictions, detector, seen_unmapped)

            status = f"inferencia: {latency_ms:.0f} ms"
            if error:
                status = f"erro: {error[:60]}"
            cv2.putText(frame, status, (12, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            cv2.imshow(WINDOW, frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        inference.stop()
        capture.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
