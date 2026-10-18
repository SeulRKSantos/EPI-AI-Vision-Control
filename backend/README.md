# Backend

Decides every access attempt. It receives the badge scan from the gate, identifies the employee and the PPE their role requires, asks the vision service what the camera sees, compares the two, records the outcome and publishes the decision back to the gate. It also serves the REST API behind the administration panel.

## Responsibilities

The backend is the only component that decides. The firmware reads a card and obeys a decision; the vision service reports what it detects. Correlating badge, role, required PPE and detected PPE happens here, and so does the audit record of every attempt.

The vision service is never called directly. Inference is requested over MQTT and the result is awaited with a timeout, so the two services stay independent and the model can change without touching this one.

## Layout

```
app/
├── main.py                  # FastAPI app; lifespan starts the DB pool and the MQTT consumer
├── core/
│   ├── config.py            # Settings from environment variables
│   ├── logging.py           # Structured JSON logging
│   ├── mqtt_client.py       # aiomqtt client; each message handled in its own task
│   ├── topics.py            # MQTT topic names
│   └── badges.py            # Badge id normalization (uppercase hex, trimmed)
├── db/
│   ├── models/              # Gates, roles, PPE types, requirements, employees, access logs
│   ├── migrations/          # Alembic
│   ├── seed.py              # Idempotent example data
│   └── session.py           # Async engine and session factory
├── schemas/
│   ├── messages.py          # MQTT contracts
│   └── entities.py          # REST contracts
├── api/v1/                  # Health, gates, PPE types, roles, employees, access logs
├── services/
│   ├── rfid_handler.py      # Consumes badge scans
│   ├── session_manager.py   # In-flight sessions, timeouts and the badge cooldown
│   ├── access_flow.py       # Scan → vision request → decision → publish
│   └── access_control.py    # The decision rule and the audit record
└── tests/
```

MQTT handlers run as independent tasks. A scan waits for its vision result, and that result arrives on the same consumer, so awaiting handlers inline would deadlock the consumer on the very message it is waiting for. `test_consumer_serves_a_second_scan_while_the_first_is_pending` guards this.

## Data model

| Table | Holds |
|---|---|
| `gates` | Access points. The seed creates `gate-01` |
| `ppe_types` | PPE the system knows. Each `code` is what the vision service reports |
| `roles` | Job roles |
| `role_ppe_requirements` | Which PPE each role requires (the matrix in the panel) |
| `employees` | People, their badge id and their role |
| `access_logs` | One record per attempt: decision, required, detected and missing PPE, latency. Filterable by badge, gate, decision, period |

Records are deactivated, never deleted. Access logs keep the badge, role and PPE codes by value, and link to the employee by id: history survives deactivations and badge changes.

## Decisions

| Value | When |
|---|---|
| `granted` | Every required PPE detected at or above the confidence threshold |
| `denied_missing_ppe` | At least one required item absent or below the threshold |
| `denied_unknown_badge` | No employee with that badge |
| `denied_inactive_employee` | Employee deactivated |
| `denied_vision_timeout` | No vision result within `SESSION_TIMEOUT_SECONDS` |
| `denied_internal_error` | Anything else that went wrong |

The default is to deny. A detection below the threshold counts as absent. A result that arrives after its session closed is discarded and logged, so a late answer can never open the gate for an attempt that already ended. The same badge is ignored for `BADGE_COOLDOWN_SECONDS` after a scan.

## MQTT contracts

| Topic | From → to | Payload |
|---|---|---|
| `access/{gate}/badge/scan` | gate → backend | `session_id`, `gate_code`, `badge_id` |
| `vision/{gate}/request` | backend → vision | `session_id`, `gate_code` |
| `vision/{gate}/result` | vision → backend | `session_id`, `detections: [{ppe_code, confidence}]`, `inference_ms` |
| `access/{gate}/decision` | backend → gate | `session_id`, `granted`, `reason` (`compliant`, `missing_ppe`, `unknown_badge`, …), `missing_ppe` |
| `access/{gate}/status` | gate → backend | `online` / `offline` (retained; also the Last Will) |

QoS 1 throughout. Every message carries the `session_id` created at scan time; that is what correlates request and answer when scans overlap.

Badge ids are normalized to the reader's format (trimmed, uppercase hex) on registration, on update and on incoming scans, so `769f8205 ` typed in the panel matches `769F8205` from the reader.

## REST API

Interactive documentation at `http://<host>:8000/docs`.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness |
| `GET` | `/health/ready` | Database and broker reachable (503 otherwise) |
| `GET` `POST` | `/api/v1/ppe-types` | List, create |
| `GET` `PATCH` `DELETE` | `/api/v1/ppe-types/{code}` | Read, update, deactivate |
| `GET` `POST` | `/api/v1/roles` | List, create |
| `GET` `PATCH` `DELETE` | `/api/v1/roles/{code}` | Read, update, deactivate |
| `GET` `PUT` | `/api/v1/roles/{code}/requirements` | Read or replace the PPE a role requires |
| `GET` `POST` | `/api/v1/employees` | List (`include_inactive`, `role_code`), register |
| `GET` `PATCH` `DELETE` | `/api/v1/employees/{badge_id}` | Read, update (including a new `badge_id`), deactivate |
| `GET` | `/api/v1/access-logs` | History with filters and paging |
| `POST` | `/api/v1/gates/{gate_code}/simulate-scan` | Publish a scan exactly as the gate would |

Changing an employee's badge keeps their history, makes the old card stop working at once, and is refused with `409` when the new card already belongs to someone else.

## Configuration

Read from environment variables (the shared `.env`); see `.env.example` at the repository root.

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` | `db`, `5432`, … | Database |
| `MQTT_HOST` / `MQTT_PORT` | `mosquitto`, `1883` | Broker |
| `MQTT_CLIENT_ID` | `epi-backend` | Must differ from the vision service's |
| `SESSION_TIMEOUT_SECONDS` | `8` | Wait for the vision result before denying |
| `DETECTION_CONFIDENCE_THRESHOLD` | `0.6` | Minimum confidence for a detection to count |
| `BADGE_COOLDOWN_SECONDS` | `5` | Repeated scans of the same badge ignored |
| `CORS_ORIGINS` | localhost dev ports | `["*"]` lets the panel run from any address on the network |

## Running

Part of the stack: `docker compose up -d backend`. On start the container waits for the database and applies the migrations before accepting connections. `./backend/app` is mounted into the container, so code changes apply with `docker compose restart backend`.

Example data (9 PPE types, 5 roles, the `gate-01` gate and employees `BADGE001`–`BADGE005`) is loaded on demand:

```bash
docker compose exec backend python -m app.db.seed
```

Running it again creates whatever is missing, but it also **resets the requirement matrix of the example roles and the role of the example employees** to their original values. Do not rerun it after adjusting the matrix in the panel. An example employee whose badge was changed is created again under its original badge.

## Tests

```bash
docker compose exec backend pytest -q
```

Without a test database the integration tests are skipped and the pure logic runs. For the full suite, point the tests at a disposable database and a broker — never the real one, the schema is dropped and recreated:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/epi_test \
TEST_MQTT_HOST=127.0.0.1 TEST_MQTT_PORT=1883 pytest -q
```

84 tests: decision rule, every denial path, session correlation and timeouts, the badge cooldown, the API including badge changes, and the full scan-to-decision flow over a real broker.
