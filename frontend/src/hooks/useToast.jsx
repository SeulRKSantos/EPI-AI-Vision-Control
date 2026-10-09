/**
 * Toast notifications.
 *
 * Confirmations use the same verb as the button that triggered them, so the
 * person can see that the change they asked for is the change that landed.
 */

import { createContext, useCallback, useContext, useMemo, useState } from "react";

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (message, tone = "ok") => {
      const id = `${Date.now()}-${Math.random()}`;
      setToasts((current) => [...current, { id, message, tone }]);
      // Errors stay longer: they carry something the person has to read.
      setTimeout(() => dismiss(id), tone === "error" ? 7000 : 4000);
    },
    [dismiss]
  );

  const value = useMemo(() => ({ push, dismiss, toasts }), [push, dismiss, toasts]);
  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast precisa estar dentro de ToastProvider");
  return context;
}
