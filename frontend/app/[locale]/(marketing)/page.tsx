'use client';

import { useEffect, useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { fetchPublicMetrics } from "@/lib/api-client";
import type { PublicMetrics } from "@/lib/api-client";
import { useLandingShell } from "@/components/landing/LandingShell";
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
      <section id="topo" className="relative overflow-hidden bg-[#06080b]">
        <div className="dark-grid pointer-events-none absolute inset-0" />
        <div className="pointer-events-none absolute -top-48 left-1/2 h-[620px] w-[1100px] -translate-x-1/2 rounded-full bg-[#19c37d]/[0.05] blur-[160px]" />
        <div className="relative mx-auto max-w-7xl px-4 pb-16 pt-14 sm:px-6 md:pb-24 md:pt-20">
          <div className="mx-auto max-w-4xl text-center">
            <div className="eyebrow-dark">
              <span className="dot" />
              {hasMetrics ? `${leadsBank.toLocaleString("en-US")} ${t("landing.heroKicker")}` : t("landing.heroLoading")}
            </div>

            <h1 className="font-display mt-7 text-[2.65rem] font-black leading-[0.95] tracking-[-0.05em] text-white sm:text-6xl lg:text-[4.55rem]">
              {t("landing.heroTitle1")}
              <br />
              <span className="text-white/38">{t("landing.heroTitle2")}</span>
            </h1>

            <p className="mx-auto mt-7 max-w-2xl text-base leading-relaxed text-white/50 sm:text-lg">
              {t("landing.heroSub")}
            </p>

            <div className="mt-8 flex flex-col items-stretch justify-center gap-3 sm:flex-row">
              <button onClick={openModal} data-track="hero_cta" className="btn-emerald px-7 py-3.5 text-[14px]">
                {t("landing.ctaPanel")}
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.4}><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" /></svg>
              </button>
              <button onClick={() => scrollTo("simulador")} data-track="sample_cta" className="btn-ghost-dark px-6 py-3.5 text-[14px]">
                {t("landing.ctaSample")}
              </button>
            </div>

            <div className="mt-7 flex flex-col items-center gap-2 text-[10.5px] font-bold uppercase tracking-[0.13em] text-white/55 sm:flex-row sm:flex-wrap sm:justify-center sm:gap-x-5">
              {L.trust.map((item) => (
                <span key={item} className="inline-flex items-center gap-1.5">
                  <svg className="h-3.5 w-3.5 text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.6}><path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
                  {item}
                </span>
              ))}
            </div>
            {L.quotes[0] && (
              <p className="mt-3 flex flex-wrap items-center justify-center gap-2 text-[12px] leading-relaxed text-white/40">
                <span className="text-white/60">★★★★★</span>
                <span>&ldquo;{L.quotes[0].badge}&rdquo; &mdash; {L.quotes[0].name}, {L.quotes[0].role}</span>
              </p>
            )}
            <p className="mt-2.5 text-[10.5px] text-white/25">{t("landing.priceLine")}</p>
          </div>

          <div className="relative mx-auto mt-12 max-w-6xl">
            <div className="app-window">
              <div className="app-chrome">
                <div className="flex gap-1.5">
                  <span className="app-dot" /><span className="app-dot" /><span className="app-dot" />
                </div>
                <div className="ml-1 flex flex-1 items-center gap-2 rounded-md border border-white/[0.06] bg-black/25 px-2.5 py-1">
                  <svg className="h-3 w-3 text-white/30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 0h10.5a1.5 1.5 0 0 1 1.5 1.5v7.5a1.5 1.5 0 0 1-1.5 1.5H6.75a1.5 1.5 0 0 1-1.5-1.5v-7.5a1.5 1.5 0 0 1 1.5-1.5Z" /></svg>
                  <span className="truncate text-[10px] tracking-tight text-white/35">app.magicleads.app/workspace</span>
                </div>
                <span className="inline-flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.16em] text-white/40">
                  <span style={{ width: 5, height: 5, borderRadius: 9999, background: "#8b95a5" }} />
                  live
                </span>
              </div>
              <div className="hidden sm:block">
                <img src="/img/app-dashboard.png" alt="Magic Leads workspace dashboard with live opportunities, counters and trade filters" width={1920} height={1080} fetchPriority="high" />
              </div>
              <div className="sm:hidden">
                <img src="/img/app-dashboard-mobile.png" alt="Magic Leads workspace on mobile with live opportunities and counters" width={780} height={1688} className="block w-full object-cover object-top" style={{ height: 560 }} />
              </div>
            </div>
            <div className="mt-3 flex flex-col items-start justify-between gap-2 sm:flex-row sm:items-center">
              <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-white/35">
                Real workspace &middot; captured from the product, not a mockup
              </p>
              <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-white/25">Exclusive Clients &middot; New York</p>
            </div>
          </div>

          <div className="mt-14 grid grid-cols-1 border-y border-white/[0.07] sm:grid-cols-3">
            <div className="metric-cell px-1 py-6 sm:px-7">
              <p className="mono-data text-3xl font-black tracking-[-0.03em] text-white">{hasMetrics ? `${leadsBank.toLocaleString("en-US")}+` : "—"}</p>
              <p className="mt-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-white/35">{t("landing.statBank")}</p>
            </div>
            <div className="metric-cell px-1 py-6 sm:px-7">
              <p className="mono-data text-3xl font-black tracking-[-0.03em] text-white">{hasMetrics ? `${withOwner.toLocaleString("en-US")}+` : "—"}</p>
              <p className="mt-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-white/35">{t("landing.statOwner")}</p>
            </div>
            <div className="metric-cell px-1 py-6 sm:px-7">
              <p className="mono-data text-3xl font-black tracking-[-0.03em] text-white">{citiesCount}+</p>
              <p className="mt-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-white/35">{t("landing.statCities")}</p>
            </div>
          </div>
          <p className="mt-5 text-[10px] font-medium uppercase tracking-[0.14em] text-white/25">
            {t("landing.updated")} {t("landing.agoLittle")}
            {hasMetrics && newThisRun > 0 && <span className="text-white/45"> &middot; {newThisRun.toLocaleString("en-US")} {t("landing.updatedNew")}</span>}
          </p>
        </div>
      </section>

      {/* FIELD / HOW IT WORKS */}
      <section id="como-funciona" className="border-y border-white/[0.06] bg-[#080b0f] py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="grid items-center gap-12 lg:grid-cols-2 lg:gap-16">
            <div className="photo-mono aspect-[4/3]">
              <img src="/img/contractor-on-phone.jpg" alt="Contractor taking a call on site" loading="lazy" />
              <div className="absolute inset-x-0 bottom-0 z-10 p-6 sm:p-8">
                <p className="max-w-sm text-lg font-semibold leading-snug text-white">{t("landing.step3t")}</p>
              </div>
            </div>

            <div>
              <span className="eyebrow-dark"><span className="dot" />{t("landing.howKicker")}</span>
              <h2 className="font-display mt-5 text-[2.2rem] font-black leading-[0.98] tracking-[-0.04em] text-white sm:text-5xl">
                {t("landing.howTitle")} <span className="text-white/38">{t("landing.howHl")}</span>
              </h2>
              <div className="mt-9 divide-y divide-white/[0.07] border-y border-white/[0.07]">
                {[
                  { n: "01", title: t("landing.step1t"), body: t("landing.step1b") },
                  { n: "02", title: t("landing.step2t"), body: t("landing.step2b") },
                  { n: "03", title: t("landing.step3t"), body: t("landing.step3b") },
                ].map((step) => (
                  <div key={step.n} className="grid grid-cols-[44px_1fr] gap-4 py-5">
                    <span className="mono-data pt-0.5 text-[11px] font-bold text-white/25">{step.n}</span>
                    <div>
                      <h3 className="text-[15px] font-bold tracking-[-0.01em] text-white">{step.title}</h3>
                      <p className="mt-1.5 text-[13.5px] leading-relaxed text-white/42">{step.body}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* COVERAGE */}
      <section className="bg-[#06080b] py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="max-w-3xl">
            <span className="eyebrow-dark"><span className="dot" />{t("landing.coverageKicker")}</span>
            <h2 className="font-display mt-5 text-[2.25rem] font-black leading-[0.98] tracking-[-0.04em] text-white sm:text-5xl">
              {t("landing.coverageTitle")} <span className="text-white/38">{t("landing.coverageHl")}</span>
            </h2>
            <p className="mt-6 max-w-2xl text-[15px] leading-relaxed text-white/45 sm:text-base">{t("landing.coverageSub")}</p>
          </div>

          <div className="mt-12 grid gap-4 md:grid-cols-3">
            {L.coverageItems.map((item, i) => (
              <article key={item.title} className="dark-panel relative p-6 sm:p-7">
                <div className="flex items-start justify-between">
                  <span className="grid h-11 w-11 place-items-center rounded-xl border border-white/10 bg-white/[0.03] text-white/55">
                    {item.icon === "phone" && <Phone className="h-5 w-5" />}
                    {item.icon === "building" && <Building2 className="h-5 w-5" />}
                    {item.icon === "shield" && <ShieldCheck className="h-5 w-5" />}
                  </span>
                  <span className="mono-data text-[10px] font-bold tracking-[0.12em] text-white/20">0{i + 1}</span>
                </div>
                <h3 className="mt-5 text-[17px] font-bold tracking-[-0.01em] text-white">{item.title}</h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-white/42">{item.desc}</p>
              </article>
            ))}
          </div>

          <div className="mt-10 border-t border-white/[0.07] pt-8">
            <div className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3 lg:grid-cols-4">
              {L.categories.map((cat) => (
                <div key={cat} className="flex items-center gap-2.5 border-b border-white/[0.05] py-2.5">
                  <span className="h-1 w-1 shrink-0 rounded-full bg-white/25" />
                  <span className="text-[13px] font-medium text-white/55">{cat}</span>
                </div>
              ))}
            </div>
            <div className="mt-8 flex flex-col items-start justify-between gap-4 rounded-xl border border-white/[0.07] bg-white/[0.02] px-5 py-4 sm:flex-row sm:items-center">
              <p className="max-w-2xl text-[13.5px] leading-relaxed text-white/55">{t("landing.coverageTrust")}</p>
              <span className="shrink-0 rounded-full border border-white/10 px-3 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-white/40">Owner verified</span>
            </div>
          </div>
        </div>
      </section>

      {/* PROBLEM */}
      <section className="border-y border-white/[0.06] bg-[#080b0f] py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="grid gap-12 lg:grid-cols-12 lg:gap-16">
            <div className="lg:col-span-5">
              <span className="eyebrow-dark"><span className="dot" style={{ background: "#f87171", boxShadow: "0 0 8px rgba(248,113,113,.6)" }} />{t("landing.problemKicker")}</span>
              <h2 className="font-display mt-5 text-[2.25rem] font-black leading-[0.98] tracking-[-0.04em] text-white sm:text-5xl">
                {t("landing.problemTitle")} <span className="text-white/38">{t("landing.problemHl")}</span>
              </h2>
              <p className="mt-6 max-w-md text-[15px] leading-relaxed text-white/45">{t("landing.problemSub")}</p>
              <button onClick={openModal} data-track="how_cta" className="btn-ghost-dark mt-8 px-5 py-3 text-[13px]">{t("landing.seeHow")}</button>
            </div>

            <div className="lg:col-span-7">
              <div className="divide-y divide-white/[0.07] border-y border-white/[0.07]">
                {L.problems.map((p) => (
                  <article key={p.kicker} className="grid gap-3 py-6 sm:grid-cols-[150px_1fr] sm:gap-6">
                    <p className="text-[10px] font-bold uppercase leading-relaxed tracking-[0.13em] text-[#f87171]/75">{p.kicker}</p>
                    <div>
                      <h3 className="text-lg font-bold tracking-[-0.01em] text-white">{p.title}</h3>
                      <p className="mt-1.5 text-[13.5px] leading-relaxed text-white/42">{p.body}</p>
                      <p className="mt-3 inline-flex rounded-md border border-white/[0.08] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-white/35">{t("landing.costWord")} {p.cost}</p>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* WORKSPACE */}
      <section id="simulador" className="scroll-mt-20 bg-[#06080b] py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="eyebrow-dark mx-auto"><span className="dot" />{t("landing.sampleKicker")}</span>
            <h2 className="font-display mt-5 text-[2.25rem] font-black leading-[0.98] tracking-[-0.04em] text-white sm:text-5xl">{t("landing.sampleTitle")}</h2>
            <p className="mx-auto mt-5 max-w-2xl text-[15px] leading-relaxed text-white/45 sm:text-base">{t("landing.sampleSub")}</p>
          </div>

          <div className="app-window mx-auto mt-12 max-w-6xl">
            <div className="app-chrome">
              <div className="flex gap-1.5"><span className="app-dot" /><span className="app-dot" /><span className="app-dot" /></div>
              <div className="ml-1 flex flex-1 items-center gap-2 rounded-md border border-white/[0.06] bg-black/25 px-2.5 py-1">
                <svg className="h-3 w-3 text-white/30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 0h10.5a1.5 1.5 0 0 1 1.5 1.5v7.5a1.5 1.5 0 0 1-1.5 1.5H6.75a1.5 1.5 0 0 1-1.5-1.5v-7.5a1.5 1.5 0 0 1 1.5-1.5Z" /></svg>
                <span className="truncate text-[10px] tracking-tight text-white/35">app.magicleads.app/workspace</span>
              </div>
              <span className="hidden text-[9px] font-bold uppercase tracking-[0.16em] text-white/35 sm:block">exclusive clients</span>
            </div>
            <div className="hidden sm:block">
              <img src="/img/app-dashboard-detail.png" alt="Live workspace with counters, trade filters and exclusive opportunity listings" width={1520} height={720} loading="lazy" />
            </div>
            <div className="sm:hidden">
              <img src="/img/app-dashboard-mobile.png" alt="Live workspace on mobile with counters and trade filters" width={780} height={1688} loading="lazy" className="block w-full object-cover object-top" style={{ height: 620 }} />
            </div>
          </div>

          <div className="mx-auto mt-6 flex max-w-6xl flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
            <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-white/25">Real interface &middot; live counters &middot; trade filters</p>
            <button onClick={openModal} data-track="unlock_cta" className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-white/60 transition hover:text-white">
              {t("landing.unlock4")}
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" /></svg>
            </button>
          </div>
        </div>
      </section>

      {/* COMPARISON */}
      <section id="comparativo" className="scroll-mt-20 border-y border-white/[0.06] bg-[#080b0f] py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="max-w-3xl">
            <span className="eyebrow-dark"><span className="dot" />{t("landing.compareKicker")}</span>
            <h2 className="font-display mt-5 text-[2.25rem] font-black leading-[0.98] tracking-[-0.04em] text-white sm:text-5xl">
              {t("landing.compareTitle")} <span className="text-white/38">{t("landing.compareHl")}</span>
            </h2>
            <p className="mt-6 text-[15px] leading-relaxed text-white/45 sm:text-base">{t("landing.compareSub")}</p>
          </div>

          <div className="mt-12 grid gap-4 lg:grid-cols-12">
            {winner && (
              <article className="relative overflow-hidden rounded-2xl border border-white/[0.10] bg-[#0a0d12] p-6 shadow-[0_30px_80px_-50px_rgba(0,0,0,0.9)] sm:p-8 lg:col-span-5">
                <div className="flex items-center justify-between">
                  <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-white/55">{t("landing.best")}</span>
                  <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-white/30">{winner.exclusivity}</span>
                </div>
                <h3 className="font-display mt-6 text-2xl font-black tracking-[-0.03em] text-white">{winner.channel}</h3>
                <p className="mt-1 text-[12px] text-white/35">{winner.sub}</p>
                <p className="mono-data mt-7 text-4xl font-black tracking-[-0.04em] text-white">{winner.cost}</p>
                <p className="mt-1 text-[10px] font-bold uppercase tracking-[0.14em] text-white/30">{winner.costLabel}</p>
                <div className="mt-7 space-y-3 border-t border-white/[0.08] pt-5">
                  {[
                    [t("landing.excl"), winner.exclusivity],
                    [t("landing.intentL"), winner.intent],
                    [t("landing.phoneL"), winner.phone],
                  ].map(([label, value]) => (
                    <div key={label} className="flex items-center justify-between gap-3 text-[13px]">
                      <span className="text-white/35">{label}</span>
                      <span className="inline-flex items-center gap-1.5 text-right font-semibold text-white/85">
                        <svg className="h-3.5 w-3.5 text-white/45" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.6}><path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
                        {value}
                      </span>
                    </div>
                  ))}
                </div>
                <button onClick={openModal} data-track="compare_cta" className="btn-emerald mt-8 w-full py-3 text-[13px]">{t("landing.ctaPanel")}</button>
                <p className="mt-3 text-center text-[9px] font-bold uppercase tracking-[0.12em] text-white/35">{t("landing.trust2")} &middot; {t("landing.trust3")}</p>
              </article>
            )}

            <div className="lg:col-span-7">
              <div className="divide-y divide-white/[0.07] border-y border-white/[0.07]">
                {rivals.map((c, i) => (
                  <article key={c.channel} className="grid gap-4 py-5 sm:grid-cols-[44px_1fr] sm:gap-5">
                    <span className="grid h-10 w-10 place-items-center rounded-lg border border-white/[0.08] text-white/35">
                      {i === 0 && <Megaphone className="h-4 w-4" />}
                      {i === 1 && <Search className="h-4 w-4" />}
                      {i === 2 && <Users className="h-4 w-4" />}
                    </span>
                    <div>
                      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                        <div>
                          <h3 className="text-[15px] font-bold tracking-[-0.01em] text-white/80">{c.channel}</h3>
                          <p className="text-[11px] text-white/30">{c.sub}</p>
                        </div>
                        <div className="text-right">
                          <p className="mono-data text-lg font-bold text-white/65">{c.cost}</p>
                          <p className="text-[9px] uppercase tracking-[0.1em] text-white/25">{c.costLabel}</p>
                        </div>
                      </div>
                      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-[11px] text-white/30">
                        <span>{t("landing.excl")}: <span className="text-white/50">{c.exclusivity}</span></span>
                        <span>{t("landing.intentL")}: <span className="text-white/50">{c.intent}</span></span>
                        <span>{t("landing.phoneL")}: <span className="text-white/50">{c.phone}</span></span>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
              <p className="mt-5 text-[10px] font-medium uppercase tracking-[0.14em] text-white/20">Public list prices &middot; shared or auctioned contacts</p>
            </div>
          </div>
        </div>
      </section>

      {/* TEMPLATES */}
      <section id="templates" className="scroll-mt-20 bg-[#06080b] py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="grid gap-12 lg:grid-cols-12 lg:items-center">
            <div className="lg:col-span-5">
              <span className="eyebrow-dark"><span className="dot" />{t("landing.tplKicker")}</span>
              <h2 className="font-display mt-5 text-[2.2rem] font-black leading-[0.98] tracking-[-0.04em] text-white sm:text-5xl">
                {t("landing.tplTitle")} <span className="text-white/38">{t("landing.tplHl")}</span>
              </h2>
              <p className="mt-6 text-[14px] leading-relaxed text-white/45">{t("landing.tplSub")}</p>
              <div className="mt-7 flex flex-wrap gap-1.5">
                {L.tradesLabel.map((label, i) => (
                  <button key={TRADE_KEYS[i]} onClick={() => setTplTrade(TRADE_KEYS[i])} className={`rounded-lg px-3 py-1.5 text-[11.5px] font-semibold transition ${tplTrade === TRADE_KEYS[i] ? "bg-white/[0.10] text-white" : "text-white/35 hover:bg-white/[0.04] hover:text-white/65"}`}>{label}</button>
                ))}
              </div>
              <div className="mt-2 flex gap-1.5">
                {CHANNELS.map((c) => (
                  <button key={c} onClick={() => setTplChannel(c)} className={`rounded-md px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.08em] transition ${tplChannel === c ? "bg-white/[0.10] text-white" : "text-white/30 hover:text-white/60"}`}>{c}</button>
                ))}
              </div>
            </div>
            <div className="lg:col-span-7">
              <div className="dark-panel overflow-hidden rounded-2xl">
                <div className="flex items-center justify-between gap-3 border-b border-white/[0.07] px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="flex gap-1.5"><span className="app-dot" /><span className="app-dot" /><span className="app-dot" /></span>
                    <span className="ml-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-white/35">{L.tradesLabel[TRADE_KEYS.indexOf(tplTrade)]} &middot; {tplChannel}</span>
                  </div>
                  <button onClick={() => copyTpl(L.templates[tplTrade][tplChannel])} className="btn-emerald px-3 py-1.5 text-[10.5px]">{copied ? t("landing.copied") : t("landing.copy")}</button>
                </div>
                <div className="p-5 sm:p-6">
                  <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-5">
                    <pre className="whitespace-pre-wrap font-sans text-[13.5px] leading-relaxed text-white/70">{L.templates[tplTrade][tplChannel]}</pre>
                  </div>
                  <p className="mt-4 text-[11px] text-white/25">{t("landing.tplFields")}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CALCULATOR */}
      <section id="calculadora" className="scroll-mt-20 border-y border-white/[0.06] bg-[#080b0f] py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="eyebrow-dark mx-auto"><span className="dot" />{t("landing.calcKicker")}</span>
            <h2 className="font-display mt-5 text-[2.25rem] font-black leading-[0.98] tracking-[-0.04em] text-white sm:text-5xl">
              {t("landing.calcTitle")} <span className="text-white/38">{t("landing.calcHl")}</span>
            </h2>
            <p className="mx-auto mt-5 max-w-2xl text-[14px] leading-relaxed text-white/45">{t("landing.calcSub")}</p>
          </div>

          <div className="mx-auto mt-12 grid max-w-5xl items-start gap-4 lg:grid-cols-2">
            <div className="dark-panel p-6 sm:p-8">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-white/30">{t("landing.ticketAvg")}</p>
                  <p className="mono-data mt-2 text-3xl font-black tracking-[-0.03em] text-white sm:text-4xl">${ticketValue.toLocaleString("en-US")}</p>
                </div>
                <span className="grid h-9 w-9 place-items-center rounded-lg border border-white/[0.08] text-[13px] font-bold text-white/40">$</span>
              </div>
              <input type="range" min={2000} max={15000} step={500} value={ticketValue} onChange={(e) => setTicketValue(Number(e.target.value))} className="range-dark mt-5 w-full" />
              <div className="mt-2 flex justify-between text-[9px] font-bold uppercase tracking-[0.12em] text-white/20"><span>$2,000</span><span>$15,000</span></div>

              <div className="mt-6 flex items-center justify-between border-t border-white/[0.07] pt-5">
                <div>
                  <p className="text-[12px] font-semibold text-white/70">{t("landing.closes20")}</p>
                  <p className="mt-0.5 text-[10px] leading-relaxed text-white/30">{t("landing.calcNote")}</p>
                </div>
                <span className="mono-data shrink-0 rounded-md border border-white/10 px-2.5 py-1 text-sm font-bold text-white/70">5%</span>
              </div>

              <div className="mt-5 grid grid-cols-3 divide-x divide-white/[0.06] border-y border-white/[0.06] py-4 text-center">
                <div><p className="mono-data text-base font-bold text-white/80">300</p><p className="mt-0.5 text-[8px] font-bold uppercase tracking-[0.1em] text-white/25">{t("landing.leadsM")}</p></div>
                <div><p className="mono-data text-base font-bold text-white/80">~{validatedPhones}</p><p className="mt-0.5 text-[8px] font-bold uppercase tracking-[0.1em] text-white/25">{t("landing.withPh")}</p></div>
                <div><p className="mono-data text-base font-bold text-white/80">~{estimatedVisits}</p><p className="mt-0.5 text-[8px] font-bold uppercase tracking-[0.1em] text-white/25">{t("landing.visitsL")}</p></div>
              </div>
            </div>

            <div className="dark-panel relative overflow-hidden p-6 sm:p-8">
              <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent" />
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-white/30">{t("landing.revEst")}</span>
                <span className="mono-data text-[9px] text-white/20">5% &middot; 60m</span>
              </div>
              <p className="font-display mt-4 text-4xl font-black tracking-[-0.04em] text-white sm:text-5xl">
                ${monthlyRevenue.toLocaleString("en-US")}
                <span className="ml-1 text-base font-medium tracking-normal text-white/30">{t("landing.perMo")}</span>
              </p>
              <p className="mt-2 text-[12px] text-white/40">{L.aboutJobs(closedJobs, ticketValue.toLocaleString("en-US"))}</p>

              <div className="my-6 space-y-3 border-y border-white/[0.07] py-5 text-[12.5px]">
                <div className="flex justify-between"><span className="text-white/35">{t("landing.invest")}</span><span className="mono-data text-white/70">$520{t("landing.perMo")}</span></div>
                <div className="flex justify-between"><span className="text-white/35">{t("landing.costDelivered")}</span><span className="mono-data text-white/70">~$2.48</span></div>
                <div className="flex items-center justify-between"><span className="text-white/35">{t("landing.onePays")}</span><span className="mono-data rounded-md border border-white/10 px-2 py-0.5 text-white/80">{monthsPaid} {t("landing.months")}</span></div>
              </div>

              <button onClick={openModal} data-track="calc_cta" className="btn-emerald w-full py-3.5 text-[12px] uppercase tracking-[0.06em]">{t("landing.calcCta")}</button>
              <p className="mt-3 text-center text-[9px] font-bold uppercase tracking-[0.12em] text-white/30">{t("landing.trust2")} &middot; {t("landing.trust3")}</p>
            </div>
          </div>
        </div>
      </section>

      {/* RESULTS */}
      <section className="bg-[#06080b] py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="max-w-3xl">
            <span className="eyebrow-dark"><span className="dot" />{t("landing.resultsKicker")}</span>
            <h2 className="font-display mt-5 text-[2.25rem] font-black leading-[0.98] tracking-[-0.04em] text-white sm:text-5xl">
              {t("landing.resultsTitle")} <span className="text-white/38">{t("landing.resultsHl")}</span>
            </h2>
          </div>
          <div className="mt-12 grid gap-4 md:grid-cols-3">
            {L.quotes.map((q, i) => (
              <figure key={q.name} className="dark-panel flex flex-col p-6">
                <div className="flex items-center justify-between">
                  <div className="text-[12px] tracking-[0.12em] text-white/55">★★★★★</div>
                  <span className="h-1 w-1 rounded-full bg-white/20" />
                </div>
                <blockquote className="mt-4 flex-1 text-[13.5px] leading-relaxed text-white/55">&ldquo;{q.text}&rdquo;</blockquote>
                <figcaption className="mt-6 flex items-center gap-3 border-t border-white/[0.07] pt-5">
                  <span className="grid h-9 w-9 place-items-center rounded-full border border-white/10 bg-white/[0.05] text-[11px] font-bold text-white/70">{q.init}</span>
                  <div><p className="text-[13px] font-semibold text-white">{q.name}</p><p className="text-[10px] text-white/30">{q.role}</p></div>
                </figcaption>
                <span className="mt-4 inline-flex w-fit rounded-md border border-white/[0.08] px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.1em] text-white/40">{q.badge}</span>
              </figure>
            ))}
          </div>
        </div>
      </section>

      {/* PRICING */}
      <section id="preco" className="scroll-mt-20 border-y border-white/[0.06] bg-[#080b0f] py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="eyebrow-dark mx-auto"><span className="dot" />{t("landing.priceKicker")}</span>
            <h2 className="font-display mt-5 text-[2.25rem] font-black leading-[0.98] tracking-[-0.04em] text-white sm:text-5xl">
              {t("landing.priceTitle")} <span className="text-white/38">{t("landing.priceHl")}</span>
            </h2>
          </div>

          <div className="mx-auto mt-12 grid max-w-5xl items-start gap-4 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="relative overflow-hidden rounded-2xl border border-white/[0.10] bg-[#0a0d12] p-6 shadow-[0_30px_80px_-50px_rgba(0,0,0,0.9)] sm:p-8">
              <div className="flex items-center justify-between">
                <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-white/55">{t("landing.planTag")}</span>
                <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-white/30">{t("landing.trust3")}</span>
              </div>
              <div className="mt-6 flex items-end gap-2.5">
                <span className="font-display text-6xl font-black tracking-[-0.05em] text-white sm:text-7xl">$120</span>
                <span className="mb-2 text-[12px] font-medium text-white/40">{t("landing.week")}<br /><span className="text-[10px] text-white/25">{t("landing.month")}</span></span>
              </div>
              <p className="mt-3 text-[12.5px] leading-relaxed text-white/40">{t("landing.planSub")}</p>

              <div className="my-6 h-px bg-white/[0.08]" />
              <ul className="grid gap-2.5 text-[13px] sm:grid-cols-2">
                {L.planFeatures.map((f) => (
                  <li key={f} className="flex items-start gap-2">
                    <svg className="mt-0.5 h-3.5 w-3.5 shrink-0 text-white/35" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.4}><path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
                    <span className="text-white/60">{f}</span>
                  </li>
                ))}
              </ul>

              <button onClick={openModal} data-track="plan_cta" className="btn-emerald mt-8 w-full py-3.5 text-[12px] uppercase tracking-[0.08em]">{t("landing.planCta")}</button>
              <div className="mt-4 rounded-xl border border-white/[0.08] bg-white/[0.025] px-4 py-3 text-center">
                <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-white/55">{t("landing.trust2")} &middot; {t("landing.trust3")}</p>
                {L.quotes[0] && <p className="mt-1 text-[10px] text-white/35">&ldquo;{L.quotes[0].badge}&rdquo; &mdash; {L.quotes[0].name}, {L.quotes[0].role}</p>}
              </div>
              <p className="mt-3 text-center text-[9px] font-medium uppercase tracking-[0.1em] text-white/20">{t("landing.planSafe")}</p>
            </div>

            <div className="space-y-4">
              <div className="dark-panel p-6">
                <p className="text-[14px] font-bold text-white">{t("landing.billing")}</p>
                <ol className="mt-4 space-y-3 text-[12.5px] text-white/45">
                  {[t("landing.bill1"), t("landing.bill2"), t("landing.bill3")].map((step, i) => (
                    <li key={step} className="flex gap-3">
                      <span className="mono-data grid h-5 w-5 shrink-0 place-items-center rounded border border-white/10 text-[10px] font-bold text-white/45">{i + 1}</span>
                      <span className="pt-0.5">{step}</span>
                    </li>
                  ))}
                </ol>
              </div>
              <div className="dark-panel p-6">
                <p className="text-[14px] font-bold text-white">{t("landing.never")}</p>
                <ul className="mt-4 space-y-2.5 text-[12.5px] text-white/45">
                  {L.neverItems.map((n) => <li key={n} className="flex gap-2.5"><span className="mt-0.5 text-white/25">✕</span>{n}</li>)}
                </ul>
              </div>
              <div className="rounded-2xl border border-[#f59e0b]/18 bg-[#f59e0b]/[0.035] p-6">
                <p className="text-[14px] font-bold text-[#fbbf24]/80">{t("landing.noRenew")}</p>
                <p className="mt-1.5 text-[12.5px] leading-relaxed text-white/40">{t("landing.risk79")}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="scroll-mt-20 bg-[#06080b] py-20 md:py-28">
        <div className="mx-auto grid max-w-7xl gap-12 px-4 sm:px-6 lg:grid-cols-[0.8fr_1.2fr]">
          <div>
            <span className="eyebrow-dark"><span className="dot" />{t("landing.faqKicker")}</span>
            <h2 className="font-display mt-5 text-[2.2rem] font-black leading-[0.98] tracking-[-0.04em] text-white sm:text-5xl">{t("landing.faqTitle")}</h2>
            <p className="mt-6 text-[13.5px] text-white/40">{t("landing.faqSub")}</p>
            <button onClick={openModal} data-track="faq_cta" className="btn-emerald mt-7 px-5 py-3 text-[12.5px]">{t("landing.faqCta")}</button>
            <div className="mt-8 rounded-xl border border-white/[0.07] px-4 py-3.5">
              <p className="text-[12px] font-semibold text-white/60">{t("landing.trust2")} &middot; {t("landing.trust3")}</p>
              <p className="mt-1 text-[10px] text-white/25">{t("landing.finalFoot")}</p>
            </div>
          </div>
          <div className="divide-y divide-white/[0.07] border-y border-white/[0.07]">
            {L.faqs.map((f, i) => {
              const open = openFaq === i;
              return (
                <div key={f.q}>
                  <button onClick={() => setOpenFaq(open ? null : i)} className="flex w-full items-center justify-between gap-4 py-5 text-left">
                    <span className="text-[14px] font-semibold tracking-[-0.01em] text-white/80">{f.q}</span>
                    <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border transition ${open ? "border-white/20 text-white" : "border-white/[0.08] text-white/30"}`}>
                      <svg className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" /></svg>
                    </span>
                  </button>
                  {open && <p className="pb-5 pr-10 text-[13px] leading-relaxed text-white/40">{f.a}</p>}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* FINAL CTA */}
      <section className="relative overflow-hidden border-t border-white/[0.06] bg-[#05070a] py-24 text-center">
        <img src="/img/contractor-site.jpg" alt="" aria-hidden className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-[0.14] grayscale" />
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(6,8,11,0.35)_0%,rgba(6,8,11,0.92)_70%)]" />
        <div className="relative mx-auto max-w-3xl px-4">
          <span className="eyebrow-dark mx-auto"><span className="dot" />{t("landing.finalKicker")}</span>
          <h2 className="font-display mt-6 text-[2.5rem] font-black leading-[0.96] tracking-[-0.045em] text-white sm:text-6xl">
            {t("landing.finalTitle")}
            <br />
            <span className="text-white/38">{t("landing.finalHl")}</span>
          </h2>
          <p className="mx-auto mt-6 max-w-lg text-[14px] leading-relaxed text-white/45">{t("landing.finalSub")}</p>
          <button onClick={openModal} data-track="final_cta" className="btn-emerald mx-auto mt-8 px-8 py-3.5 text-[13px] uppercase tracking-[0.08em]">{t("landing.finalCta")}</button>
          <div className="mx-auto mt-6 flex max-w-xl flex-wrap items-center justify-center gap-x-5 gap-y-2 text-[10px] font-bold uppercase tracking-[0.12em] text-white/40">
            <span>{t("landing.trust2")}</span>
            <span>{t("landing.trust3")}</span>
            <span>{t("landing.trust1")}</span>
          </div>
          {L.quotes[0] && <p className="mt-3 text-[11px] text-white/30">&ldquo;{L.quotes[0].badge}&rdquo; &mdash; {L.quotes[0].name}, {L.quotes[0].role}</p>}
          <p className="mt-4 text-[9px] font-medium uppercase tracking-[0.12em] text-white/20">{t("landing.finalFoot")}</p>
        </div>
      </section>

      {/* STICKY MOBILE */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-white/[0.08] bg-[#06080b]/95 px-4 py-3 backdrop-blur-xl sm:hidden">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-display text-base font-black leading-none text-white">$120<span className="text-[10px] font-medium text-white/35">{t("landing.week")}</span></p>
            <p className="mt-1 text-[10px] font-medium text-white/40">{t("landing.stickyArea")}</p>
            <p className="text-[9px] font-medium text-white/25">{t("landing.trust2")} &middot; {t("landing.trust3")}</p>
          </div>
          <button onClick={openModal} data-track="sticky_cta" className="btn-emerald px-5 py-2.5 text-[12px]">{t("landing.stickyNow")}</button>
        </div>
      </div>
    </>
  );
}
