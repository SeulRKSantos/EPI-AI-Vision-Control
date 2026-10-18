/**
 * Gate view.
 *
 * The camera as the model sees it. Next to the picture, the same detections
 * as a list — readable at a glance, and the only place where a class the
 * system ignores (a distractor such as the eye make-up class) is named
 * rather than just drawn in grey.
 */

import { api } from "../api/client";
import { CameraFeed, useDetections } from "../components/CameraFeed";
import { Pill } from "../components/ui";
import { useResource } from "../hooks/useResource";
import { PageHead } from "./Matrix";

export default function CameraView() {
  const ppeTypes = useResource(() => api.ppeTypes.list({ include_inactive: true }), []);
  const { data, error } = useDetections(1000);

  const ppeLabel = (code) =>
    (ppeTypes.data || []).find((p) => p.code === code)?.label || code;

  return (
    <div>
      <PageHead
        title="Visão do portão"
        subtitle="O que a câmera do portão está vendo agora, com os equipamentos reconhecidos pelo modelo."
      />

      <div className="grid gap-6 xl:grid-cols-[1fr_340px] items-start">
        <CameraFeed />

        <aside className="bg-paper-raised border border-ink-line">
          <header className="px-5 py-4 border-b border-ink-line">
            <h2 className="font-display text-xl font-semibold">Reconhecido agora</h2>
            <SourceLine data={data} error={error} />
          </header>

          <DetectionList data={data} error={error} ppeLabel={ppeLabel} />

          <footer className="px-5 py-4 border-t border-ink-line space-y-1.5">
            <Legend color="#32AA3C" text="Reconhecido com confiança suficiente" />
            <Legend color="#E1A514" text="Visto, mas com confiança baixa" />
            <Legend color="#969696" text="Ignorado: não é EPI da matriz" />
            {data && data.live_enabled && (
              <p className="text-xs text-ink-mute pt-2">
                O modelo roda a cada {data.interval_s} s enquanto esta tela está
                aberta, e para quando ela fecha. Cada análise consome a cota do
                serviço de visão.
              </p>
            )}
            {data && !data.live_enabled && (
              <p className="text-xs text-ink-mute pt-2">
                Análise ao vivo desligada. As caixas aparecem só quando um crachá é lido.
              </p>
            )}
          </footer>
        </aside>
      </div>
    </div>
  );
}

function SourceLine({ data, error }) {
  if (error) return <p className="text-sm text-signal-denied mt-0.5">Serviço de visão indisponível.</p>;
  if (!data) return <p className="text-sm text-ink-mute mt-0.5">Conectando…</p>;
  if (data.error) return <p className="text-sm text-signal-warn mt-0.5">Falha na análise: {data.error}</p>;
  if (!data.fresh) return <p className="text-sm text-ink-mute mt-0.5">Aguardando a próxima análise…</p>;

  const origin = data.source === "scan" ? "Leitura de crachá" : "Análise ao vivo";
  return (
    <p className="text-sm text-ink-mute mt-0.5">
      {origin} · há {data.age_s.toFixed(1)} s · {Math.round(data.latency_ms)} ms
    </p>
  );
}

export function DetectionList({ data, error, ppeLabel, compact = false }) {
  if (error || !data) return null;

  if (!data.boxes.length) {
    return (
      <p className={`text-sm text-ink-mute ${compact ? "py-2" : "px-5 py-6"}`}>
        {data.fresh ? "Nenhum item reconhecido." : "Sem análise recente."}
      </p>
    );
  }

  const sorted = [...data.boxes].sort((a, b) => {
    const rank = (box) => (box.accepted ? 0 : box.ppe_code ? 1 : 2);
    return rank(a) - rank(b) || b.confidence - a.confidence;
  });

  return (
    <ul className={compact ? "space-y-1.5" : "divide-y divide-ink-line"}>
      {sorted.map((box, index) => (
        <li
          key={`${box.class_name}-${index}`}
          className={`flex items-center justify-between gap-3 ${compact ? "" : "px-5 py-2.5"}`}
        >
          <div className="min-w-0">
            <p className={`text-sm ${box.ppe_code ? "font-medium" : "text-ink-mute"}`}>
              {box.ppe_code ? ppeLabel(box.ppe_code) : box.class_name}
            </p>
            {!compact && (
              <p className="text-xs text-ink-mute">
                {box.ppe_code ? `classe do modelo: ${box.class_name}` : "não conta como EPI"}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-sm tabular-nums text-ink-mute">
              {Math.round(box.confidence * 100)}%
            </span>
            {box.accepted ? (
              <Pill tone="granted">Ok</Pill>
            ) : box.ppe_code ? (
              <Pill tone="warn">Baixa</Pill>
            ) : (
              <Pill tone="neutral">Ignorado</Pill>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

function Legend({ color, text }) {
  return (
    <p className="flex items-center gap-2 text-xs text-ink-soft">
      <span className="inline-block w-3 h-3 rounded-[2px]" style={{ backgroundColor: color }} aria-hidden />
      {text}
    </p>
  );
}
