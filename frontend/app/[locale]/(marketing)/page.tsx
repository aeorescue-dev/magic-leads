'use client';

import { useEffect, useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { fetchPublicMetrics } from "@/lib/api-client";
import type { PublicMetrics } from "@/lib/api-client";
import { FoldWave, useLandingShell } from "@/components/landing/LandingShell";
import { LiveTradeGrid } from "@/components/landing/LiveTradeGrid";
import { Building2, Phone, ShieldCheck, Megaphone, Search, Users } from "lucide-react";

// ------------------------------------------------------------------
// Tipos e dados ilustrativos do "painel amostra"
// (endereços mascarados, telefones fictícios da central 555, nomes truncados)
//
// Só o que muda de idioma (ofício, gravidade e descrição) vem do i18n
// (`landing.sampleLeads`); rua, bairro, nome e telefone são iguais em EN/PT/ES.
// ------------------------------------------------------------------
type City = "New York" | "Boston" | "Dallas" | "Chicago";
type TradeKey = "Telhado" | "Encanamento" | "Estrutura" | "Pintura" | "Elétrica" | "Aquecimento";
type Channel = "whatsapp" | "sms" | "email";
type BadgeKey = "urgent" | "high" | "medium";

const CITIES: City[] = ["New York", "Boston", "Dallas", "Chicago"];
const TRADE_KEYS: TradeKey[] = ["Telhado", "Encanamento", "Estrutura", "Pintura", "Elétrica", "Aquecimento"];
const CHANNELS: Channel[] = ["whatsapp", "sms", "email"];

const BADGE_STYLE: Record<BadgeKey, string> = {
  urgent: "badge-urgent",
  high: "badge-high",
  medium: "badge-medium",
};

interface SampleLeadBase {
  id: string;
  address: string;
  neighborhood: string;
  timeAgo: string;
  ownerName: string;
  ownerPhone: string;
}

interface SampleLead extends SampleLeadBase {
  category: string;
  badge: BadgeKey;
  badgeLabel: string;
  description: string;
}

const SAMPLE_LEADS_BASE: Record<City, SampleLeadBase[]> = {
  "New York": [
    { id: "ny-1", address: "•••• Flatbush Ave", neighborhood: "Flatbush, Brooklyn", timeAgo: "3 min", ownerName: "Maria S.", ownerPhone: "(347) 555-0192" },
    { id: "ny-2", address: "•••• 30th Ave", neighborhood: "Astoria, Queens", timeAgo: "14 min", ownerName: "Carlos M.", ownerPhone: "(917) 555-0143" },
    { id: "ny-3", address: "•••• 5th Ave", neighborhood: "Park Slope, Brooklyn", timeAgo: "28 min", ownerName: "Roberto L.", ownerPhone: "(718) 555-0188" },
  ],
  Boston: [
    { id: "bos-1", address: "•••• Centre St", neighborhood: "Jamaica Plain", timeAgo: "5 min", ownerName: "Fernanda C.", ownerPhone: "(617) 555-0129" },
    { id: "bos-2", address: "•••• Meridian St", neighborhood: "East Boston", timeAgo: "19 min", ownerName: "David M.", ownerPhone: "(857) 555-0174" },
    { id: "bos-3", address: "•••• Dorchester Ave", neighborhood: "Dorchester", timeAgo: "42 min", ownerName: "Juliana D.", ownerPhone: "(617) 555-0199" },
  ],
  Dallas: [
    { id: "dal-1", address: "•••• Jefferson Blvd", neighborhood: "Oak Cliff", timeAgo: "8 min", ownerName: "Lucas A.", ownerPhone: "(214) 555-0112" },
    { id: "dal-2", address: "•••• Gaston Ave", neighborhood: "Lakewood", timeAgo: "25 min", ownerName: "Patricia R.", ownerPhone: "(469) 555-0165" },
    { id: "dal-3", address: "•••• Preston Rd", neighborhood: "Preston Hollow", timeAgo: "51 min", ownerName: "Ricardo S.", ownerPhone: "(972) 555-0131" },
  ],
  Chicago: [
    { id: "chi-1", address: "•••• Milwaukee Ave", neighborhood: "Logan Square", timeAgo: "4 min", ownerName: "Eduardo F.", ownerPhone: "(312) 555-0184" },
    { id: "chi-2", address: "•••• 18th St", neighborhood: "Pilsen", timeAgo: "22 min", ownerName: "Sandra M.", ownerPhone: "(773) 555-0156" },
    { id: "chi-3", address: "•••• 53rd St", neighborhood: "Hyde Park", timeAgo: "39 min", ownerName: "Gabriel R.", ownerPhone: "(872) 555-0120" },
  ],
};

const SIGNAL_STYLE = [
  { color: "#f59e0b", bg: "#fff7ed", ring: "#fde68a" },
  { color: "#2563eb", bg: "#eff6ff", ring: "#bfdbfe" },
  { color: "#475569", bg: "#f1f5f9", ring: "#cbd5e1" },
];

const AVATAR_GRAD = [
  "linear-gradient(135deg,#10b981,#0a8f65)",
  "linear-gradient(135deg,#7c5cff,#9d80ff)",
  "linear-gradient(135deg,#b45309,#92400e)",
];

// ------------------------------------------------------------------
// Helpers de parsing das chaves serializadas do i18n (landing.*)
// ------------------------------------------------------------------
function blocks(s: string): string[][] {
  return (s || "").split("||").filter(Boolean).map((b) => b.split("|").map((f) => f.trim()));
}

function listOf(s: string): string[] {
  return (s || "").split(",").map((x) => x.trim()).filter(Boolean);
}

export default function LandingPage() {
  const { t } = useI18n();
  const { openModal, scrollTo } = useLandingShell();

  // ------------------------------------------------ estado
  const [activeCity, setActiveCity] = useState<City>("New York");
  const [reservedLeadId, setReservedLeadId] = useState<string | null>(null);
  const [timerSeconds, setTimerSeconds] = useState(3600);
  const [whatsappLead, setWhatsappLead] = useState<SampleLead | null>(null);
  const [copied, setCopied] = useState(false);
  const [tplTrade, setTplTrade] = useState<TradeKey>("Telhado");
  const [tplChannel, setTplChannel] = useState<Channel>("whatsapp");
  const [ticketValue, setTicketValue] = useState(6500);
  const [openFaq, setOpenFaq] = useState<number | null>(0);

  // dados reais (métricas públicas — fonte única da verdade)
  // null = ainda a carregar: nunca mostramos "0" antes de haver resposta.
  const [metrics, setMetrics] = useState<PublicMetrics | null>(null);

  useEffect(() => {
    let mounted = true;
    (async () => {
      const m = await fetchPublicMetrics();
      if (mounted) setMetrics(m);
    })();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!reservedLeadId) return;
    const i = setInterval(() => setTimerSeconds((v) => (v > 0 ? v - 1 : 0)), 1000);
    return () => clearInterval(i);
  }, [reservedLeadId]);

  // ------------------------------------------------ copy estruturada (parse)
  const L = useMemo(() => {
    const categories = listOf(t("landing.categoriesList"));
    const tradesLabel = listOf(t("landing.tplTrades"));
    const signals = blocks(t("landing.signals")).map((f) => ({
      label: f[0], hint: f[1], body: f[2],
    }));
    const problems = blocks(t("landing.problems")).map((f) => ({
      kicker: f[0], title: f[1], body: f[2], cost: f[3],
    }));
    const comparisons = blocks(t("landing.comparisons")).map((f) => ({
      channel: f[0], sub: f[1], cost: f[2], costLabel: f[3],
      exclusivity: f[4], intent: f[5], phone: f[6], winner: f[7] === "true",
    }));
    const quotes = blocks(t("landing.quotes")).map((f) => ({
      init: f[0], grad: f[1], name: f[2], role: f[3], badge: f[4], text: f[5],
    }));
    const planFeatures = listOf(t("landing.planFeatures"));
    const neverItems = listOf(t("landing.neverItems"));
    const faqs = blocks(t("landing.faqs")).map((f) => ({ q: f[0], a: f[1] }));
    const templates: Record<TradeKey, Record<Channel, string>> = {} as Record<TradeKey, Record<Channel, string>>;
    blocks(t("landing.templates")).forEach((f) => {
      const k = f[0] as TradeKey;
      if (TRADE_KEYS.includes(k)) templates[k] = { whatsapp: f[1], sms: f[2], email: f[3] };
    });
    const trust = [t("landing.trust1"), t("landing.trust2"), t("landing.trust3")];
    const coverageItems = blocks(t("landing.coverageItems")).map((f) => ({
      icon: f[0] ?? "", title: f[1] ?? "", desc: f[2] ?? "", color: f[3] || "#10b981",
    }));
    // id | ofício | gravidade | descrição (traduzidos; rua/nome/telefone vêm da base)
    const sampleMeta: Record<string, { category: string; badge: BadgeKey; description: string }> = {};
    blocks(t("landing.sampleLeads")).forEach((f) => {
      if (!f[0]) return;
      sampleMeta[f[0]] = {
        category: f[1] ?? "",
        badge: (f[2] === "urgent" || f[2] === "high" ? f[2] : "medium") as BadgeKey,
        description: f[3] ?? "",
      };
    });

    const waMsg = (name: string, cat: string, addr: string) =>
      t("landing.waMsg").replace("{name}", name).replace("{cat}", cat).replace("{addr}", addr);
    const aboutJobs = (n: number, ticket: string) =>
      t("landing.aboutJobs").replace("{n}", String(n)).replace("{ticket}", ticket);

    return { categories, tradesLabel, signals, problems, comparisons, quotes, planFeatures, neverItems, faqs, templates, trust, waMsg, aboutJobs, coverageItems, sampleMeta };
  }, [t]);

  const leadsByCity = useMemo(() => {
    const out = {} as Record<City, SampleLead[]>;
    CITIES.forEach((city) => {
      out[city] = (SAMPLE_LEADS_BASE[city] ?? []).map((base) => {
        const meta = L.sampleMeta[base.id];
        const badge = meta?.badge ?? "medium";
        return {
          ...base,
          category: meta?.category ?? "",
          badge,
          badgeLabel: t(`landing.badge.${badge}`),
          description: meta?.description ?? "",
        };
      });
    });
    return out;
  }, [L, t]);

  // ------------------------------------------------ derivados (métricas públicas)
  const hasMetrics = (metrics?.total_leads ?? 0) > 0;
  const leadsBank = metrics?.total_leads ?? 0;
  const withOwner = metrics?.leads_with_owner ?? 0;
  const citiesCount = metrics?.cities_count ?? CITIES.length;
  const newThisRun = metrics?.last_scrape?.novas_oportunidades ?? 0;

  const fmtTimer = (s: number) =>
    `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;
  const validatedPhones = Math.round(300 * 0.7);
  const estimatedVisits = Math.round(validatedPhones * 0.25);
  const closedJobs = Math.max(0, Math.round(estimatedVisits / 20));
  const monthlyRevenue = closedJobs * ticketValue;
  const monthsPaid = (ticketValue / 520).toFixed(1);
  const winner = L.comparisons.find((c) => c.winner);
  const rivals = L.comparisons.filter((c) => !c.winner);

  const copyTpl = (text: string) => {
    navigator.clipboard?.writeText(text).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <>
      {/* HERO */}
      <section id="topo" className="landing-dark aurora-dark relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 grid-fade" />
        <div className="pointer-events-none absolute -top-48 left-1/2 h-[720px] w-[1150px] -translate-x-1/2 rounded-full bg-[#10b981]/[0.13] blur-[170px]" />
        <div className="pointer-events-none absolute -right-24 top-24 h-[440px] w-[440px] rounded-full bg-[#7c5cff]/[0.16] blur-[150px]" />

        <div className="relative mx-auto max-w-7xl px-4 pb-16 pt-14 sm:px-6 md:pb-20 md:pt-20">
          <div className="grid items-center gap-14 lg:grid-cols-[1.04fr_0.96fr] lg:gap-10">
            <div className="text-center lg:text-left">
              <div className="fade-up eyebrow">
                <span className="dot" />
                {hasMetrics ? `${leadsBank.toLocaleString("en-US")} ${t("landing.heroKicker")}` : t("landing.heroLoading")}
              </div>

              <h1 className="fade-up font-display mt-7 text-[2.4rem] font-black leading-[0.95] tracking-[-0.04em] text-white sm:text-6xl lg:text-[4.35rem]">
                {t("landing.heroTitle1")}
                <br />
                <span className="hl">
                  {t("landing.heroTitle2")}
                </span>
              </h1>

              <p className="fade-up mx-auto mt-7 max-w-xl text-base leading-relaxed text-[#9fb0c6] sm:text-lg lg:mx-0">
                {t("landing.heroSub")}
              </p>

              <div className="fade-up mt-9 flex flex-col items-stretch justify-center gap-3 sm:flex-row lg:justify-start">
                <button onClick={openModal} data-track="hero_cta" className="btn-mint group flex items-center justify-center gap-2.5 px-8 py-4 text-[15px]">
                  {t("landing.ctaPanel")}
                  <svg className="h-5 w-5 transition-transform group-hover:translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" /></svg>
                </button>
                <button onClick={() => scrollTo("simulador")} data-track="sample_cta" className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/14 bg-white/[0.055] px-7 py-4 text-sm font-bold text-white backdrop-blur-md transition hover:border-[#34e0a1]/40 hover:bg-white/[0.09]">
                  {t("landing.ctaSample")}
                </button>
              </div>

              <div className="fade-up mt-7 rounded-2xl border border-[#34e0a1]/20 bg-[#34e0a1]/[0.07] px-4 py-3.5 backdrop-blur-sm">
                <div className="grid grid-cols-3 gap-x-1 gap-y-2 text-[8px] font-black uppercase tracking-[0.06em] text-[#8ff5c8] sm:flex sm:flex-wrap sm:items-center sm:justify-center sm:gap-x-5 sm:text-[11px] sm:tracking-wider lg:justify-start">
                  {L.trust.map((item) => (
                    <span key={item} className="flex flex-col items-center justify-center gap-0.5 text-center sm:inline-flex sm:flex-row sm:gap-1.5 lg:justify-start">
                      <svg className="h-3 w-3 shrink-0 text-[#34e0a1] sm:h-3.5 sm:w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
                      {item}
                    </span>
                  ))}
                </div>
                {L.quotes[0] && (
                  <p className="mt-2.5 flex items-start justify-center gap-2 text-[11px] font-semibold leading-snug text-white/65 lg:justify-start">
                    <span className="mt-0.5 shrink-0 text-[#34e0a1]">★★★★★</span>
                    <span>“{L.quotes[0].badge}” — {L.quotes[0].name}, {L.quotes[0].role}</span>
                  </p>
                )}
              </div>

              <p className="mt-4 text-xs font-medium text-white/40">{t("landing.priceLine")}</p>
            </div>

            {/* Glass product console */}
            <div className="pop-in relative mx-auto w-full max-w-[540px]">
              <div className="pointer-events-none absolute -inset-6 rounded-[2.4rem] bg-[#10b981]/[0.10] blur-3xl" />
              <div className="glass-panel relative rounded-[1.7rem] p-2">
                <div className="overflow-hidden rounded-[1.35rem] border border-white/[0.06] bg-[#070c15]/95">
                  <div className="browser-chrome flex items-center gap-3 px-4 py-3">
                    <div className="flex gap-1.5">
                      <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]/80" />
                      <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]/80" />
                      <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]/80" />
                    </div>
                    <div className="flex flex-1 items-center gap-2 rounded-md border border-white/[0.07] bg-black/30 px-2.5 py-1">
                      <svg className="h-3 w-3 text-[#34e0a1]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 0h10.5a1.5 1.5 0 0 1 1.5 1.5v7.5a1.5 1.5 0 0 1-1.5 1.5H6.75a1.5 1.5 0 0 1-1.5-1.5v-7.5a1.5 1.5 0 0 1 1.5-1.5Z" /></svg>
                      <span className="mono-data text-[10px] tracking-tight text-white/60">painel.magicleads.app</span>
                    </div>
                    <span className="inline-flex items-center gap-1.5 text-[9px] font-black uppercase tracking-[0.16em] text-[#34e0a1]">
                      <span className="blink-dot" /> live
                    </span>
                  </div>

                  <div className="px-4 pb-4 pt-3.5">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-[9px] font-black uppercase tracking-[0.18em] text-white/35">New York · Manhattan</p>
                        <p className="mt-0.5 text-sm font-bold text-white">Today&apos;s exclusive jobs</p>
                      </div>
                      <div className="text-right">
                        <p className="mono-data text-xl font-black leading-none text-[#34e0a1]">12</p>
                        <p className="text-[8px] font-bold uppercase tracking-widest text-white/35">new</p>
                      </div>
                    </div>

                    <div className="mt-3 status-bar"><span style={{ width: "76%" }} /></div>
                    <div className="mt-1.5 flex justify-between text-[8px] font-bold uppercase tracking-widest text-white/30">
                      <span>76%</span><span>{t("landing.updated")}</span>
                    </div>

                    <div className="mt-3.5 space-y-2">
                      {leadsByCity["New York"].slice(0, 3).map((lead) => (
                        <div key={`hero-${lead.id}`} className="lead-row flex items-center gap-3 px-3 py-2.5">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className={`priority-pill ${BADGE_STYLE[lead.badge]}`}>{lead.badgeLabel}</span>
                              <span className="mono-data truncate text-[9px] text-white/30">{lead.id.toUpperCase()} · {lead.timeAgo}</span>
                            </div>
                            <p className="mt-1 truncate text-[12px] font-bold text-white">{lead.category}</p>
                            <p className="truncate text-[10px] text-[#34e0a1]">{lead.neighborhood}</p>
                          </div>
                          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.04] text-white/40">
                            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" /></svg>
                          </span>
                        </div>
                      ))}
                    </div>

                    <div className="mt-3 flex items-center justify-between rounded-xl border border-[#34e0a1]/15 bg-[#34e0a1]/[0.06] px-3 py-2.5">
                      <span className="inline-flex items-center gap-1.5 text-[9px] font-black uppercase tracking-wider text-[#34e0a1]">
                        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>
                        {t("landing.reserveHour")}
                      </span>
                      <span className="mono-data text-[9px] font-bold text-white/40">$120/wk</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="glass-panel-strong absolute -bottom-6 -left-4 hidden items-center gap-3 rounded-2xl px-4 py-3 sm:flex">
                <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#34e0a1]/15 text-[#34e0a1]">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 6.75c0 8.284 6.716 15 15 15h2.25a2.25 2.25 0 0 0 2.25-2.25v-1.372c0-.516-.351-.966-.852-1.091l-4.423-1.106c-.44-.11-.902.055-1.173.417l-.97 1.293c-.282.376-.769.542-1.21.38a12.035 12.035 0 0 1-7.143-7.143c-.162-.441.004-.928.38-1.21l1.293-.97c.363-.271.527-.734.417-1.173L6.963 3.102a1.125 1.125 0 0 0-1.091-.852H4.5A2.25 2.25 0 0 0 2.25 4.5v2.25Z" /></svg>
                </span>
                <div>
                  <p className="text-[9px] font-black uppercase tracking-widest text-white/40">{t("landing.owner")}</p>
                  <p className="mono-data text-xs font-bold text-white">(347) 555-0192</p>
                </div>
              </div>
            </div>
          </div>

          {/* Glass metric tiles */}
          <div className="mt-14 grid gap-3 sm:grid-cols-3">
            <div className="metric-tile px-5 py-4">
              <div className="flex items-center justify-between">
                <p className="text-[9px] font-black uppercase tracking-[0.18em] text-white/35">{t("landing.statBank")}</p>
                <span className="h-1.5 w-1.5 rounded-full bg-[#34e0a1] shadow-[0_0_10px_#34e0a1]" />
              </div>
              <p className="mono-data mt-2 text-2xl font-black text-white sm:text-3xl">{hasMetrics ? `${leadsBank.toLocaleString("en-US")}+` : "—"}</p>
            </div>
            <div className="metric-tile px-5 py-4">
              <div className="flex items-center justify-between">
                <p className="text-[9px] font-black uppercase tracking-[0.18em] text-white/35">{t("landing.statOwner")}</p>
                <span className="h-1.5 w-1.5 rounded-full bg-[#a78bfa] shadow-[0_0_10px_#a78bfa]" />
              </div>
              <p className="mono-data mt-2 text-2xl font-black text-white sm:text-3xl">{hasMetrics ? `${withOwner.toLocaleString("en-US")}+` : "—"}</p>
            </div>
            <div className="metric-tile px-5 py-4">
              <div className="flex items-center justify-between">
                <p className="text-[9px] font-black uppercase tracking-[0.18em] text-white/35">{t("landing.statCities")}</p>
                <span className="h-1.5 w-1.5 rounded-full bg-[#34e0a1] shadow-[0_0_10px_#34e0a1]" />
              </div>
              <p className="mono-data mt-2 text-2xl font-black text-white sm:text-3xl">{citiesCount}+</p>
            </div>
          </div>

          <p className="mt-5 flex flex-wrap items-center justify-center gap-2 text-[10px] font-bold uppercase tracking-[0.14em] text-white/30">
            <span className="blink-dot" /><span className="blink-dot blink-dot-delay" /><span className="blink-dot blink-dot-delay-2" />
            {t("landing.updated")} {t("landing.agoLittle")}
            {hasMetrics && newThisRun > 0 && <span className="text-[#34e0a1]">· {newThisRun.toLocaleString("en-US")} {t("landing.updatedNew")}</span>}
          </p>
        </div>

        <div className="relative overflow-hidden border-t border-white/[0.07] bg-[#060911]/80 py-4">
          <div className="animate-marquee items-center gap-8 text-[10px] font-bold uppercase tracking-[0.22em] text-white/25">
            {[...L.categories, ...L.categories].map((c, i) => (
              <span key={`${c}-${i}`} className="flex shrink-0 items-center gap-8">{c}<span className="h-1 w-1 rounded-full bg-[#34e0a1]/70" /></span>
            ))}
          </div>
        </div>
      </section>

      <LiveTradeGrid categories={L.categories} onCta={openModal} />

      {/* COBERTURA COMPLETA */}
      <section className="surface-light relative py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="max-w-3xl">
            <span className="eyebrow eyebrow-light"><span className="dot" />{t("landing.coverageKicker")}</span>
            <h2 className="font-display mt-5 text-[2.35rem] font-black leading-[0.98] tracking-[-0.03em] text-[#0b1220] sm:text-5xl md:text-[3.4rem]">
              {t("landing.coverageTitle")} <span className="hl">{t("landing.coverageHl")}</span>
            </h2>
            <p className="mt-6 text-base leading-relaxed text-[#54617a] sm:text-lg">{t("landing.coverageSub")}</p>
          </div>

          <div className="mt-14 grid gap-5 md:grid-cols-3">
            {L.coverageItems.map((item, i) => (
              <article key={item.title} className="bento-light group relative overflow-hidden p-8">
                <span className="mono-data absolute right-6 top-6 text-[10px] font-bold tracking-widest text-[#94a3b8]">0{i + 1}</span>
                <span
                  className="flex h-14 w-14 items-center justify-center rounded-2xl shadow-inner"
                  style={{ background: `${item.color}14`, color: item.color, boxShadow: `inset 0 0 0 1px ${item.color}24` }}
                >
                  {item.icon === "phone" && <Phone className="h-6 w-6" />}
                  {item.icon === "building" && <Building2 className="h-6 w-6" />}
                  {item.icon === "shield" && <ShieldCheck className="h-6 w-6" />}
                </span>
                <h3 className="font-display mt-6 text-xl font-black tracking-[-0.02em] text-[#0b1220]">{item.title}</h3>
                <p className="mt-3 flex-1 text-[15px] leading-relaxed text-[#54617a]">{item.desc}</p>
                <span className="mt-6 block h-1 w-10 rounded-full" style={{ background: `linear-gradient(90deg, ${item.color}, transparent)` }} />
              </article>
            ))}
          </div>

          <div className="landing-dark relative mt-6 overflow-hidden rounded-[1.6rem] border border-white/10 bg-[#070a12] p-8 md:p-10">
            <div className="pointer-events-none absolute -right-16 -top-24 h-64 w-64 rounded-full bg-[#34e0a1]/[0.10] blur-3xl" />
            <div className="relative flex flex-col items-start gap-6 md:flex-row md:items-center">
              <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-[#34e0a1]/12 text-[#34e0a1] ring-1 ring-[#34e0a1]/25">
                <ShieldCheck className="h-7 w-7" />
              </span>
              <p className="flex-1 text-xl font-bold leading-snug tracking-[-0.01em] text-white sm:text-2xl">
                {t("landing.coverageTrust")}
              </p>
              <span className="ai-chip shrink-0">Owner verified</span>
            </div>
          </div>
        </div>
      </section>

      {/* PROBLEMA */}
      <section className="relative bg-white py-20 md:py-28">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#e6ebf2] to-transparent" />
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="max-w-3xl">
            <span className="eyebrow eyebrow-light"><span className="dot" style={{ background: "#f43f5e", boxShadow: "0 0 10px #f43f5e" }} />{t("landing.problemKicker")}</span>
            <h2 className="font-display mt-5 text-[2.5rem] font-black leading-[0.98] tracking-[-0.035em] text-[#0b1220] sm:text-5xl md:text-[3.4rem]">
              {t("landing.problemTitle")} <span className="hl">{t("landing.problemHl")}</span>
            </h2>
            <p className="mt-6 text-base leading-relaxed text-[#54617a] sm:text-lg">{t("landing.problemSub")}</p>
          </div>
          <div className="mt-14 grid gap-5 md:grid-cols-3">
            {L.problems.map((p) => (
              <article key={p.kicker} className="bento-light flex flex-col p-8">
                <div className="flex items-center justify-between">
                  <p className="kicker text-[#e11d48]">{p.kicker}</p>
                  <span className="grid h-8 w-8 place-items-center rounded-full bg-[#f43f5e]/10 text-[#e11d48]">
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m0 3.75h.008v.008H12v-.008ZM21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>
                  </span>
                </div>
                <h3 className="font-display mt-4 text-2xl font-black tracking-[-0.02em] text-[#0b1220]">{p.title}</h3>
                <p className="mt-3 flex-1 text-[15px] leading-relaxed text-[#54617a]">{p.body}</p>
                <span className="mono-data mt-6 inline-flex w-fit rounded-lg bg-[#fef2f4] px-3.5 py-2 text-[11px] font-bold uppercase tracking-wider text-[#be123c] ring-1 ring-[#fecdd3]">{t("landing.costWord")} {p.cost}</span>
              </article>
            ))}
          </div>
          <div className="landing-dark relative mt-6 overflow-hidden rounded-[1.6rem] bg-[#070a12] p-8 ring-1 ring-white/10 md:p-10">
            <div className="pointer-events-none absolute -left-16 -top-20 h-64 w-64 rounded-full bg-[#7c5cff]/[0.14] blur-3xl" />
            <div className="relative flex flex-col items-start gap-6 md:flex-row md:items-center">
              <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-[#34e0a1] to-[#0a8f65] text-[#04120d] shadow-lg shadow-[#10b981]/25"><svg className="h-7 w-7" viewBox="0 0 24 24" fill="currentColor"><path d="m13 2-9 12h7l-1 8 10-13h-7V2Z" /></svg></span>
              <p className="flex-1 text-xl font-bold leading-snug tracking-[-0.01em] text-white sm:text-2xl">{t("landing.flip")}</p>
              <button onClick={openModal} data-track="how_cta" className="btn-mint shrink-0 px-6 py-3.5 text-sm">{t("landing.seeHow")}</button>
            </div>
          </div>
        </div>
      </section>

      {/* OFÍCIOS */}
      <section id="oficios" className="surface-white relative scroll-mt-20 py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="max-w-3xl">
            <span className="eyebrow eyebrow-light"><span className="dot" style={{ background: "#7c5cff", boxShadow: "0 0 10px #7c5cff" }} />{t("landing.oficiosKicker")}</span>
            <h2 className="font-display mt-5 text-[2.4rem] font-black leading-[0.98] tracking-[-0.03em] text-[#0b1220] sm:text-5xl md:text-[3.2rem]">
              {t("landing.oficiosTitle")} <span className="hl">{t("landing.oficiosHl")}</span>
            </h2>
            <p className="mt-6 text-base leading-relaxed text-[#54617a] sm:text-lg">{t("landing.oficiosSub")}</p>
          </div>
          <div className="mt-12 grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
            {L.categories.map((cat) => (
              <div key={cat} className="trade-pill flex items-center gap-3 px-4 py-3.5">
                <span className="h-2 w-2 shrink-0 rounded-full bg-[#10b981] shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
                <span className="text-sm font-bold text-[#0b1220]">{cat}</span>
              </div>
            ))}
          </div>
          <p className="mt-14 text-center text-sm font-bold uppercase tracking-[0.14em] text-[#94a3b8]">{t("landing.oficiosPaths")}</p>
          <div className="mt-6 grid gap-5 md:grid-cols-3">
            {L.signals.map((s, i) => (
              <article key={s.label} className="bento-light relative overflow-hidden p-7">
                <span className="absolute inset-x-0 top-0 h-1" style={{ background: `linear-gradient(90deg, ${SIGNAL_STYLE[i].color}, transparent)` }} />
                <span className="inline-flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.14em]" style={{ color: SIGNAL_STYLE[i].color }}>
                  <span className="h-2 w-2 rounded-full" style={{ background: SIGNAL_STYLE[i].color, boxShadow: `0 0 10px ${SIGNAL_STYLE[i].color}` }} />{s.hint}
                </span>
                <h3 className="font-display mt-3 text-2xl font-black tracking-[-0.02em] text-[#0b1220]">{s.label}</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-[#54617a]">{s.body}</p>
              </article>
            ))}
          </div>
          <p className="mx-auto mt-6 max-w-2xl text-center text-sm text-[#94a3b8]">{t("landing.oficiosFoot")}</p>
        </div>
      </section>

      {/* PAINEL AMOSTRA */}
      <section id="simulador" className="landing-dark aurora-dark relative scroll-mt-20 overflow-hidden py-20 text-white md:py-24">
        <div className="pointer-events-none absolute inset-0 grid-fade opacity-60" />
        <div className="relative mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="eyebrow mx-auto"><span className="dot" />{t("landing.sampleKicker")}</span>
            <h2 className="font-display mt-5 text-4xl font-black leading-[0.98] tracking-[-0.035em] sm:text-5xl">{t("landing.sampleTitle")}</h2>
            <p className="mx-auto mt-5 max-w-2xl text-base text-[#9fb0c6] sm:text-lg">{t("landing.sampleSub")}</p>
          </div>

          <div className="relative mx-auto mt-14 max-w-6xl">
            <div className="pointer-events-none absolute -inset-8 rounded-[3rem] bg-[#10b981]/[0.07] blur-3xl" />
            <div className="glass-panel relative rounded-[2rem] p-2">
              <div className="overflow-hidden rounded-[1.55rem] border border-white/[0.07] bg-[#070c15]">
                {/* Browser chrome */}
                <div className="browser-chrome flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
                  <div className="flex gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]/80" />
                    <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]/80" />
                    <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]/80" />
                  </div>
                  <div className="hidden items-center gap-2 text-white/25 sm:flex">
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" /></svg>
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" /></svg>
                  </div>
                  <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-white/[0.07] bg-black/35 px-3 py-1.5">
                    <svg className="h-3.5 w-3.5 shrink-0 text-[#34e0a1]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 0h10.5a1.5 1.5 0 0 1 1.5 1.5v7.5a1.5 1.5 0 0 1-1.5 1.5H6.75a1.5 1.5 0 0 1-1.5-1.5v-7.5a1.5 1.5 0 0 1 1.5-1.5Z" /></svg>
                    <span className="mono-data truncate text-[11px] text-white/55">painel.magicleads.app/opportunities</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="ai-chip"><span className="blink-dot" /> live</span>
                    <span className="hidden h-6 w-6 place-items-center rounded-full bg-gradient-to-br from-[#34e0a1] to-[#7c5cff] text-[9px] font-black text-[#04120d] sm:grid">ML</span>
                  </div>
                </div>

                {/* App toolbar */}
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] bg-[#0a101b]/60 px-4 py-3 sm:px-5">
                  <div className="grid w-full grid-cols-4 gap-1 sm:flex sm:w-auto sm:flex-wrap">
                    {CITIES.map((c) => (
                      <button key={c} onClick={() => { setActiveCity(c); setReservedLeadId(null); }} className={`whitespace-nowrap rounded-lg px-1.5 py-1.5 text-center text-[10px] font-bold transition sm:px-3 sm:text-[11px] ${activeCity === c ? "bg-[#34e0a1]/15 text-[#34e0a1] ring-1 ring-[#34e0a1]/30" : "text-white/45 hover:bg-white/5 hover:text-white"}`}>{c}</button>
                    ))}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="hidden items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-1 text-[9px] font-bold uppercase tracking-widest text-white/35 sm:inline-flex">
                      <span className="h-1.5 w-1.5 rounded-full bg-[#34e0a1]" /> synced
                    </span>
                    <span className="mono-data hidden rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-1 text-[9px] text-white/35 sm:inline">⌘K</span>
                  </div>
                </div>

                {/* Priority legend + counts */}
                <div className="flex flex-wrap items-center justify-between gap-3 px-4 pt-4 sm:px-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="priority-pill badge-urgent">{t("landing.badge.urgent")} 1</span>
                    <span className="priority-pill badge-high">{t("landing.badge.high")} 2</span>
                    <span className="priority-pill badge-medium">{t("landing.badge.medium")} 0</span>
                  </div>
                  <p className="mono-data text-[10px] uppercase tracking-widest text-white/30">{leadsByCity[activeCity].length} jobs · 60 min hold</p>
                </div>

                <div className="grid gap-3.5 p-4 sm:p-5 lg:grid-cols-3">
                  {leadsByCity[activeCity].map((lead) => {
                    const reserved = reservedLeadId === lead.id;
                    return (
                      <div key={lead.id} className={`relative flex flex-col justify-between overflow-hidden rounded-2xl border p-4 transition ${reserved ? "border-[#34e0a1]/60 bg-[#0a1a18] shadow-[0_0_40px_-12px_rgba(52,224,161,0.35)]" : "border-white/[0.08] bg-[#0b111d] hover:border-white/20"}`}>
                        {lead.badge === "urgent" && !reserved && <span className="pointer-events-none absolute -right-10 -top-10 h-24 w-24 rounded-full bg-[#f43f5e]/10 blur-2xl" />}
                        <div className="relative">
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span className={`priority-pill ${BADGE_STYLE[lead.badge]}`}>{lead.badgeLabel}</span>
                              <span className="mono-data text-[9px] uppercase tracking-wider text-white/25">#{lead.id}</span>
                            </div>
                            <span className="mono-data inline-flex items-center gap-1 text-[9px] text-white/35">
                              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>
                              {lead.timeAgo}
                            </span>
                          </div>

                          <h4 className="font-display mt-3 text-[17px] font-bold leading-tight tracking-[-0.01em] text-white">{lead.category}</h4>
                          <p className="mt-1 inline-flex items-center gap-1 text-[11px] font-semibold text-[#34e0a1]">
                            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" /><path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1 1 15 0Z" /></svg>
                            {lead.neighborhood}
                          </p>
                          <p className="mt-2.5 line-clamp-2 text-[11.5px] leading-relaxed text-white/50">{lead.description}</p>
                        </div>

                        <div className="relative mt-4 border-t border-white/[0.07] pt-3.5">
                          {reserved ? (
                            <div className="space-y-2.5">
                              <div>
                                <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-[#34e0a1]">
                                  <span className="inline-flex items-center gap-1.5"><span className="blink-dot" />{t("landing.reserved")}</span>
                                  <span className="mono-data">{fmtTimer(timerSeconds)}</span>
                                </div>
                                <div className="status-bar mt-2"><span style={{ width: `${Math.max(0, Math.min(100, (timerSeconds / 3600) * 100))}%` }} /></div>
                              </div>
                              <div className="rounded-lg border border-[#34e0a1]/20 bg-black/45 p-2.5">
                                <div className="flex items-center justify-between">
                                  <p className="text-[10px] font-bold uppercase tracking-wider text-white/35">{t("landing.owner")}</p>
                                  <span className="mono-data text-[9px] text-white/25">✓</span>
                                </div>
                                <p className="mt-0.5 text-[11px] font-bold text-white">{lead.ownerName}</p>
                                <p className="mono-data mt-0.5 text-[15px] font-black tracking-tight text-[#34e0a1]">{lead.ownerPhone}</p>
                                <p className="mono-data mt-1 text-[9px] text-white/30">{lead.address}</p>
                              </div>
                              <button onClick={() => setWhatsappLead(lead)} data-track="open_whatsapp" className="btn-mint flex w-full items-center justify-center gap-1.5 py-2.5 text-[11px] uppercase tracking-wider">{t("landing.openWa")}</button>
                            </div>
                          ) : (
                            <div className="space-y-2.5">
                              <div className="flex items-center justify-between text-[10px] text-white/40">
                                <span>{t("landing.address")}</span>
                                <span className="mono-data text-white/70">{lead.address}</span>
                              </div>
                              <button onClick={() => { setReservedLeadId(lead.id); setTimerSeconds(3600); }} data-track="reserve_hour" className="flex w-full items-center justify-center gap-2 rounded-lg border border-[#34e0a1]/35 bg-[#34e0a1]/[0.08] py-2.5 text-[11px] font-bold text-[#34e0a1] transition hover:bg-[#34e0a1] hover:text-[#04120d]">
                                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 0h10.5a1.5 1.5 0 0 1 1.5 1.5v7.5a1.5 1.5 0 0 1-1.5 1.5H6.75a1.5 1.5 0 0 1-1.5-1.5v-7.5a1.5 1.5 0 0 1 1.5-1.5Z" /></svg>
                                {t("landing.reserveHour")}
                                <span className="mono-data ml-0.5 rounded bg-black/20 px-1.5 py-0.5 text-[9px]">60m</span>
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.07] bg-[#0a101b] px-4 py-3.5 text-xs sm:px-5">
                  <span className="inline-flex items-center gap-2 text-white/35">
                    <svg className="h-3.5 w-3.5 text-[#34e0a1]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>
                    {t("landing.payOk")}
                  </span>
                  <button onClick={openModal} data-track="unlock_cta" className="inline-flex items-center gap-1.5 font-bold text-[#34e0a1] hover:text-white">{t("landing.unlock4")}<svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" /></svg></button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* COMPARATIVO */}
      <section id="comparativo" className="landing-dark relative scroll-mt-20 overflow-hidden bg-[#070a12] py-20 md:py-28">
        <div className="pointer-events-none absolute -left-32 top-10 h-[420px] w-[420px] rounded-full bg-[#7c5cff]/[0.12] blur-[130px]" />
        <div className="pointer-events-none absolute -right-24 bottom-0 h-[460px] w-[460px] rounded-full bg-[#10b981]/[0.12] blur-[140px]" />
        <div className="relative mx-auto max-w-7xl px-4 sm:px-6">
          <div className="max-w-3xl">
            <span className="eyebrow"><span className="dot" style={{ background: "#a78bfa", boxShadow: "0 0 10px #a78bfa" }} />{t("landing.compareKicker")}</span>
            <h2 className="font-display mt-5 text-[2.4rem] font-black leading-[0.98] tracking-[-0.035em] text-white sm:text-5xl md:text-[3.2rem]">
              {t("landing.compareTitle")} <span className="hl">{t("landing.compareHl")}</span>
            </h2>
            <p className="mt-6 text-base leading-relaxed text-[#9fb0c6] sm:text-lg">{t("landing.compareSub")}</p>
          </div>

          <div className="mt-14 grid gap-4 lg:grid-cols-12">
            {winner && (
              <article className="relative overflow-hidden rounded-[1.7rem] border border-[#34e0a1]/35 bg-gradient-to-b from-[#0a1c19] via-[#08131a] to-[#070c14] p-7 shadow-[0_40px_100px_-40px_rgba(16,185,129,0.45)] sm:p-8 lg:col-span-5">
                <div className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-[#34e0a1]/[0.18] blur-3xl" />
                <div className="relative flex h-full flex-col">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-[#34e0a1] px-3 py-1 text-[9px] font-black uppercase tracking-[0.14em] text-[#04120d]">
                      <svg className="h-3 w-3" viewBox="0 0 24 24" fill="currentColor"><path d="m13 2-9 12h7l-1 8 10-13h-7V2Z" /></svg>
                      {t("landing.best")}
                    </span>
                    <span className="ai-chip">{winner.exclusivity}</span>
                  </div>

                  <h3 className="font-display mt-6 text-3xl font-black tracking-[-0.03em] text-white">{winner.channel}</h3>
                  <p className="mt-1 text-sm text-white/50">{winner.sub}</p>

                  <div className="mt-7">
                    <p className="font-display text-5xl font-black tracking-[-0.04em] text-white">{winner.cost}</p>
                    <p className="mt-1 text-xs font-bold uppercase tracking-[0.14em] text-white/40">{winner.costLabel}</p>
                  </div>

                  <div className="mt-7 space-y-3 border-t border-white/10 pt-6 text-sm">
                    {[
                      [t("landing.excl"), winner.exclusivity],
                      [t("landing.intentL"), winner.intent],
                      [t("landing.phoneL"), winner.phone],
                    ].map(([label, value]) => (
                      <div key={label} className="flex items-center justify-between gap-3">
                        <span className="text-white/45">{label}</span>
                        <span className="inline-flex items-center gap-1.5 text-right font-bold text-white">
                          <svg className="h-3.5 w-3.5 text-[#34e0a1]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
                          {value}
                        </span>
                      </div>
                    ))}
                  </div>

                  <div className="mt-auto pt-8">
                    <button onClick={openModal} data-track="compare_cta" className="btn-mint w-full py-3.5 text-sm">{t("landing.ctaPanel")}</button>
                    <p className="mt-3 text-center text-[10px] font-bold uppercase tracking-[0.14em] text-[#8ff5c8]">✓ {t("landing.trust2")} · ✓ {t("landing.trust3")}</p>
                  </div>
                </div>
              </article>
            )}

            <div className="grid gap-4 lg:col-span-7">
              {rivals.map((c, i) => (
                <article key={c.channel} className="bento-card group flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:gap-5">
                  <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-white/10 bg-white/[0.04] text-white/45 transition group-hover:text-white/70">
                    {i === 0 && <Megaphone className="h-5 w-5" />}
                    {i === 1 && <Search className="h-5 w-5" />}
                    {i === 2 && <Users className="h-5 w-5" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                      <div>
                        <h3 className="font-display text-lg font-black tracking-[-0.01em] text-white">{c.channel}</h3>
                        <p className="text-[11px] text-white/35">{c.sub}</p>
                      </div>
                      <div className="text-right">
                        <p className="mono-data text-xl font-black text-white/80">{c.cost}</p>
                        <p className="text-[9px] font-bold uppercase tracking-wider text-white/30">{c.costLabel}</p>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-white/[0.06] pt-3 text-[11px]">
                      <span className="inline-flex items-center gap-1.5 text-white/35"><span className="text-[#f43f5e]">✕</span>{t("landing.excl")}: <span className="text-white/60">{c.exclusivity}</span></span>
                      <span className="inline-flex items-center gap-1.5 text-white/35"><span className="text-[#f43f5e]">✕</span>{t("landing.intentL")}: <span className="text-white/60">{c.intent}</span></span>
                      <span className="inline-flex items-center gap-1.5 text-white/35"><span className="text-[#f43f5e]">✕</span>{t("landing.phoneL")}: <span className="text-white/60">{c.phone}</span></span>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* COMO FUNCIONA */}
      <section id="como-funciona" className="surface-light relative scroll-mt-20 py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="eyebrow eyebrow-light mx-auto"><span className="dot" />{t("landing.howKicker")}</span>
            <h2 className="font-display mt-5 text-[2.3rem] font-black leading-[0.98] tracking-[-0.03em] text-[#0b1220] sm:text-5xl">
              {t("landing.howTitle")} <span className="hl">{t("landing.howHl")}</span>
            </h2>
          </div>
          <div className="relative mt-16 grid gap-5 md:grid-cols-3">
            <div className="pointer-events-none absolute left-[12%] right-[12%] top-12 hidden h-px bg-white/10 md:block" />
            {(
              [
                { n: "01", tint: "#10b981", bg: "#10b98115", title: t("landing.step1t"), body: t("landing.step1b") },
                { n: "02", tint: "#7c5cff", bg: "#7c5cff15", title: t("landing.step2t"), body: t("landing.step2b"), featured: true },
                { n: "03", tint: "#f59e0b", bg: "#f59e0b15", title: t("landing.step3t"), body: t("landing.step3b") },
              ] as { n: string; tint: string; bg: string; title: string; body: string; featured?: boolean }[]
            ).map((s) => (
              <article key={s.n} className={`bento-light relative p-8 ${s.featured ? "ring-2 ring-[#7c5cff]/20" : ""}`}>
                <span className="relative z-10 flex h-14 w-14 items-center justify-center rounded-2xl font-display text-xl font-black ring-4 ring-white" style={{ background: s.bg, color: s.tint }}>{s.n}</span>
                <h3 className="font-display mt-6 text-xl font-bold tracking-[-0.02em] text-[#0b1220]">{s.title}</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-[#54617a]">{s.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* TEMPLATES */}
      <section id="templates" className="relative scroll-mt-20 bg-white py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="grid gap-12 lg:grid-cols-12 lg:items-center">
            <div className="lg:col-span-5">
              <span className="eyebrow eyebrow-light"><span className="dot" style={{ background: "#f43f5e", boxShadow: "0 0 10px #f43f5e" }} />{t("landing.tplKicker")}</span>
              <h2 className="font-display mt-5 text-[2.3rem] font-black leading-[0.98] tracking-[-0.03em] text-[#0b1220] sm:text-5xl">
                {t("landing.tplTitle")} <span className="hl">{t("landing.tplHl")}</span>
              </h2>
              <p className="mt-6 text-[15px] leading-relaxed text-[#54617a]">{t("landing.tplSub")}</p>
              <div className="mt-7 flex flex-wrap gap-2">
                {L.tradesLabel.map((label, i) => (
                  <button key={TRADE_KEYS[i]} onClick={() => setTplTrade(TRADE_KEYS[i])} className={`rounded-lg px-3.5 py-2 text-xs font-bold transition ${tplTrade === TRADE_KEYS[i] ? "bg-[#0b1220] text-white shadow-lg shadow-[#0b1220]/15" : "bg-[#f1f4f9] text-[#54617a] hover:bg-[#e8edf5]"}`}>{label}</button>
                ))}
              </div>
              <div className="mt-3 flex gap-2">
                {CHANNELS.map((c) => (
                  <button key={c} onClick={() => setTplChannel(c)} className={`rounded-lg px-3.5 py-2 text-xs font-bold uppercase tracking-wide transition ${tplChannel === c ? "bg-[#10b981] text-white shadow-lg shadow-[#10b981]/20" : "border border-[#e2e8f0] bg-white text-[#54617a] hover:border-[#10b981]/30"}`}>{c}</button>
                ))}
              </div>
            </div>
            <div className="lg:col-span-7">
              <div className="bento-light overflow-hidden">
                <div className="flex items-center justify-between gap-3 border-b border-[#eef1f6] bg-[#f8fafc] px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="flex gap-1.5">
                      <span className="h-2.5 w-2.5 rounded-full bg-[#fda4af]" />
                      <span className="h-2.5 w-2.5 rounded-full bg-[#fcd34d]" />
                      <span className="h-2.5 w-2.5 rounded-full bg-[#6ee7b7]" />
                    </span>
                    <span className="ml-2 text-[11px] font-bold text-[#54617a]">{L.tradesLabel[TRADE_KEYS.indexOf(tplTrade)]} · {tplChannel.toUpperCase()}</span>
                  </div>
                  <button onClick={() => copyTpl(L.templates[tplTrade][tplChannel])} className="btn-dark px-3.5 py-1.5 text-xs">{copied ? t("landing.copied") : t("landing.copy")}</button>
                </div>
                <div className="p-5 sm:p-6">
                  <div className="rounded-2xl border border-[#10b981]/15 bg-gradient-to-br from-[#e8f9ef] to-[#f4fdf8] p-5 shadow-inner">
                    <pre className="whitespace-pre-wrap font-sans text-[14px] leading-relaxed text-[#123326]">{L.templates[tplTrade][tplChannel]}</pre>
                  </div>
                  <p className="mt-4 text-xs text-[#94a3b8]">{t("landing.tplFields")}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <FoldWave from="#ffffff" to="#070a12" />

      {/* CALCULADORA */}
      <section id="calculadora" className="landing-dark aurora-dark relative scroll-mt-20 overflow-hidden py-20 text-white md:py-24">
        <div className="pointer-events-none absolute inset-0 grid-fade opacity-50" />
        <div className="relative mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="eyebrow mx-auto"><span className="dot" />{t("landing.calcKicker")}</span>
            <h2 className="font-display mt-5 text-[2.4rem] font-black leading-[0.98] tracking-[-0.035em] sm:text-5xl">
              {t("landing.calcTitle")} <span className="hl">{t("landing.calcHl")}</span>
            </h2>
            <p className="mx-auto mt-5 max-w-2xl text-base text-[#9fb0c6] sm:text-lg">{t("landing.calcSub")}</p>
          </div>

          <div className="mt-14 grid items-start gap-5 lg:grid-cols-12">
            <div className="glass-panel rounded-[1.6rem] p-6 sm:p-8 lg:col-span-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[10px] font-black uppercase tracking-[0.16em] text-white/35">{t("landing.ticketAvg")}</p>
                  <p className="mono-data mt-2 text-4xl font-black tracking-tight text-white sm:text-5xl">${ticketValue.toLocaleString("en-US")}</p>
                </div>
                <span className="mono-data grid h-10 w-10 place-items-center rounded-xl bg-[#34e0a1]/10 text-lg font-black text-[#34e0a1] ring-1 ring-[#34e0a1]/20">$</span>
              </div>
              <input type="range" min={2000} max={15000} step={500} value={ticketValue} onChange={(e) => setTicketValue(Number(e.target.value))} className="range-dark mt-5 w-full" />
              <div className="mt-2 flex justify-between text-[10px] font-bold uppercase tracking-widest text-white/25">
                <span>$2,000</span><span>$15,000</span>
              </div>

              <div className="mt-7 flex items-center justify-between rounded-xl border border-white/[0.08] bg-white/[0.035] px-4 py-3">
                <div>
                  <p className="text-xs font-bold text-white/80">{t("landing.closes20")}</p>
                  <p className="mt-0.5 text-[10px] text-white/35">{t("landing.calcNote")}</p>
                </div>
                <span className="mono-data shrink-0 rounded-lg bg-white/[0.06] px-3 py-1.5 text-xl font-black text-white/70 ring-1 ring-white/10">5%</span>
              </div>

              <div className="mt-5 grid grid-cols-3 gap-2.5 text-center">
                <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] px-2 py-3">
                  <p className="mono-data text-lg font-black text-white">300</p>
                  <p className="mt-0.5 text-[9px] font-bold uppercase tracking-wider text-white/35">{t("landing.leadsM")}</p>
                </div>
                <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] px-2 py-3">
                  <p className="mono-data text-lg font-black text-white">~{validatedPhones}</p>
                  <p className="mt-0.5 text-[9px] font-bold uppercase tracking-wider text-white/35">{t("landing.withPh")}</p>
                </div>
                <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] px-2 py-3">
                  <p className="mono-data text-lg font-black text-white">~{estimatedVisits}</p>
                  <p className="mt-0.5 text-[9px] font-bold uppercase tracking-wider text-white/35">{t("landing.visitsL")}</p>
                </div>
              </div>
            </div>

            <div className="relative flex flex-col justify-between overflow-hidden rounded-[1.6rem] bg-gradient-to-br from-[#10b981] via-[#0a8f65] to-[#064e3b] p-6 shadow-[0_40px_100px_-40px_rgba(16,185,129,0.6)] sm:p-8 lg:col-span-6">
              <div className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-white/20 blur-3xl" />
              <div className="relative">
                <div className="flex items-center justify-between">
                  <span className="rounded-full bg-white/20 px-3 py-1 text-[10px] font-black uppercase tracking-[0.12em] backdrop-blur">{t("landing.revEst")}</span>
                  <span className="mono-data text-[10px] font-bold text-white/60">5% · 60m</span>
                </div>
                <p className="font-display mt-5 text-5xl font-black tracking-[-0.04em] text-white sm:text-6xl">${monthlyRevenue.toLocaleString("en-US")}<span className="ml-1 text-xl font-bold tracking-normal text-white/55">{t("landing.perMo")}</span></p>
                <p className="mt-2 text-sm font-bold text-white/85">{L.aboutJobs(closedJobs, ticketValue.toLocaleString("en-US"))}</p>
              </div>

              <div className="relative my-6 space-y-2.5 rounded-xl border border-white/15 bg-black/15 p-4 text-sm font-semibold backdrop-blur-sm">
                <div className="flex justify-between"><span className="text-white/70">{t("landing.invest")}</span><span className="mono-data text-white">$520{t("landing.perMo")}</span></div>
                <div className="flex justify-between"><span className="text-white/70">{t("landing.costDelivered")}</span><span className="mono-data text-white">~$2.48</span></div>
                <div className="flex items-center justify-between border-t border-white/15 pt-2.5 text-base"><span>{t("landing.onePays")}</span><span className="mono-data rounded-lg bg-[#04231a] px-2.5 py-0.5 text-[#34e0a1]">{monthsPaid} {t("landing.months")}</span></div>
              </div>

              <div className="relative">
                <button onClick={openModal} data-track="calc_cta" className="w-full rounded-xl bg-white py-4 text-sm font-black uppercase tracking-[0.08em] text-[#0a8f65] shadow-lg shadow-black/20 transition hover:-translate-y-0.5 hover:bg-[#f0fdf8]">{t("landing.calcCta")}</button>
                <p className="mt-3 text-center text-[10px] font-black uppercase tracking-[0.12em] text-white/80">✓ {t("landing.trust2")} · ✓ {t("landing.trust3")}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <FoldWave from="#070a12" to="#ffffff" />

      {/* RESULTADOS */}
      <section className="surface-light py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="max-w-3xl">
            <span className="eyebrow eyebrow-light"><span className="dot" style={{ background: "#f59e0b", boxShadow: "0 0 10px #f59e0b" }} />{t("landing.resultsKicker")}</span>
            <h2 className="font-display mt-5 text-[2.3rem] font-black leading-[0.98] tracking-[-0.03em] text-[#0b1220] sm:text-5xl">
              {t("landing.resultsTitle")} <span className="hl">{t("landing.resultsHl")}</span>
            </h2>
          </div>
          <div className="mt-14 grid gap-5 md:grid-cols-3">
            {L.quotes.map((q, i) => (
              <figure key={q.name} className="bento-light relative flex flex-col overflow-hidden p-7">
                <span className="pointer-events-none absolute right-4 top-2 font-display text-[5rem] leading-none text-[#0b1220]/[0.05]">”</span>
                <div className="flex items-center justify-between">
                  <div className="text-[#f59e0b]">★★★★★</div>
                  <span className="h-1.5 w-1.5 rounded-full bg-[#10b981] shadow-[0_0_8px_#10b981]" />
                </div>
                <blockquote className="relative mt-4 flex-1 text-[15px] leading-relaxed text-[#3f4a5e]">"{q.text}"</blockquote>
                <figcaption className="mt-6 flex items-center gap-3 border-t border-[#eef1f6] pt-5">
                  <span className="flex h-11 w-11 items-center justify-center rounded-full text-sm font-black text-white shadow-lg" style={{ background: AVATAR_GRAD[i % AVATAR_GRAD.length] }}>{q.init}</span>
                  <div><p className="text-sm font-black text-[#0b1220]">{q.name}</p><p className="text-xs text-[#94a3b8]">{q.role}</p></div>
                </figcaption>
                <span className="mt-4 inline-flex w-fit rounded-lg bg-[#e8f9ef] px-3 py-1.5 text-[11px] font-black text-[#0a8f65] ring-1 ring-[#10b981]/15">{q.badge}</span>
              </figure>
            ))}
          </div>
        </div>
      </section>

      {/* PREÇO */}
      <section id="preco" className="landing-dark aurora-dark relative scroll-mt-20 overflow-hidden py-20 md:py-28">
        <div className="pointer-events-none absolute inset-0 grid-fade opacity-40" />
        <div className="relative mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="eyebrow mx-auto"><span className="dot" />{t("landing.priceKicker")}</span>
            <h2 className="font-display mt-5 text-[2.4rem] font-black leading-[0.98] tracking-[-0.035em] text-white sm:text-5xl">
              {t("landing.priceTitle")} <span className="hl">{t("landing.priceHl")}</span>
            </h2>
          </div>

          <div className="mx-auto mt-14 grid max-w-6xl gap-5 lg:grid-cols-[1.08fr_0.92fr]">
            <div className="relative overflow-hidden rounded-[1.7rem] border border-[#34e0a1]/30 bg-gradient-to-b from-[#0a1c19] via-[#08131a] to-[#070c14] p-7 shadow-[0_50px_120px_-50px_rgba(16,185,129,0.55)] sm:p-9">
              <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[#34e0a1]/[0.16] blur-3xl" />
              <div className="relative">
                <div className="flex items-center justify-between">
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-[#34e0a1]/30 bg-[#34e0a1]/10 px-3 py-1 text-[10px] font-black uppercase tracking-[0.14em] text-[#34e0a1]">
                    <span className="blink-dot" />{t("landing.planTag")}
                  </span>
                  <span className="mono-data text-[10px] uppercase tracking-widest text-white/30">{t("landing.trust3")}</span>
                </div>

                <div className="mt-6 flex items-end gap-3">
                  <span className="font-display text-6xl font-black tracking-[-0.05em] text-white sm:text-7xl">$120</span>
                  <span className="mb-2 text-sm font-semibold text-white/45">{t("landing.week")}<br /><span className="text-xs text-white/30">{t("landing.month")}</span></span>
                </div>
                <p className="mt-3 text-sm text-white/50">{t("landing.planSub")}</p>

                <div className="my-6 h-px bg-white/10" />

                <ul className="grid gap-3 text-[14px] sm:grid-cols-2">
                  {L.planFeatures.map((f) => (
                    <li key={f} className="flex items-start gap-2.5">
                      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#34e0a1]/12 text-[#34e0a1] ring-1 ring-[#34e0a1]/20">✓</span>
                      <span className="text-white/75">{f}</span>
                    </li>
                  ))}
                </ul>

                <button onClick={openModal} data-track="plan_cta" className="btn-mint mt-8 w-full py-4 text-sm uppercase tracking-[0.1em]">{t("landing.planCta")}</button>

                <div className="mt-4 rounded-xl border border-[#34e0a1]/25 bg-[#34e0a1]/[0.08] px-4 py-3 text-center">
                  <p className="text-[11px] font-black uppercase tracking-[0.1em] text-[#8ff5c8]">✓ {t("landing.trust2")} · ✓ {t("landing.trust3")}</p>
                  {L.quotes[0] && (
                    <p className="mt-1.5 text-[11px] font-semibold text-white/65">“{L.quotes[0].badge}” — {L.quotes[0].name}, {L.quotes[0].role}</p>
                  )}
                </div>
                <p className="mt-3 text-center text-[10px] font-semibold uppercase tracking-[0.1em] text-white/30">{t("landing.planSafe")}</p>
              </div>
            </div>

            <div className="flex flex-col gap-4">
              <div className="glass-panel rounded-[1.4rem] p-6">
                <p className="font-display text-lg font-bold text-white">{t("landing.billing")}</p>
                <ol className="mt-4 space-y-3 text-sm text-white/55">
                  {[t("landing.bill1"), t("landing.bill2"), t("landing.bill3")].map((step, i) => (
                    <li key={step} className="flex gap-3">
                      <span className="mono-data grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-[#34e0a1]/12 text-[11px] font-black text-[#34e0a1] ring-1 ring-[#34e0a1]/20">{i + 1}</span>
                      <span className="pt-0.5">{step}</span>
                    </li>
                  ))}
                </ol>
              </div>

              <div className="glass-panel rounded-[1.4rem] p-6">
                <p className="font-display text-lg font-bold text-white">{t("landing.never")}</p>
                <ul className="mt-4 space-y-2.5 text-sm text-white/55">
                  {L.neverItems.map((n) => (
                    <li key={n} className="flex gap-2.5"><span className="mt-0.5 text-[#f43f5e]">✕</span>{n}</li>
                  ))}
                </ul>
              </div>

              <div className="rounded-[1.4rem] border border-[#f59e0b]/25 bg-[#f59e0b]/[0.07] p-6">
                <div className="flex items-center gap-2">
                  <span className="grid h-8 w-8 place-items-center rounded-lg bg-[#f59e0b]/15 text-[#fbbf24]">
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" /></svg>
                  </span>
                  <p className="font-display text-lg font-black text-[#fbbf24]">{t("landing.noRenew")}</p>
                </div>
                <p className="mt-2 text-sm text-white/50">{t("landing.risk79")}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="surface-light scroll-mt-20 py-20 md:py-28">
        <div className="mx-auto grid max-w-7xl gap-12 px-4 sm:px-6 lg:grid-cols-[0.85fr_1.15fr]">
          <div>
            <span className="eyebrow eyebrow-light"><span className="dot" style={{ background: "#f43f5e", boxShadow: "0 0 10px #f43f5e" }} />{t("landing.faqKicker")}</span>
            <h2 className="font-display mt-5 text-[2.3rem] font-black leading-[0.98] tracking-[-0.03em] text-[#0b1220] sm:text-5xl">{t("landing.faqTitle")}</h2>
            <p className="mt-6 text-[15px] leading-relaxed text-[#54617a]">{t("landing.faqSub")}</p>
            <button onClick={openModal} data-track="faq_cta" className="btn-dark mt-7 px-6 py-3.5 text-sm">{t("landing.faqCta")}</button>
            <div className="mt-8 rounded-2xl border border-[#10b981]/15 bg-white/70 p-5">
              <p className="text-[10px] font-black uppercase tracking-[0.14em] text-[#0a8f65]">{t("landing.trust2")}</p>
              <p className="mt-1 text-sm font-semibold text-[#0b1220]">✓ {t("landing.trust2")} · ✓ {t("landing.trust3")}</p>
            </div>
          </div>
          <div className="space-y-3">
            {L.faqs.map((f, i) => {
              const open = openFaq === i;
              return (
                <div key={f.q} className={`overflow-hidden rounded-2xl border bg-white transition ${open ? "border-[#10b981]/30 shadow-[0_24px_60px_-34px_rgba(16,185,129,0.35)]" : "border-[#e6ebf2] shadow-[0_14px_40px_-30px_rgba(15,23,42,0.35)]"}`}>
                  <button onClick={() => setOpenFaq(open ? null : i)} className="flex w-full items-center justify-between gap-4 p-5 text-left">
                    <span className="font-display text-[16px] font-bold tracking-[-0.01em] text-[#0b1220]">{f.q}</span>
                    <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition ${open ? "bg-[#0b1220] text-[#34e0a1]" : "bg-[#f1f4f9] text-[#54617a]"}`}>
                      <svg className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" /></svg>
                    </span>
                  </button>
                  {open && <p className="px-5 pb-5 text-[14px] leading-relaxed text-[#54617a]">{f.a}</p>}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* CTA FINAL */}
      <section className="landing-dark aurora-dark relative overflow-hidden py-24 text-center text-white">
        <div className="pointer-events-none absolute inset-0 grid-fade opacity-50" />
        <div className="pointer-events-none absolute left-1/2 top-0 h-[440px] w-[820px] -translate-x-1/2 rounded-full bg-[#10b981]/[0.14] blur-[150px]" />
        <div className="relative mx-auto max-w-4xl px-4">
          <span className="eyebrow mx-auto"><span className="blink-dot" />{t("landing.finalKicker")}</span>
          <h2 className="font-display mt-6 text-[2.7rem] font-black leading-[0.95] tracking-[-0.04em] sm:text-6xl">
            {t("landing.finalTitle")}<br />
            <span className="hl">{t("landing.finalHl")}</span>
          </h2>
          <p className="mx-auto mt-6 max-w-xl text-base text-[#9fb0c6] sm:text-lg">{t("landing.finalSub")}</p>
          <button onClick={openModal} data-track="final_cta" className="btn-mint mx-auto mt-9 inline-flex items-center gap-2.5 px-9 py-4 text-sm uppercase tracking-[0.1em]">{t("landing.finalCta")}</button>
          <div className="glass-panel mx-auto mt-6 flex max-w-xl flex-col items-center gap-2 rounded-2xl px-5 py-4">
            <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-[11px] font-black uppercase tracking-[0.12em] text-[#8ff5c8]">
              <span>✓ {t("landing.trust2")}</span>
              <span>✓ {t("landing.trust3")}</span>
              <span>✓ {t("landing.trust1")}</span>
            </div>
            {L.quotes[0] && <p className="text-[11px] font-semibold text-white/60">“{L.quotes[0].badge}” — {L.quotes[0].name}, {L.quotes[0].role}</p>}
          </div>
          <p className="mt-4 text-[10px] font-semibold uppercase tracking-[0.12em] text-white/30">{t("landing.finalFoot")}</p>
        </div>
      </section>

      {/* STICKY MOBILE */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-white/10 bg-[#070a12]/95 px-4 py-3 backdrop-blur-xl sm:hidden">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-display text-lg font-black leading-none text-white">$120<span className="text-xs font-bold text-white/40">{t("landing.week")}</span></p>
            <p className="text-[11px] font-bold text-[#34e0a1]">{t("landing.stickyArea")}</p>
            <p className="text-[10px] font-bold text-[#8ff5c8]">✓ {t("landing.trust2")} · ✓ {t("landing.trust3")}</p>
          </div>
          <button onClick={openModal} data-track="sticky_cta" className="btn-mint flex-1 py-3 text-sm">{t("landing.stickyNow")}</button>
        </div>
      </div>

      {/* MODAL WHATSAPP */}
      {whatsappLead && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0b1220]/60 p-4 backdrop-blur-sm" onClick={() => setWhatsappLead(null)}>
          <div className="relative w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => setWhatsappLead(null)} className="absolute right-4 top-4 text-[#94a3b8]">✕</button>
            <div className="flex items-center gap-3 border-b border-[#eef1f6] pb-4">
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-[#25D366] text-white font-black">W</div>
              <div><p className="text-sm font-bold">{whatsappLead.ownerName}</p><p className="font-mono text-xs text-[#10b981]">{whatsappLead.ownerPhone}</p></div>
            </div>
            <div className="my-4 rounded-2xl bg-[#dcf8c6] p-4 text-sm leading-relaxed">
              {L.waMsg(whatsappLead.ownerName.split(" ")[0], whatsappLead.category.toLowerCase(), whatsappLead.address)}
            </div>
            <button onClick={() => { setWhatsappLead(null); openModal(); }} data-track="activate_send" className="btn-mint w-full py-3.5 text-sm uppercase tracking-wider">{t("landing.activateSend")}</button>
          </div>
        </div>
      )}
    </>
  );
}