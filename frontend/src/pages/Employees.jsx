/**
 * Employee and badge management.
 *
 * The badge identifier is the key the gate reads, so it is shown in a
 * monospaced face and in the reader's own format (uppercase hex). It can be
 * changed to hand someone a different card: access history is linked to the
 * person, and each past record keeps the badge that was actually used.
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
  Select,
} from "../components/ui";
import { useResource } from "../hooks/useResource";
import { useToast } from "../hooks/useToast";
import { PageHead } from "./Matrix";

export default function Employees() {
  const { push } = useToast();
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState(null); // employee | "new" | null

  const employees = useResource(
    () => api.employees.list({ include_inactive: showInactive }),
    [showInactive]
  );
  const roles = useResource(() => api.roles.list(), []);

  const deactivate = async (employee) => {
    if (!confirm(`Desativar o crachá de ${employee.name}? O acesso passa a ser negado.`))
      return;
    try {
      await api.employees.deactivate(employee.badge_id);
      push(`${employee.name} desativado.`);
      employees.reload();
    } catch (err) {
      push(err.message, "error");
    }
  };

  const reactivate = async (employee) => {
    try {
      await api.employees.update(employee.badge_id, { is_active: true });
      push(`${employee.name} reativado.`);
      employees.reload();
    } catch (err) {
      push(err.message, "error");
    }
  };

  return (
    <div>
      <PageHead
        title="Funcionários"
        subtitle="Cada crachá é vinculado a uma função, e é a função que determina quais EPIs serão exigidos no portão."
        action={<Button onClick={() => setEditing("new")}>Cadastrar funcionário</Button>}
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

      {employees.loading ? (
        <Loading />
      ) : employees.error ? (
        <ErrorNote message={employees.error} onRetry={employees.reload} />
      ) : !employees.data?.length ? (
        <Empty
          message="Nenhum funcionário cadastrado."
          action={<Button onClick={() => setEditing("new")}>Cadastrar o primeiro</Button>}
        />
      ) : (
        <div className="bg-paper-raised border border-ink-line">
          <table className="w-full">
            <thead>
              <tr className="border-b-2 border-ink-line text-left">
                <Th>Crachá</Th>
                <Th>Nome</Th>
                <Th>Matrícula</Th>
                <Th>Função</Th>
                <Th>EPIs exigidos</Th>
                <Th className="text-right">Ações</Th>
              </tr>
            </thead>
            <tbody>
              {employees.data.map((employee) => (
                <tr key={employee.badge_id} className="border-b border-ink-line last:border-0">
                  <Td>
                    <span className="font-mono text-sm">{employee.badge_id}</span>
                  </Td>
                  <Td>
                    <span className="text-sm font-medium">{employee.name}</span>
                    {!employee.is_active && (
                      <span className="ml-2">
                        <Pill tone="denied">Desativado</Pill>
                      </span>
                    )}
                  </Td>
                  <Td>
                    <span className="text-sm text-ink-mute">{employee.registration || "—"}</span>
                  </Td>
                  <Td>
                    <span className="text-sm">{employee.role.name}</span>
                  </Td>
                  <Td>
                    {employee.role.required_ppe.length === 0 ? (
                      <span className="text-sm text-ink-mute">Nenhum</span>
                    ) : (
                      <span className="text-sm text-ink-soft">
                        {employee.role.required_ppe.map((p) => p.label).join(", ")}
                      </span>
                    )}
                  </Td>
                  <Td className="text-right whitespace-nowrap">
                    <Button tone="quiet" className="px-2.5 py-1" onClick={() => setEditing(employee)}>
                      Editar
                    </Button>{" "}
                    {employee.is_active ? (
                      <Button
                        tone="danger"
                        className="px-2.5 py-1"
                        onClick={() => deactivate(employee)}
                      >
                        Desativar
                      </Button>
                    ) : (
                      <Button
                        tone="quiet"
                        className="px-2.5 py-1"
                        onClick={() => reactivate(employee)}
                      >
                        Reativar
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <EmployeeForm
        target={editing}
        roles={roles.data || []}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          employees.reload();
        }}
      />
    </div>
  );
}

function EmployeeForm({ target, roles, onClose, onSaved }) {
  const { push } = useToast();
  const isNew = target === "new";
  const employee = isNew ? null : target;

  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(false);

  // Reset the fields whenever a different target opens the dialog.
  const key = isNew ? "new" : employee?.badge_id;
  const [lastKey, setLastKey] = useState(null);
  if (key !== lastKey) {
    setLastKey(key);
    setForm({
      badge_id: employee?.badge_id || "",
      name: employee?.name || "",
      registration: employee?.registration || "",
      role_code: employee?.role?.code || roles[0]?.code || "",
    });
  }

  if (!target) return null;

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      if (isNew) {
        await api.employees.create({
          badge_id: form.badge_id.trim(),
          name: form.name.trim(),
          registration: form.registration.trim() || null,
          role_code: form.role_code,
        });
        push(`${form.name} cadastrado.`);
      } else {
        const newBadge = form.badge_id.trim().toUpperCase();
        const changes = {
          name: form.name.trim(),
          registration: form.registration.trim() || null,
          role_code: form.role_code,
        };
        if (newBadge !== employee.badge_id) changes.badge_id = newBadge;
        await api.employees.update(employee.badge_id, changes);
        push(
          changes.badge_id
            ? `${form.name} atualizado. Crachá trocado para ${newBadge}.`
            : `${form.name} atualizado.`
        );
      }
      onSaved();
    } catch (err) {
      push(
        err.status === 409
          ? `O cartão ${form.badge_id.trim().toUpperCase()} já está cadastrado para outro funcionário.`
          : err.message,
        "error"
      );
    } finally {
      setBusy(false);
    }
  };

  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value });
  const badgeChanged =
    !isNew && form.badge_id.trim() !== "" && form.badge_id.trim() !== employee.badge_id;

  return (
    <Modal
      open
      onClose={onClose}
      title={isNew ? "Cadastrar funcionário" : `Editar ${employee.name}`}
    >
      <form onSubmit={submit} className="space-y-4">
        <Field
          label="Crachá"
          hint={
            isNew
              ? "Identificador lido pelo leitor RFID no portão."
              : badgeChanged
                ? `O cartão ${employee.badge_id} deixa de funcionar ao salvar. O histórico continua ligado a este funcionário.`
                : "Para entregar outro cartão, digite o novo identificador."
          }
        >
          <Input
            value={form.badge_id}
            onChange={(event) => setForm({ ...form, badge_id: event.target.value.toUpperCase() })}
            required
            maxLength={64}
            className="font-mono"
            placeholder="BADGE001"
          />
        </Field>

        <Field label="Nome">
          <Input value={form.name} onChange={set("name")} required maxLength={150} />
        </Field>

        <Field label="Matrícula" hint="Opcional.">
          <Input value={form.registration} onChange={set("registration")} maxLength={50} />
        </Field>

        <Field label="Função" hint="Define os EPIs que serão exigidos.">
          <Select value={form.role_code} onChange={set("role_code")} required>
            {roles.map((role) => (
              <option key={role.code} value={role.code}>
                {role.name}
                {role.required_ppe.length === 0 ? " — sem exigência" : ""}
              </option>
            ))}
          </Select>
        </Field>

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" tone="quiet" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "Salvando" : isNew ? "Cadastrar" : "Salvar"}
          </Button>
        </div>
      </form>
    </Modal>
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
