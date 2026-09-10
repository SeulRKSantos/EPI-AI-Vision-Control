"""Asynchronous MQTT client.

Wraps aiomqtt with the two things the application needs beyond the raw
library: automatic reconnection, and dispatch of incoming messages to
handlers registered per topic filter.

A dropped broker connection must never leave the service silently deaf, so
the consumer loop reconnects on its own and reports its state through
`is_connected` — which the readiness probe reads.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import aiomqtt
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

MessageHandler = Callable[[str, bytes], Awaitable[None]]

RECONNECT_DELAY_SECONDS = 3.0


class MQTTClient:
    """Owns the broker connection and the consumer task."""

    def __init__(self) -> None:
        self._client: aiomqtt.Client | None = None
        self._handlers: dict[str, MessageHandler] = {}
        self._task: asyncio.Task | None = None
        self._connected = asyncio.Event()
        self._stopping = False
        # Handler tasks are kept referenced so the event loop does not
        # garbage-collect them mid-flight.
        self._inflight: set[asyncio.Task] = set()

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def register(self, topic_filter: str, handler: MessageHandler) -> None:
        """Attach a handler to a topic filter. Must be called before start()."""
        self._handlers[topic_filter] = handler

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="mqtt-consumer")

    async def stop(self) -> None:
        self._stopping = True
        for task in list(self._inflight):
            task.cancel()
        self._inflight.clear()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._connected.clear()

    async def publish(self, topic: str, payload: BaseModel | str | bytes) -> None:
        """Publish a message, serializing Pydantic models to JSON.

        Raises when there is no connection: callers decide what a failed
        publish means. For the decision message it means the gate stays shut.
        """
        if self._client is None or not self.is_connected:
            raise ConnectionError("MQTT client is not connected")

        if isinstance(payload, BaseModel):
            body: str | bytes = payload.model_dump_json()
        else:
            body = payload

        await self._client.publish(topic, body, qos=settings.mqtt_qos)
        logger.debug("Published message", extra={"topic": topic})

    async def wait_until_connected(self, timeout: float = 10.0) -> bool:
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
            return True
        except TimeoutError:
            return False

    # --- internals ---------------------------------------------------------

    async def _run(self) -> None:
        """Consumer loop. Reconnects until stop() is called."""
        while not self._stopping:
            try:
                async with aiomqtt.Client(
                    hostname=settings.mqtt_host,
                    port=settings.mqtt_port,
                    username=settings.mqtt_username or None,
                    password=settings.mqtt_password or None,
                    identifier=settings.mqtt_client_id,
                ) as client:
                    self._client = client
                    self._connected.set()
                    logger.info(
                        "Connected to MQTT broker",
                        extra={"host": settings.mqtt_host, "port": settings.mqtt_port},
                    )

                    for topic_filter in self._handlers:
                        await client.subscribe(topic_filter, qos=settings.mqtt_qos)
                        logger.info("Subscribed", extra={"topic": topic_filter})

                    async for message in client.messages:
                        await self._dispatch(message)

            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - loop must survive anything
                self._connected.clear()
                self._client = None
                if self._stopping:
                    break
                logger.warning(
                    "MQTT connection lost, retrying",
                    extra={"error": str(exc), "retry_in": RECONNECT_DELAY_SECONDS},
                )
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    async def _dispatch(self, message: aiomqtt.Message) -> None:
        """Hand the message to its handler and return immediately.

        Handlers run as independent tasks rather than being awaited here.
        This is essential: handling a badge scan blocks until the vision
        result arrives, and that result is itself a message this same loop
        has to read. Awaiting the handler inline would deadlock the consumer
        against the very message it is waiting for.
        """
        topic = str(message.topic)
        payload = (
            message.payload if isinstance(message.payload, bytes)
            else str(message.payload).encode()
        )

        for topic_filter, handler in self._handlers.items():
            if message.topic.matches(topic_filter):
                task = asyncio.create_task(self._run_handler(handler, topic, payload))
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)
                return

        logger.debug("No handler for topic", extra={"topic": topic})

    async def _run_handler(
        self, handler: MessageHandler, topic: str, payload: bytes
    ) -> None:
        """A failing handler must not affect the consumer or other messages."""
        try:
            await handler(topic, payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Handler failed", extra={"topic": topic})


mqtt_client = MQTTClient()
