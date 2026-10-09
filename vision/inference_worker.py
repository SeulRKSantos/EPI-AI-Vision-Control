"""Vision service.

Sits idle until the backend asks. A badge scan makes the backend publish an
inference request; this service grabs the freshest frame, runs the model, and
answers on the result topic with the same session identifier it was given.

Running on demand rather than continuously matters: a loop that inferred
every frame would burn API calls all day and still have to decide which frame
mattered. The scan is what says when.
"""

import asyncio
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import aiomqtt

from camera import Camera
from config import settings
from detector import Detector

logger = logging.getLogger("vision")

REQUEST_TOPIC = "vision/+/request"
RESULT_TOPIC = "vision/{gate_code}/result"


def configure_logging() -> None:
    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            for key, value in record.__dict__.items():
                if key not in logging.LogRecord("", 0, "", 0, "", (), None).__dict__:
                    if not key.startswith("_") and key != "taskName":
                        payload[key] = value
            if record.exc_info:
                payload["exception"] = self.formatException(record.exc_info)
            return json.dumps(payload, default=str, ensure_ascii=False)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())


def gate_from_topic(topic: str) -> str | None:
    parts = topic.split("/")
    return parts[1] if len(parts) >= 3 else None


class VisionService:
    def __init__(self, camera: Camera, detector: Detector) -> None:
        self._camera = camera
        self._detector = detector
        # Inference is a blocking HTTP call. Running it in a worker thread
        # keeps the MQTT loop free, so a second request is read rather than
        # queued behind the first.
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="infer")

    async def handle_request(self, client: aiomqtt.Client, topic: str, payload: bytes) -> None:
        try:
            request = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("Malformed request discarded", extra={"topic": topic})
            return

        session_id = request.get("session_id")
        if not session_id:
            logger.warning("Request without session_id discarded", extra={"topic": topic})
            return

        gate_code = request.get("gate_code") or gate_from_topic(topic)
        if not gate_code:
            logger.warning("Request without gate discarded", extra={"session_id": session_id})
            return

        started = time.monotonic()
        logger.info(
            "Inference requested",
            extra={"session_id": session_id, "gate_code": gate_code},
        )

        frame = self._camera.grab()
        if frame is None:
            # No answer is published. The backend's timeout turns that into a
            # refusal, which is the honest outcome: nothing was seen, so
            # nothing can be vouched for. Publishing an empty detection list
            # would instead read as "the equipment was absent", which is a
            # different and misleading claim.
            logger.error(
                "No usable frame; no result will be published",
                extra={"session_id": session_id},
            )
            return

        try:
            loop = asyncio.get_running_loop()
            detections = await asyncio.wait_for(
                loop.run_in_executor(self._pool, self._detector.detect, frame),
                timeout=settings.inference_timeout_s,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Inference timed out; no result will be published",
                extra={"session_id": session_id, "timeout_s": settings.inference_timeout_s},
            )
            return
        except Exception:
            logger.exception(
                "Inference failed; no result will be published",
                extra={"session_id": session_id},
            )
            return

        elapsed_ms = (time.monotonic() - started) * 1000.0

        if settings.save_snapshots:
            self._save_snapshot(frame, session_id)

        result = {
            "session_id": session_id,
            "detections": [
                {"ppe_code": d.ppe_code, "confidence": round(d.confidence, 4)}
                for d in detections
            ],
            "inference_ms": round(elapsed_ms, 1),
        }

        await client.publish(
            RESULT_TOPIC.format(gate_code=gate_code),
            json.dumps(result),
            qos=settings.mqtt_qos,
        )

        logger.info(
            "Result published",
            extra={
                "session_id": session_id,
                "detected": [d.ppe_code for d in detections],
                "inference_ms": round(elapsed_ms, 1),
            },
        )

    def _save_snapshot(self, frame, session_id: str) -> None:
        """Keeps the frame a decision was made from, for audit review."""
        try:
            import cv2

            directory = Path(settings.snapshot_dir)
            directory.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(directory / f"{session_id}.jpg"), frame)
        except Exception:
            logger.exception("Could not save snapshot", extra={"session_id": session_id})

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)


async def run() -> None:
    configure_logging()

    problems = settings.validate()
    if problems:
        for problem in problems:
            logger.error("Configuration problem", extra={"problem": problem})
        logger.error("Refusing to start without valid configuration")
        sys.exit(1)

    camera = Camera(settings.camera_index, settings.camera_width, settings.camera_height)
    if not camera.start():
        logger.error("Refusing to start without a camera")
        sys.exit(1)

    detector = Detector(
        api_url=settings.roboflow_api_url,
        api_key=settings.roboflow_api_key,
        workspace=settings.roboflow_workspace,
        workflow=settings.roboflow_workflow,
        class_map=settings.class_map,
    )
    service = VisionService(camera, detector)

    logger.info(
        "Vision service starting",
        extra={"mapped_classes": sorted(set(settings.class_map.values()))},
    )

    try:
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=settings.mqtt_host,
                    port=settings.mqtt_port,
                    username=settings.mqtt_username,
                    password=settings.mqtt_password,
                    identifier=settings.mqtt_client_id,
                ) as client:
                    await client.subscribe(REQUEST_TOPIC, qos=settings.mqtt_qos)
                    logger.info(
                        "Connected to broker",
                        extra={"host": settings.mqtt_host, "topic": REQUEST_TOPIC},
                    )

                    async for message in client.messages:
                        # Each request is its own task: a slow inference must
                        # not stop the next request from being read.
                        asyncio.create_task(
                            service.handle_request(
                                client, str(message.topic), bytes(message.payload)
                            )
                        )

            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                logger.warning(
                    "Broker connection lost, retrying",
                    extra={"error": str(exc), "retry_in": 3.0},
                )
                await asyncio.sleep(3.0)
    finally:
        service.shutdown()
        camera.stop()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
