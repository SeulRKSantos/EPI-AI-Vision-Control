/**
 * API client.
 *
 * One place that knows how to talk to the backend, so every screen reports
 * failures the same way. The backend answers validation problems with a
 * `detail` field; we surface that text rather than a generic message,
 * because it names the actual problem (an unknown PPE code, a duplicate
 * badge) and the person can act on it.
 */

// The API answers on the same host the panel was served from, so the panel
// works on localhost and on any LAN address without being rebuilt.
// VITE_API_URL still overrides it when the API lives elsewhere.
const BASE =
  import.meta.env.VITE_API_URL ||
  `${window.location.protocol}//${window.location.hostname}:8000`;
const V1 = `${BASE}/api/v1`;

// The vision service publishes the camera on its own port, on the same host.
const VISION =
  import.meta.env.VITE_VISION_URL ||
  `${window.location.protocol}//${window.location.hostname}:8081`;

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${V1}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new ApiError("Sem conexão com o servidor.", 0);
  }

  if (response.status === 204) return null;

  const body = await response.json().catch(() => null);

  if (!response.ok) {
    throw new ApiError(describe(body, response.status), response.status);
  }
  return body;
}

function describe(body, status) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors arrive as a list of field problems.
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = first.loc?.filter((p) => p !== "body").join(".");
    return field ? `${field}: ${first.msg}` : first.msg;
  }
  if (status === 0) return "Sem conexão com o servidor.";
  return `Falha na requisição (${status}).`;
}

const query = (params) => {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.append(key, value);
    }
  });
  const s = search.toString();
  return s ? `?${s}` : "";
};

export const api = {
  health: () => fetch(`${BASE}/health/ready`).then((r) => r.json()),

  ppeTypes: {
    list: (params) => request(`/ppe-types${query(params)}`),
    create: (data) => request("/ppe-types", { method: "POST", body: JSON.stringify(data) }),
    update: (code, data) =>
      request(`/ppe-types/${code}`, { method: "PATCH", body: JSON.stringify(data) }),
    deactivate: (code) => request(`/ppe-types/${code}`, { method: "DELETE" }),
  },

  roles: {
    list: (params) => request(`/roles${query(params)}`),
    create: (data) => request("/roles", { method: "POST", body: JSON.stringify(data) }),
    update: (code, data) =>
      request(`/roles/${code}`, { method: "PATCH", body: JSON.stringify(data) }),
    setRequirements: (code, ppeCodes) =>
      request(`/roles/${code}/requirements`, {
        method: "PUT",
        body: JSON.stringify({ required_ppe: ppeCodes }),
      }),
    deactivate: (code) => request(`/roles/${code}`, { method: "DELETE" }),
  },

  employees: {
    list: (params) => request(`/employees${query(params)}`),
    get: (badgeId) => request(`/employees/${badgeId}`),
    create: (data) => request("/employees", { method: "POST", body: JSON.stringify(data) }),
    update: (badgeId, data) =>
      request(`/employees/${badgeId}`, { method: "PATCH", body: JSON.stringify(data) }),
    deactivate: (badgeId) => request(`/employees/${badgeId}`, { method: "DELETE" }),
  },

  accessLogs: {
    list: (params) => request(`/access-logs${query(params)}`),
  },

  vision: {
    streamUrl: () => `${VISION}/stream.mjpg`,
    detections: async () => {
      const response = await fetch(`${VISION}/detections`);
      if (!response.ok) throw new ApiError("Serviço de visão indisponível.", response.status);
      return response.json();
    },
    health: async () => {
      const response = await fetch(`${VISION}/health`);
      return { ok: response.ok, ...(await response.json().catch(() => ({}))) };
    },
  },

  gates: {
    simulateScan: (gateCode, badgeId) =>
      request(`/gates/${gateCode}/simulate-scan`, {
        method: "POST",
        body: JSON.stringify({ badge_id: badgeId }),
      }),
  },
};
