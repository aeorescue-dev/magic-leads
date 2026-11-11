"use client";

import { Building2, Clock, Layers, ShieldCheck } from "lucide-react";

export function HeroLeadPanel({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="relative w-full max-w-[540px] lg:justify-self-end">
      <div className="rounded-[1.6rem] border border-[#e8e4da] bg-white p-2 shadow-[0_34px_90px_-58px_rgba(15,23,42,0.45)]">
        <div className="rounded-[1.2rem] border border-[#f0ece3] bg-[#fdfcf9]">
          <div className="flex items-center justify-between border-b border-[#f0ece3] px-5 py-4">
            <div className="flex items-center gap-2.5">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-[#0b1220] text-white">
                <Layers className="h-3.5 w-3.5" />
              </span>
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.14em] text-[#0b1220]">
                  Signal feed
                </p>
                <p className="text-[8px] font-bold uppercase tracking-[0.12em] text-[#94a3b8]">
                  Private lead intelligence
                </p>
              </div>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#d9f3e8] bg-[#effbf5] px-2.5 py-1 text-[8px] font-black uppercase tracking-[0.1em] text-[#0a8f65]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#10b981]" />
              Private
            </span>
          </div>

          <div className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-[9px] font-black uppercase tracking-[0.14em] text-[#94a3b8]">
                New signal
              </span>
              <span className="text-[9px] font-medium text-[#94a3b8]">3 min ago</span>
            </div>

            <div className="mt-3 rounded-xl border border-[#e8e4da] bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="grid h-10 w-10 place-items-center rounded-xl bg-[#e9f8f1] text-[#0a8f65]">
                    <Building2 className="h-4 w-4" />
                  </span>
                  <div>
                    <p className="text-[13px] font-bold text-[#0b1220]">Structure</p>
                    <p className="mt-0.5 text-[11px] text-[#64748b]">Bronx · 10457</p>
                  </div>
                </div>
                <span className="rounded-full border border-[#d9f3e8] bg-[#effbf5] px-2 py-1 text-[7.5px] font-black uppercase tracking-[0.08em] text-[#0a8f65]">
                  Exclusive 1/1
                </span>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[9.5px] font-semibold text-[#64748b]">
                <span className="inline-flex items-center gap-1.5">
                  <ShieldCheck className="h-3.5 w-3.5 text-[#10b981]" />
                  Owner verified
                </span>
                <span className="h-1 w-1 rounded-full bg-[#cbd5e1]" />
                <span className="inline-flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5 text-[#10b981]" />
                  1-hour head start
                </span>
              </div>
            </div>

            <div className="mt-3 grid grid-cols-3 divide-x divide-[#e8e4da] rounded-xl border border-[#e8e4da] bg-white">
              <div className="px-3 py-3 text-center">
                <p className="mono-data text-sm font-black text-[#0b1220]">1/1</p>
                <p className="mt-1 text-[7px] font-bold uppercase tracking-[0.1em] text-[#94a3b8]">
                  Contractor
                </p>
              </div>
              <div className="px-3 py-3 text-center">
                <p className="mono-data text-sm font-black text-[#0a8f65]">✓</p>
                <p className="mt-1 text-[7px] font-bold uppercase tracking-[0.1em] text-[#94a3b8]">
                  Owner
                </p>
              </div>
              <div className="px-3 py-3 text-center">
                <p className="mono-data text-sm font-black text-[#0b1220]">01h</p>
                <p className="mt-1 text-[7px] font-bold uppercase tracking-[0.1em] text-[#94a3b8]">
                  Head start
                </p>
              </div>
            </div>

            <div className="mt-3 space-y-1.5">
              <div className="flex items-center justify-between rounded-lg bg-[#fbfaf7] px-3 py-2.5">
                <span className="text-[10px] font-semibold text-[#64748b]">Owner contact</span>
                <span className="text-[9px] font-black uppercase tracking-[0.06em] text-[#0a8f65]">
                  Unlocked
                </span>
              </div>
              <div className="flex items-center justify-between rounded-lg bg-[#fbfaf7] px-3 py-2.5">
                <span className="text-[10px] font-semibold text-[#64748b]">Competition</span>
                <span className="text-[9px] font-black uppercase tracking-[0.06em] text-[#0b1220]">
                  None
                </span>
              </div>
            </div>

            <button
              type="button"
              onClick={onOpen}
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-[#0b1220] px-4 py-3 text-[9.5px] font-black uppercase tracking-[0.1em] text-white transition hover:bg-[#0a8f65]"
            >
              Open live feed
              <span aria-hidden>→</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
