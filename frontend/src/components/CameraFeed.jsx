/**
 * The gate camera, as published by the vision service.
 *
 * The stream is MJPEG, which a browser plays in a plain <img>; the boxes are
 * already drawn into the frames on the server. Mounting this component is
 * also what tells the service someone is watching — the live inference that
 * draws the boxes runs only while at least one feed is open, and stops when
 * the last one unmounts.
 */

import { useEffect, useState } from "react";
import { api } from "../api/client";

const RETRY_MS = 3000;

export function CameraFeed({ compact = false }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState("connecting"); // connecting | live | down

  useEffect(() => {
    if (state !== "down") return undefined;
    const timer = setTimeout(() => {
      setState("connecting");
      setAttempt((n) => n + 1);
    }, RETRY_MS);
    return () => clearTimeout(timer);
  }, [state]);

  return (
    <div
      className={`relative bg-ink overflow-hidden ${compact ? "" : "border border-ink-line"}`}
      style={{ aspectRatio: "4 / 3" }}
    >
      <img
        key={attempt}
        src={`${api.vision.streamUrl()}?v=${attempt}`}
        alt="Imagem ao vivo da câmera do portão"
        onLoad={() => setState("live")}
        onError={() => setState("down")}
        className={`absolute inset-0 w-full h-full object-contain ${
          state === "live" ? "" : "opacity-0"
        }`}
      />

      {state !== "live" && (
        <div className="absolute inset-0 flex items-center justify-center p-4 text-center">
          <p className={`text-white/70 ${compact ? "text-xs" : "text-sm"}`}>
            {state === "connecting"
              ? "Conectando à câmera…"
              : "Câmera indisponível. Verifique se o serviço de visão está no ar. Tentando de novo…"}
          </p>
        </div>
      )}

      {state === "live" && (
        <span
          className={`absolute top-2 right-2 inline-flex items-center gap-1.5 bg-ink/70 text-white rounded-sm ${
            compact ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-xs"
          }`}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-[#E5484D]" aria-hidden />
          Ao vivo
        </span>
      )}
    </div>
  );
}

/** Polls the boxes currently drawn on the stream. */
export function useDetections(intervalMs = 1000) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    const tick = async () => {
      try {
        const body = await api.vision.detections();
        if (active) {
          setData(body);
          setError(null);
        }
      } catch (err) {
        if (active) setError(err.message);
      }
    };
    tick();
    const timer = setInterval(tick, intervalMs);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [intervalMs]);

  return { data, error };
}
