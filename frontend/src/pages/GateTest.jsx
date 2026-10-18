/**
 * Gate test.
 *
 * Publishes a badge scan exactly as the gate device would, then follows the
 * attempt until its decision lands in the access log. This is how the whole
 * system is exercised without firmware: the real camera, the real model and
 * the real decision rule all run; only the badge read is simulated.
 *
 * The result is shown item by item against what the role requires, because
 * "denied" on its own does not tell a safety officer what to fix.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { CameraFeed } from "../components/CameraFeed";
import { Button, ErrorNote, Field, Input, Loading, Pill, Select } from "../components/ui";
import { describeDecision, explainDecision } from "../decisions";
import { useResource } from "../hooks/useResource";
import { useToast } from "../hooks/useToast";
import { PageHead } from "./Matrix";

const OTHER = "__other__";
// A little past the backend's own timeout, so a timed-out attempt is still
// caught here as the refusal it is, rather than reported as lost.
const FOLLOW_UP_LIMIT_MS = 15000;
const POLL_INTERVAL_MS = 400;

export default function GateTest() {
  const { push } = useToast();
  const employees = useResource(() => api.employees.list({ include_inactive: true }), []);
  const ppeTypes = useResource(() => api.ppeTypes.list({ include_inactive: true }), []);

  const [gateCode, setGateCode] = useState("gate-01");
  const [choice, setChoice] = useState("");
  const [otherBadge, setOtherBadge] = useState("");
  const [attempt, setAttempt] = useState(null); // {sessionId, badgeId, startedAt, log, lost}
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef(null);

  useEffect(() => {
    if (!choice && employees.data?.length) setChoice(employees.data[0].badge_id);
  }, [employees.data, choice]);

  useEffect(() => () => clearInterval(timer.current), []);

  const ppeLabel = (code) =>
    (ppeTypes.data || []).find((p) => p.code === code)?.label || code;

  const badgeId = choice === OTHER ? otherBadge.trim() : choice;
  const selected = (employees.data || []).find((e) => e.badge_id === choice);
  const waiting = attempt && !attempt.log && !attempt.lost;

  const follow = (sessionId, startedAt) => {
    clearInterval(timer.current);
    timer.current = setInterval(async () => {
      const spent = Date.now() - startedAt;
      setElapsed(spent);

      if (spent > FOLLOW_UP_LIMIT_MS) {
        clearInterval(timer.current);
        setAttempt((current) => current && { ...current, lost: true });
        return;
      }

      try {
        const page = await api.accessLogs.list({ limit: 20 });
        const log = page.items.find((item) => item.session_id === sessionId);
        if (log) {
          clearInterval(timer.current);
          setAttempt((current) => current && { ...current, log });
        }
      } catch {
        // A failed poll is retried on the next tick; the limit above ends it.
      }
    }, POLL_INTERVAL_MS);
  };

  const scan = async () => {
    if (!badgeId) return;
    try {
      const response = await api.gates.simulateScan(gateCode.trim(), badgeId);
      const startedAt = Date.now();
      setElapsed(0);
      setAttempt({ sessionId: response.session_id, badgeId, startedAt, log: null, lost: false });
      follow(response.session_id, startedAt);
    } catch (err) {
      push(err.message, "error");
    }
  };

  if (employees.loading || ppeTypes.loading) return <Loading />;
  if (employees.error) return <ErrorNote message={employees.error} onRetry={employees.reload} />;

  return (
    <div>
      <PageHead
        title="Testar portão"
        subtitle="Simula a leitura de um crachá como o leitor do portão faria. Câmera, modelo de visão e regra de decisão rodam de verdade; só o cartão é simulado."
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(280px,360px)_1fr] items-start">
        {/* --- Controls ---------------------------------------------------- */}
        <div className="space-y-4">
        <div className="bg-paper-raised border border-ink-line p-5 space-y-4">
          <Field label="Crachá">
            <Select value={choice} onChange={(e) => setChoice(e.target.value)}>
              {(employees.data || []).map((e) => (
                <option key={e.badge_id} value={e.badge_id}>
                  {e.badge_id} — {e.name}
                  {e.is_active ? "" : " (desativado)"}
                </option>
              ))}
              <option value={OTHER}>Outro crachá…</option>
            </Select>
          </Field>

          {choice === OTHER && (
            <Field label="Identificador" hint="Use um crachá não cadastrado para testar a recusa.">
              <Input
                value={otherBadge}
                onChange={(e) => setOtherBadge(e.target.value)}
                className="font-mono"
                placeholder="A1B2C3D4"
                maxLength={64}
              />
            </Field>
          )}

          {selected && (
            <div className="border-t border-ink-line pt-4">
              <p className="text-sm text-ink-mute">Função</p>
              <p className="text-sm font-medium">{selected.role.name}</p>
              <p className="text-sm text-ink-mute mt-3">A câmera precisa reconhecer</p>
              {selected.role.required_ppe.length === 0 ? (
                <p className="text-sm">Nenhum EPI</p>
              ) : (
                <ul className="flex flex-wrap gap-1.5 mt-1">
                  {selected.role.required_ppe.map((p) => (
                    <li key={p.code}>
                      <Pill tone="neutral">{p.label}</Pill>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <Field label="Portão">
            <Input
              value={gateCode}
              onChange={(e) => setGateCode(e.target.value)}
              className="font-mono"
              maxLength={50}
            />
          </Field>

          <Button onClick={scan} disabled={!badgeId || waiting} className="w-full">
            {waiting ? "Verificando" : "Simular leitura"}
          </Button>
          <p className="text-xs text-ink-mute">
            Posicione-se diante da câmera antes de simular. O mesmo crachá é
            ignorado por alguns segundos após cada leitura.
          </p>
        </div>

        <div className="bg-paper-raised border border-ink-line p-3">
          <p className="text-sm font-medium px-1 pb-2">Câmera do portão</p>
          <CameraFeed compact />
        </div>
        </div>

        {/* --- Result ------------------------------------------------------ */}
        <div>
          {!attempt && (
            <div className="border border-dashed border-ink-line p-10 text-center">
              <p className="text-sm text-ink-mute">
                O resultado da verificação aparece aqui.
              </p>
            </div>
          )}

          {waiting && (
            <div className="bg-paper-raised border border-ink-line p-6">
              <p className="font-display text-2xl font-semibold">Verificando…</p>
              <p className="text-sm text-ink-mute mt-1">
                Crachá <span className="font-mono">{attempt.badgeId}</span> lido.
                Aguardando a câmera e a decisão ({(elapsed / 1000).toFixed(1)} s).
              </p>
            </div>
          )}

          {attempt?.lost && (
            <ErrorNote
              message={`Nenhum registro apareceu em ${FOLLOW_UP_LIMIT_MS / 1000} s. O mesmo crachá pode ter sido lido há pouco e ignorado pela janela de repetição, ou o backend não recebeu a leitura. Aguarde alguns segundos e tente de novo.`}
            />
          )}

          {attempt?.log && <Result log={attempt.log} ppeLabel={ppeLabel} />}
        </div>
      </div>
    </div>
  );
}

function Result({ log, ppeLabel }) {
  const decision = describeDecision(log.decision);
  const granted = log.decision === "granted";

  const detected = new Map(
    (log.detected_ppe || []).map((d) => [d.ppe_code, d.confidence])
  );
  const missing = new Set(log.missing_ppe || []);
  const extras = [...detected.keys()].filter((code) => !log.required_ppe.includes(code));

  return (
    <div className="bg-paper-raised border border-ink-line">
      <div
        className={`px-6 py-5 border-b border-ink-line ${
          granted ? "bg-signal-grantedWash" : decision.tone === "warn" ? "bg-signal-warnWash" : "bg-signal-deniedWash"
        }`}
      >
        <p
          className={`font-display text-3xl font-semibold ${
            granted ? "text-signal-granted" : decision.tone === "warn" ? "text-signal-warn" : "text-signal-denied"
          }`}
        >
          {granted ? "Acesso liberado" : "Acesso negado"}
        </p>
        <p className="text-sm text-ink-soft mt-1">{explainDecision(log, ppeLabel)}</p>
      </div>

      {log.required_ppe.length > 0 && (
        <table className="w-full">
          <thead>
            <tr className="border-b border-ink-line text-left">
              <th className="px-6 py-2.5 text-sm font-medium text-ink-mute">EPI exigido</th>
              <th className="px-6 py-2.5 text-sm font-medium text-ink-mute">Câmera</th>
              <th className="px-6 py-2.5 text-sm font-medium text-ink-mute text-right">Confiança</th>
            </tr>
          </thead>
          <tbody>
            {log.required_ppe.map((code) => {
              const confidence = detected.get(code);
              const absent = missing.has(code);
              return (
                <tr key={code} className="border-b border-ink-line last:border-0">
                  <td className="px-6 py-2.5 text-sm font-medium">{ppeLabel(code)}</td>
                  <td className="px-6 py-2.5">
                    {absent ? (
                      <Pill tone="denied">
                        {confidence === undefined ? "Não reconhecido" : "Confiança baixa"}
                      </Pill>
                    ) : (
                      <Pill tone="granted">Reconhecido</Pill>
                    )}
                  </td>
                  <td className="px-6 py-2.5 text-right text-sm tabular-nums text-ink-mute">
                    {confidence === undefined ? "—" : `${Math.round(confidence * 100)}%`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <div className="px-6 py-4 border-t border-ink-line flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <span className="text-ink-mute">
          Crachá <span className="font-mono text-ink">{log.badge_id}</span>
        </span>
        <span className="text-ink-mute">
          Resultado <span className="text-ink">{decision.label}</span>
        </span>
        {log.latency_ms != null && (
          <span className="text-ink-mute">
            Tempo total <span className="text-ink tabular-nums">{Math.round(log.latency_ms)} ms</span>
          </span>
        )}
        {extras.length > 0 && (
          <span className="text-ink-mute">
            Também reconhecido{" "}
            <span className="text-ink">{extras.map(ppeLabel).join(", ")}</span>
          </span>
        )}
      </div>
    </div>
  );
}
