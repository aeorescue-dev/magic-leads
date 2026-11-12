"use client";

import Link from "next/link";
import { ArrowUpRight, Loader2, Phone } from "lucide-react";
import useSWR from "swr";

import { fetchVoiceCampaigns } from "@/lib/admin-api";

function nextLabel(value?: string | null): string {
  if (!value) return "—";
  const normalized = /Z$|[+-]\d{2}:?\d{2}$/.test(value)
    ? value
    : `${value.replace(" ", "T")}Z`;
  const stamp = Date.parse(normalized);
  if (!Number.isFinite(stamp)) return value;
  return new Date(stamp).toLocaleString("pt-PT", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }) + "Z";
}

export function VoiceCampaignsCard() {
  const { data, error, isLoading } = useSWR(
    "admin-voice-campaigns-card",
    () => fetchVoiceCampaigns(50),
    { refreshInterval: 30_000, revalidateOnFocus: true }
  );

  const campaigns = data?.campaigns ?? [];
  const rows = campaigns
    .filter(
      (campaign) =>
        campaign.status === "running" ||
        (campaign.status === "paused" && campaign.next_batch_at)
    )
    .sort((a, b) => {
      if (a.status === "running" && b.status !== "running") return -1;
      if (b.status === "running" && a.status !== "running") return 1;
      return String(a.next_batch_at || "").localeCompare(
        String(b.next_batch_at || "")
      );
    })
    .slice(0, 5);

  return (
    <section className="rounded-2xl border border-white/10 bg-[#10131a] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-bold text-slate-200">
            <Phone className="h-4 w-4 text-emerald-400" />
            Campanhas de voz
          </h2>
          <p className="mt-0.5 text-[10px] text-slate-500">
            Agendamentos ativos e próximos lotes · atualiza a cada 30 s
          </p>
        </div>
        <Link
          href="/admin/voice"
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-[10px] font-bold text-slate-300 transition hover:border-emerald-400/30 hover:text-emerald-200"
        >
          Abrir Voice B2B
          <ArrowUpRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {error ? (
        <p className="mt-3 text-[11px] text-rose-300">
          Não foi possível carregar as campanhas.
        </p>
      ) : isLoading && !rows.length ? (
        <p className="mt-3 inline-flex items-center gap-1.5 text-[11px] text-slate-500">
          <Loader2 className="h-3 w-3 animate-spin" /> A carregar campanhas…
        </p>
      ) : rows.length ? (
        <div className="mt-3 divide-y divide-white/[0.06]">
          {rows.map((campaign) => (
            <div
              key={campaign.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-[10.5px]"
            >
              <span className="font-mono text-slate-500">#{campaign.id}</span>
              <span className="min-w-0 flex-1 truncate font-semibold text-slate-200">
                {campaign.name}
              </span>
              <span
                className={`rounded-full px-2 py-0.5 text-[8px] font-black uppercase tracking-[0.08em] ${
                  campaign.status === "running"
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-white/[0.05] text-slate-400"
                }`}
              >
                {campaign.status === "running" ? "a ligar" : "agendada"}
              </span>
              <span className="text-slate-500">
                {campaign.calls_started}/{campaign.quota_total ?? campaign.max_calls}
              </span>
              <span className="w-full text-[9.5px] text-slate-600 sm:w-auto">
                {campaign.status === "running"
                  ? "em curso"
                  : nextLabel(campaign.next_batch_at)}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-[11px] text-slate-500">
          Sem campanhas ativas ou agendadas.
        </p>
      )}
    </section>
  );
}
