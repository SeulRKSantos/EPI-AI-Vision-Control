"""Live view tests: drawing, the HTTP endpoints, and the cost guard.

A synthetic camera stands in for the webcam and a scripted detector for the
model. The server is the real one, on a real port.

    python3 tests/test_live.py
"""

import asyncio
import sys
from pathlib import Path

import numpy as np
from aiohttp import ClientSession

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import http_server  # noqa: E402
from detector import Box, Detector  # noqa: E402
from live import LiveView  # noqa: E402

PORT = 18081
BASE = f"http://127.0.0.1:{PORT}"

failures = 0
checks = 0


def check(condition, name):
    global failures, checks
    checks += 1
    print(f"  {'ok  ' if condition else 'FALHA'}  {name}")
    if not condition:
        failures += 1


class SyntheticCamera:
    def __init__(self, available=True):
        self.available = available

    def grab(self, max_age_s: float = 2.0):
        if not self.available:
            return None
        return np.full((480, 640, 3), 40, dtype=np.uint8)


class ScriptedDetector(Detector):
    """Real mapping and box logic; only the network call is replaced."""

    def __init__(self, class_map):
        self._class_map = self.build_lookup(class_map)
        self._unmapped_seen = set()
        self.calls = 0
        self.script = [
            {"class": "Capacete", "confidence": 0.92, "x": 200, "y": 120, "width": 120, "height": 90},
            {"class": "Óculos", "confidence": 0.41, "x": 200, "y": 200, "width": 100, "height": 40},
            {"class": "Rímel", "confidence": 0.77, "x": 260, "y": 205, "width": 30, "height": 20},
        ]

    def predictions(self, frame):
        self.calls += 1
        return list(self.script)


CLASS_MAP = {"capacete": "helmet", "oculos": "goggles"}


# --- Drawing --------------------------------------------------------------

def test_boxes_keep_unmapped_classes():
    """Distractors are drawn too, flagged, so a person sees what took their place."""
    detector = ScriptedDetector(CLASS_MAP)
    boxes = detector.boxes(detector.script)
    names = {b.class_name: b.ppe_code for b in boxes}
    check(len(boxes) == 3, "uma caixa por predicao")
    check(names["Capacete"] == "helmet", "classe mapeada carrega o codigo")
    check(names["Rímel"] is None, "distratora aparece sem codigo")


def test_annotate_draws_on_the_frame():
    camera = SyntheticCamera()
    detector = ScriptedDetector(CLASS_MAP)
    live = LiveView(camera, detector, interval_s=1.0, threshold=0.6)
    live.publish(detector.boxes(detector.script), source="scan", latency_ms=200)

    frame = camera.grab()
    before = frame.copy()
    live.annotate(frame)
    check(not np.array_equal(before, frame), "caixas desenhadas no quadro")
    live.shutdown()


def test_stale_overlay_is_not_drawn():
    """A box where someone stood seconds ago would misrepresent the gate."""
    camera = SyntheticCamera()
    detector = ScriptedDetector(CLASS_MAP)
    live = LiveView(camera, detector, interval_s=1.0, threshold=0.6)
    live.publish(detector.boxes(detector.script), source="live", latency_ms=200)
    live._overlay.updated_at -= 60  # age it

    frame = camera.grab()
    before = frame.copy()
    live.annotate(frame)
    check(np.array_equal(before, frame), "sobreposicao antiga nao e desenhada")
    check(live.snapshot()["boxes"] == [], "lista de deteccoes vazia quando antiga")
    live.shutdown()


def test_snapshot_flags_acceptance():
    camera = SyntheticCamera()
    detector = ScriptedDetector(CLASS_MAP)
    live = LiveView(camera, detector, interval_s=1.0, threshold=0.6)
    live.publish(detector.boxes(detector.script), source="scan", latency_ms=250,
                 session_id="abc")
    snap = {b["class_name"]: b for b in live.snapshot()["boxes"]}
    check(snap["Capacete"]["accepted"] is True, "acima do limiar marcado aceito")
    check(snap["Óculos"]["accepted"] is False, "abaixo do limiar marcado nao aceito")
    check(snap["Rímel"]["accepted"] is False, "distratora nunca aceita")
    check(live.snapshot()["session_id"] == "abc", "sessao da leitura exposta")
    live.shutdown()


# --- HTTP and the cost guard ----------------------------------------------

async def with_server(camera, detector, interval, coro):
    live = LiveView(camera, detector, interval_s=interval, threshold=0.6)
    runner = await http_server.start(
        http_server.build_app(camera, live, fps=20, max_width=640), PORT
    )
    task = asyncio.create_task(live.run())
    try:
        return await coro(live)
    finally:
        task.cancel()
        live.shutdown()
        await runner.cleanup()


async def read_stream(session, seconds):
    """Reads the MJPEG stream for a while and returns the bytes received."""
    received = b""
    async with session.get(f"{BASE}/stream.mjpg") as response:
        content_type = response.headers.get("Content-Type", "")
        end = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < end:
            try:
                chunk = await asyncio.wait_for(response.content.read(65536), 0.5)
            except asyncio.TimeoutError:
                continue
            if not chunk:
                break
            received += chunk
    return content_type, received


