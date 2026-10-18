"""Vision service settings, read from environment variables."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CLASS_MAP_PATH = Path(__file__).parent / "class_map.json"


def _load_class_map() -> dict[str, str]:
    """Maps model class names onto the PPE codes the backend knows.

    The model and the database are developed by different people and need not
    agree on spelling. Keeping the translation in a data file means a class
    rename on the model side is a one-line change here, not a code change on
    either side.
    """
    if not CLASS_MAP_PATH.exists():
        return {}
    with CLASS_MAP_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@dataclass(frozen=True)
class Settings:
    # --- Broker ---
    mqtt_host: str = os.getenv("MQTT_HOST", "mosquitto")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_username: str | None = os.getenv("MQTT_USERNAME") or None
    mqtt_password: str | None = os.getenv("MQTT_PASSWORD") or None
    mqtt_client_id: str = os.getenv("MQTT_CLIENT_ID", "epi-vision")
    mqtt_qos: int = int(os.getenv("MQTT_QOS", "1"))

    # --- Camera ---
    camera_index: int = int(os.getenv("CAMERA_INDEX", "0"))
    camera_width: int = int(os.getenv("CAMERA_WIDTH", "1280"))
    camera_height: int = int(os.getenv("CAMERA_HEIGHT", "720"))

    # --- Roboflow ---
    roboflow_api_url: str = os.getenv("ROBOFLOW_API_URL", "https://serverless.roboflow.com")
    roboflow_api_key: str = os.getenv("ROBOFLOW_API_KEY", "")
    roboflow_workspace: str = os.getenv("ROBOFLOW_WORKSPACE", "")
    roboflow_workflow: str = os.getenv("ROBOFLOW_WORKFLOW", "")

    # Give up on a single inference after this long. The backend has its own
    # timeout; failing faster here lets the gate answer sooner.
    inference_timeout_s: float = float(os.getenv("INFERENCE_TIMEOUT_SECONDS", "6.0"))

    # --- Live view (panel) ---
    http_port: int = int(os.getenv("VISION_HTTP_PORT", "8081"))
    stream_fps: float = float(os.getenv("STREAM_FPS", "10"))
    stream_max_width: int = int(os.getenv("STREAM_MAX_WIDTH", "960"))
    # Seconds between inferences that draw boxes on the live view, run only
    # while someone is watching. Each one is a billed call to the model API,
    # so this is a cost knob as much as a smoothness one. 0 turns the live
    # boxes off and leaves the plain video.
    live_inference_interval_s: float = float(
        os.getenv("LIVE_INFERENCE_INTERVAL_SECONDS", "1.5")
    )
    # Only colours the boxes. The decision itself is the backend's, which
    # reads the same variable from the shared .env.
    display_threshold: float = float(os.getenv("DETECTION_CONFIDENCE_THRESHOLD", "0.6"))

    # --- Behaviour ---
    # Detections are published with raw confidence. The acceptance threshold
    # is the backend's policy, not the model's, so it can be tuned without
    # touching this service.
    save_snapshots: bool = os.getenv("SAVE_SNAPSHOTS", "false").lower() == "true"
    snapshot_dir: str = os.getenv("SNAPSHOT_DIR", "/app/snapshots")

    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    class_map: dict[str, str] = field(default_factory=_load_class_map)

    def validate(self) -> list[str]:
        """Returns the settings that are missing or unusable."""
        problems = []
        if not self.roboflow_api_key:
            problems.append("ROBOFLOW_API_KEY is not set")
        if not self.roboflow_workspace:
            problems.append("ROBOFLOW_WORKSPACE is not set")
        if not self.roboflow_workflow:
            problems.append("ROBOFLOW_WORKFLOW is not set")
        if not self.class_map:
            problems.append(f"class map is empty or missing at {CLASS_MAP_PATH}")
        return problems


settings = Settings()
