/**
 * The requirement matrix.
 *
 * This is the configuration the whole system turns on: every badge scan is
 * decided by reading a row of this grid. It is presented as a grid rather
 * than as one form per role because the useful question is comparative —
 * "who needs a respirator?" reads down a column, and a role missing an
 * obvious item stands out against its neighbours.
 *
 * Edits are staged locally and saved per role. Nothing reaches the gate
 * until the row is saved, so a half-finished thought never becomes policy.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { Button, ErrorNote, Loading } from "../components/ui";
import { useResource } from "../hooks/useResource";
import { useToast } from "../hooks/useToast";

export default function Matrix() {
  const { push } = useToast();

  const roles = useResource(() => api.roles.list(), []);
  const ppeTypes = useResource(() => api.ppeTypes.list(), []);

  // roleCode -> Set of ppe codes, as edited on screen.
  const [draft, setDraft] = useState({});
  const [saving, setSaving] = useState(null);

  useEffect(() => {
    if (!roles.data) return;
    const next = {};
    roles.data.forEach((role) => {
      next[role.code] = new Set(role.required_ppe.map((p) => p.code));
    });
    setDraft(next);
  }, [roles.data]);

  const savedSets = useMemo(() => {
    const map = {};
    (roles.data || []).forEach((role) => {
      map[role.code] = new Set(role.required_ppe.map((p) => p.code));
    });
    return map;
  }, [roles.data]);

  const isDirty = (roleCode) => {
    const saved = savedSets[roleCode];
    const current = draft[roleCode];
    if (!saved || !current) return false;
    if (saved.size !== current.size) return true;
    return [...current].some((code) => !saved.has(code));
  };

  const toggle = (roleCode, ppeCode) => {
    setDraft((current) => {
      const next = new Set(current[roleCode]);
      next.has(ppeCode) ? next.delete(ppeCode) : next.add(ppeCode);
      return { ...current, [roleCode]: next };
    });
  };

  const save = async (roleCode) => {
    setSaving(roleCode);
    try {
      await api.roles.setRequirements(roleCode, [...draft[roleCode]]);
      push(`Exigências de ${roleCode} salvas.`);
      await roles.reload();
    } catch (err) {
      push(err.message, "error");
    } finally {
      setSaving(null);
    }
  };

  const discard = (roleCode) => {
    setDraft((current) => ({ ...current, [roleCode]: new Set(savedSets[roleCode]) }));
  };

  if (roles.loading || ppeTypes.loading) return <Loading />;
  if (roles.error) return <ErrorNote message={roles.error} onRetry={roles.reload} />;
  if (ppeTypes.error) return <ErrorNote message={ppeTypes.error} onRetry={ppeTypes.reload} />;

  const items = ppeTypes.data || [];
  const list = roles.data || [];

  return (
    <div>
      <PageHead
        title="Matriz de exigências"
        subtitle="Marque os EPIs que cada função precisa usar para ter o acesso liberado. As mudanças valem para a próxima leitura de crachá."
      />

      <div className="bg-paper-raised border border-ink-line overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="sticky left-0 bg-paper-raised text-left align-bottom px-4 py-3 border-b-2 border-ink-line min-w-[190px]">
                <span className="font-display text-lg font-semibold">Função</span>
              </th>
              {items.map((ppe) => (
                <th
                  key={ppe.code}
                  className="border-b-2 border-ink-line border-l border-ink-line/60 px-1 py-3 align-bottom"
                >
                  <div className="h-44 flex items-end justify-center">
                    <span
                      className="font-display text-base font-medium whitespace-nowrap text-ink-soft"
                      style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }}
                      title={ppe.description || ppe.label}
                    >
                      {ppe.label}
                    </span>
                  </div>
                </th>
              ))}
              <th className="border-b-2 border-ink-line px-4 py-3 align-bottom text-right min-w-[150px]">
                <span className="text-sm font-medium text-ink-mute">Alterações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {list.map((role) => {
              const dirty = isDirty(role.code);
              const marked = draft[role.code] || new Set();
              return (
                <tr key={role.code} className={dirty ? "bg-signal-warnWash/50" : ""}>
                  <th
                    scope="row"
                    className={`sticky left-0 text-left px-4 py-2.5 border-b border-ink-line font-normal
                      ${dirty ? "bg-signal-warnWash" : "bg-paper-raised"}`}
                  >
                    <span className="block text-sm font-medium text-ink">{role.name}</span>
                    <span className="block font-mono text-xs text-ink-mute">{role.code}</span>
                  </th>

                  {items.map((ppe) => {
                    const on = marked.has(ppe.code);
                    return (
                      <td
                        key={ppe.code}
                        className="border-b border-l border-ink-line/60 p-0 text-center"
                      >
                        <button
                          onClick={() => toggle(role.code, ppe.code)}
                          aria-pressed={on}
                          aria-label={`${ppe.label} para ${role.name}`}
                          className={`w-full h-11 transition-colors
                            ${on ? "bg-teal-wash hover:bg-teal-wash/70" : "hover:bg-paper-sunk"}`}
                        >
                          <span
                            className={`inline-block w-4 h-4 border-2 rounded-[2px]
                              ${on ? "bg-teal border-teal" : "border-ink-line bg-paper-raised"}`}
                          >
                            {on && (
                              <svg viewBox="0 0 16 16" className="w-full h-full text-white">
                                <path
                                  d="M3 8.5l3.2 3.2L13 5"
                                  fill="none"
                                  stroke="currentColor"
                                  strokeWidth="2.5"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                              </svg>
                            )}
                          </span>
                        </button>
                      </td>
                    );
                  })}

                  <td className="border-b border-ink-line px-3 py-2 text-right whitespace-nowrap">
                    {dirty ? (
                      <div className="flex gap-2 justify-end">
                        <Button
                          tone="quiet"
                          onClick={() => discard(role.code)}
                          className="px-2.5 py-1"
                        >
                          Desfazer
                        </Button>
                        <Button
                          onClick={() => save(role.code)}
                          disabled={saving === role.code}
                          className="px-2.5 py-1"
                        >
                          {saving === role.code ? "Salvando" : "Salvar"}
                        </Button>
                      </div>
                    ) : (
                      <span className="text-xs text-ink-mute">
                        {marked.size === 0 ? "Sem exigência" : `${marked.size} EPIs`}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-sm text-ink-mute mt-4 max-w-[65ch]">
        Uma função sem nenhum EPI marcado libera o acesso assim que o crachá é
        identificado. É o caso do pessoal de escritório.
      </p>
    </div>
  );
}

export function PageHead({ title, subtitle, action }) {
  return (
    <div className="flex items-start justify-between gap-6 mb-6">
      <div>
        <h1 className="font-display text-3xl font-semibold text-ink">{title}</h1>
        {subtitle && (
          <p className="text-sm text-ink-mute mt-1 max-w-[70ch]">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}
