"""End-to-end test of the request/response cycle.

Runs the real service loop against a real broker, with the camera and the
model stubbed. What is being verified is the contract with the backend: that
a request is answered on the right topic, carrying the same session
identifier, in the shape the backend parses — and that the failure paths stay
silent so the backend's timeout can do its job.

    TEST_MQTT_HOST=127.0.0.1 TEST_MQTT_PORT=1884 python3 tests/test_service_e2e.py
"""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import aiomqtt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detector import Detection  # noqa: E402
import inference_worker  # noqa: E402

HOST = os.getenv("TEST_MQTT_HOST", "127.0.0.1")
PORT = int(os.getenv("TEST_MQTT_PORT", "1884"))
GATE = "gate-test"

failures = 0
checks = 0


def check(condition, name):
    global failures, checks
    checks += 1
    print(f"  {'ok  ' if condition else 'FALHA'}  {name}")
    if not condition:
        failures += 1


class FakeCamera:
    """Stands in for the webcam. `frame=None` reproduces a camera failure."""

    def __init__(self, frame="frame"):
        self._frame = frame

    def grab(self, max_age_s: float = 2.0):
        return self._frame


class FakeDetector:
    """Stands in for the model. Speaks the same interface the service uses."""

    def __init__(self, detections=None, raises=False, delay=0.0):
        self._detections = detections or []
        self._raises = raises
        self._delay = delay
        self.calls = 0

    def predictions(self, frame):
        self.calls += 1
        if self._delay:
            import time
            time.sleep(self._delay)
        if self._raises:
            raise RuntimeError("inference exploded")
        return [
            {"class": d.ppe_code, "confidence": d.confidence,
             "x": 100, "y": 100, "width": 40, "height": 40}
            for d in self._detections
        ]

    def parse_predictions(self, predictions):
        return [Detection(p["class"], p["confidence"]) for p in predictions]

    def boxes(self, predictions):
        return []


async def run_service(service, stop: asyncio.Event):
    async with aiomqtt.Client(
        hostname=HOST, port=PORT, identifier=f"vision-{uuid.uuid4()}"
    ) as client:
        await client.subscribe(inference_worker.REQUEST_TOPIC, qos=1)
        async def consume():
            try:
                async for message in client.messages:
                    await service.handle_request(
                        client, str(message.topic), bytes(message.payload)
                    )
            except aiomqtt.MqttError:
                pass  # expected when the test tears the client down
        task = asyncio.create_task(consume())
        await stop.wait()
        task.cancel()


async def request_and_collect(payload: str, timeout: float = 5.0):
    """Publishes a request and returns the result, or None if none arrives."""
    async with aiomqtt.Client(
        hostname=HOST, port=PORT, identifier=f"backend-{uuid.uuid4()}"
    ) as client:
        await client.subscribe(f"vision/{GATE}/result", qos=1)
        await asyncio.sleep(0.3)
        await client.publish(f"vision/{GATE}/request", payload, qos=1)

        async def first():
            async for message in client.messages:
                return json.loads(message.payload)

        try:
            return await asyncio.wait_for(first(), timeout)
        except asyncio.TimeoutError:
            return None


async def with_service(camera, detector, coro):
    service = inference_worker.VisionService(camera, detector)
    stop = asyncio.Event()
    runner = asyncio.create_task(run_service(service, stop))
    await asyncio.sleep(0.6)
    try:
        return await coro()
    finally:
        stop.set()
        runner.cancel()
        service.shutdown()
        await asyncio.sleep(0.2)


# --- Tests ----------------------------------------------------------------

async def test_answers_with_echoed_session_id():
    """The identifier must come back untouched or the backend discards it."""
    session_id = str(uuid.uuid4())
    detector = FakeDetector([
        Detection("helmet", 0.95), Detection("goggles", 0.88),
    ])

    async def act():
        return await request_and_collect(
            json.dumps({"session_id": session_id, "gate_code": GATE})
        )

    result = await with_service(FakeCamera(), detector, act)

    check(result is not None, "resposta publicada")
    if result:
        check(result["session_id"] == session_id, "session_id ecoado sem alteracao")
        codes = {d["ppe_code"] for d in result["detections"]}
        check(codes == {"goggles", "helmet"}, "deteccoes no payload")
        check(all("confidence" in d for d in result["detections"]), "confianca presente")
        check("inference_ms" in result, "latencia reportada")


