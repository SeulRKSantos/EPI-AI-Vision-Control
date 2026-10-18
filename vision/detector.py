"""PPE detection through the Roboflow workflow.

The parsing here follows the shape the workflow actually returns, which
nests predictions one level deeper than the plain inference endpoint. The
detections are passed on with their raw confidence: filtering is the
backend's job, so the acceptance threshold stays a policy that can be tuned
without redeploying this service.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def normalize_class_name(name: str) -> str:
    """Folds case, accents and separators so near-identical names match.

    Class names are typed by whoever labels the dataset, and "Capacete",
    "capacete" and "CAPACETE" are the same class. So are "Óculos" and
    "oculos", and "safety vest", "safety_vest" and "Safety-Vest". Matching on
    the folded form keeps a cosmetic difference in the dataset from silently
    turning into "equipment not detected".
    """
    decomposed = unicodedata.normalize("NFKD", name)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[\s_\-]+", "-", without_accents.strip().lower())


@dataclass(frozen=True)
class Detection:
    ppe_code: str
    confidence: float


@dataclass(frozen=True)
class Box:
    """A prediction placed on the frame, for drawing.

    Unlike `Detection`, every prediction becomes a box — including classes
    with no mapping, such as the distractors. Seeing them drawn is how a
    person tells "the camera missed the goggles" from "the camera saw
    something else there".
    """

    class_name: str
    ppe_code: str | None
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int


class Detector:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        workspace: str,
        workflow: str,
        class_map: dict[str, str],
    ) -> None:
        self._workspace = workspace
        self._workflow = workflow
        self._class_map = self.build_lookup(class_map)
        self._unmapped_seen: set[str] = set()

        # Imported here so the module can be loaded (and tested) without the
        # SDK installed.
        from inference_sdk import InferenceConfiguration, InferenceHTTPClient

        self._client = InferenceHTTPClient(
            api_url=api_url, api_key=api_key
        ).configure(InferenceConfiguration(api_key_transport="header"))

    @staticmethod
    def build_lookup(class_map: dict[str, str]) -> dict[str, str]:
        """Indexes the class map by normalized name, skipping comment keys."""
        return {
            normalize_class_name(key): value
            for key, value in class_map.items()
            if not key.startswith("_")
        }

    def map_class(self, class_name: str) -> str | None:
        """The PPE code for a model class, or None when it has no mapping."""
        return self._class_map.get(normalize_class_name(class_name))

    def predictions(self, frame) -> list[dict]:
        """Runs the model on a frame and returns the raw predictions.

        One call serves both consumers: the detections published to the
        backend and the boxes drawn on the live view come from the same
        inference, so what the person sees is what the gate decided on.
        """
        result = self._client.run_workflow(
            workspace_name=self._workspace,
            workflow_id=self._workflow,
            images={"image": frame},
            use_cache=True,
        )
        return list(self._iter_predictions(result))

    def detect(self, frame) -> list[Detection]:
        return self.parse_predictions(self.predictions(frame))

    def parse(self, result) -> list[Detection]:
        """Turns a workflow response into detections the backend understands."""
        return self.parse_predictions(self._iter_predictions(result))

    def boxes(self, predictions) -> list[Box]:
        """Every prediction with usable coordinates, mapped or not."""
        out: list[Box] = []
        for prediction in predictions:
            class_name = prediction.get("class") or prediction.get("class_name") or ""
            x, y = prediction.get("x"), prediction.get("y")
            w, h = prediction.get("width"), prediction.get("height")
            if not class_name or None in (x, y, w, h):
                continue
            out.append(Box(
                class_name=class_name,
                ppe_code=self.map_class(class_name),
                confidence=float(prediction.get("confidence", 0.0)),
                x1=int(x - w / 2), y1=int(y - h / 2),
                x2=int(x + w / 2), y2=int(y + h / 2),
            ))
        return out

    def parse_predictions(self, predictions) -> list[Detection]:
        """Maps raw predictions onto the PPE codes the backend knows."""
        detections: list[Detection] = []

        for prediction in predictions:
            class_name = (
                prediction.get("class")
                or prediction.get("class_name")
                or ""
            )
            if not class_name:
                continue

            ppe_code = self.map_class(class_name)
            if ppe_code is None:
                # Logged once per class: a model class with no mapping will
                # never count as detected, and silence would make that look
                # like the equipment simply was not worn.
                if class_name not in self._unmapped_seen:
                    self._unmapped_seen.add(class_name)
                    logger.warning(
                        "Model class has no mapping and will be ignored",
                        extra={"class_name": class_name},
                    )
                continue

            confidence = float(prediction.get("confidence", 0.0))
            detections.append(Detection(ppe_code=ppe_code, confidence=confidence))

        return self._keep_strongest(detections)

    @staticmethod
    def _iter_predictions(result):
        """Walks the workflow response to the list of predictions.

        The workflow returns a list whose first element holds the outputs, and
        `predictions` there may be the list itself or a dict wrapping it.
        """
        if not isinstance(result, list) or not result:
            return []

        output = result[0]
        if not isinstance(output, dict):
            return []

        predictions = output.get("predictions", [])
        if isinstance(predictions, dict):
            predictions = predictions.get("predictions", [])

        return predictions if isinstance(predictions, list) else []

    @staticmethod
    def _keep_strongest(detections: list[Detection]) -> list[Detection]:
        """One entry per PPE code, keeping the most confident sighting.

        Two people in frame, or one helmet detected twice, would otherwise
        send duplicates. The backend tolerates them, but a single clear value
        per item makes the access log readable.
        """
        strongest: dict[str, Detection] = {}
        for detection in detections:
            current = strongest.get(detection.ppe_code)
            if current is None or detection.confidence > current.confidence:
                strongest[detection.ppe_code] = detection
        return sorted(strongest.values(), key=lambda d: d.ppe_code)