async def test_no_viewers_means_no_inference():
    """The guard that keeps an idle dashboard from spending the API quota."""
    detector = ScriptedDetector(CLASS_MAP)

    async def act(live):
        await asyncio.sleep(1.5)
        return detector.calls

    calls = await with_server(SyntheticCamera(), detector, 0.3, act)
    check(calls == 0, "nenhuma inferencia sem ninguem assistindo")


async def test_stream_serves_jpeg_frames_and_drives_inference():
    detector = ScriptedDetector(CLASS_MAP)

    async def act(live):
        async with ClientSession() as session:
            content_type, body = await read_stream(session, 1.6)
        await asyncio.sleep(0.3)  # let the disconnect register
        return content_type, body, live.viewers

    content_type, body, viewers_after = await with_server(
        SyntheticCamera(), detector, 0.3, act
    )
    check("multipart/x-mixed-replace" in content_type, "stream e MJPEG")
    check(body.count(b"\xff\xd8") >= 3, "varios quadros JPEG recebidos")
    check(detector.calls >= 2, "inferencia ao vivo roda enquanto alguem assiste")
    check(viewers_after == 0, "espectador liberado ao desconectar")


async def test_detections_endpoint():
    detector = ScriptedDetector(CLASS_MAP)

    async def act(live):
        live.publish(detector.boxes(detector.script), source="scan", latency_ms=180)
        async with ClientSession() as session:
            async with session.get(f"{BASE}/detections") as response:
                return response.status, response.headers, await response.json()

    status, headers, body = await with_server(SyntheticCamera(), detector, 0, act)
    check(status == 200, "endpoint de deteccoes responde")
    check(headers.get("Access-Control-Allow-Origin") == "*", "CORS liberado para o painel")
    check(len(body["boxes"]) == 3 and body["source"] == "scan", "deteccoes da leitura expostas")


async def test_health_reports_camera_loss():
    async def act(live):
        async with ClientSession() as session:
            async with session.get(f"{BASE}/health") as response:
                return response.status, await response.json()

    status, body = await with_server(
        SyntheticCamera(available=False), ScriptedDetector(CLASS_MAP), 0, act
    )
    check(status == 503 and body["camera"] == "unavailable", "camera ausente reportada")


async def test_live_disabled_streams_plain_video():
    """Interval 0 keeps the video and spends nothing."""
    detector = ScriptedDetector(CLASS_MAP)

    async def act(live):
        async with ClientSession() as session:
            _, body = await read_stream(session, 1.0)
        return body

    body = await with_server(SyntheticCamera(), detector, 0, act)
    check(body.count(b"\xff\xd8") >= 2, "video segue sem caixas ao vivo")
    check(detector.calls == 0, "nenhuma inferencia com intervalo zero")


class HangingDetector(ScriptedDetector):
    """The first call never returns, as a stuck HTTP request would."""

    def __init__(self, class_map):
        super().__init__(class_map)
        import threading
        self.release = threading.Event()

    def predictions(self, frame):
        self.calls += 1
        if self.calls == 1:
            self.release.wait(10)
        return list(self.script)


async def test_hung_call_does_not_silence_the_live_view():
    """A call that never answers must not stop every later one."""
    detector = HangingDetector(CLASS_MAP)
    live = LiveView(SyntheticCamera(), detector, interval_s=0.2, threshold=0.6, timeout_s=0.4)
    live.viewer_joined()
    task = asyncio.create_task(live.run())
    errors_seen = []
    try:
        for _ in range(32):  # watch the state for 1.6 s
            await asyncio.sleep(0.05)
            error = live.snapshot()["error"]
            if error:
                errors_seen.append(error)
        later = live.snapshot()
    finally:
        task.cancel()
        detector.release.set()

    check(any("resposta" in e for e in errors_seen), "chamada travada vira erro visivel")
    check(detector.calls >= 2, "proximas chamadas seguem apos a travada")
    check(later["source"] == "live" and later["fresh"], "caixas ao vivo voltam a aparecer")
    check(later["error"] is None, "erro some quando o servico responde")
    check(later["last_success_age_s"] is not None, "ultimo sucesso exposto no diagnostico")


async def test_failing_calls_keep_the_loop_running():
    class Failing(ScriptedDetector):
        def predictions(self, frame):
            self.calls += 1
            raise RuntimeError("quota exceeded")

    detector = Failing(CLASS_MAP)
    live = LiveView(SyntheticCamera(), detector, interval_s=0.1, threshold=0.6, timeout_s=0.5)
    live.viewer_joined()
    task = asyncio.create_task(live.run())
    try:
        await asyncio.sleep(0.6)
        snap = live.snapshot()
    finally:
        task.cancel()
    check(detector.calls >= 3, "falhas nao derrubam o laco ao vivo")
    check(snap["error"] == "quota exceeded", "motivo da falha exposto ao painel")


async def main():
    print("Visão ao vivo\n")
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        print(f"{name}:")
        if asyncio.iscoroutinefunction(fn):
            await fn()
        else:
            fn()
    print(f"\n{checks} verificações, {failures} falhas")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
