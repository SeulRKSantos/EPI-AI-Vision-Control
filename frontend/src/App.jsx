/**
 * Application shell.
 *
 * The side rail carries a live system indicator: this panel configures a
 * physical gate, and someone editing the matrix should be able to see at a
 * glance whether that gate is actually reachable. A saved change means
 * nothing if the broker is down.
 */

import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import { ToastHost } from "./components/ui";
import { ToastProvider } from "./hooks/useToast";
import AccessLogs from "./pages/AccessLogs";
import Employees from "./pages/Employees";
import Matrix from "./pages/Matrix";
import { PPETypes, Roles } from "./pages/Registries";

const NAV = [
  { to: "/", label: "Matriz de exigências", end: true },
  { to: "/funcionarios", label: "Funcionários" },
  { to: "/funcoes", label: "Funções" },
  { to: "/equipamentos", label: "Equipamentos" },
  { to: "/historico", label: "Histórico de acessos" },
];

export default function App() {
  return (
    <ToastProvider>
      <div className="min-h-screen flex flex-col lg:flex-row">
        <SideRail />
        <main className="flex-1 px-6 py-8 lg:px-10 lg:py-10 max-w-[1400px]">
          <Routes>
            <Route path="/" element={<Matrix />} />
            <Route path="/funcionarios" element={<Employees />} />
            <Route path="/funcoes" element={<Roles />} />
            <Route path="/equipamentos" element={<PPETypes />} />
            <Route path="/historico" element={<AccessLogs />} />
          </Routes>
        </main>
        <ToastHost />
      </div>
    </ToastProvider>
  );
}

function SideRail() {
  return (
    <nav className="lg:w-64 shrink-0 bg-ink text-paper lg:min-h-screen lg:flex lg:flex-col">
      <div className="px-6 py-6 border-b border-white/10">
        <p className="font-display text-[1.6rem] font-semibold leading-none tracking-tight">
          Controle de acesso
        </p>
        <p className="text-sm text-white/55 mt-0.5">Verificação de EPI</p>
      </div>

      <ul className="py-3 lg:flex-1">
        {NAV.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block px-6 py-2.5 text-sm border-l-[3px] transition-colors ${
                  isActive
                    ? "border-teal bg-white/[0.07] text-white font-medium"
                    : "border-transparent text-white/70 hover:text-white hover:bg-white/[0.04]"
                }`
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>

      <SystemStatus />
    </nav>
  );
}

function SystemStatus() {
  const [state, setState] = useState({ status: "checking" });

  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const body = await api.health();
        if (active) setState({ status: "up", checks: body.checks });
      } catch {
        if (active) setState({ status: "down" });
      }
    };
    check();
    const timer = setInterval(check, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  const items =
    state.status === "up"
      ? [
          { label: "Banco de dados", ok: state.checks?.database === "ok" },
          { label: "Portão (MQTT)", ok: state.checks?.mqtt === "ok" },
        ]
      : [];

  return (
    <div className="px-6 py-4 border-t border-white/10">
      {state.status === "checking" && (
        <p className="text-xs text-white/50">Verificando o sistema…</p>
      )}

      {state.status === "down" && (
        <p className="text-xs text-white/80">
          <Dot ok={false} /> Servidor fora do ar
        </p>
      )}

      {state.status === "up" &&
        items.map((item) => (
          <p key={item.label} className="text-xs text-white/70 leading-6">
            <Dot ok={item.ok} /> {item.label}
            {!item.ok && <span className="text-white/50"> — indisponível</span>}
          </p>
        ))}
    </div>
  );
}

function Dot({ ok }) {
  return (
    <span
      aria-hidden
      className="inline-block w-2 h-2 rounded-full mr-2 align-middle"
      style={{ backgroundColor: ok ? "#4CAF7D" : "#C4553F" }}
    />
  );
}
