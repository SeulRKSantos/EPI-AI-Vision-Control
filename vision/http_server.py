"""HTTP endpoints for the panel.

    GET /stream.mjpg   live video with the model's boxes (multipart MJPEG)
    GET /detections    the boxes currently drawn, as JSON
    GET /health        camera and live-view status

MJPEG is used because a browser shows it with a plain <img> tag: no player,
no codec negotiation, nothing to install. The cost is bandwidth, which is
bounded here by capping width and frame rate.

The endpoints only read. Nothing here can trigger a decision or move the
lock, so exposing them on the bench network does not widen what an outsider
could do to the gate.
"""

import asyncio
import logging

import cv2
from aiohttp import web

from live import LiveView

logger = logging.getLogger("vision.http")

BOUNDARY = "frame"


def _cors(response: web.StreamResponse) -> web.StreamResponse:
    # The panel is served from another port, so the JSON endpoints need an
    # explicit allowance. The stream itself is an <img> and needs none.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = "no-store"
    return response


def build_app(camera, live: LiveView, fps: float, max_width: int) -> web.Application:
    frame_interval = 1.0 / max(fps, 1.0)

    def encode(frame) -> bytes | None:
        height, width = frame.shape[:2]
        if width > max_width:
            scale = max_width / width
            frame = cv2.resize(frame, (max_width, int(height * scale)))
        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
        return buffer.tobytes() if ok else None

    async def stream(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={
            "Content-Type": f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        })
        await response.prepare(request)

        live.viewer_joined()
        logger.info("Viewer connected", extra={"viewers": live.viewers})
        loop = asyncio.get_running_loop()
        try:
            while True:
                frame = camera.grab(max_age_s=5.0)
                if frame is not None:
                    live.annotate(frame)
                    jpeg = await loop.run_in_executor(None, encode, frame)
                    if jpeg:
                        await response.write(
                            f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                            f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                            + jpeg + b"\r\n"
                        )
                await asyncio.sleep(frame_interval)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            # Leaving is what stops the live inference when the tab closes.
            live.viewer_left()
            logger.info("Viewer disconnected", extra={"viewers": live.viewers})
        return response

    async def detections(request: web.Request) -> web.Response:
        return _cors(web.json_response(live.snapshot()))

    async def health(request: web.Request) -> web.Response:
        has_frame = camera.grab(max_age_s=5.0) is not None
        status = 200 if has_frame else 503
        return _cors(web.json_response(
            {"camera": "ok" if has_frame else "unavailable", "viewers": live.viewers},
            status=status,
        ))

    app = web.Application()
    app.router.add_get("/stream.mjpg", stream)
    app.router.add_get("/detections", detections)
    app.router.add_get("/health", health)
    return app


async def start(app: web.Application, port: int) -> web.AppRunner:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info("Live view listening", extra={"port": port})
    return runner
