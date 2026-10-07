import { X } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { STAGE_ORDER, stageIndex, useStageCountdown } from "@/lib/stage-countdown";
import type { StageKey } from "@/lib/stage-countdown";
import type { LeadResponse } from "@/lib/api-client";

const STEP_CHIP: Record<string, string> = {
  active: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  next: "bg-sky-500/15 text-sky-400 border-sky-500/25",
  locked: "bg-white/5 text-slate-500 border-white/10",
  done: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
};

function stepKind(stage: StageKey | undefined, idx: number, isConverted: boolean): "active" | "next" | "locked" | "done" {
  if (isConverted) return "done";
  const current = stageIndex(stage);
  if (idx === current) return "active";
  if (idx === current + 1) return "next";
  if (idx < current) return "done";
  return "locked";
}

export function ReserveGuideModal({
  lead,
  isDark,
  onClose,
}: {
  lead: LeadResponse & { stage_expires_at?: string; server_now?: string };
  isDark?: boolean;
  onClose: (openAnalytic: boolean) => void;
}) {
  const { t } = useI18n();
  const cast = lead.stage as StageKey | undefined;
  const isConverted = lead.stage === "converted";
  const countdown = useStageCountdown(lead.stage_expires_at, lead.server_now);

  return (
    <div
      className="fixed inset-0 z-[110] flex items-end sm:items-center justify-center sm:p-4"
      style={{ backgroundColor: isDark ? "rgba(11,13,18,0.85)" : "rgba(248,250,252,0.9)" }}
      onClick={() => onClose(false)}
    >
      <div
        className={`w-full sm:max-w-lg max-h-[92vh] overflow-y-auto rounded-t-3xl sm:rounded-2xl border p-6 shadow-2xl space-y-5 animate-scale-in ${
          isDark ? "bg-[#10121a] border-white/10 text-slate-100" : "bg-white border-slate-200 text-slate-900"
        }`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="reserve-guide-title"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-indigo-500/20 text-indigo-400">
              {lead.issue_category}
            </span>
            <h2 id="reserve-guide-title" className="text-base font-bold mt-1.5 truncate">
              {lead.address}
            </h2>
            <p className="text-[11px] text-slate-400 mt-0.5">
              {t("dashboard.reserve.step1.title")} · {t("dashboard.reserve.step1.window")}
            </p>
          </div>
          <button
            onClick={() => onClose(false)}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition"
            aria-label={t("dashboard.reserve.close")}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {!isConverted && (
          <div className={`rounded-xl border p-4 text-center ${isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"}`}>
            <p className="text-[11px] uppercase tracking-wider font-semibold text-slate-400">
              {t("dashboard.reserve.remaining")}
            </p>
            <p
              data-testid="stage-countdown"
              className={`font-mono text-4xl font-bold tabular-nums mt-1 ${
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
            </p>
            <p className={`text-[11px] mt-1.5 ${countdown.severity === "critical" ? "text-rose-400/90" : countdown.severity === "warning" ? "text-amber-400/90" : "text-slate-500"}`}>
              {countdown.severity === "critical"
                ? t("dashboard.reserve.tier_critical")
                : countdown.severity === "warning"
                  ? t("dashboard.reserve.tier_warning")
                  : t("dashboard.reserve.subtitle")}
            </p>
          </div>
        )}

        <ol className="space-y-3">
          {STAGE_ORDER.map((key, idx) => {
            const kind = stepKind(cast, idx, isConverted);
            const active = kind === "active";
            return (
              <li
                key={key}
                className={`flex items-start gap-3 rounded-xl border p-3 transition ${
                  active
                    ? isDark
                      ? "border-emerald-500/30 bg-emerald-500/5"
                      : "border-emerald-500/40 bg-emerald-50"
                    : isDark
                      ? "border-white/5 bg-white/[0.02]"
                      : "border-slate-200 bg-slate-50/50"
                }`}
              >
                <span
                  className={`h-6 w-6 shrink-0 rounded-full flex items-center justify-center text-[11px] font-bold ${
                    active
                      ? "bg-emerald-500 text-white"
                      : kind === "done"
                        ? "bg-emerald-500/30 text-emerald-500"
                        : isDark
                          ? "bg-white/10 text-slate-400"
                          : "bg-slate-200 text-slate-500"
                  }`}
                >
                  {idx + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold">
                      {t(`dashboard.reserve.step${idx + 1}.title`)}
                    </span>
                    <span className="text-[10px] font-medium text-slate-400">
                      {t(`dashboard.reserve.step${idx + 1}.window`)}
                    </span>
                    <span className={`ml-auto text-[9px] px-1.5 py-px rounded-full border font-bold uppercase tracking-wide ${STEP_CHIP[kind]}`}>
                      {t(`dashboard.reserve.${kind}`)}
                    </span>
                  </div>
                  {active && (
                    <p className={`text-[11px] leading-snug mt-1 ${isDark ? "text-slate-300" : "text-slate-600"}`}>
                      {t(`dashboard.reserve.step${idx + 1}.desc`)}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>

        <div className="flex flex-col sm:flex-row gap-2 pt-1">
          <button
            onClick={() => onClose(true)}
            className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold bg-indigo-500 hover:bg-indigo-600 text-white transition"
          >
            {t("dashboard.reserve.open_pipeline")}
          </button>
          <button
            onClick={() => onClose(false)}
            className={`px-4 py-2.5 rounded-xl text-sm font-semibold transition ${isDark ? "bg-white/10 text-slate-300 hover:bg-white/20" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
          >
            {t("dashboard.reserve.close")}
          </button>
        </div>
      </div>
    </div>
  );
}