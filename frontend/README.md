# Administration panel

Web panel for the people who run the gate: the PPE requirement matrix, employees and their badges, roles and PPE types, the live gate camera, a gate test that needs no hardware, and the access history. The interface is in Portuguese; the code and comments are in English.

## Pages

| Route | Page | File |
|---|---|---|
| `/` | Matriz de exigências: which PPE each role requires, edited in place | `pages/Matrix.jsx` |
| `/camera` | Visão do portão: live camera with the model's boxes and what is recognized now | `pages/CameraView.jsx` |
| `/portao` | Testar portão: simulates a badge read and shows the result item by item, with a small live camera | `pages/GateTest.jsx` |
| `/funcionarios` | Employees: register, change badge, deactivate | `pages/Employees.jsx` |
| `/funcoes`, `/equipamentos` | Roles and PPE types; deactivating a role names the employees affected | `pages/Registries.jsx` |
| `/historico` | Access history, refreshed every 3 s while on the first page, each row expandable into the reason for the decision | `pages/AccessLogs.jsx` |

The header shows three status lights: database, gate broker (MQTT) and camera.

## How it reaches the services

The API and the camera addresses are built at runtime from the address the panel was opened on:

| Service | Address |
|---|---|
| API | `http(s)://<same host>:8000` |
| Camera (vision service) | `http(s)://<same host>:8081` |

Opening the panel at `http://192.168.15.18:3000` therefore talks to `192.168.15.18:8000` and `:8081`, and the same build works from any machine on the network with no configuration. `VITE_API_URL` and `VITE_VISION_URL` override this at build time when the services live elsewhere. The backend must allow the panel's origin (`CORS_ORIGINS=["*"]` in `.env`).

## Structure

```
src/
├── App.jsx                 # Layout, navigation, routes, status lights
├── api/client.js           # REST client (API and vision service); errors carry the HTTP status
├── components/
│   ├── ui.jsx              # Buttons, fields, modal, pills, page states
│   └── CameraFeed.jsx      # MJPEG feed with reconnection, and the detections poller
├── hooks/                  # useResource (load/reload/error), useToast
├── decisions.js            # Labels and plain-language explanations for each decision
└── pages/
```

The live feed is a plain `<img>` pointed at the MJPEG stream; the boxes are drawn by the vision service. Mounting a feed is what tells that service someone is watching, and live inference stops when the last feed unmounts.

## Running

In the stack, built and served by nginx on port 3000:

```bash
docker compose up -d --build frontend
```

After a rebuild, reload the browser with Ctrl+Shift+R to drop the cached bundle.

For development with hot reload:

```bash
npm install
npm run dev          # http://localhost:5173
```

The dev server still talks to the API on port 8000 of the same host. If port 5173 is taken, run `npx vite --port 5174`.

## Stack

React 19, React Router 7, Vite, Tailwind CSS 3, oxlint. The production image is a multi-stage build: Node builds the static bundle and nginx serves it, with every route falling back to `index.html` so reloading a page such as `/historico` works.
