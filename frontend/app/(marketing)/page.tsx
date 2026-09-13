'use client';

import { useEffect, useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { fetchStats, fetchCities, fetchScraperStatus } from "@/lib/api-client";
import type { LeadStats, ScraperRunState } from "@/lib/api-client";
import { FoldWave, useLandingShell } from "@/components/landing/LandingShell";

// ------------------------------------------------------------------
// Tipos e dados ilustrativos do "painel amostra"
// (endereços mascarados, telefones fictícios da central 555, nomes truncados)
// ------------------------------------------------------------------
type City = "New York" | "Boston" | "Dallas" | "Chicago";
type TradeKey = "Telhado" | "Encanamento" | "Estrutura" | "Pintura" | "Elétrica" | "Aquecimento";
type Channel = "whatsapp" | "sms" | "email";

const CITIES: City[] = ["New York", "Boston", "Dallas", "Chicago"];
const TRADE_KEYS: TradeKey[] = ["Telhado", "Encanamento", "Estrutura", "Pintura", "Elétrica", "Aquecimento"];
const CHANNELS: Channel[] = ["whatsapp", "sms", "email"];

interface SampleLead {
  id: string;
  category: string;
  badge: "URGENTE" | "ALTA" | "MÉDIA";
  addressMasked: string;
  addressFull: string;
  neighborhood: string;
  description: string;
  timeAgo: string;
  ownerName: string;
  ownerPhone: string;
}

const SAMPLE_LEADS: Record<City, SampleLead[]> = {
  "New York": [
    { id: "ny-1", category: "Telhado & Cobertura", badge: "URGENTE", addressMasked: "•••• Flatbush Ave", addressFull: "•••• Flatbush Ave", neighborhood: "Flatbush, Brooklyn", description: "Infiltração grave no teto após chuva intensa. Proprietário busca vistoria imediata.", timeAgo: "3 min", ownerName: "Maria S.", ownerPhone: "(347) 555-0192" },
    { id: "ny-2", category: "Encanamento & Hidráulica", badge: "ALTA", addressMasked: "•••• 30th Ave", addressFull: "•••• 30th Ave", neighborhood: "Astoria, Queens", description: "Vazamento em tubulação principal e troca de aquecedor de água.", timeAgo: "14 min", ownerName: "Carlos M.", ownerPhone: "(917) 555-0143" },
    { id: "ny-3", category: "Estrutura & Fundação", badge: "ALTA", addressMasked: "•••• 5th Ave", addressFull: "•••• 5th Ave", neighborhood: "Park Slope, Brooklyn", description: "Trinca estrutural visível na parede lateral. Requer laudo e reforço.", timeAgo: "28 min", ownerName: "Roberto L.", ownerPhone: "(718) 555-0188" },
  ],
  Boston: [
    { id: "bos-1", category: "Pintura & Fachada", badge: "ALTA", addressMasked: "•••• Centre St", addressFull: "•••• Centre St", neighborhood: "Jamaica Plain", description: "Descamação e infiltração na fachada. Deseja impermeabilização e pintura.", timeAgo: "5 min", ownerName: "Fernanda C.", ownerPhone: "(617) 555-0129" },
    { id: "bos-2", category: "Telhado & Cobertura", badge: "URGENTE", addressMasked: "•••• Meridian St", addressFull: "•••• Meridian St", neighborhood: "East Boston", description: "Dano em telhado plano de membrana. Goteira no último andar.", timeAgo: "19 min", ownerName: "David M.", ownerPhone: "(857) 555-0174" },
    { id: "bos-3", category: "Elétrica & Painel", badge: "MÉDIA", addressMasked: "•••• Dorchester Ave", addressFull: "•••• Dorchester Ave", neighborhood: "Dorchester", description: "Painel antigo de 100A desarmando. Necessária atualização para 200A.", timeAgo: "42 min", ownerName: "Juliana D.", ownerPhone: "(617) 555-0199" },
  ],
  Dallas: [
    { id: "dal-1", category: "Estrutura & Fundação", badge: "URGENTE", addressMasked: "•••• Jefferson Blvd", addressFull: "•••• Jefferson Blvd", neighborhood: "Oak Cliff", description: "Afundamento no piso e desnível de porta. Necessita nivelamento de fundação.", timeAgo: "8 min", ownerName: "Lucas A.", ownerPhone: "(214) 555-0112" },
    { id: "dal-2", category: "Pintura & Exterior", badge: "MÉDIA", addressMasked: "•••• Gaston Ave", addressFull: "•••• Gaston Ave", neighborhood: "Lakewood", description: "Pintura externa completa de sobrado residencial de 2 pisos.", timeAgo: "25 min", ownerName: "Patricia R.", ownerPhone: "(469) 555-0165" },
    { id: "dal-3", category: "Encanamento & Esgoto", badge: "ALTA", addressMasked: "•••• Preston Rd", addressFull: "•••• Preston Rd", neighborhood: "Preston Hollow", description: "Retorno de água na linha principal subterrânea. Necessita substituição.", timeAgo: "51 min", ownerName: "Ricardo S.", ownerPhone: "(972) 555-0131" },
  ],
  Chicago: [
    { id: "chi-1", category: "Aquecimento & Caldeira", badge: "URGENTE", addressMasked: "•••• Milwaukee Ave", addressFull: "•••• Milwaukee Ave", neighborhood: "Logan Square", description: "Caldeira parou de aquecer os radiadores. Família precisa de conserto urgente.", timeAgo: "4 min", ownerName: "Eduardo F.", ownerPhone: "(312) 555-0184" },
    { id: "chi-2", category: "Telhado & Calha", badge: "ALTA", addressMasked: "•••• 18th St", addressFull: "•••• 18th St", neighborhood: "Pilsen", description: "Telhas arrancadas por vento forte e calha entupida transbordando.", timeAgo: "22 min", ownerName: "Sandra M.", ownerPhone: "(773) 555-0156" },
    { id: "chi-3", category: "Elétrica & Fiação", badge: "MÉDIA", addressMasked: "•••• 53rd St", addressFull: "•••• 53rd St", neighborhood: "Hyde Park", description: "Instalação de tomadas dedicadas para ar-condicionado e revisão da fiação.", timeAgo: "39 min", ownerName: "Gabriel R.", ownerPhone: "(872) 555-0120" },
  ],
};

const SIGNAL_STYLE = [
  { color: "#f59e0b", bg: "#fff7ed", ring: "#fde68a" },
  { color: "#2563eb", bg: "#eff6ff", ring: "#bfdbfe" },
  { color: "#475569", bg: "#f1f5f9", ring: "#cbd5e1" },
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

function Kicker({ children, color }: { children: React.ReactNode; color: string }) {
  return <p className="kicker" style={{ color }}>{children}</p>;
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
  const [conversionRate, setConversionRate] = useState(3);
  const [openFaq, setOpenFaq] = useState<number | null>(0);

  // dados reais (públicos)
  const [stats, setStats] = useState<LeadStats | null>(null);
  const [servedCities, setServedCities] = useState(CITIES.length);
  const [scraper, setScraper] = useState<ScraperRunState | null>(null);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const s = await fetchStats();
        if (mounted) setStats(s);
      } catch {
        /* sem dados públicos -> valores iniciais zero */
      }
      try {
        const cities = await fetchCities();
        if (mounted) setServedCities(cities.length);
      } catch {
        /* sem lista de cidades -> usa fallback */
      }
      try {
        const status = await fetchScraperStatus();
        if (mounted) setScraper(status);
      } catch {
        /* sem status do scraper -> esconde contagem de novas */
      }
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

    const waMsg = (name: string, cat: string, addr: string) =>
      t("landing.waMsg").replace("{name}", name).replace("{cat}", cat).replace("{addr}", addr);
    const aboutJobs = (n: number, ticket: string) =>
      t("landing.aboutJobs").replace("{n}", String(n)).replace("{ticket}", ticket);

    return { categories, tradesLabel, signals, problems, comparisons, quotes, planFeatures, neverItems, faqs, templates, trust, waMsg, aboutJobs };
  }, [t]);

  // ------------------------------------------------ derivados
  const leadsBank = stats?.total_leads ?? stats?.total ?? 0;
  const withOwner = stats?.leads_with_owner ?? stats?.with_owner ?? stats?.contacted ?? 0;
  const citiesCount = servedCities || stats?.cities?.length || CITIES.length;
  const newThisRun = Math.max(500, scraper?.last_run?.inserted ?? 0);

  const fmtTimer = (s: number) =>
    `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;
  const validatedPhones = Math.round(300 * 0.7);
  const estimatedVisits = Math.round(validatedPhones * 0.25);
  const closedJobs = Math.max(1, Math.round(estimatedVisits * (conversionRate / 20)));
  const monthlyRevenue = closedJobs * ticketValue;
  const monthsPaid = (ticketValue / 340).toFixed(1);

  const copyTpl = (text: string) => {
    navigator.clipboard?.writeText(text).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <>
      {/* HERO */}
      <section id="topo" className="bg-grid-soft relative overflow-hidden">
        <div className="pointer-events-none absolute -top-32 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-[#10b981]/[0.09] blur-[150px]" />
        <div className="relative mx-auto max-w-6xl px-4 pb-16 pt-16 text-center sm:px-6 md:pb-24 md:pt-24">
          <div className="fade-up inline-flex items-center gap-2 text-[12px] font-bold tracking-wider text-[#0a8f65]">
            <span className="blink-dot" /><span className="blink-dot blink-dot-delay" /><span className="blink-dot blink-dot-delay-2" />
            {leadsBank.toLocaleString("en-US")} {t("landing.heroKicker")}
          </div>
          <h1 className="fade-up font-display mx-auto mt-8 max-w-5xl text-[3.1rem] font-black leading-[0.9] sm:text-7xl lg:text-[6.2rem] lg:leading-[0.88]">
            {t("landing.heroTitle1")}<br /><span className="hl">{t("landing.heroTitle2")}</span>
          </h1>
          <p className="fade-up mx-auto mt-8 max-w-2xl text-lg leading-relaxed text-[#54617a] sm:text-xl">{t("landing.heroSub")}</p>
          <div className="fade-up mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <button onClick={openModal} className="btn-mint flex w-full items-center justify-center gap-2.5 px-9 py-4 text-base sm:w-auto">
              {t("landing.ctaPanel")}
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" /></svg>
            </button>
            <button onClick={() => scrollTo("simulador")} className="btn-outline flex w-full items-center justify-center px-7 py-4 text-sm sm:w-auto">{t("landing.ctaSample")}</button>
          </div>
          <div className="fade-up mt-8 flex flex-wrap items-center justify-center gap-x-8 gap-y-2 text-sm font-medium text-[#54617a]">
            {L.trust.map((item) => (
              <span key={item} className="flex items-center gap-1.5">
                <svg className="h-4 w-4 text-[#10b981]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
                {item}
              </span>
            ))}
          </div>
          <p className="mt-4 text-sm text-[#94a3b8]">{t("landing.priceLine")}</p>
          <div className="pop-in mx-auto mt-14 max-w-4xl">
            <div className="grid gap-8 sm:grid-cols-3">
              <div className="text-center">
                <p className="inline-flex items-center gap-2 font-display text-4xl font-black text-[#10b981] sm:text-5xl"><span className="blink-dot" />{leadsBank.toLocaleString("en-US")}+</p>
                <p className="mt-2 text-[11px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("landing.statBank")}</p>
              </div>
              <div className="text-center">
                <p className="inline-flex items-center gap-2 font-display text-4xl font-black text-[#10b981] sm:text-5xl"><span className="blink-dot blink-dot-delay" />{withOwner.toLocaleString("en-US")}+</p>
                <p className="mt-2 text-[11px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("landing.statOwner")}</p>
              </div>
              <div className="text-center">
                <p className="inline-flex items-center gap-2 font-display text-4xl font-black text-[#10b981] sm:text-5xl"><span className="blink-dot blink-dot-delay-2" />{citiesCount}+</p>
                <p className="mt-2 text-[11px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("landing.statCities")}</p>
              </div>
            </div>
            <p className="mt-8 flex items-center justify-center gap-2 text-sm font-medium text-[#0a8f65]">
              <span className="blink-dot" /><span className="blink-dot blink-dot-delay" /><span className="blink-dot blink-dot-delay-2" />
              {t("landing.updated")} {t("landing.agoLittle")}
              {" · "}
              {newThisRun.toLocaleString("en-US")} {t("landing.updatedNew")}
            </p>
          </div>
        </div>
        <div className="overflow-hidden border-t border-[#eef1f6] bg-white py-4">
          <div className="animate-marquee items-center gap-8 text-xs font-bold uppercase tracking-widest text-[#94a3b8]">
            {[...L.categories, ...L.categories].map((c, i) => (
              <span key={`${c}-${i}`} className="flex shrink-0 items-center gap-8">{c}<span className="h-1.5 w-1.5 rounded-full bg-[#10b981]" /></span>
            ))}
          </div>
        </div>
      </section>

      {/* PROBLEMA */}
      <section className="bg-dots py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Kicker color="#7c5cff">{t("landing.problemKicker")}</Kicker>
          <h2 className="font-display mt-5 max-w-4xl text-[2.5rem] font-black leading-[0.98] sm:text-6xl">{t("landing.problemTitle")} <span className="hl">{t("landing.problemHl")}</span></h2>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-[#54617a]">{t("landing.problemSub")}</p>
          <div className="mt-14 grid gap-6 md:grid-cols-3">
            {L.problems.map((p) => (
              <article key={p.kicker} className="card card-hover flex flex-col p-8">
                <p className="kicker text-[#f43f5e]">{p.kicker}</p>
                <h3 className="font-display mt-4 text-2xl font-black">{p.title}</h3>
                <p className="mt-4 flex-1 text-[15px] leading-relaxed text-[#54617a]">{p.body}</p>
                <span className="mt-6 inline-flex w-fit rounded-lg bg-[#f1f4f9] px-3.5 py-2 text-xs font-bold text-[#54617a]">{t("landing.costWord")} {p.cost}</span>
              </article>
            ))}
          </div>
          <div className="mt-8 overflow-hidden rounded-[1.6rem] bg-[#0b1220] p-8 md:p-10">
            <div className="flex flex-col items-start gap-6 md:flex-row md:items-center">
              <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-[#10b981] text-white"><svg className="h-7 w-7" viewBox="0 0 24 24" fill="currentColor"><path d="m13 2-9 12h7l-1 8 10-13h-7V2Z" /></svg></span>
              <p className="text-xl font-bold leading-snug text-white sm:text-2xl">{t("landing.flip")}</p>
              <button onClick={openModal} className="btn-mint shrink-0 px-6 py-3.5 text-sm">{t("landing.seeHow")}</button>
            </div>
          </div>
        </div>
      </section>

      {/* OFÍCIOS */}
      <section id="oficios" className="scroll-mt-20 bg-white py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Kicker color="#7c5cff">{t("landing.oficiosKicker")}</Kicker>
          <h2 className="font-display mt-5 max-w-4xl text-[2.4rem] font-black leading-[0.98] sm:text-5xl md:text-6xl">{t("landing.oficiosTitle")} <span className="hl">{t("landing.oficiosHl")}</span></h2>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-[#54617a]">{t("landing.oficiosSub")}</p>
          <div className="mt-12 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {L.categories.map((cat) => (
              <div key={cat} className="card flex items-center gap-3 px-4 py-3.5">
                <span className="h-2 w-2 shrink-0 rounded-full bg-[#10b981]" />
                <span className="text-sm font-bold !text-slate-900">{cat}</span>
              </div>
            ))}
          </div>
          <p className="mt-14 text-center text-sm font-semibold text-[#54617a]">{t("landing.oficiosPaths")}</p>
          <div className="mt-6 grid gap-5 md:grid-cols-3">
            {L.signals.map((s, i) => (
              <article key={s.label} className="rounded-3xl p-7" style={{ background: SIGNAL_STYLE[i].bg, boxShadow: `inset 0 0 0 1px ${SIGNAL_STYLE[i].ring}` }}>
                <span className="inline-flex items-center gap-2 text-xs font-black uppercase tracking-wider" style={{ color: SIGNAL_STYLE[i].color }}>
                  <span className="h-2 w-2 rounded-full" style={{ background: SIGNAL_STYLE[i].color }} />{s.hint}
                </span>
                <h3 className="font-display mt-3 text-2xl font-black">{s.label}</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-[#54617a]">{s.body}</p>
              </article>
            ))}
          </div>
          <p className="mx-auto mt-6 max-w-2xl text-center text-sm text-[#94a3b8]">{t("landing.oficiosFoot")}</p>
        </div>
      </section>

      <FoldWave from="#ffffff" to="#0b1220" />

      {/* PAINEL AMOSTRA */}
      <section id="simulador" className="scroll-mt-20 bg-[#0b1220] py-20 text-white md:py-24">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="kicker justify-center text-[#34e0a1]">{t("landing.sampleKicker")}</span>
            <h2 className="font-display mt-5 text-4xl font-black leading-[0.98] sm:text-5xl">{t("landing.sampleTitle")}</h2>
            <p className="mt-5 text-lg text-[#9aa7ba]">{t("landing.sampleSub")}</p>
          </div>
          <div className="mt-14 overflow-hidden rounded-[1.8rem] border border-white/10 bg-gradient-to-b from-[#111a29] to-[#0a101b]">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 bg-[#0a0f1a] p-4 sm:px-6">
              <span className="text-xs font-semibold text-[#9aa7ba]">painel.magicleads.app</span>
              <div className="flex flex-wrap gap-1 rounded-xl border border-white/10 bg-[#0c1220] p-1">
                {CITIES.map((c) => (
                  <button key={c} onClick={() => { setActiveCity(c); setReservedLeadId(null); }} className={`rounded-lg px-3 py-1.5 text-xs font-bold ${activeCity === c ? "bg-[#10b981] text-white" : "text-[#9aa7ba] hover:text-white"}`}>{c}</button>
                ))}
              </div>
            </div>
            <div className="grid gap-5 p-4 sm:p-6 lg:grid-cols-3">
              {SAMPLE_LEADS[activeCity].map((lead) => {
                const reserved = reservedLeadId === lead.id;
                return (
                  <div key={lead.id} className={`flex flex-col justify-between rounded-2xl border p-5 ${reserved ? "border-[#10b981] bg-[#0b1e1c]" : "border-white/10 bg-[#0d1422]"}`}>
                    <div>
                      <div className="flex items-center justify-between">
                        <span className={`rounded-md px-2 py-0.5 text-[10px] font-black ${lead.badge === "URGENTE" ? "bg-[#f43f5e]/15 text-[#ff7a8a]" : lead.badge === "ALTA" ? "bg-[#f59e0b]/15 text-[#f59e0b]" : "bg-white/10 text-[#9aa7ba]"}`}>{lead.badge}</span>
                        <span className="text-xs text-[#64748b]">{lead.timeAgo}</span>
                      </div>
                      <h4 className="font-display mt-3 text-lg font-bold">{lead.category}</h4>
                      <p className="text-xs font-bold text-[#34e0a1]">{lead.neighborhood}</p>
                      <p className="mt-2 text-xs leading-relaxed text-[#9aa7ba]">{lead.description}</p>
                    </div>
                    <div className="mt-5 border-t border-white/10 pt-4">
                      {reserved ? (
                        <div className="space-y-3">
                          <div className="flex items-center justify-between rounded-lg border border-[#10b981]/30 bg-[#10b981]/10 p-2.5 text-xs font-bold text-[#34e0a1]">
                            <span>{t("landing.reserved")}</span><span className="font-mono">{fmtTimer(timerSeconds)}</span>
                          </div>
                          <div className="rounded-lg border border-white/10 bg-black/60 p-3">
                            <p className="text-[11px] text-[#9aa7ba]">{lead.ownerName} · {t("landing.owner")}</p>
                            <p className="font-mono text-base font-black text-[#34e0a1]">{lead.ownerPhone}</p>
                            <p className="mt-1 text-[10px] text-[#64748b]">{lead.addressFull}</p>
                          </div>
                          <button onClick={() => setWhatsappLead(lead)} className="btn-mint w-full py-2.5 text-xs uppercase tracking-wider">{t("landing.openWa")}</button>
                        </div>
                      ) : (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between text-[11px] text-[#9aa7ba]"><span>{t("landing.address")}</span><span className="font-mono text-white">{lead.addressMasked}</span></div>
                          <button onClick={() => { setReservedLeadId(lead.id); setTimerSeconds(3600); }} className="flex w-full items-center justify-center rounded-lg border border-[#10b981]/40 bg-[#10b981]/10 py-2.5 text-xs font-bold text-[#34e0a1] hover:bg-[#10b981] hover:text-white">{t("landing.reserveHour")}</button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 bg-[#0a0f1a] p-4 text-xs sm:px-6">
              <span className="text-[#9aa7ba]">{t("landing.payOk")}</span>
              <button onClick={openModal} className="font-bold text-[#34e0a1] hover:underline">{t("landing.unlock4")}</button>
            </div>
          </div>
        </div>
      </section>

      <FoldWave from="#0b1220" to="#ffffff" />

      {/* COMPARATIVO */}
      <section id="comparativo" className="scroll-mt-20 bg-white py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Kicker color="#7c5cff">{t("landing.compareKicker")}</Kicker>
          <h2 className="font-display mt-5 max-w-4xl text-[2.4rem] font-black leading-[0.98] sm:text-5xl">{t("landing.compareTitle")} <span className="hl">{t("landing.compareHl")}</span></h2>
          <p className="mt-6 max-w-2xl text-lg text-[#54617a]">{t("landing.compareSub")}</p>
          <div className="mt-14 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {L.comparisons.map((c) => (
              <article key={c.channel} className={`flex flex-col rounded-3xl p-7 ${c.winner ? "bg-[#0b1220] text-white shadow-2xl md:-translate-y-3" : "card card-hover"}`}>
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className={`font-display text-xl font-black ${c.winner ? "text-[#34e0a1]" : "!text-slate-900"}`}>{c.channel}</h3>
                    <p className="text-xs text-[#94a3b8]">{c.sub}</p>
                  </div>
                  {c.winner && <span className="rounded-full bg-[#10b981] px-2.5 py-1 text-[10px] font-black text-white">{t("landing.best")}</span>}
                </div>
                <div className="mt-6">
                  <p className={`font-display text-3xl font-black ${c.winner ? "text-white" : "!text-slate-900"}`}>{c.cost}</p>
                  <p className="text-xs text-[#94a3b8]">{c.costLabel}</p>
                </div>
<div className={`mt-6 space-y-3 border-t pt-5 text-sm ${c.winner ? "border-white/10" : "border-[#eef1f6]"}`}>
  <div className="flex justify-between gap-3"><span className={c.winner ? "text-[#94a3b8]" : "!text-slate-500"}>{t("landing.excl")}</span><span className={`text-right font-bold ${c.winner ? "text-[#34e0a1]" : "!text-slate-900"}`}>{c.exclusivity}</span></div>
  <div className="flex justify-between gap-3"><span className={c.winner ? "text-[#94a3b8]" : "!text-slate-500"}>{t("landing.intentL")}</span><span className={`text-right font-bold ${c.winner ? "text-[#34e0a1]" : "!text-slate-900"}`}>{c.intent}</span></div>
  <div className="flex justify-between gap-3"><span className={c.winner ? "text-[#94a3b8]" : "!text-slate-500"}>{t("landing.phoneL")}</span><span className={`text-right font-bold ${c.winner ? "text-[#34e0a1]" : "!text-slate-900"}`}>{c.phone}</span></div>
</div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* COMO FUNCIONA */}
      <section id="como-funciona" className="bg-dots scroll-mt-20 py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="kicker justify-center text-[#10b981]">{t("landing.howKicker")}</span>
            <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t("landing.howTitle")} <span className="hl">{t("landing.howHl")}</span></h2>
          </div>
          <div className="mt-16 grid gap-6 md:grid-cols-3">
            {(
              [
                { n: "01", tint: "#10b981", bg: "#10b98115", title: t("landing.step1t"), body: t("landing.step1b") },
                { n: "02", tint: "#7c5cff", bg: "#7c5cff15", title: t("landing.step2t"), body: t("landing.step2b"), featured: true },
                { n: "03", tint: "#f59e0b", bg: "#f59e0b15", title: t("landing.step3t"), body: t("landing.step3b") },
              ] as { n: string; tint: string; bg: string; title: string; body: string; featured?: boolean }[]
            ).map((s) => (
              <article key={s.n} className={`card card-hover p-8 ${s.featured ? "ring-2 ring-[#7c5cff]/25" : ""}`}>
                <span className="flex h-14 w-14 items-center justify-center rounded-2xl font-display text-xl font-black" style={{ background: s.bg, color: s.tint }}>{s.n}</span>
                <h3 className="font-display mt-6 text-xl font-bold !text-slate-900">{s.title}</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-[#54617a]">{s.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* TEMPLATES */}
      <section id="templates" className="scroll-mt-20 bg-white py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="grid gap-12 lg:grid-cols-12 lg:items-center">
            <div className="lg:col-span-5">
              <Kicker color="#f43f5e">{t("landing.tplKicker")}</Kicker>
              <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t("landing.tplTitle")} <span className="hl">{t("landing.tplHl")}</span></h2>
              <p className="mt-6 text-[15px] text-[#54617a]">{t("landing.tplSub")}</p>
              <div className="mt-7 flex flex-wrap gap-2">
                {L.tradesLabel.map((label, i) => (
                  <button key={TRADE_KEYS[i]} onClick={() => setTplTrade(TRADE_KEYS[i])} className={`rounded-lg px-3.5 py-1.5 text-xs font-bold ${tplTrade === TRADE_KEYS[i] ? "bg-[#0b1220] text-white" : "bg-[#f1f4f9] text-[#54617a]"}`}>{label}</button>
                ))}
              </div>
              <div className="mt-3 flex gap-2">
                {CHANNELS.map((c) => (
                  <button key={c} onClick={() => setTplChannel(c)} className={`rounded-lg px-3.5 py-1.5 text-xs font-bold uppercase ${tplChannel === c ? "bg-[#10b981] text-white" : "border border-[#e2e8f0] text-[#54617a]"}`}>{c}</button>
                ))}
              </div>
            </div>
            <div className="lg:col-span-7">
              <div className="card overflow-hidden">
                <div className="flex items-center justify-between border-b border-[#eef1f6] bg-[#f8fafc] p-4">
                  <span className="text-xs font-bold text-[#54617a]">{L.tradesLabel[TRADE_KEYS.indexOf(tplTrade)]} · {tplChannel.toUpperCase()}</span>
                  <button onClick={() => copyTpl(L.templates[tplTrade][tplChannel])} className="btn-dark px-3.5 py-1.5 text-xs">{copied ? t("landing.copied") : t("landing.copy")}</button>
                </div>
                <div className="p-6">
                  <div className="rounded-2xl bg-[#e8f9ef] p-5"><pre className="whitespace-pre-wrap font-sans text-[15px] leading-relaxed !text-slate-900">{L.templates[tplTrade][tplChannel]}</pre></div>
                  <p className="mt-4 text-xs text-[#94a3b8]">{t("landing.tplFields")}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <FoldWave from="#ffffff" to="#0b1220" />

      {/* CALCULADORA */}
      <section id="calculadora" className="scroll-mt-20 bg-[#0b1220] py-20 text-white md:py-24">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="kicker justify-center text-[#34e0a1]">{t("landing.calcKicker")}</span>
            <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t("landing.calcTitle")} <span className="text-[#34e0a1]">{t("landing.calcHl")}</span></h2>
            <p className="mt-5 text-lg text-[#9aa7ba]">{t("landing.calcSub")}</p>
          </div>
          <div className="mt-14 grid gap-6 lg:grid-cols-12">
            <div className="rounded-[1.5rem] border border-white/10 bg-[#111a29] p-7 lg:col-span-6">
              <div className="flex items-center justify-between"><span className="text-sm font-bold text-[#cbd5e1]">{t("landing.ticketAvg")}</span><span className="font-display text-2xl font-black text-[#34e0a1]">${ticketValue.toLocaleString("en-US")}</span></div>
              <input type="range" min={2000} max={15000} step={500} value={ticketValue} onChange={(e) => setTicketValue(Number(e.target.value))} className="range-dark mt-4 w-full" />
              <div className="mt-8 border-t border-white/10 pt-6">
                <div className="flex items-center justify-between"><span className="text-sm font-bold text-[#cbd5e1]">{t("landing.closes20")}</span><span className="font-display text-2xl font-black text-[#9d80ff]">{conversionRate}</span></div>
                <input type="range" min={1} max={6} step={1} value={conversionRate} onChange={(e) => setConversionRate(Number(e.target.value))} className="range-dark mt-4 w-full" />
                <div className="mt-2 flex justify-between text-[10px] font-bold text-[#64748b]"><span>{t("landing.conservative")}</span><span>{t("landing.normal")}</span><span>{t("landing.high")}</span></div>
              </div>
              <div className="mt-8 grid grid-cols-3 gap-3 border-t border-white/10 pt-6 text-center">
                <div className="rounded-xl bg-white/5 p-3"><p className="font-display text-lg font-black">300</p><p className="text-[10px] text-[#9aa7ba]">{t("landing.leadsM")}</p></div>
                <div className="rounded-xl bg-white/5 p-3"><p className="font-display text-lg font-black">~{validatedPhones}</p><p className="text-[10px] text-[#9aa7ba]">{t("landing.withPh")}</p></div>
                <div className="rounded-xl bg-white/5 p-3"><p className="font-display text-lg font-black">~{estimatedVisits}</p><p className="text-[10px] text-[#9aa7ba]">{t("landing.visitsL")}</p></div>
              </div>
            </div>
            <div className="flex flex-col justify-between rounded-[1.5rem] bg-gradient-to-br from-[#10b981] to-[#0a8f65] p-8 lg:col-span-6">
              <div>
                <span className="rounded-full bg-white/20 px-3 py-1 text-xs font-black">{t("landing.revEst")}</span>
                <p className="font-display mt-4 text-6xl font-black">${monthlyRevenue.toLocaleString("en-US")}<span className="text-2xl font-bold text-white/60">{t("landing.perMo")}</span></p>
                <p className="mt-3 text-sm font-bold">{L.aboutJobs(closedJobs, ticketValue.toLocaleString("en-US"))}</p>
              </div>
              <div className="my-6 space-y-3 border-y border-white/20 py-5 text-sm font-semibold">
                <div className="flex justify-between"><span className="text-white/80">{t("landing.invest")}</span><span>$340{t("landing.perMo")}</span></div>
                <div className="flex justify-between"><span className="text-white/80">{t("landing.costDelivered")}</span><span>~$1.62</span></div>
                <div className="flex justify-between text-base"><span>{t("landing.onePays")}</span><span className="rounded-lg bg-[#04231a] px-2.5 py-0.5 text-[#34e0a1]">{monthsPaid} {t("landing.months")}</span></div>
              </div>
              <button onClick={openModal} className="w-full rounded-xl bg-white py-4 text-sm font-black uppercase tracking-wider text-[#0a8f65]">{t("landing.calcCta")}</button>
            </div>
          </div>
        </div>
      </section>

      <FoldWave from="#0b1220" to="#f6f8fc" />

      {/* RESULTADOS */}
      <section className="bg-dots py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Kicker color="#7c5cff">{t("landing.resultsKicker")}</Kicker>
          <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t("landing.resultsTitle")} <span className="hl">{t("landing.resultsHl")}</span></h2>
          <div className="mt-14 grid gap-6 md:grid-cols-3">
            {L.quotes.map((q) => (
              <figure key={q.name} className="card card-hover flex flex-col p-7">
                <div className="text-[#f59e0b]">★★★★★</div>
                <blockquote className="mt-4 flex-1 text-[15px] leading-relaxed text-[#3f4a5e]">"{q.text}"</blockquote>
                <figcaption className="mt-6 flex items-center gap-3 border-t border-[#eef1f6] pt-5">
                  <span className={`flex h-11 w-11 items-center justify-center rounded-full bg-gradient-to-br ${q.grad} text-sm font-black text-white`}>{q.init}</span>
                  <div><p className="text-sm font-black">{q.name}</p><p className="text-xs text-[#94a3b8]">{q.role}</p></div>
                </figcaption>
                <span className="mt-4 inline-flex w-fit rounded-lg bg-[#e8f9ef] px-3 py-1.5 text-[11px] font-black text-[#0a8f65]">{q.badge}</span>
              </figure>
            ))}
          </div>
        </div>
      </section>

      {/* PREÇO */}
      <section id="preco" className="scroll-mt-20 bg-white py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="kicker justify-center text-[#10b981]">{t("landing.priceKicker")}</span>
            <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t("landing.priceTitle")} <span className="hl">{t("landing.priceHl")}</span></h2>
          </div>
          <div className="mx-auto mt-14 grid max-w-5xl gap-6 lg:grid-cols-[1.15fr_0.85fr]">
            <div className="rounded-[1.6rem] bg-[#0b1220] p-8 text-white sm:p-10">
              <span className="rounded-full bg-[#10b981]/15 px-3 py-1 text-[11px] font-black text-[#34e0a1]">{t("landing.planTag")}</span>
              <div className="mt-5 flex items-end gap-2">
                <span className="font-display text-7xl font-black">$79</span>
                <span className="mb-3 text-[#9aa7ba]">{t("landing.week")}<br /><span className="text-sm">{t("landing.month")}</span></span>
              </div>
              <p className="mt-3 text-sm text-[#9aa7ba]">{t("landing.planSub")}</p>
              <div className="my-7 h-px bg-white/10" />
              <ul className="space-y-3.5 text-[15px]">
                {L.planFeatures.map((f) => (
                  <li key={f} className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#10b981]/15 text-[#34e0a1]">✓</span>
                    <span className="text-[#e2e8f0]">{f}</span>
                  </li>
                ))}
              </ul>
              <button onClick={openModal} className="btn-mint mt-8 w-full py-4 text-base uppercase tracking-wider">{t("landing.planCta")}</button>
              <p className="mt-3 text-center text-xs text-[#64748b]">{t("landing.planSafe")}</p>
            </div>
            <div className="flex flex-col gap-6">
              <div className="card p-7">
                <p className="font-display text-lg font-bold">{t("landing.billing")}</p>
                <ol className="mt-4 space-y-3 text-sm text-[#54617a]">
                  <li className="flex gap-3"><span className="font-black text-[#10b981]">1.</span>{t("landing.bill1")}</li>
                  <li className="flex gap-3"><span className="font-black text-[#10b981]">2.</span>{t("landing.bill2")}</li>
                  <li className="flex gap-3"><span className="font-black text-[#10b981]">3.</span>{t("landing.bill3")}</li>
                </ol>
              </div>
              <div className="card p-7">
                <p className="font-display text-lg font-bold">{t("landing.never")}</p>
                <ul className="mt-4 space-y-2.5 text-sm text-[#54617a]">
                  {L.neverItems.map((n) => <li key={n} className="flex gap-2.5"><span className="text-[#f43f5e]">✕</span>{n}</li>)}
                </ul>
              </div>
              <div className="rounded-[1.5rem] border border-[#f59e0b]/25 bg-[#fff7ed] p-7">
                <p className="font-display text-lg font-black text-[#b45309]">{t("landing.noRenew")}</p>
                <p className="mt-2 text-sm text-[#92702a]">{t("landing.risk79")}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="bg-dots scroll-mt-20 py-20 md:py-28">
        <div className="mx-auto grid max-w-7xl gap-12 px-4 sm:px-6 lg:grid-cols-[0.85fr_1.15fr]">
          <div>
            <Kicker color="#f43f5e">{t("landing.faqKicker")}</Kicker>
            <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t("landing.faqTitle")}</h2>
            <p className="mt-6 text-[15px] text-[#54617a]">{t("landing.faqSub")}</p>
            <button onClick={openModal} className="btn-dark mt-7 px-6 py-3.5 text-sm">{t("landing.faqCta")}</button>
          </div>
          <div className="space-y-3">
            {L.faqs.map((f, i) => {
              const open = openFaq === i;
              return (
                <div key={f.q} className={`card overflow-hidden ${open ? "shadow-lg" : ""}`}>
                  <button onClick={() => setOpenFaq(open ? null : i)} className="flex w-full items-center justify-between gap-4 p-5 text-left">
                    <span className="font-display text-[17px] font-bold !text-slate-900">{f.q}</span>
                    <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${open ? "bg-[#0b1220] text-[#34e0a1]" : "bg-[#f1f4f9]"}`}>
                      <svg className={`h-4 w-4 ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" /></svg>
                    </span>
                  </button>
                  {open && <p className="px-5 pb-5 text-[15px] text-[#54617a]">{f.a}</p>}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* CTA FINAL */}
      <section className="relative overflow-hidden bg-[#0b1220] py-24 text-center text-white">
        <div className="relative mx-auto max-w-4xl px-4">
          <div className="inline-flex items-center gap-2 rounded-full border border-[#10b981]/30 bg-[#10b981]/10 px-4 py-1.5 text-[11px] font-bold tracking-wider text-[#34e0a1]">
            <span className="blink-dot" />{t("landing.finalKicker")}
          </div>
          <h2 className="font-display mt-6 text-4xl font-black sm:text-6xl">{t("landing.finalTitle")}<br /><span className="hl">{t("landing.finalHl")}</span></h2>
          <p className="mx-auto mt-6 max-w-xl text-lg text-[#9aa7ba]">{t("landing.finalSub")}</p>
          <button onClick={openModal} className="btn-mint mx-auto mt-9 inline-flex items-center gap-2.5 px-9 py-4 text-base uppercase tracking-wider">{t("landing.finalCta")}</button>
          <p className="mt-4 text-xs text-[#64748b]">{t("landing.finalFoot")}</p>
        </div>
      </section>

      {/* STICKY MOBILE */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-[#eef1f6] bg-white/95 px-4 py-3 backdrop-blur-xl sm:hidden">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-display text-lg font-black leading-none">$79<span className="text-xs font-bold text-[#94a3b8]">{t("landing.week")}</span></p>
            <p className="text-[11px] font-bold text-[#10b981]">{t("landing.stickyArea")}</p>
          </div>
          <button onClick={openModal} className="btn-mint flex-1 py-3 text-sm">{t("landing.stickyNow")}</button>
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
              {L.waMsg(whatsappLead.ownerName.split(" ")[0], whatsappLead.category.toLowerCase(), whatsappLead.addressFull)}
            </div>
            <button onClick={() => { setWhatsappLead(null); openModal(); }} className="btn-mint w-full py-3.5 text-sm uppercase tracking-wider">{t("landing.activateSend")}</button>
          </div>
        </div>
      )}
    </>
  );
}