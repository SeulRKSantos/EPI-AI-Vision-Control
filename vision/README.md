# Vision service

Detects PPE on request and reports what it saw. It makes no decision about access — it reports detections with their raw confidence, and the backend compares them against what the employee's role requires.

## How it fits

The service sits idle until a badge is scanned. The backend then publishes an inference request, and this service grabs the freshest camera frame, runs the model, and answers with the same session identifier it was given.

```
badge scan ──► backend ──► vision/{gate}/request ──► this service
                   ▲                                      │
                   └────── vision/{gate}/result ◄──────────┘
```

Running on demand rather than continuously matters twice over: a loop inferring every frame would burn API calls all day, and it would still have to decide which frame the decision rests on. The scan is what says when.

## Message contract

Received on `vision/+/request`:

```json
{ "session_id": "<uuid>", "gate_code": "gate-01", "requested_at": "..." }
```

Published to `vision/{gate_code}/result`:

```json
{
  "session_id": "<echoed from the request>",
  "detections": [
    { "ppe_code": "helmet", "confidence": 0.95 },
    { "ppe_code": "goggles", "confidence": 0.88 }
  ],
  "inference_ms": 240.5
}
```

Two rules make this work, and breaking either is silent:

The `session_id` must be echoed back exactly. A new identifier cannot be matched to the session waiting for it, so the backend discards the answer and the attempt times out into a refusal.

Confidence is published raw, with no filtering. The acceptance threshold is the backend's policy (`DETECTION_CONFIDENCE_THRESHOLD`), which means it can be tuned against measured results without retraining the model or redeploying this service.

## Class mapping

`class_map.json` translates the model's class names into the `ppe_types.code` values the backend knows. The model and the database are built by different people and need not agree on spelling; keeping the translation in a data file makes a rename a one-line change.

A class with no mapping is ignored and logged once:

```
Model class has no mapping and will be ignored  {"class_name": "person"}
```

That log is how you discover the names the workflow actually emits. Run the preview tool, watch the warnings, add the mappings.

Never map a negative class such as `no-helmet`. The backend infers absence from what is missing; mapping an absence class would report the equipment as present, which inverts the whole system.

## Failure behaviour

When the camera gives no usable frame, or inference fails or times out, the service publishes nothing. The backend's own timeout turns that silence into a refusal.

That is deliberate. Publishing an empty detection list would be read as "the equipment was absent" — a different and misleading claim. Nothing was seen, so nothing is vouched for.

A frame older than two seconds is also refused. Deciding from a stale image is worse than not deciding: the backend's timeout keeps the gate shut, while a wrong frame could open it for the person who was standing there before.

## Configuration

| Variable | Purpose |
|---|---|
| `ROBOFLOW_API_KEY` | API key. Never commit it |
| `ROBOFLOW_WORKSPACE` | Workspace name |
| `ROBOFLOW_WORKFLOW` | Workflow id |
| `MQTT_HOST` / `MQTT_PORT` | Broker |
| `CAMERA_INDEX` | Which camera, usually `0` |
| `INFERENCE_TIMEOUT_SECONDS` | Give up on one inference. Keep it under the backend's `SESSION_TIMEOUT_SECONDS` so the gate answers sooner |
| `SAVE_SNAPSHOTS` | Keep the frame each decision rested on, for audit review |

The service refuses to start with incomplete configuration rather than running and failing every request.

## Running

As part of the stack:

```bash
docker compose up -d vision
```

The container needs the camera passed through, which the compose file does with `devices: ["/dev/video0:/dev/video0"]`.

## Preview tool

`tools/preview.py` runs the model continuously against the webcam and draws what it finds. It is a development tool, not part of the service — it is how you check framing, lighting and distance before trusting the gate to it.

```bash
ROBOFLOW_API_KEY=... ROBOFLOW_WORKSPACE=... ROBOFLOW_WORKFLOW=... \
    python tools/preview.py
```

Boxes are green above the preview threshold, amber below it, and red for a class with no mapping — which is the case worth watching for, since the service would ignore it in silence.

## Tests

```bash
python3 tests/test_detector.py                      # parsing and mapping, no deps
TEST_MQTT_HOST=127.0.0.1 python3 tests/test_service_e2e.py   # needs a broker
```

The parser tests cover the response shapes, the mapping, unmapped classes, and duplicate detections. The end-to-end tests run the real service loop against a real broker with the camera and model stubbed, covering session echo, camera failure, inference failure, malformed requests, and concurrent requests.

## Limitation

The model confirms that an item is present, not that it is the right item for the risk. It does not distinguish a class B helmet from an ordinary one, or a nitrile glove from a leather one — distinctions NR-10 and chemical exposure require. This is an additional layer of control, not a replacement for the safety procedure.
