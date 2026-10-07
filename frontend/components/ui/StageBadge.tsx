import { Clock } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { useStageCountdown, StageKey } from "@/lib/stage-countdown";

const severityCls: Record<string, string> = {
  normal: "bg-indigo-500/15 text-indigo-400 border-indigo-500/20",
  warning: "bg-amber-500/15 text-amber-400 border-amber-500/25",
  critical: "bg-rose-500/15 text-rose-400 border-rose-500/30 animate-pulse",
};

const stageLabelKey: Record<StageKey, string> = {
  reserved: "dashboard.stage.reserved",
  contacted: "dashboard.stage.contacted",
  in_negotiation: "dashboard.stage.in_negotiation",
  converted: "dashboard.stage.converted",
};

export function StageBadge({
  stage,
  stageExpiresAt,
  serverNow,
}: {
  stage?: string;
  stageExpiresAt?: string;
  serverNow?: string;
}) {
  const { t } = useI18n();
  const countdown = useStageCountdown(stageExpiresAt, serverNow);
  if (!stage || stage === "converted") return null;
  const label = stageLabelKey[stage as StageKey] ?? "dashboard.stage.reserved";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${severityCls[countdown.severity]}`}
      role="timer"
    >
      <Clock className="h-3 w-3" />
      {t(label)} · {countdown.text}
    </span>
  );
}