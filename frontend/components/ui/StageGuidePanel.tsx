import { Lock, CheckCircle2 } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { STAGE_ORDER, stageIndex, useStageCountdown } from "@/lib/stage-countdown";
import type { StageKey } from "@/lib/stage-countdown";

const STEP_KIND = {
  active: {
    chip: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    dot: "bg-emerald-400",
    ring: "ring-emerald-400/30",
  },
  next: {
    chip: "bg-sky-500/15 text-sky-400 border-sky-500/25",
    dot: "bg-sky-400",
    ring: "ring-sky-400/25",
  },
  locked: {
    chip: "bg-white/5 text-slate-500 border-white/10",
    dot: "bg-slate-600",
    ring: "",
  },
  done: {
    chip: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    dot: "bg-emerald-400",
    ring: "",
  },
};

const statusLabel: Record<string, string> = {
  active: "dashboard.reserve.active",
  next: "dashboard.reserve.next",
  locked: "dashboard.reserve.locked",
  done: "dashboard.reserve.done",
};

function stepKind(stage: StageKey | undefined, idx: number, isConverted: boolean): "active" | "next" | "locked" | "done" {
  if (isConverted) return "done";
  const current = stageIndex(stage);
  if (idx === current) return "active";
  if (idx === current + 1) return "next";
  if (idx < current) return "done";
  return "locked";
}

export function StageGuidePanel({
  stage,
  stageExpiresAt,
  serverNow,
  isDark,
}: {
  stage?: string;
  stageExpiresAt?: string;
  serverNow?: string;
  isDark?: boolean;
}) {
  const { t } = useI18n();
  const cast = stage as StageKey | undefined;
  const isConverted = stage === "converted";
  const countdown = useStageCountdown(stageExpiresAt, serverNow);

  return (
    <div className={`sticky top-0 z-20 -mx-6 -mt-6 px-6 py-4 border-b backdrop-blur-md ${isDark ? "bg-[#14161d]/95 border-white/10" : "bg-white/95 border-slate-200"}`}>
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
            {t("dashboard.reserve.title")}
          </span>
          {isConverted ? (
            <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-emerald-400">
              <CheckCircle2 className="h-3.5 w-3.5" /> {t("dashboard.reserve.done")}
            </span>
          ) : (
            <span
              data-testid="stage-countdown"
              className={`font-mono text-sm font-bold tabular-nums ${
                countdown.severity === "critical"
                  ? "text-rose-400 animate-pulse"
                  : countdown.severity === "warning"
                    ? "text-amber-400"
                    : "text-emerald-400"
              }`}
              role="timer"
              aria-live={countdown.severity === "critical" ? "assertive" : countdown.severity === "warning" ? "polite" : undefined}
            >
              {countdown.text}
            </span>
          )}
        </div>

        <ol className="flex items-start gap-1" aria-label={t("dashboard.reserve.title")}>
          {STAGE_ORDER.map((key, idx) => {
            const kind = stepKind(cast, idx, isConverted);
            const cls = STEP_KIND[kind];
            return (
              <li key={key} className="flex-1 min-w-0">
                <div className="flex items-center gap-1">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${cls.dot} ${kind === "active" ? "ring-4 animate-pulse" : ""} ${cls.ring}`} />
                  <span className={`text-[10px] font-semibold uppercase tracking-wide truncate ${kind === "locked" ? "text-slate-500" : ""}`}>
                    {t(`dashboard.reserve.step${idx + 1}.title`)}
                  </span>
                  <span className={`ml-auto shrink-0 text-[9px] px-1.5 py-px rounded-full border inline-flex items-center gap-1 font-bold uppercase tracking-wide ${cls.chip}`}>
                    {kind === "locked" && <Lock className="h-2.5 w-2.5" />}
                    {t(statusLabel[kind])}
                  </span>
                </div>
              </li>
            );
          })}
        </ol>

        {!isConverted && (
          <p className={`text-[11px] leading-snug ${countdown.severity === "critical" ? "text-rose-400/90" : countdown.severity === "warning" ? "text-amber-400/90" : "text-slate-400"}`}>
            {t(`dashboard.reserve.step${stageIndex(cast) + 1}.desc`)}
          </p>
        )}
      </div>
    </div>
  );
}