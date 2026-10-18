/**
 * How each access decision is described to a person.
 *
 * Shared by every screen that shows an outcome, so the gate test and the
 * access history never describe the same decision in two different ways.
 */

export const DECISIONS = {
  granted: { label: "Liberado", tone: "granted" },
  denied_missing_ppe: { label: "EPI faltando", tone: "denied" },
  denied_unknown_badge: { label: "Crachá desconhecido", tone: "denied" },
  denied_inactive_employee: { label: "Crachá desativado", tone: "denied" },
  denied_vision_timeout: { label: "Câmera sem resposta", tone: "warn" },
  denied_internal_error: { label: "Falha interna", tone: "warn" },
};

export function describeDecision(code) {
  return DECISIONS[code] || { label: code, tone: "neutral" };
}

/** One sentence explaining a denial, in terms of what the person can do. */
export function explainDecision(log, ppeLabel) {
  switch (log.decision) {
    case "granted":
      return log.required_ppe.length
        ? "Todos os EPIs exigidos pela função foram reconhecidos."
        : "A função não exige EPI; o crachá foi identificado.";
    case "denied_missing_ppe":
      return `Faltou: ${log.missing_ppe.map(ppeLabel).join(", ")}.`;
    case "denied_unknown_badge":
      return "Este crachá não está cadastrado.";
    case "denied_inactive_employee":
      return "O funcionário ou a função dele está desativado.";
    case "denied_vision_timeout":
      return "O serviço de visão não respondeu a tempo. Verifique se a câmera e o serviço estão no ar.";
    case "denied_internal_error":
      return "Erro interno ao decidir. Consulte os logs do backend.";
    default:
      return "";
  }
}
