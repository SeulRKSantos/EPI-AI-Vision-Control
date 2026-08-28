# Backend — EPI-AI-Vision-Control

Service responsible for the access control decision logic: it receives the badge scan sent by the ESP32, identifies the employee and the PPE required by their role, requests inference from the vision service, and returns the decision to grant or deny access.

## Responsibilities

The backend is the only component that decides. The firmware only reads and actuates; the vision service only detects. All correlation between credential, role, required PPE and detected PPE happens here, as does the auditable record of every access attempt.

There is no direct call to the YOLO model from this service. Inference is requested by message and the result is awaited asynchronously, with a timeout — keeping both services independent and allowing the vision side to evolve without backend changes.

## Internal architecture

```
app/
├── main.py                    # FastAPI application and lifespan
├── core/
│   ├── config.py               # Configuration from environment variables
│   ├── logging.py              # Structured logging
│   └── mqtt_client.py          # Asynchronous MQTT client (aiomqtt)
├── db/
│   ├── base.py                 # SQLAlchemy declarative base
│   ├── session.py              # Async engine and session factory
│   ├── models/                 # ORM mapping of the entities
│   ├── repositories/           # Data access isolated from business logic
│   └── migrations/             # Versioned migrations (Alembic)
├── schemas/                    # Pydantic contracts — API and MQTT messages
├── api/v1/                     # REST endpoints for administration and queries
├── services/
│   ├── session_manager.py       # Correlation, state and timeout per session
│   ├── rfid_handler.py          # Consumes badge scans from the ESP32
│   ├── vision_gateway.py        # Requests inference and awaits the result
│   └── access_control.py        # Compares required PPE against detected PPE
└── tests/
```

`main.py` initializes the database connection pool and the MQTT client inside the application `lifespan`, keeping an asynchronous consumer running for as long as the application is up. The REST API and the MQTT consumer share the same event loop, without blocking each other.

## Data model

| Entity | Description |
|---|---|
| `gates` | Physical access points controlled by the system |
| `roles` | Roles performed by employees (operator, electrician, technician) |
| `ppe_types` | Recognized PPE types; each type's code matches a vision model class |
| `role_ppe_requirements` | Relationship between a role and its mandatory PPE |
| `employees` | Employees, associated with a role and a badge identifier |
| `access_logs` | Auditable record of each attempt: decision, detected PPE, missing PPE and latency |

Each PPE type code is the coupling point between the database and the vision model. Changes to the model's classes require a corresponding update to `ppe_types` — this correspondence is validated at service startup.

## MQTT contracts

| Topic | Source | Destination | Content |
|---|---|---|---|
| `access/{gate_id}/badge/scan` | ESP32 | Backend | Badge and session identifiers |
| `vision/{gate_id}/request` | Backend | Vision | Inference request carrying the session identifier |
| `vision/{gate_id}/result` | Vision | Backend | Detected PPE and respective confidence scores |
| `access/{gate_id}/decision` | Backend | ESP32 | Release decision and missing PPE |
| `access/{gate_id}/status` | ESP32 | Backend | Device availability (heartbeat and Last Will) |

Every message carries the session identifier generated at scan time. That identifier is what allows requests and responses to be correlated when there are simultaneous scans or concurrency between access points.

## REST API

The API serves system administration and auditing. It is not part of the critical decision path, which is driven entirely by messaging.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Service liveness check |
| `GET` | `/health/ready` | Dependency check (database and broker) |
| `GET` `POST` `PATCH` `DELETE` | `/api/v1/employees` | Employee management |
| `GET` `POST` `PATCH` `DELETE` | `/api/v1/roles` | Role management |
| `GET` `PUT` | `/api/v1/roles/{id}/requirements` | Mandatory PPE matrix per role |
| `GET` `POST` | `/api/v1/ppe-types` | Recognized PPE types |
| `GET` | `/api/v1/access-logs` | Access history queries, with filters |
| `POST` | `/api/v1/gates/{id}/simulate-scan` | Badge scan simulation, for testing without hardware |

The simulation endpoint is what allows the full decision logic to be developed and tested before the firmware is ready, and it remains useful afterwards as an automated testing tool.

## Failure behavior

The system's default decision is to deny access. The backend publishes a negative decision when the badge matches no active employee, when the vision service does not respond within the configured timeout, when detection confidence falls below the defined threshold, or when any internal dependency is unavailable. The absence of a message is never interpreted as authorization.

Every session has a limited lifetime. Inference results arriving after a session has closed are discarded and logged, preventing a late response from releasing an access that was already decided.

## Configuration

All settings are read from environment variables, with no sensitive values committed to the repository. The `.env.example` file at the repository root documents the expected keys, among them the database connection URL, the MQTT broker address and credentials, the session timeout and the confidence threshold accepted for detections.

## Running

The service runs as a container, orchestrated alongside the broker, the database and the vision service by the `docker-compose.yml` at the repository root. Database migrations are applied at startup, before the application begins accepting connections.
