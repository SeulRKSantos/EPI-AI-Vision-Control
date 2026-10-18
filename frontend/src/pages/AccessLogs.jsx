/**
 * Access history.
 *
 * Read-only, because this is the audit trail: it is written by the decision
 * path and must not be editable from a screen. Denials are the reason
 * anyone opens this page, so the reason for each one is spelled out rather
 * than left as a status code.
 *
 * The list refreshes on its own while it is open, so an attempt at the gate
 * shows up here without anyone reaching for a button. Refreshes are silent:
 * the table is updated in place rather than blanked and redrawn.
 */

import { Fragment, useEffect, useState } from "react";
import { api } from "../api/client";
import { Button, Empty, ErrorNote, Field, Loading, Pill, Select } from "../components/ui";
import { DECISIONS, describeDecision, explainDecision } from "../decisions";
import { useResource } from "../hooks/useResource";
import { PageHead } from "./Matrix";

const PAGE_SIZE = 25;
const REFRESH_MS = 3000;

export default function AccessLogs() {
  const [filters, setFilters] = useState({ decision: "", badge_id: "" });
  const [offset, setOffset] = useState(0);
  const [live, setLive] = useState(true);
  const [expanded, setExpanded] = useState(null);

  // The log stores the codes the vision model and the gate speak. The person
  // reading this page speaks the names on the equipment, so both are looked
  // up and translated here rather than exposing internal identifiers.
  const ppeTypes = useResource(() => api.ppeTypes.list({ include_inactive: true }), []);
  const roles = useResource(() => api.roles.list({ include_inactive: true }), []);

  const ppeLabel = (code) =>
    (ppeTypes.data || []).find((p) => p.code === code)?.label || code;
  const roleName = (code) =>
    (roles.data || []).find((r) => r.code === code)?.name || code;

  const query = () => api.accessLogs.list({ ...filters, limit: PAGE_SIZE, offset });

  const logs = useResource(query, [filters.decision, filters.badge_id, offset]);

  // Live refresh only on the first page: a person paging back through
  // history should not have rows shifting under them.
  useEffect(() => {
    if (!live || offset !== 0) return undefined;
    const timer = setInterval(async () => {
      try {
        logs.setData(await query());
      } catch {
        // The next tick retries; a blip should not replace the table with an error.
      }
    }, REFRESH_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, offset, filters.decision, filters.badge_id]);

  const setFilter = (field) => (event) => {
    setOffset(0);
    setFilters((current) => ({ ...current, [field]: event.target.value }));
  };

  const total = logs.data?.total ?? 0;
  const items = logs.data?.items ?? [];

  return (
    <div>
      <PageHead
        title="Histórico de acessos"
        subtitle="Toda tentativa fica registrada, liberada ou não. O registro não pode ser editado. Clique numa linha para ver o que a câmera reconheceu."
      />

      <div className="flex flex-wrap gap-4 items-end mb-5">
        <div className="w-56">
          <Field label="Resultado">
            <Select value={filters.decision} onChange={setFilter("decision")}>
              <option value="">Todos</option>
              {Object.entries(DECISIONS).map(([value, { label }]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <div className="w-48">
          <Field label="Crachá">
            <input
              value={filters.badge_id}
              onChange={setFilter("badge_id")}
              placeholder="BADGE001"
              className="w-full px-3 py-2 rounded-sm border border-ink-line bg-paper-raised text-sm font-mono placeholder:font-sans placeholder:text-ink-mute focus:border-teal"
            />
          </Field>
        </div>
        <label className="inline-flex items-center gap-2 text-sm text-ink-soft pb-2">
          <input
            type="checkbox"
            checked={live}
            onChange={(e) => setLive(e.target.checked)}
            className="accent-teal"
          />
          Atualizar automaticamente
        </label>
        {!live && (
          <Button tone="quiet" onClick={() => logs.reload()}>
            Atualizar
          </Button>
        )}
      </div>

      {logs.loading && !logs.data ? (
        <Loading />
      ) : logs.error ? (
        <ErrorNote message={logs.error} onRetry={logs.reload} />
      ) : !items.length ? (
        <Empty
          message={
            filters.decision || filters.badge_id
              ? "Nenhum acesso encontrado com esses filtros."
              : "Nenhum acesso registrado ainda. O primeiro aparece aqui assim que um crachá for lido."
          }
        />
      ) : (
        <>
          <div className="bg-paper-raised border border-ink-line overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b-2 border-ink-line text-left">
                  <Th>Momento</Th>
                  <Th>Crachá</Th>
                  <Th>Função</Th>
                  <Th>Resultado</Th>
                  <Th>Faltou</Th>
                  <Th className="text-right">Tempo</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((log) => {
                  const decision = describeDecision(log.decision);
                  const open = expanded === log.id;
                  return (
                    <Fragment key={log.id}>
                      <tr
                        onClick={() => setExpanded(open ? null : log.id)}
                        className={`border-b border-ink-line cursor-pointer hover:bg-paper-sunk ${
                          open ? "bg-paper-sunk" : ""
                        }`}
                        aria-expanded={open}
                      >
                        <Td>
                          <span className="text-sm tabular-nums">
                            {new Date(log.created_at).toLocaleString("pt-BR")}
                          </span>
                        </Td>
                        <Td>
                          <span className="font-mono text-sm">{log.badge_id}</span>
                        </Td>
                        <Td>
                          <span className="text-sm text-ink-mute">
                            {log.role_code ? roleName(log.role_code) : "—"}
                          </span>
                        </Td>
                        <Td>
                          <Pill tone={decision.tone}>{decision.label}</Pill>
                        </Td>
                        <Td>
                          {log.missing_ppe.length ? (
                            <span className="text-sm text-signal-denied">
                              {log.missing_ppe.map(ppeLabel).join(", ")}
                            </span>
                          ) : (
                            <span className="text-sm text-ink-mute">—</span>
                          )}
                        </Td>
                        <Td className="text-right">
                          <span className="text-sm text-ink-mute tabular-nums">
                            {log.latency_ms ? `${Math.round(log.latency_ms)} ms` : "—"}
                          </span>
                        </Td>
                      </tr>
                      {open && (
                        <tr className="border-b border-ink-line bg-paper-sunk">
                          <td colSpan={6} className="px-4 pb-4 pt-1">
                            <Details log={log} ppeLabel={ppeLabel} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between mt-4">
            <p className="text-sm text-ink-mute">
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} de {total}
              {live && offset === 0 && " · atualizando a cada 3 s"}
            </p>
            <div className="flex gap-2">
              <Button
                tone="quiet"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Anteriores
              </Button>
              <Button
                tone="quiet"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Próximos
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Details({ log, ppeLabel }) {
  const detections = [...(log.detected_ppe || [])].sort(
    (a, b) => b.confidence - a.confidence
  );
  const required = new Set(log.required_ppe);

  return (
    <div className="bg-paper-raised border border-ink-line p-4 grid gap-4 md:grid-cols-[1fr_1fr]">
      <div>
        <p className="text-sm font-medium">Por que</p>
        <p className="text-sm text-ink-soft mt-1">{explainDecision(log, ppeLabel)}</p>
        <p className="text-xs text-ink-mute mt-3">
          Sessão <span className="font-mono">{log.session_id}</span>
        </p>
      </div>
      <div>
        <p className="text-sm font-medium">O que a câmera reconheceu</p>
        {detections.length === 0 ? (
          <p className="text-sm text-ink-mute mt-1">
            {log.decision === "denied_vision_timeout" ||
            log.decision === "denied_unknown_badge" ||
            log.decision === "denied_inactive_employee"
              ? "Nenhuma imagem foi avaliada para esta tentativa."
              : "Nenhum EPI reconhecido."}
          </p>
        ) : (
          <ul className="mt-1 space-y-1">
            {detections.map((d) => (
              <li key={d.ppe_code} className="flex justify-between text-sm">
                <span className={required.has(d.ppe_code) ? "" : "text-ink-mute"}>
                  {ppeLabel(d.ppe_code)}
                  {!required.has(d.ppe_code) && " (não exigido)"}
                </span>
                <span className="tabular-nums text-ink-mute">
                  {Math.round(d.confidence * 100)}%
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Th({ children, className = "" }) {
  return (
    <th className={`px-4 py-2.5 text-sm font-medium text-ink-mute ${className}`}>{children}</th>
  );
}

function Td({ children, className = "" }) {
  return <td className={`px-4 py-2.5 align-middle ${className}`}>{children}</td>;
}
