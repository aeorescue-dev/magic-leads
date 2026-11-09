"use client";

import { useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  MapPin,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { LP_WIDGET_ENABLED } from "@/lib/lp-widget";
import LpWidgetInboxPreview from "@/components/landing/LpWidget/LpWidgetInboxPreview";
import LpWidgetInline from "@/components/landing/LpWidget/LpWidgetInline";
import LpWidgetLauncher from "@/components/landing/LpWidget/LpWidgetLauncher";
import type { LpDemoSubmission } from "@/components/landing/LpWidget/LpWidgetPanel";
import type { LpIntentKey } from "@/components/landing/LpWidget/data";

export default function LpWidgetPreview() {
  const [open, setOpen] = useState(false);
  const [intent, setIntent] = useState<LpIntentKey | null>(null);
  const [intentQuestion, setIntentQuestion] = useState("");
  const [submission, setSubmission] = useState<LpDemoSubmission | null>(null);
  const [submissionId, setSubmissionId] = useState(0);
  const [teamReply, setTeamReply] = useState<{ text: string; at: number } | null>(
    null
  );

  return (
    <div className="min-h-screen bg-[#f6f8fc] text-slate-900">
      <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-[10.5px] font-semibold leading-relaxed text-amber-900">
        <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-amber-500 align-middle" />
        Preview isolado · <b>NEXT_PUBLIC_LP_WIDGET={String(LP_WIDGET_ENABLED)}</b> ·
        nenhum código da LP oficial, AuthForm, Stripe ou voz foi alterado
      </div>

      <header className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-4">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-tr from-violet-500 to-emerald-500 text-sm font-black text-white">
            ⚡
          </span>
          <span className="text-[15px] font-black tracking-tight">
            Magic<span className="text-emerald-600">Leads</span>
          </span>
          <span className="ml-1 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[9px] font-black uppercase tracking-wide text-slate-500">
            Preview
          </span>
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1">
          <span className="rounded-md px-2 py-1 text-[9px] font-black text-slate-400">
            PT
          </span>
          <span className="rounded-md bg-slate-900 px-2 py-1 text-[9px] font-black text-white">
            EN
          </span>
          <span className="rounded-md px-2 py-1 text-[9px] font-black text-slate-400">
            ES
          </span>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-5 px-4 pb-28 pt-1 lg:grid-cols-[1.15fr_0.85fr] lg:items-start">
        <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm shadow-slate-900/[0.03]">
          <div className="border-b border-slate-100 px-5 py-8 text-center sm:px-8">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-[9.5px] font-black uppercase tracking-[0.08em] text-emerald-800">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              12,480+ opportunities · updated today
            </span>
            <h1 className="mx-auto mt-4 max-w-[560px] text-[30px] font-black leading-[1.02] tracking-[-0.04em] sm:text-[40px]">
              Real renovation leads.
              <br />
              <span className="text-emerald-600">Owner identified.</span>
            </h1>
            <p className="mx-auto mt-3 max-w-[540px] text-[12.5px] leading-relaxed text-slate-500">
              Exclusive opportunities sourced from public records and verified
              property databases, monitored by our proprietary system. One owner,
              one phone, one contractor — reserved for 60 minutes.
            </p>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
              <button
                type="button"
                className="rounded-lg bg-emerald-500 px-4 py-2.5 text-[11.5px] font-bold text-white shadow-sm shadow-emerald-500/20"
              >
                Start now
              </button>
              <button
                type="button"
                className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-[11.5px] font-bold text-slate-700"
              >
                See sample
              </button>
            </div>
            <p className="mt-3 text-[10px] text-slate-400">
              $120/week · weekly pass · cancel anytime
            </p>
          </div>

          <div className="px-5 py-5 sm:px-8">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[9px] font-black uppercase tracking-[0.12em] text-slate-400">
                  Sample dashboard
                </p>
                <p className="mt-1 text-[12px] font-bold text-slate-900">
                  Today&apos;s opportunities
                </p>
              </div>
              <div className="flex gap-1 rounded-lg border border-slate-200 bg-white p-1">
                {["New York", "Boston", "Dallas"].map((city, index) => (
                  <span
                    key={city}
                    className={`rounded-md px-2 py-1 text-[9px] font-bold ${
                      index === 0
                        ? "bg-slate-900 text-white"
                        : "text-slate-400"
                    }`}
                  >
                    {city}
                  </span>
                ))}
              </div>
            </div>

            <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
              {[
                {
                  badge: "New",
                  trade: "Roofing",
                  city: "Brooklyn",
                  text: "Residential roof replacement. Owner on record, verified property activity confirmed.",
                  phone: "(***) ***-4821",
                  tone: "emerald",
                },
                {
                  badge: "High intent",
                  trade: "HVAC",
                  city: "Queens",
                  text: "Commercial unit replacement. Recent activity on the property record.",
                  phone: "(***) ***-1934",
                  tone: "violet",
                },
              ].map((lead) => (
                <article
                  key={lead.trade}
                  className="rounded-xl border border-slate-200 bg-white p-3"
                >
                  <span
                    className={`inline-block rounded px-1.5 py-0.5 text-[8px] font-black uppercase tracking-wide ${
                      lead.tone === "emerald"
                        ? "bg-emerald-50 text-emerald-700"
                        : "bg-violet-50 text-violet-700"
                    }`}
                  >
                    {lead.badge}
                  </span>
                  <h3 className="mt-2 text-[12px] font-bold text-slate-900">
                    {lead.trade} · {lead.city}
                  </h3>
                  <p className="mt-0.5 flex items-center gap-1 text-[9.5px] font-semibold text-emerald-700">
                    <ShieldCheck className="h-3 w-3" />
                    Owner identified · phone verified
                  </p>
                  <p className="mt-1.5 text-[9.5px] leading-relaxed text-slate-500">
                    {lead.text}
                  </p>
                  <div className="mt-2.5 flex items-center justify-between border-t border-slate-100 pt-2">
                    <span className="flex items-center gap-1 text-[8.5px] text-slate-400">
                      <MapPin className="h-3 w-3" />
                      Reserved 60 min
                    </span>
                    <span className="font-mono text-[9.5px] font-bold text-slate-700">
                      {lead.phone}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          </div>

          <div className="border-t border-slate-100 bg-slate-50/40 px-5 py-4 sm:px-8">
            <LpWidgetInline onOpen={() => setOpen(true)} />
            <p className="mt-2 text-center text-[9px] text-slate-400">
              Secondary entry point. The floating launcher at the bottom-right is
              the primary, low-intrusion channel.
            </p>
          </div>
        </section>

        <div className="space-y-3">
          <LpWidgetInboxPreview
            key={`${intent ?? "empty"}-${submissionId}`}
            intent={intent}
            submission={submission}
            questionPreview={intentQuestion}
            onSendReply={(text) =>
              setTeamReply({ text, at: Date.now() })
            }
          />

          <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-[0.12em] text-slate-400">
              <Sparkles className="h-3 w-3 text-violet-500" />
              O que esta prévia prova
            </p>
            <ul className="mt-2 space-y-1.5 text-[10.5px] leading-relaxed text-slate-500">
              {[
                "Chips de dor + composer livre, sem bloco escuro.",
                "Launcher flutuante como canal principal; inline é uma faixa leve.",
                "Fluxo adaptativo: 2 passos, ou 3 quando a intenção é cidade+ofício.",
                "Inbox PT-BR com tradução, sugestões e aprovação humana antes do EN.",
                "Entrega simulada: widget instantâneo + email transacional.",
              ].map((item) => (
                <li key={item} className="flex gap-1.5">
                  <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-500" />
                  {item}
                </li>
              ))}
            </ul>
            <div className="mt-3 flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50 px-2.5 py-2 text-[9px] font-semibold text-slate-500">
              <span>Fase 0 + Fase 1</span>
              <span className="flex items-center gap-1 text-emerald-700">
                Feature flag
                <ArrowRight className="h-3 w-3" />
              </span>
            </div>
          </div>
        </div>
      </main>

      <LpWidgetLauncher
        mode="demo"
        open={open}
        onOpenChange={setOpen}
        onIntentChange={(next, question) => {
          setIntent(next);
          setIntentQuestion(question ?? "");
        }}
        onDemoSubmit={(payload) => {
          setSubmission(payload);
          setSubmissionId((value) => value + 1);
          setTeamReply(null);
        }}
        teamReply={teamReply}
      />

      <footer className="border-t border-slate-200 bg-white px-4 py-4 text-center text-[9.5px] leading-relaxed text-slate-400">
        Protótipo isolado · componentes em{" "}
        <code className="rounded bg-slate-100 px-1 py-0.5 text-slate-600">
          components/landing/LpWidget
        </code>{" "}
        · nenhuma alteração à LP oficial, AuthForm, Stripe, preços ou voz.
      </footer>
    </div>
  );
}
