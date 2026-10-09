"""Visual preview with bounding boxes.

A development tool, not part of the service: it runs the model continuously
against the webcam and draws what it finds, which is how you check framing,
lighting and distance before trusting the gate to it.

It also prints the PPE code each class maps to, so a class the service would
silently ignore shows up here as "unmapped" while you can still fix it.

    ROBOFLOW_API_KEY=... ROBOFLOW_WORKSPACE=... ROBOFLOW_WORKFLOW=... \
        python tools/preview.py
"""

import os
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from detector import Detector  # noqa: E402

# Drawn only to show where the backend's cut-off would land. The service
# itself publishes every detection and lets the backend decide.
PREVIEW_THRESHOLD = float(os.getenv("PREVIEW_THRESHOLD", "0.5"))

ACCEPTED = (54, 122, 47)    # BGR, green
BELOW = (11, 134, 184)      # BGR, amber
UNMAPPED = (42, 55, 163)    # BGR, red


def main() -> int:
    problems = settings.validate()
    if problems:
        for problem in problems:
            print(f"configuração: {problem}")
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
        print("não foi possível abrir a câmera")
        return 1

    print("pressione 'q' para sair")
    seen_unmapped: set[str] = set()

    while True:
        ok, frame = capture.read()
        if not ok:
            print("falha ao capturar imagem")
            break

        try:
            raw = detector._client.run_workflow(
                workspace_name=settings.roboflow_workspace,
                workflow_id=settings.roboflow_workflow,
                images={"image": frame},
                use_cache=True,
            )
            predictions = detector._iter_predictions(raw)
        except Exception as exc:  # noqa: BLE001 - a preview should not crash
            print(f"inferência falhou: {exc}")
            predictions = []

        for prediction in predictions:
            class_name = prediction.get("class") or prediction.get("class_name") or "?"
            confidence = float(prediction.get("confidence", 0.0))

            ppe_code = settings.class_map.get(class_name)
            if ppe_code is None:
                color = UNMAPPED
                label = f"{class_name} {confidence:.2f} SEM MAPEAMENTO"
                if class_name not in seen_unmapped:
                    seen_unmapped.add(class_name)
                    print(f"classe sem mapeamento em class_map.json: {class_name}")
            else:
                color = ACCEPTED if confidence >= PREVIEW_THRESHOLD else BELOW
                label = f"{ppe_code} {confidence:.2f}"

            x, y = prediction.get("x"), prediction.get("y")
            w, h = prediction.get("width"), prediction.get("height")
            if None in (x, y, w, h):
                continue

            x1, y1 = int(x - w / 2), int(y - h / 2)
            x2, y2 = int(x + w / 2), int(y + h / 2)

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame, label, (x1, max(y1 - 8, 18)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2,
            )

        cv2.imshow("EPI — preview", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    capture.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
