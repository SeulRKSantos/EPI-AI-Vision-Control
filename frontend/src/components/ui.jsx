/**
 * Shared interface pieces.
 *
 * Kept in one file because each is small and they are always used together;
 * splitting them would mean five imports on every screen.
 */

import { useEffect, useRef } from "react";
import { useToast } from "../hooks/useToast";

/* --- Buttons ----------------------------------------------------------- */

const BUTTON_TONES = {
  primary: "bg-teal text-white hover:bg-teal-deep disabled:bg-ink-mute",
  quiet: "bg-transparent text-ink-soft hover:bg-paper-sunk border border-ink-line",
  danger: "bg-transparent text-signal-denied hover:bg-signal-deniedWash border border-signal-denied",
};

export function Button({ tone = "primary", className = "", ...props }) {
  return (
    <button
      className={`px-4 py-2 rounded-sm text-sm font-medium transition-colors
        disabled:cursor-not-allowed disabled:opacity-60 ${BUTTON_TONES[tone]} ${className}`}
      {...props}
    />
  );
}

/* --- Form fields -------------------------------------------------------- */

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-ink-soft mb-1.5">{label}</span>
      {children}
      {hint && <span className="block text-xs text-ink-mute mt-1">{hint}</span>}
    </label>
  );
}

const INPUT = `w-full px-3 py-2 rounded-sm border border-ink-line bg-paper-raised
  text-sm text-ink placeholder:text-ink-mute focus:border-teal`;

export function Input({ className = "", ...props }) {
  return <input className={`${INPUT} ${className}`} {...props} />;
}

export function Select({ className = "", children, ...props }) {
  return (
    <select className={`${INPUT} ${className}`} {...props}>
      {children}
    </select>
  );
}

/* --- Modal -------------------------------------------------------------- */

export function Modal({ open, title, onClose, children }) {
  const panel = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/40 p-4 pt-20"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-lg bg-paper-raised border border-ink-line shadow-lg outline-none"
      >
        <header className="px-5 py-3 border-b border-ink-line">
          <h2 className="font-display text-xl font-semibold">{title}</h2>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

/* --- Feedback states ---------------------------------------------------- */

export function Loading({ label = "Carregando" }) {
  return <p className="text-sm text-ink-mute py-8">{label}…</p>;
}

export function ErrorNote({ message, onRetry }) {
  return (
    <div className="border-l-4 border-signal-denied bg-signal-deniedWash px-4 py-3 my-4">
      <p className="text-sm text-ink">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="text-sm text-teal-deep underline mt-1.5 font-medium"
        >
          Tentar novamente
        </button>
      )}
    </div>
  );
}

export function Empty({ message, action }) {
  return (
    <div className="py-12 text-center">
      <p className="text-sm text-ink-mute">{message}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

/* --- Toast host --------------------------------------------------------- */

const TOAST_TONES = {
  ok: "border-signal-granted bg-signal-grantedWash",
  error: "border-signal-denied bg-signal-deniedWash",
};

export function ToastHost() {
  const { toasts, dismiss } = useToast();
  if (!toasts.length) return null;

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 w-80">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className={`border-l-4 px-4 py-3 shadow-md text-sm ${TOAST_TONES[toast.tone]}`}
        >
          <div className="flex items-start justify-between gap-3">
            <span>{toast.message}</span>
            <button
              onClick={() => dismiss(toast.id)}
              aria-label="Fechar aviso"
              className="text-ink-mute hover:text-ink leading-none"
            >
              ×
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

/* --- Status pill -------------------------------------------------------- */

export function Pill({ tone, children }) {
  const tones = {
    granted: "bg-signal-grantedWash text-signal-granted",
    denied: "bg-signal-deniedWash text-signal-denied",
    warn: "bg-signal-warnWash text-signal-warn",
    neutral: "bg-paper-sunk text-ink-mute",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded-sm text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}
