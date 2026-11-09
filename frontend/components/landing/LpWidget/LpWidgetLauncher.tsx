"use client";

import { MessageCircle } from "lucide-react";

import LpWidgetPanel, { type LpWidgetPanelProps } from "./LpWidgetPanel";

export interface LpWidgetLauncherProps
  extends Omit<LpWidgetPanelProps, "open" | "onClose"> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Canal principal: launcher flutuante, leve e não intrusivo.
 * O painel só existe no DOM quando aberto — zero custo no carregamento da LP.
 */
export default function LpWidgetLauncher({
  open,
  onOpenChange,
  ...panelProps
}: LpWidgetLauncherProps) {
  return (
    <>
      {!open && (
        <button
          type="button"
          onClick={() => onOpenChange(true)}
          aria-label="Talk to a Magic Leads specialist"
          className="fixed bottom-5 right-5 z-[70] flex items-center gap-2.5 rounded-full border border-slate-200 bg-white py-2.5 pl-2.5 pr-4 text-slate-900 shadow-lg shadow-slate-900/10 transition hover:-translate-y-0.5 hover:border-emerald-300 hover:shadow-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 focus-visible:ring-offset-2"
        >
          <span className="relative flex h-9 w-9 items-center justify-center rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100">
            <MessageCircle className="h-4 w-4" />
            <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-emerald-500" />
          </span>
          <span className="hidden text-[12.5px] font-bold sm:inline">
            Talk to a specialist
          </span>
        </button>
      )}

      {open && (
        <LpWidgetPanel
          {...panelProps}
          onClose={() => onOpenChange(false)}
        />
      )}
    </>
  );
}
