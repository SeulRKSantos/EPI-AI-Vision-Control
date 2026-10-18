# Vision service

Detects PPE and reports what it saw. It makes no access decision: it publishes each detection with its raw confidence, and the backend compares them against what the employee's role requires. It also streams the gate camera to the panel with the model's boxes drawn on it.

The model is a Roboflow workflow (`epis-v2-logic`), called through `inference-sdk`.

## How it fits

```
badge scan ──► backend ──► vision/{gate}/request ──► this service ──► camera + model
                   ▲                                      │
                   └────── vision/{gate}/result ◄─────────┘

panel ──► :8081/stream.mjpg   (live video with boxes)
      ──► :8081/detections    (what is recognized right now)
```

Decisions run on demand: one inference per badge scan, on the freshest frame. A loop inferring every frame would spend API calls all day and would still have to choose which frame the decision rests on; the scan says when.

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
  "inference_ms": 1240.5
}
```

The `session_id` must be echoed exactly; a new id cannot be matched to the session waiting for it, and the attempt times out into a refusal. Confidence is published raw: the acceptance threshold is the backend's policy, tunable without retraining or redeploying this service. When the same PPE appears twice, only the most confident sighting is sent.

## Class mapping

`class_map.json` translates model class names into the backend's `ppe_types.code`. Lookup ignores case, accents and separators: `Capacete`, `capacete` and `CAPACETE` are one entry, and so are `Protetor_Auricular` and `protetor auricular`.

| Model class | PPE code |
|---|---|
| Capacete | `helmet` |
| Óculos | `goggles` |
| Luvas | `gloves` |
| Protetor_Auricular | `ear_protection` |
| Macacão | `coverall` |
| Cinto de segurança | `harness` |

Deliberately **not** mapped:

| Class | Why |
|---|---|
| Cinto | The trouser belt, a separate class from "Cinto de segurança". Mapping it to `harness` would clear someone for work at height without fall protection |
| Rímel | A negative class trained to absorb dark circles and eye make-up the model used to mistake for goggles. Mapping it would report goggles exactly when they are absent |
| Bota, Calça, Jaqueta | Outside the requirement matrix |

A class with no mapping is ignored and logged once (`Model class has no mapping and will be ignored`). Never map an absence class such as `sem-capacete`: the backend infers absence from what is missing.

The current model has **no class for vest or respirator**. While those stay in the matrix, roles requiring them are always denied.

## Live view

`http_server.py` serves, on `VISION_HTTP_PORT` (8081), with CORS open for the panel:

| Route | Returns |
|---|---|
| `/stream.mjpg` | MJPEG video with the boxes drawn on the server. Plays in a plain `<img>` |
| `/detections` | The boxes currently drawn, the source (`live` or `scan`), and the live loop's health |
| `/health` | `200` with a fresh frame, `503` without one |

Two sources feed the boxes:

- **Live loop:** one inference every `LIVE_INFERENCE_INTERVAL_SECONDS` while at least one stream is open. Nobody watching means no calls, so an unattended dashboard spends nothing.
- **Badge scans:** the boxes of the inference that decided an attempt are published as soon as it returns, marked `LEITURA DE CRACHA`, so the panel shows exactly what the gate saw.

Box colours carry the decision rule: green is accepted, amber is a matrix PPE below the threshold (counts as absent), grey is a class that is not PPE.

Each live call runs on its own client and thread and is abandoned after `INFERENCE_TIMEOUT_SECONDS`. A call that hangs can neither block the next ones nor hold up a badge scan, and the panel shows `Sem resposta do serviço de visão…` instead of going quiet. `/detections` reports `live_attempts`, `last_attempt_age_s`, `last_success_age_s`, `stuck_calls` and the last `error`, which is the first place to look when the boxes stop.

## Failure behaviour

When the camera gives no usable frame, or inference fails or times out, a badge scan gets **no answer**. The backend's timeout turns that silence into a refusal. Publishing an empty list would instead claim the equipment was absent, a different and misleading statement.

A frame older than two seconds is never used for a decision: an old image could open the gate for whoever was standing there before.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ROBOFLOW_API_KEY` | — | Required. Never commit it |
| `ROBOFLOW_WORKSPACE` / `ROBOFLOW_WORKFLOW` | — | Required |
| `ROBOFLOW_API_URL` | `https://serverless.roboflow.com` | Point at a local inference server to run offline |
| `CAMERA_INDEX` | `0` | `/dev/video0` |
| `CAMERA_WIDTH` / `CAMERA_HEIGHT` | `1280` / `720` | Capture resolution |
| `INFERENCE_TIMEOUT_SECONDS` | `6` | Give up on one inference. Keep it under the backend's `SESSION_TIMEOUT_SECONDS` |
| `LIVE_INFERENCE_INTERVAL_SECONDS` | `1.5` | Live boxes pace; `0` streams plain video |
| `DETECTION_CONFIDENCE_THRESHOLD` | `0.6` | Colours the live boxes; use the same value as the backend |
| `VISION_HTTP_PORT` | `8081` | Live view port |
| `STREAM_FPS` / `STREAM_MAX_WIDTH` | `10` / `960` | Stream frame rate and size |
| `MQTT_CLIENT_ID` | `epi-vision` | Set in `docker-compose.yml`; must differ from the backend's |
| `SAVE_SNAPSHOTS` / `SNAPSHOT_DIR` | `false` / `/app/snapshots` | Keep the frame each decision rested on |

The service refuses to start with incomplete configuration rather than failing every request.

## Running

```bash
docker compose up -d --build vision
```

The compose file passes the webcam through (`/dev/video0`) and publishes port 8081. Only one process can hold the camera: close `tools/preview.py` or any other camera program first. If port 8081 is taken on the host, the container will not start; `sudo ss -ltnp 'sport = :8081'` shows by whom.

## Preview tool

`tools/preview.py` runs the model continuously on the local webcam and draws what it finds, outside Docker. It is how you check framing, lighting and distance before trusting the gate to them.

```bash
ROBOFLOW_API_KEY=... ROBOFLOW_WORKSPACE=... ROBOFLOW_WORKFLOW=... python tools/preview.py
```

Green is above the preview threshold, amber below it, red a class with no mapping. Locally, install only `opencv-python` (not the `-headless` variant alongside it), or the window stays black.

## Tests

```bash
python3 tests/test_detector.py      # parsing and mapping (43 checks)
python3 tests/test_live.py          # drawing, endpoints, cost guard, hung calls (28 checks)
TEST_MQTT_HOST=127.0.0.1 TEST_MQTT_PORT=1884 python3 tests/test_service_e2e.py   # needs a broker (13 checks)
```

Run the end-to-end suite against a broker the running service is not using; otherwise the real service answers the test's requests.

## Limitation

The model confirms that an item is present, not that it is right for the risk. It does not distinguish a class B helmet from an ordinary one, or a nitrile glove from a leather one, as NR-10 and chemical exposure require. It is an additional layer of control, not a replacement for the safety procedure.
