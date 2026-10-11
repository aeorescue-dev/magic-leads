"use client";

import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { SlidersHorizontal } from "lucide-react";

const DISMISSED_KEY = "garimpador.interests.nudge.dismissed";

export function InterestsNudgeBanner({
  show,
  onSetup,
}: {
  show: boolean;
  onSetup: () => void;
}) {
  const { t } = useI18n();
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem(DISMISSED_KEY) === "1") setDismissed(true);
    } catch {
      /* storage indisponível (ex.: modo privado) */
    }
  }, []);

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      /* ignore */
    }
    setDismissed(true);
  };

  if (!show || dismissed) return null;

  return (
    <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 rounded-2xl border border-indigo-500/30 bg-indigo-500/10 px-4 py-3">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-indigo-500/20 p-2">
          <SlidersHorizontal className="h-5 w-5 text-indigo-400" />
        </div>
        <div>
          <p className="text-sm font-semibold text-indigo-300">
            {t("dashboard.nudge.interests.title")}
          </p>
          <p className="text-xs text-indigo-400/80 mt-0.5 max-w-md">
            {t("dashboard.nudge.interests.body")}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 sm:ml-auto shrink-0">
        <button
          onClick={dismiss}
          className="px-3 py-1.5 rounded-lg text-xs font-medium text-indigo-400/80 hover:text-indigo-300 transition"
        >
          {t("dashboard.nudge.interests.dismiss")}
        </button>
        <button
          onClick={onSetup}
          className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-indigo-500 text-white hover:bg-indigo-400 transition"
        >
          {t("dashboard.nudge.interests.cta")}
        </button>
      </div>
    </div>
  );
}

export default InterestsNudgeBanner;
