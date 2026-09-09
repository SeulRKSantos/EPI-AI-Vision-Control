/**
 * PPE type and role registries.
 *
 * The PPE code is the name the vision model outputs; it is shown in a
 * monospaced face and locked after creation, because the detection pipeline
 * matches on it. Renaming would silently stop an item from ever counting as
 * detected.
 */

import { useState } from "react";
import { api } from "../api/client";
import {
  Button,
  Empty,
  ErrorNote,
  Field,
  Input,
  Loading,
  Modal,
  Pill,
} from "../components/ui";
import { useResource } from "../hooks/useResource";
import { useToast } from "../hooks/useToast";
import { PageHead } from "./Matrix";

export function PPETypes() {
  const { push } = useToast();
  const [editing, setEditing] = useState(null);
  const [showInactive, setShowInactive] = useState(false);

  const ppe = useResource(
    () => api.ppeTypes.list({ include_inactive: showInactive }),
    [showInactive]
  );

  const deactivate = async (item) => {
    if (!confirm(`Desativar "${item.label}"? Ele deixa de ser exigido em todas as funções.`))
      return;
    try {
      await api.ppeTypes.deactivate(item.code);
      push(`${item.label} desativado.`);
      ppe.reload();
    } catch (err) {
      push(err.message, "error");
    }
  };

  const reactivate = async (item) => {
    try {
      await api.ppeTypes.update(item.code, { is_active: true });
      push(`${item.label} reativado.`);
      ppe.reload();
    } catch (err) {
      push(err.message, "error");
    }
  };

  return (
    <div>
      <PageHead
        title="Equipamentos"
        subtitle="Os itens que a câmera sabe reconhecer. O código precisa ser o mesmo que o modelo de visão devolve."
        action={<Button onClick={() => setEditing("new")}>Adicionar equipamento</Button>}
      />

      <label className="inline-flex items-center gap-2 mb-4 text-sm text-ink-soft">
        <input
          type="checkbox"
          checked={showInactive}
          onChange={(e) => setShowInactive(e.target.checked)}
          className="accent-teal"
        />
        Mostrar desativados
      </label>

      {ppe.loading ? (
        <Loading />
      ) : ppe.error ? (
        <ErrorNote message={ppe.error} onRetry={ppe.reload} />
      ) : !ppe.data?.length ? (
        <Empty
          message="Nenhum equipamento cadastrado."
          action={<Button onClick={() => setEditing("new")}>Adicionar o primeiro</Button>}
        />
      ) : (
        <div className="bg-paper-raised border border-ink-line">
          <table className="w-full">
            <thead>
              <tr className="border-b-2 border-ink-line text-left">
                <th className="px-4 py-2.5 text-sm font-medium text-ink-mute">Código</th>
                <th className="px-4 py-2.5 text-sm font-medium text-ink-mute">Equipamento</th>
                <th className="px-4 py-2.5 text-sm font-medium text-ink-mute">Descrição</th>
                <th className="px-4 py-2.5 text-sm font-medium text-ink-mute text-right">
                  Ações
                </th>
              </tr>
            </thead>
            <tbody>
              {ppe.data.map((item) => (
                <tr key={item.code} className="border-b border-ink-line last:border-0">
                  <td className="px-4 py-2.5">
                    <span className="font-mono text-sm">{item.code}</span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-sm font-medium">{item.label}</span>
                    {!item.is_active && (
                      <span className="ml-2">
                        <Pill tone="denied">Desativado</Pill>
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-sm text-ink-mute">{item.description || "—"}</span>
                  </td>
                  <td className="px-4 py-2.5 text-right whitespace-nowrap">
                    <Button tone="quiet" className="px-2.5 py-1" onClick={() => setEditing(item)}>
                      Editar
                    </Button>{" "}
                    {item.is_active ? (
                      <Button
                        tone="danger"
                        className="px-2.5 py-1"
                        onClick={() => deactivate(item)}
                      >
                        Desativar
                      </Button>
                    ) : (
                      <Button
                        tone="quiet"
                        className="px-2.5 py-1"
                        onClick={() => reactivate(item)}
                      >
                        Reativar
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <PPEForm
        target={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          ppe.reload();
        }}
      />
    </div>
  );
}

function PPEForm({ target, onClose, onSaved }) {
  const { push } = useToast();
  const isNew = target === "new";
  const item = isNew ? null : target;

  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(false);

  const key = isNew ? "new" : item?.code;
  const [lastKey, setLastKey] = useState(null);
  if (key !== lastKey) {
    setLastKey(key);
    setForm({
      code: item?.code || "",
      label: item?.label || "",
      description: item?.description || "",
    });
  }

  if (!target) return null;

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      if (isNew) {
        await api.ppeTypes.create({
          code: form.code.trim(),
          label: form.label.trim(),
          description: form.description.trim() || null,
        });
        push(`${form.label} adicionado.`);
      } else {
        await api.ppeTypes.update(item.code, {
          label: form.label.trim(),
          description: form.description.trim() || null,
        });
        push(`${form.label} atualizado.`);
      }
      onSaved();
    } catch (err) {
      push(err.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  return (
    <Modal
      open
      onClose={onClose}
      title={isNew ? "Adicionar equipamento" : `Editar ${item.label}`}
    >
      <form onSubmit={submit} className="space-y-4">
        <Field
          label="Código"
          hint={
            isNew
              ? "Precisa ser idêntico ao nome da classe no modelo de visão. Ex.: helmet, goggles."
              : "O código não pode ser alterado: o modelo de visão identifica o equipamento por ele."
          }
        >
          <Input
            value={form.code}
            onChange={set("code")}
            disabled={!isNew}
            required
            maxLength={50}
            pattern="[a-z0-9_]+"
            title="Apenas letras minúsculas, números e underscore"
            className="font-mono"
            placeholder="helmet"
          />
        </Field>

        <Field label="Nome" hint="Como aparece nas telas e nos avisos do portão.">
          <Input value={form.label} onChange={set("label")} required maxLength={120} />
        </Field>

        <Field label="Descrição" hint="Opcional.">
          <Input value={form.description} onChange={set("description")} maxLength={300} />
        </Field>

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" tone="quiet" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "Salvando" : isNew ? "Adicionar" : "Salvar"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/* --- Roles -------------------------------------------------------------- */

export function Roles() {
  const { push } = useToast();
  const [creating, setCreating] = useState(false);
  const roles = useResource(() => api.roles.list({ include_inactive: true }), []);

  const [form, setForm] = useState({ code: "", name: "", description: "" });
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      await api.roles.create({
        code: form.code.trim(),
        name: form.name.trim(),
        description: form.description.trim() || null,
        required_ppe: [],
      });
      push(`${form.name} criada. Marque os EPIs na matriz.`);
      setForm({ code: "", name: "", description: "" });
      setCreating(false);
      roles.reload();
    } catch (err) {
      push(err.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  return (
    <div>
      <PageHead
        title="Funções"
        subtitle="Cada funcionário tem uma função, e é ela que define a lista de EPIs exigidos no portão."
        action={<Button onClick={() => setCreating(true)}>Criar função</Button>}
      />

      {roles.loading ? (
        <Loading />
      ) : roles.error ? (
        <ErrorNote message={roles.error} onRetry={roles.reload} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(roles.data || []).map((role) => (
            <div key={role.code} className="bg-paper-raised border border-ink-line p-4">
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="font-display text-xl font-semibold">{role.name}</h2>
                {!role.is_active && <Pill tone="denied">Desativada</Pill>}
              </div>
              <p className="font-mono text-xs text-ink-mute">{role.code}</p>
              {role.description && (
                <p className="text-sm text-ink-mute mt-2">{role.description}</p>
              )}
              <div className="mt-3 pt-3 border-t border-ink-line">
                {role.required_ppe.length === 0 ? (
                  <p className="text-sm text-ink-mute">Não exige EPI</p>
                ) : (
                  <ul className="flex flex-wrap gap-1.5">
                    {role.required_ppe.map((p) => (
                      <li key={p.code}>
                        <Pill tone="neutral">{p.label}</Pill>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal open={creating} onClose={() => setCreating(false)} title="Criar função">
        <form onSubmit={submit} className="space-y-4">
          <Field label="Código" hint="Sem espaços. Ex.: electrician, chemist.">
            <Input
              value={form.code}
              onChange={set("code")}
              required
              maxLength={50}
              pattern="[a-z0-9_]+"
              title="Apenas letras minúsculas, números e underscore"
              className="font-mono"
            />
          </Field>
          <Field label="Nome">
            <Input value={form.name} onChange={set("name")} required maxLength={120} />
          </Field>
          <Field label="Descrição" hint="Opcional.">
            <Input value={form.description} onChange={set("description")} maxLength={300} />
          </Field>
          <p className="text-sm text-ink-mute">
            A função é criada sem exigências. Os EPIs são marcados na matriz.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" tone="quiet" onClick={() => setCreating(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Criando" : "Criar"}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
