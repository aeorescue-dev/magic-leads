import { useEffect, useState } from "react";

// Ciclo de vida por fases (1h / 48h / 48h / terminal). O backend devolve
// `stage_expires_at` (prazo da fase em ISO/UTC) e `server_now` (relógio do
// servidor) para corrigir a deriva de relógio entre cliente e servidor.

export type StageKey = "reserved" | "contacted" | "in_negotiation" | "converted";

export const STAGE_ORDER: StageKey[] = ["reserved", "contacted", "in_negotiation", "converted"];

// Deriva de relógio: server_now - client_now. Persistida no módulo para ser
// consistente entre renders/componentes da mesma sessão.
let clockOffsetMs = 0;

export function syncClock(serverNow?: string): number {
  if (!serverNow) return clockOffsetMs;
  const t = Date.parse(serverNow);
  if (Number.isFinite(t)) clockOffsetMs = t - Date.now();
  return clockOffsetMs;
}

export function clockNow(): number {
  return Date.now() + clockOffsetMs;
}

export function stageRemainingMs(expiresAt?: string): number {
  if (!expiresAt) return 0;
  const target = Date.parse(expiresAt);
  if (!Number.isFinite(target)) return 0;
  return Math.max(0, target - clockNow());
}

export type Severity = "normal" | "warning" | "critical";

export function severityFor(ms: number): Severity {
  if (ms <= 60 * 60 * 1000) return "critical";
  if (ms <= 6 * 60 * 60 * 1000) return "warning";
  return "normal";
}

// Formato aprovado: >=1h -> "47h 12m"; <1h -> "59:32"; esgotado -> "00:00".
export function formatStageRemaining(ms: number): string {
  if (ms <= 0) return "00:00";
  const totalSec = Math.floor(ms / 1000);
  if (totalSec >= 3600) {
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    return `${h}h ${String(m).padStart(2, "0")}m`;
  }
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function stageIndex(stage?: StageKey): number {
  if (!stage) return 0;
  const i = STAGE_ORDER.indexOf(stage);
  return i === -1 ? 0 : i;
}

export function useStageCountdown(expiresAt?: string, serverNow?: string) {
  useEffect(() => {
    syncClock(serverNow);
  }, [serverNow]);

  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const remaining = stageRemainingMs(expiresAt);
  return {
    remainingMs: remaining,
    severity: severityFor(remaining),
    text: formatStageRemaining(remaining),
    expired: remaining <= 0,
  };
}