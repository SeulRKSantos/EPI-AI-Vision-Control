/**
 * Access history.
 *
 * Read-only, because this is the audit trail: it is written by the decision
 * path and must not be editable from a screen. Denials are the reason
 * anyone opens this page, so the reason for each one is spelled out rather
 * than left as a status code.
 */

import { useState } from "react";
import { api } from "../api/client";
import { Button, Empty, ErrorNote, Field, Loading, Pill, Select } from "../components/ui";
import { useResource } from "../hooks/useResource";
import { PageHead } from "./Matrix";

const PAGE_SIZE = 25;

const DECISIONS = {
  granted: { label: "Liberado", tone: "granted" },
  denied_missing_ppe: { label: "EPI faltando", tone: "denied" },
  denied_unknown_badge: { label: "Crachá desconhecido", tone: "denied" },
  denied_inactive_employee: { label: "Crachá desativado", tone: "denied" },
  denied_vision_timeout: { label: "Câmera sem resposta", tone: "warn" },
  denied_internal_error: { label: "Falha interna", tone: "warn" },
};

export default function AccessLogs() {
  const [filters, setFilters] = useState({ decision: "", badge_id: "" });
  const [offset, setOffset] = useState(0);

  // The log stores the codes the vision model and the gate speak. The person
  // reading this page speaks the names on the equipment, so both are looked
  // up and translated here rather than exposing internal identifiers.
  const ppeTypes = useResource(() => api.ppeTypes.list({ include_inactive: true }), []);
  const roles = useResource(() => api.roles.list({ include_inactive: true }), []);

  const ppeLabel = (code) =>
    (ppeTypes.data || []).find((p) => p.code === code)?.label || code;
  const roleName = (code) =>
    (roles.data || []).find((r) => r.code === code)?.name || code;

  const logs = useResource(
    () =>
      api.accessLogs.list({
        ...filters,
        limit: PAGE_SIZE,
        offset,
      }),
    [filters.decision, filters.badge_id, offset]
  );

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
        subtitle="Toda tentativa fica registrada, liberada ou não. O registro não pode ser editado."
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
        <Button tone="quiet" onClick={() => logs.reload()} className="mb-0">
          Atualizar
        </Button>
      </div>

      {logs.loading ? (
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
                  const decision = DECISIONS[log.decision] || {
                    label: log.decision,
                    tone: "neutral",
                  };
                  return (
                    <tr key={log.id} className="border-b border-ink-line last:border-0">
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
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between mt-4">
            <p className="text-sm text-ink-mute">
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} de {total}
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

function Th({ children, className = "" }) {
  return (
    <th className={`px-4 py-2.5 text-sm font-medium text-ink-mute ${className}`}>{children}</th>
  );
}

function Td({ children, className = "" }) {
  return <td className={`px-4 py-2.5 align-middle ${className}`}>{children}</td>;
}