async def test_no_detections_is_an_empty_list_not_silence():
    """Seeing nothing is an answer; it is the backend that calls it a denial."""
    async def act():
        return await request_and_collect(
            json.dumps({"session_id": str(uuid.uuid4()), "gate_code": GATE})
        )

    result = await with_service(FakeCamera(), FakeDetector([]), act)
    check(result is not None and result["detections"] == [],
          "nenhuma deteccao vira lista vazia")


async def test_camera_failure_publishes_nothing():
    """No frame means nothing can be vouched for: stay silent and let the
    backend time out into a refusal."""
    detector = FakeDetector([Detection("helmet", 0.9)])

    async def act():
        return await request_and_collect(
            json.dumps({"session_id": str(uuid.uuid4()), "gate_code": GATE}), timeout=2.0
        )

    result = await with_service(FakeCamera(frame=None), detector, act)
    check(result is None, "falha de camera nao publica resultado")
    check(detector.calls == 0, "nem chama o modelo sem imagem")


async def test_inference_failure_publishes_nothing():
    async def act():
        return await request_and_collect(
            json.dumps({"session_id": str(uuid.uuid4()), "gate_code": GATE}), timeout=2.0
        )

    result = await with_service(FakeCamera(), FakeDetector(raises=True), act)
    check(result is None, "falha de inferencia nao publica resultado")


async def test_malformed_request_is_survivable():
    """A bad message must not deafen the service to the next one."""
    session_id = str(uuid.uuid4())
    detector = FakeDetector([Detection("helmet", 0.9)])

    async def act():
        async with aiomqtt.Client(
            hostname=HOST, port=PORT, identifier=f"junk-{uuid.uuid4()}"
        ) as client:
            await client.publish(f"vision/{GATE}/request", b"{not json", qos=1)
            await client.publish(f"vision/{GATE}/request", b'{"gate_code":"x"}', qos=1)
        await asyncio.sleep(0.4)
        return await request_and_collect(
            json.dumps({"session_id": session_id, "gate_code": GATE})
        )

    result = await with_service(FakeCamera(), detector, act)
    check(result is not None and result["session_id"] == session_id,
          "requisicao valida apos lixo continua atendida")


async def test_gate_is_taken_from_topic_when_absent():
    """The topic is authoritative, so a request without gate_code still works."""
    session_id = str(uuid.uuid4())

    async def act():
        return await request_and_collect(json.dumps({"session_id": session_id}))

    result = await with_service(FakeCamera(), FakeDetector([]), act)
    check(result is not None, "gate deduzido do topico")


async def test_concurrent_requests_do_not_queue():
    """A slow inference must not block the next request from being read."""
    detector = FakeDetector([Detection("helmet", 0.9)], delay=0.8)
    first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
    seen = []

    async def act():
        async with aiomqtt.Client(
            hostname=HOST, port=PORT, identifier=f"two-{uuid.uuid4()}"
        ) as client:
            await client.subscribe(f"vision/{GATE}/result", qos=1)
            await asyncio.sleep(0.3)
            await client.publish(
                f"vision/{GATE}/request",
                json.dumps({"session_id": first_id, "gate_code": GATE}), qos=1)
            await client.publish(
                f"vision/{GATE}/request",
                json.dumps({"session_id": second_id, "gate_code": GATE}), qos=1)

            async def collect_two():
                async for message in client.messages:
                    seen.append(json.loads(message.payload)["session_id"])
                    if len(seen) == 2:
                        return

            try:
                await asyncio.wait_for(collect_two(), 6.0)
            except asyncio.TimeoutError:
                pass
        return seen

    await with_service(FakeCamera(), detector, act)
    check(len(seen) == 2, "duas requisicoes concorrentes atendidas")
    check(set(seen) == {first_id, second_id}, "cada resposta com sua sessao")


async def main():
    print("Serviço de visão — ciclo completo\n")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and asyncio.iscoroutinefunction(fn):
            print(f"{name}:")
            await fn()
    print(f"\n{checks} verificações, {failures} falhas")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
