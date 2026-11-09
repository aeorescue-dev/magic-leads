"use client";

import { ArrowRight, MessageCircle } from "lucide-react";

export interface LpWidgetInlineProps {
  onOpen: () => void;
  className?: string;
}

/**
 * Âncora inline opcional. É uma faixa clara, com uma única linha de copy e um
 * botão — não um segundo widget embutido. O launcher flutuante continua a ser
 * o canal principal.
 */
export default function LpWidgetInline({
  onOpen,
  className = "",
}: LpWidgetInlineProps) {
  return (
    <div
      className={`flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm shadow-slate-900/[0.03] sm:flex-row sm:items-center sm:justify-between ${className}`}
    >
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100">
          <MessageCircle className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-slate-900">
            Questions about leads in your city?
          </p>
          <p className="mt-0.5 text-[11.5px] leading-snug text-slate-500">
            Talk to a specialist. Real answers, no pressure.
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={onOpen}
        className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-[11.5px] font-bold text-slate-900 transition hover:border-emerald-300 hover:bg-emerald-50/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 focus-visible:ring-offset-2"
      >
        Start chat
        <ArrowRight className="h-3.5 w-3.5 text-emerald-600" />
      </button>
    </div>
  );
}
