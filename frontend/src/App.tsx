import { useState, useEffect } from "react";
import { COPY, LANGS, type Lang } from "./i18n";

type City = "New York" | "Boston" | "Dallas" | "Chicago";
type Trade = "Telhado" | "Encanamento" | "Estrutura" | "Pintura" | "Elétrica" | "Aquecimento";
type Channel = "whatsapp" | "sms" | "email";
const TRADE_KEYS: Trade[] = ["Telhado", "Encanamento", "Estrutura", "Pintura", "Elétrica", "Aquecimento"];

interface LeadItem {
  id: string; category: string; badge: "URGENTE" | "ALTA" | "MÉDIA";
  addressMasked: string; addressFull: string; neighborhood: string; city: City;
  description: string; timeAgo: string; ownerName: string; ownerPhone: string;
}

const LIVE_LEADS: Record<City, LeadItem[]> = {
  "New York": [
    { id: "ny-101", category: "Telhado & Cobertura", badge: "URGENTE", addressMasked: "•••• Flatbush Ave", addressFull: "1428 Flatbush Ave", neighborhood: "Flatbush, Brooklyn", city: "New York", description: "Infiltração grave no teto após chuva intensa. Proprietário busca vistoria imediata.", timeAgo: "3 min", ownerName: "Maria Silveira", ownerPhone: "(347) 555-0192" },
    { id: "ny-102", category: "Encanamento & Hidráulica", badge: "ALTA", addressMasked: "•••• 30th Ave", addressFull: "31-14 30th Ave", neighborhood: "Astoria, Queens", city: "New York", description: "Vazamento em tubulação principal e troca de aquecedor de água.", timeAgo: "14 min", ownerName: "Carlos Mendes", ownerPhone: "(917) 555-0143" },
    { id: "ny-103", category: "Estrutura & Fundação", badge: "ALTA", addressMasked: "•••• 5th Ave", addressFull: "482 5th Ave", neighborhood: "Park Slope, Brooklyn", city: "New York", description: "Trinca estrutural visível na parede lateral. Requer laudo e reforço.", timeAgo: "28 min", ownerName: "Roberto Lima", ownerPhone: "(718) 555-0188" },
  ],
  Boston: [
    { id: "bos-201", category: "Pintura & Fachada", badge: "ALTA", addressMasked: "•••• Centre St", addressFull: "640 Centre St", neighborhood: "Jamaica Plain", city: "Boston", description: "Descamação e infiltração na fachada. Deseja impermeabilização e pintura.", timeAgo: "5 min", ownerName: "Fernanda Costa", ownerPhone: "(617) 555-0129" },
    { id: "bos-202", category: "Telhado & Cobertura", badge: "URGENTE", addressMasked: "•••• Meridian St", addressFull: "215 Meridian St", neighborhood: "East Boston", city: "Boston", description: "Dano em telhado plano de membrana. Goteira no último andar.", timeAgo: "19 min", ownerName: "David Miller", ownerPhone: "(857) 555-0174" },
    { id: "bos-203", category: "Elétrica & Painel", badge: "MÉDIA", addressMasked: "•••• Dorchester Ave", addressFull: "1040 Dorchester Ave", neighborhood: "Dorchester", city: "Boston", description: "Painel antigo de 100A desarmando. Necessária atualização para 200A.", timeAgo: "42 min", ownerName: "Juliana Duarte", ownerPhone: "(617) 555-0199" },
  ],
  Dallas: [
    { id: "dal-301", category: "Estrutura & Fundação", badge: "URGENTE", addressMasked: "•••• Jefferson Blvd", addressFull: "1230 W Jefferson Blvd", neighborhood: "Oak Cliff", city: "Dallas", description: "Afundamento no piso e desnível de porta. Necessita nivelamento de fundação.", timeAgo: "8 min", ownerName: "Lucas Albuquerque", ownerPhone: "(214) 555-0112" },
    { id: "dal-302", category: "Pintura & Exterior", badge: "MÉDIA", addressMasked: "•••• Gaston Ave", addressFull: "5812 Gaston Ave", neighborhood: "Lakewood", city: "Dallas", description: "Pintura externa completa de sobrado residencial de 2 pisos.", timeAgo: "25 min", ownerName: "Patricia Ramos", ownerPhone: "(469) 555-0165" },
    { id: "dal-303", category: "Encanamento & Esgoto", badge: "ALTA", addressMasked: "•••• Preston Rd", addressFull: "7820 Preston Rd", neighborhood: "Preston Hollow", city: "Dallas", description: "Retorno de água na linha principal subterrânea. Necessita substituição.", timeAgo: "51 min", ownerName: "Ricardo Santos", ownerPhone: "(972) 555-0131" },
  ],
  Chicago: [
    { id: "chi-401", category: "Aquecimento & Caldeira", badge: "URGENTE", addressMasked: "•••• Milwaukee Ave", addressFull: "2410 N Milwaukee Ave", neighborhood: "Logan Square", city: "Chicago", description: "Caldeira parou de aquecer os radiadores. Família precisa de conserto urgente.", timeAgo: "4 min", ownerName: "Eduardo Farias", ownerPhone: "(312) 555-0184" },
    { id: "chi-402", category: "Telhado & Calha", badge: "ALTA", addressMasked: "•••• 18th St", addressFull: "1645 W 18th St", neighborhood: "Pilsen", city: "Chicago", description: "Telhas arrancadas por vento forte e calha entupida transbordando.", timeAgo: "22 min", ownerName: "Sandra Menezes", ownerPhone: "(773) 555-0156" },
    { id: "chi-403", category: "Elétrica & Fiação", badge: "MÉDIA", addressMasked: "•••• 53rd St", addressFull: "1420 E 53rd St", neighborhood: "Hyde Park", city: "Chicago", description: "Instalação de tomadas dedicadas para ar-condicionado e revisão da fiação.", timeAgo: "39 min", ownerName: "Gabriel Rocha", ownerPhone: "(872) 555-0120" },
  ],
};



const SIGNAL_STYLE = [
  { color: "#f59e0b", bg: "#fff7ed", ring: "#fde68a" },
  { color: "#2563eb", bg: "#eff6ff", ring: "#bfdbfe" },
  { color: "#475569", bg: "#f1f5f9", ring: "#cbd5e1" },
];

function FoldWave({ from, to }: { from: string; to: string }) {
  return (
    <div className="relative -mt-px" style={{ background: from, lineHeight: 0 }}>
      <svg viewBox="0 0 1440 80" preserveAspectRatio="none" className="block h-[60px] w-full sm:h-[80px]">
        <path d="M0,40 C240,80 480,0 720,32 C960,64 1200,16 1440,40 L1440,80 L0,80 Z" fill={to} />
      </svg>
    </div>
  );
}

function Flag({ id, className = "h-5 w-7" }: { id: Lang; className?: string }) {
  if (id === "pt") {
    return (
      <svg className={className} viewBox="0 0 28 20" aria-hidden>
        <rect width="28" height="20" rx="3" fill="#009B3A" />
        <polygon points="14,3 25,10 14,17 3,10" fill="#FEDD00" />
        <circle cx="14" cy="10" r="4" fill="#002776" />
      </svg>
    );
  }
  if (id === "en") {
    return (
      <svg className={className} viewBox="0 0 28 20" aria-hidden>
        <rect width="28" height="20" rx="3" fill="#B22234" />
        <rect y="1.54" width="28" height="1.54" fill="#fff" />
        <rect y="4.62" width="28" height="1.54" fill="#fff" />
        <rect y="7.7" width="28" height="1.54" fill="#fff" />
        <rect y="10.77" width="28" height="1.54" fill="#fff" />
        <rect y="13.85" width="28" height="1.54" fill="#fff" />
        <rect y="16.92" width="28" height="1.54" fill="#fff" />
        <rect width="12" height="10.8" rx="2" fill="#3C3B6E" />
      </svg>
    );
  }
  return (
    <svg className={className} viewBox="0 0 28 20" aria-hidden>
      <rect width="28" height="20" rx="3" fill="#AA151B" />
      <rect y="5.5" width="28" height="9" fill="#F1BF00" />
    </svg>
  );
}

function LangSwitch({ lang, setLang }: { lang: Lang; setLang: (l: Lang) => void }) {
  return (
    <div className="flex items-center gap-1 rounded-[18px] bg-[#141820] p-1.5" role="group" aria-label="Language">
      {LANGS.map((l) => (
        <button
          key={l.id}
          onClick={() => setLang(l.id)}
          aria-label={l.label}
          aria-pressed={lang === l.id}
          className={`grid h-10 w-11 place-items-center rounded-[12px] transition ${lang === l.id ? "bg-[#0f2a24] ring-2 ring-[#2feaa8]" : "opacity-70 hover:opacity-100"}`}
        >
          <Flag id={l.id} />
        </button>
      ))}
    </div>
  );
}

function Kicker({ children, color }: { children: React.ReactNode; color: string }) {
  return <p className="kicker" style={{ color }}>{children}</p>;
}

function timeAgoLabel(from: number, now: number, t: (typeof COPY)[Lang]) {
  const minutes = Math.max(1, Math.floor((now - from) / 60000));
  if (minutes < 60) return t.agoMin(minutes);
  const hours = Math.floor(minutes / 60);
  if (hours === 1) return t.agoHour;
  if (hours < 24) return t.agoHours(hours);
  return t.agoLittle;
}

export default function App() {
  const [lang, setLang] = useState<Lang>("pt");
  const t = COPY[lang];
  const [activeCity, setActiveCity] = useState<City>("New York");
  const [reservedLeadId, setReservedLeadId] = useState<string | null>(null);
  const [timerSeconds, setTimerSeconds] = useState(3600);
  const [whatsappLead, setWhatsappLead] = useState<LeadItem | null>(null);
  const [tplTrade, setTplTrade] = useState<Trade>("Telhado");
  const [tplChannel, setTplChannel] = useState<Channel>("whatsapp");
  const [copied, setCopied] = useState(false);
  const [ticketValue, setTicketValue] = useState(6500);
  const [conversionRate, setConversionRate] = useState(3);
  const [openFaq, setOpenFaq] = useState<number | null>(0);
  const [modalOpen, setModalOpen] = useState(false);
  const [formSent, setFormSent] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [leadsBank, setLeadsBank] = useState(11256);
  const [withOwner, setWithOwner] = useState(8499);
  const [lastScanAt] = useState(() => Date.now() - 1000 * 60 * 96);
  const [nowTick, setNowTick] = useState(Date.now());
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    const i = setInterval(() => {
      setLeadsBank((v) => v + (Math.random() > 0.45 ? 1 : 0));
      setWithOwner((v) => v + (Math.random() > 0.7 ? 1 : 0));
    }, 6500);
    return () => clearInterval(i);
  }, []);

  useEffect(() => {
    const i = setInterval(() => setNowTick(Date.now()), 30000);
    return () => clearInterval(i);
  }, []);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!reservedLeadId) return;
    const i = setInterval(() => setTimerSeconds((v) => (v > 0 ? v - 1 : 0)), 1000);
    return () => clearInterval(i);
  }, [reservedLeadId]);

  const fmtTimer = (s: number) => `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;
  const validatedPhones = Math.round(300 * 0.7);
  const estimatedVisits = Math.round(validatedPhones * 0.25);
  const closedJobs = Math.max(1, Math.round(estimatedVisits * (conversionRate / 20)));
  const monthlyRevenue = closedJobs * ticketValue;
  const monthsPaid = (ticketValue / 340).toFixed(1);
  const openModal = () => { setFormSent(false); setModalOpen(true); };
  const scrollTo = (id: string) => { document.getElementById(id)?.scrollIntoView({ behavior: "smooth" }); setMenuOpen(false); };
  const copyTpl = (text: string) => { navigator.clipboard?.writeText(text).catch(() => {}); setCopied(true); setTimeout(() => setCopied(false), 2500); };

  return (
    <div className="min-h-screen bg-white text-[#0b1220] selection:bg-[#10b981] selection:text-white">
      <header className={`sticky top-0 z-40 transition-all duration-300 ${scrolled ? "border-b border-[#eef1f6] bg-white/90 backdrop-blur-xl shadow-sm" : "bg-white/80 backdrop-blur-md"}`}>
        <div className="mx-auto max-w-[1400px] px-4 sm:px-6">
          <div className="flex h-16 items-center justify-between gap-4">
            <button onClick={() => scrollTo("topo")} className="flex shrink-0 items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-tr from-[#7c5cff] to-[#10b981] shadow-md shadow-[#10b981]/20">
                <svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor"><path d="m13 2-9 12h7l-1 8 10-13h-7V2Z" /></svg>
              </div>
              <span className="font-display text-lg font-black">Magic<span className="text-[#10b981]">Leads</span></span>
            </button>
            <div className="flex shrink-0 items-center gap-3">
              <LangSwitch lang={lang} setLang={setLang} />
              <button onClick={openModal} className="btn-mint hidden px-5 py-2.5 text-[13px] sm:block">{t.start}</button>
              <button onClick={() => setMenuOpen(!menuOpen)} className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#e2e8f0] lg:hidden" aria-label="Menu">
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  {menuOpen ? <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" /> : <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />}
                </svg>
              </button>
            </div>
          </div>
          <nav className="hidden h-11 items-center justify-center gap-8 border-t border-[#eef1f6] text-[13px] font-semibold text-[#54617a] lg:flex">
            {t.nav.map(([label, id]) => (
              <button key={id} onClick={() => scrollTo(id)} className="whitespace-nowrap transition hover:text-[#0b1220]">{label}</button>
            ))}
          </nav>
        </div>
        {menuOpen && (
          <div className="border-t border-[#eef1f6] bg-white px-4 py-4 lg:hidden">
            <div className="flex flex-col gap-1">
              {t.nav.map(([label, id]) => (
                <button key={id} onClick={() => scrollTo(id)} className="rounded-lg px-3 py-2.5 text-left text-sm font-semibold text-[#54617a] hover:bg-[#f1f4f9]">{label}</button>
              ))}
              <button onClick={openModal} className="btn-mint mt-2 py-3 text-sm">{t.start}</button>
            </div>
          </div>
        )}
      </header>

      <section id="topo" className="bg-grid-soft relative overflow-hidden">
        <div className="pointer-events-none absolute -top-32 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-[#10b981]/[0.09] blur-[150px]" />
        <div className="relative mx-auto max-w-6xl px-4 pb-16 pt-16 text-center sm:px-6 md:pb-24 md:pt-24">
          <div className="fade-up inline-flex items-center gap-2 text-[12px] font-bold tracking-wider text-[#0a8f65]">
            <span className="blink-dot" /><span className="blink-dot blink-dot-delay" /><span className="blink-dot blink-dot-delay-2" />
            {leadsBank.toLocaleString("en-US")} {t.heroKicker}
          </div>
          <h1 className="fade-up font-display mx-auto mt-8 max-w-5xl text-[3.1rem] font-black leading-[0.9] sm:text-7xl lg:text-[6.2rem] lg:leading-[0.88]">
            {t.heroTitle1}<br /><span className="hl">{t.heroTitle2}</span>
          </h1>
          <p className="fade-up mx-auto mt-8 max-w-2xl text-lg leading-relaxed text-[#54617a] sm:text-xl">{t.heroSub}</p>
          <div className="fade-up mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <button onClick={openModal} className="btn-mint flex w-full items-center justify-center gap-2.5 px-9 py-4 text-base sm:w-auto">
              {t.ctaPanel}
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" /></svg>
            </button>
            <button onClick={() => scrollTo("simulador")} className="btn-outline flex w-full items-center justify-center px-7 py-4 text-sm sm:w-auto">{t.ctaSample}</button>
          </div>
          <div className="fade-up mt-8 flex flex-wrap items-center justify-center gap-x-8 gap-y-2 text-sm font-medium text-[#54617a]">
            {t.trust.map((item) => (
              <span key={item} className="flex items-center gap-1.5">
                <svg className="h-4 w-4 text-[#10b981]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" /></svg>
                {item}
              </span>
            ))}
          </div>
          <p className="mt-4 text-sm text-[#94a3b8]">{t.priceLine}</p>
          <div className="pop-in mx-auto mt-14 max-w-4xl">
            <div className="grid gap-8 sm:grid-cols-3">
              <div className="text-center">
                <p className="inline-flex items-center gap-2 font-display text-4xl font-black text-[#10b981] sm:text-5xl"><span className="blink-dot" />{leadsBank.toLocaleString("en-US")}+</p>
                <p className="mt-2 text-[11px] font-bold uppercase tracking-wider text-[#94a3b8]">{t.statBank}</p>
              </div>
              <div className="text-center">
                <p className="inline-flex items-center gap-2 font-display text-4xl font-black text-[#10b981] sm:text-5xl"><span className="blink-dot blink-dot-delay" />{withOwner.toLocaleString("en-US")}+</p>
                <p className="mt-2 text-[11px] font-bold uppercase tracking-wider text-[#94a3b8]">{t.statOwner}</p>
              </div>
              <div className="text-center">
                <p className="inline-flex items-center gap-2 font-display text-4xl font-black text-[#10b981] sm:text-5xl"><span className="blink-dot blink-dot-delay-2" />5+</p>
                <p className="mt-2 text-[11px] font-bold uppercase tracking-wider text-[#94a3b8]">{t.statCities}</p>
              </div>
            </div>
            <p className="mt-8 flex items-center justify-center gap-2 text-sm font-medium text-[#0a8f65]">
              <span className="blink-dot" /><span className="blink-dot blink-dot-delay" /><span className="blink-dot blink-dot-delay-2" />
              {t.updated} {timeAgoLabel(lastScanAt, nowTick, t)}
            </p>
          </div>
        </div>
        <div className="overflow-hidden border-t border-[#eef1f6] bg-white py-4">
          <div className="animate-marquee items-center gap-8 text-xs font-bold uppercase tracking-widest text-[#94a3b8]">
            {[...t.categories, ...t.categories].map((c, i) => (
              <span key={`${c}-${i}`} className="flex shrink-0 items-center gap-8">{c}<span className="h-1.5 w-1.5 rounded-full bg-[#10b981]" /></span>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-dots py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Kicker color="#7c5cff">{t.problemKicker}</Kicker>
          <h2 className="font-display mt-5 max-w-4xl text-[2.5rem] font-black leading-[0.98] sm:text-6xl">{t.problemTitle} <span className="hl">{t.problemHl}</span></h2>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-[#54617a]">{t.problemSub}</p>
          <div className="mt-14 grid gap-6 md:grid-cols-3">
            {t.problems.map((p) => (
              <article key={p.kicker} className="card card-hover flex flex-col p-8">
                <p className="kicker text-[#f43f5e]">{p.kicker}</p>
                <h3 className="font-display mt-4 text-2xl font-black">{p.title}</h3>
                <p className="mt-4 flex-1 text-[15px] leading-relaxed text-[#54617a]">{p.body}</p>
                <span className="mt-6 inline-flex w-fit rounded-lg bg-[#f1f4f9] px-3.5 py-2 text-xs font-bold text-[#54617a]">{t.costWord} {p.cost}</span>
              </article>
            ))}
          </div>
          <div className="mt-8 overflow-hidden rounded-[1.6rem] bg-[#0b1220] p-8 md:p-10">
            <div className="flex flex-col items-start gap-6 md:flex-row md:items-center">
              <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-[#10b981] text-white"><svg className="h-7 w-7" viewBox="0 0 24 24" fill="currentColor"><path d="m13 2-9 12h7l-1 8 10-13h-7V2Z" /></svg></span>
              <p className="text-xl font-bold leading-snug text-white sm:text-2xl">{t.flip}</p>
              <button onClick={openModal} className="btn-mint shrink-0 px-6 py-3.5 text-sm">{t.seeHow}</button>
            </div>
          </div>
        </div>
      </section>

      <section id="oficios" className="scroll-mt-20 bg-white py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Kicker color="#7c5cff">{t.oficiosKicker}</Kicker>
          <h2 className="font-display mt-5 max-w-4xl text-[2.4rem] font-black leading-[0.98] sm:text-5xl md:text-6xl">{t.oficiosTitle} <span className="hl">{t.oficiosHl}</span></h2>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-[#54617a]">{t.oficiosSub}</p>
          <div className="mt-12 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {t.categories.map((cat) => (
              <div key={cat} className="card flex items-center gap-3 px-4 py-3.5">
                <span className="h-2 w-2 shrink-0 rounded-full bg-[#10b981]" />
                <span className="text-sm font-bold">{cat}</span>
              </div>
            ))}
          </div>
          <p className="mt-14 text-center text-sm font-semibold text-[#54617a]">{t.oficiosPaths}</p>
          <div className="mt-6 grid gap-5 md:grid-cols-3">
            {t.signals.map((s, i) => (
              <article key={s.label} className="rounded-3xl p-7" style={{ background: SIGNAL_STYLE[i].bg, boxShadow: `inset 0 0 0 1px ${SIGNAL_STYLE[i].ring}` }}>
                <span className="inline-flex items-center gap-2 text-xs font-black uppercase tracking-wider" style={{ color: SIGNAL_STYLE[i].color }}>
                  <span className="h-2 w-2 rounded-full" style={{ background: SIGNAL_STYLE[i].color }} />{s.hint}
                </span>
                <h3 className="font-display mt-3 text-2xl font-black">{s.label}</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-[#54617a]">{s.body}</p>
              </article>
            ))}
          </div>
          <p className="mx-auto mt-6 max-w-2xl text-center text-sm text-[#94a3b8]">{t.oficiosFoot}</p>
        </div>
      </section>

      <FoldWave from="#ffffff" to="#0b1220" />

      <section id="simulador" className="scroll-mt-20 bg-[#0b1220] py-20 text-white md:py-24">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="kicker justify-center text-[#34e0a1]">{t.sampleKicker}</span>
            <h2 className="font-display mt-5 text-4xl font-black leading-[0.98] sm:text-5xl">{t.sampleTitle}</h2>
            <p className="mt-5 text-lg text-[#9aa7ba]">{t.sampleSub}</p>
          </div>
          <div className="mt-14 overflow-hidden rounded-[1.8rem] border border-white/10 bg-gradient-to-b from-[#111a29] to-[#0a101b]">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 bg-[#0a0f1a] p-4 sm:px-6">
              <span className="text-xs font-semibold text-[#9aa7ba]">painel.magicleads.app</span>
              <div className="flex flex-wrap gap-1 rounded-xl border border-white/10 bg-[#0c1220] p-1">
                {(["New York", "Boston", "Dallas", "Chicago"] as City[]).map((c) => (
                  <button key={c} onClick={() => { setActiveCity(c); setReservedLeadId(null); }} className={`rounded-lg px-3 py-1.5 text-xs font-bold ${activeCity === c ? "bg-[#10b981] text-white" : "text-[#9aa7ba] hover:text-white"}`}>{c}</button>
                ))}
              </div>
            </div>
            <div className="grid gap-5 p-4 sm:p-6 lg:grid-cols-3">
              {LIVE_LEADS[activeCity].map((lead) => {
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
                            <span>{t.reserved}</span><span className="font-mono">{fmtTimer(timerSeconds)}</span>
                          </div>
                          <div className="rounded-lg border border-white/10 bg-black/60 p-3">
                            <p className="text-[11px] text-[#9aa7ba]">{lead.ownerName} · {t.owner}</p>
                            <p className="font-mono text-base font-black text-[#34e0a1]">{lead.ownerPhone}</p>
                            <p className="mt-1 text-[10px] text-[#64748b]">{lead.addressFull}</p>
                          </div>
                          <button onClick={() => setWhatsappLead(lead)} className="btn-mint w-full py-2.5 text-xs uppercase tracking-wider">{t.openWa}</button>
                        </div>
                      ) : (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between text-[11px] text-[#9aa7ba]"><span>{t.address}</span><span className="font-mono text-white">{lead.addressMasked}</span></div>
                          <button onClick={() => { setReservedLeadId(lead.id); setTimerSeconds(3600); }} className="flex w-full items-center justify-center rounded-lg border border-[#10b981]/40 bg-[#10b981]/10 py-2.5 text-xs font-bold text-[#34e0a1] hover:bg-[#10b981] hover:text-white">{t.reserveHour}</button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 bg-[#0a0f1a] p-4 text-xs sm:px-6">
              <span className="text-[#9aa7ba]">{t.payOk}</span>
              <button onClick={openModal} className="font-bold text-[#34e0a1] hover:underline">{t.unlock4}</button>
            </div>
          </div>
        </div>
      </section>

      <FoldWave from="#0b1220" to="#ffffff" />

      <section id="comparativo" className="scroll-mt-20 bg-white py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Kicker color="#7c5cff">{t.compareKicker}</Kicker>
          <h2 className="font-display mt-5 max-w-4xl text-[2.4rem] font-black leading-[0.98] sm:text-5xl">{t.compareTitle} <span className="hl">{t.compareHl}</span></h2>
          <p className="mt-6 max-w-2xl text-lg text-[#54617a]">{t.compareSub}</p>
          <div className="mt-14 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {t.comparisons.map((c) => (
              <article key={c.channel} className={`flex flex-col rounded-3xl p-7 ${c.winner ? "bg-[#0b1220] text-white shadow-2xl md:-translate-y-3" : "card card-hover"}`}>
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className={`font-display text-xl font-black ${c.winner ? "text-[#34e0a1]" : ""}`}>{c.channel}</h3>
                    <p className="text-xs text-[#94a3b8]">{c.sub}</p>
                  </div>
                  {c.winner && <span className="rounded-full bg-[#10b981] px-2.5 py-1 text-[10px] font-black text-white">{t.best}</span>}
                </div>
                <div className="mt-6">
                  <p className={`font-display text-3xl font-black ${c.winner ? "text-white" : ""}`}>{c.cost}</p>
                  <p className="text-xs text-[#94a3b8]">{c.costLabel}</p>
                </div>
                <div className={`mt-6 space-y-3 border-t pt-5 text-sm ${c.winner ? "border-white/10" : "border-[#eef1f6]"}`}>
                  {[[t.excl, c.exclusivity], [t.intentL, c.intent], [t.phoneL, c.phone]].map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-3">
                      <span className="text-[#94a3b8]">{k}</span>
                      <span className={`text-right font-bold ${c.winner ? "text-[#34e0a1]" : ""}`}>{v}</span>
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="como-funciona" className="bg-dots scroll-mt-20 py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="kicker justify-center text-[#10b981]">{t.howKicker}</span>
            <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t.howTitle} <span className="hl">{t.howHl}</span></h2>
          </div>
          <div className="mt-16 grid gap-6 md:grid-cols-3">
            {[{ n: "01", tint: "#10b981", bg: "#10b98115", title: t.step1t, body: t.step1b }, { n: "02", tint: "#7c5cff", bg: "#7c5cff15", title: t.step2t, body: t.step2b, featured: true }, { n: "03", tint: "#f59e0b", bg: "#f59e0b15", title: t.step3t, body: t.step3b }].map((s) => (
              <article key={s.n} className={`card card-hover p-8 ${s.featured ? "ring-2 ring-[#7c5cff]/25" : ""}`}>
                <span className="flex h-14 w-14 items-center justify-center rounded-2xl font-display text-xl font-black" style={{ background: s.bg, color: s.tint }}>{s.n}</span>
                <h3 className="font-display mt-6 text-xl font-bold">{s.title}</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-[#54617a]">{s.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="templates" className="scroll-mt-20 bg-white py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="grid gap-12 lg:grid-cols-12 lg:items-center">
            <div className="lg:col-span-5">
              <Kicker color="#f43f5e">{t.tplKicker}</Kicker>
              <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t.tplTitle} <span className="hl">{t.tplHl}</span></h2>
              <p className="mt-6 text-[15px] text-[#54617a]">{t.tplSub}</p>
              <div className="mt-7 flex flex-wrap gap-2">
                {t.trades.map((label, i) => (
                  <button key={TRADE_KEYS[i]} onClick={() => setTplTrade(TRADE_KEYS[i])} className={`rounded-lg px-3.5 py-1.5 text-xs font-bold ${tplTrade === TRADE_KEYS[i] ? "bg-[#0b1220] text-white" : "bg-[#f1f4f9] text-[#54617a]"}`}>{label}</button>
                ))}
              </div>
              <div className="mt-3 flex gap-2">
                {(["whatsapp", "sms", "email"] as Channel[]).map((c) => (
                  <button key={c} onClick={() => setTplChannel(c)} className={`rounded-lg px-3.5 py-1.5 text-xs font-bold uppercase ${tplChannel === c ? "bg-[#10b981] text-white" : "border border-[#e2e8f0] text-[#54617a]"}`}>{c}</button>
                ))}
              </div>
            </div>
            <div className="lg:col-span-7">
              <div className="card overflow-hidden">
                <div className="flex items-center justify-between border-b border-[#eef1f6] bg-[#f8fafc] p-4">
                  <span className="text-xs font-bold text-[#54617a]">{t.trades[TRADE_KEYS.indexOf(tplTrade)]} · {tplChannel.toUpperCase()}</span>
                  <button onClick={() => copyTpl(t.templates[tplTrade][tplChannel])} className="btn-dark px-3.5 py-1.5 text-xs">{copied ? t.copied : t.copy}</button>
                </div>
                <div className="p-6">
                  <div className="rounded-2xl bg-[#e8f9ef] p-5"><pre className="whitespace-pre-wrap font-sans text-[15px] leading-relaxed">{t.templates[tplTrade][tplChannel]}</pre></div>
                  <p className="mt-4 text-xs text-[#94a3b8]">{t.tplFields}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <FoldWave from="#ffffff" to="#0b1220" />

      <section id="calculadora" className="scroll-mt-20 bg-[#0b1220] py-20 text-white md:py-24">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="kicker justify-center text-[#34e0a1]">{t.calcKicker}</span>
            <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t.calcTitle} <span className="text-[#34e0a1]">{t.calcHl}</span></h2>
            <p className="mt-5 text-lg text-[#9aa7ba]">{t.calcSub}</p>
          </div>
          <div className="mt-14 grid gap-6 lg:grid-cols-12">
            <div className="rounded-[1.5rem] border border-white/10 bg-[#111a29] p-7 lg:col-span-6">
              <div className="flex items-center justify-between"><span className="text-sm font-bold text-[#cbd5e1]">{t.ticketAvg}</span><span className="font-display text-2xl font-black text-[#34e0a1]">${ticketValue.toLocaleString()}</span></div>
              <input type="range" min={2000} max={15000} step={500} value={ticketValue} onChange={(e) => setTicketValue(Number(e.target.value))} className="range-dark mt-4 w-full" />
              <div className="mt-8 border-t border-white/10 pt-6">
                <div className="flex items-center justify-between"><span className="text-sm font-bold text-[#cbd5e1]">{t.closes20}</span><span className="font-display text-2xl font-black text-[#9d80ff]">{conversionRate}</span></div>
                <input type="range" min={1} max={6} step={1} value={conversionRate} onChange={(e) => setConversionRate(Number(e.target.value))} className="range-dark mt-4 w-full" />
                <div className="mt-2 flex justify-between text-[10px] font-bold text-[#64748b]"><span>{t.conservative}</span><span>{t.normal}</span><span>{t.high}</span></div>
              </div>
              <div className="mt-8 grid grid-cols-3 gap-3 border-t border-white/10 pt-6 text-center">
                {[["300", t.leadsM], [`~${validatedPhones}`, t.withPh], [`~${estimatedVisits}`, t.visitsL]].map(([n, l]) => (
                  <div key={l} className="rounded-xl bg-white/5 p-3"><p className="font-display text-lg font-black">{n}</p><p className="text-[10px] text-[#9aa7ba]">{l}</p></div>
                ))}
              </div>
            </div>
            <div className="flex flex-col justify-between rounded-[1.5rem] bg-gradient-to-br from-[#10b981] to-[#0a8f65] p-8 lg:col-span-6">
              <div>
                <span className="rounded-full bg-white/20 px-3 py-1 text-xs font-black">{t.revEst}</span>
                <p className="font-display mt-4 text-6xl font-black">${monthlyRevenue.toLocaleString()}<span className="text-2xl font-bold text-white/60">{t.perMo}</span></p>
                <p className="mt-3 text-sm font-bold">{t.aboutJobs(closedJobs, ticketValue.toLocaleString())}</p>
              </div>
              <div className="my-6 space-y-3 border-y border-white/20 py-5 text-sm font-semibold">
                <div className="flex justify-between"><span className="text-white/80">{t.invest}</span><span>$340{t.perMo}</span></div>
                <div className="flex justify-between"><span className="text-white/80">{t.costDelivered}</span><span>~$1.62</span></div>
                <div className="flex justify-between text-base"><span>{t.onePays}</span><span className="rounded-lg bg-[#04231a] px-2.5 py-0.5 text-[#34e0a1]">{monthsPaid} {t.months}</span></div>
              </div>
              <button onClick={openModal} className="w-full rounded-xl bg-white py-4 text-sm font-black uppercase tracking-wider text-[#0a8f65]">{t.calcCta}</button>
            </div>
          </div>
        </div>
      </section>

      <FoldWave from="#0b1220" to="#f6f8fc" />

      <section className="bg-dots py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Kicker color="#7c5cff">{t.resultsKicker}</Kicker>
          <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t.resultsTitle} <span className="hl">{t.resultsHl}</span></h2>
          <div className="mt-14 grid gap-6 md:grid-cols-3">
            {t.quotes.map((q) => (
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

      <section id="preco" className="scroll-mt-20 bg-white py-20 md:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="mx-auto max-w-3xl text-center">
            <span className="kicker justify-center text-[#10b981]">{t.priceKicker}</span>
            <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t.priceTitle} <span className="hl">{t.priceHl}</span></h2>
          </div>
          <div className="mx-auto mt-14 grid max-w-5xl gap-6 lg:grid-cols-[1.15fr_0.85fr]">
            <div className="rounded-[1.6rem] bg-[#0b1220] p-8 text-white sm:p-10">
              <span className="rounded-full bg-[#10b981]/15 px-3 py-1 text-[11px] font-black text-[#34e0a1]">{t.planTag}</span>
              <div className="mt-5 flex items-end gap-2">
                <span className="font-display text-7xl font-black">$79</span>
                <span className="mb-3 text-[#9aa7ba]">{t.week}<br /><span className="text-sm">{t.month}</span></span>
              </div>
              <p className="mt-3 text-sm text-[#9aa7ba]">{t.planSub}</p>
              <div className="my-7 h-px bg-white/10" />
              <ul className="space-y-3.5 text-[15px]">
                {t.planFeatures.map((f) => (
                  <li key={f} className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#10b981]/15 text-[#34e0a1]">✓</span>
                    <span className="text-[#e2e8f0]">{f}</span>
                  </li>
                ))}
              </ul>
              <button onClick={openModal} className="btn-mint mt-8 w-full py-4 text-base uppercase tracking-wider">{t.planCta}</button>
              <p className="mt-3 text-center text-xs text-[#64748b]">{t.planSafe}</p>
            </div>
            <div className="flex flex-col gap-6">
              <div className="card p-7">
                <p className="font-display text-lg font-bold">{t.billing}</p>
                <ol className="mt-4 space-y-3 text-sm text-[#54617a]">
                  <li className="flex gap-3"><span className="font-black text-[#10b981]">1.</span>{t.bill1}</li>
                  <li className="flex gap-3"><span className="font-black text-[#10b981]">2.</span>{t.bill2}</li>
                  <li className="flex gap-3"><span className="font-black text-[#10b981]">3.</span>{t.bill3}</li>
                </ol>
              </div>
              <div className="card p-7">
                <p className="font-display text-lg font-bold">{t.never}</p>
                <ul className="mt-4 space-y-2.5 text-sm text-[#54617a]">
                  {t.neverItems.map((n) => <li key={n} className="flex gap-2.5"><span className="text-[#f43f5e]">✕</span>{n}</li>)}
                </ul>
              </div>
              <div className="rounded-[1.5rem] border border-[#f59e0b]/25 bg-[#fff7ed] p-7">
                <p className="font-display text-lg font-black text-[#b45309]">{t.noRenew}</p>
                <p className="mt-2 text-sm text-[#92702a]">{t.risk79}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="faq" className="bg-dots scroll-mt-20 py-20 md:py-28">
        <div className="mx-auto grid max-w-7xl gap-12 px-4 sm:px-6 lg:grid-cols-[0.85fr_1.15fr]">
          <div>
            <Kicker color="#f43f5e">{t.faqKicker}</Kicker>
            <h2 className="font-display mt-5 text-4xl font-black sm:text-5xl">{t.faqTitle}</h2>
            <p className="mt-6 text-[15px] text-[#54617a]">{t.faqSub}</p>
            <button onClick={openModal} className="btn-dark mt-7 px-6 py-3.5 text-sm">{t.faqCta}</button>
          </div>
          <div className="space-y-3">
            {t.faqs.map((f, i) => {
              const open = openFaq === i;
              return (
                <div key={f.q} className={`card overflow-hidden ${open ? "shadow-lg" : ""}`}>
                  <button onClick={() => setOpenFaq(open ? null : i)} className="flex w-full items-center justify-between gap-4 p-5 text-left">
                    <span className="font-display text-[17px] font-bold">{f.q}</span>
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

      <section className="relative overflow-hidden bg-[#0b1220] py-24 text-center text-white">
        <div className="relative mx-auto max-w-4xl px-4">
          <div className="inline-flex items-center gap-2 rounded-full border border-[#10b981]/30 bg-[#10b981]/10 px-4 py-1.5 text-[11px] font-bold tracking-wider text-[#34e0a1]">
            <span className="blink-dot" />{t.finalKicker}
          </div>
          <h2 className="font-display mt-6 text-4xl font-black sm:text-6xl">{t.finalTitle}<br /><span className="hl">{t.finalHl}</span></h2>
          <p className="mx-auto mt-6 max-w-xl text-lg text-[#9aa7ba]">{t.finalSub}</p>
          <button onClick={openModal} className="btn-mint mx-auto mt-9 inline-flex items-center gap-2.5 px-9 py-4 text-base uppercase tracking-wider">{t.finalCta}</button>
          <p className="mt-4 text-xs text-[#64748b]">{t.finalFoot}</p>
        </div>
      </section>

      <FoldWave from="#0b1220" to="#080d16" />
      <footer className="bg-[#080d16] pb-16 pt-8 text-sm text-[#64748b] sm:pb-12">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="grid gap-10 border-b border-white/10 pb-10 md:grid-cols-4">
            <div className="md:col-span-2">
              <div className="flex items-center gap-2.5 text-white">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-tr from-[#7c5cff] to-[#10b981]"><svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor"><path d="m13 2-9 12h7l-1 8 10-13h-7V2Z" /></svg></div>
                <span className="font-display text-lg font-black">Magic<span className="text-[#34e0a1]">Leads</span></span>
              </div>
              <p className="mt-4 max-w-sm leading-relaxed">{t.footerBio}</p>
              <p className="mt-4 text-xs font-semibold text-[#9aa7ba]">New York · Boston · Dallas · Chicago</p>
            </div>
            <div>
              <p className="text-xs font-black uppercase tracking-widest text-white">{t.platform}</p>
              <div className="mt-4 flex flex-col gap-2.5">{t.nav.slice(0, 4).map(([label, id]) => <button key={id} onClick={() => scrollTo(id)} className="text-left hover:text-white">{label}</button>)}</div>
            </div>
            <div>
              <p className="text-xs font-black uppercase tracking-widest text-white">{t.account}</p>
              <div className="mt-4 flex flex-col gap-2.5">
                {t.nav.slice(4).map(([label, id]) => <button key={id} onClick={() => scrollTo(id)} className="text-left hover:text-white">{label}</button>)}
                <a href="mailto:contato@magicleads.app" className="hover:text-white">{t.talk}</a>
                <button onClick={openModal} className="text-left font-semibold text-[#34e0a1]">{t.startWeek}</button>
              </div>
            </div>
          </div>
          <div className="mt-8 flex flex-col justify-between gap-3 text-xs text-[#475569] sm:flex-row">
            <span>© {new Date().getFullYear()} Magic Leads. {t.rights}</span>
            <span>{t.vary}</span>
          </div>
        </div>
      </footer>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-[#eef1f6] bg-white/95 px-4 py-3 backdrop-blur-xl sm:hidden">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-display text-lg font-black leading-none">$79<span className="text-xs font-bold text-[#94a3b8]">{t.week}</span></p>
            <p className="text-[11px] font-bold text-[#10b981]">{t.stickyArea}</p>
          </div>
          <button onClick={openModal} className="btn-mint flex-1 py-3 text-sm">{t.stickyNow}</button>
        </div>
      </div>

      {whatsappLead && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0b1220]/60 p-4 backdrop-blur-sm" onClick={() => setWhatsappLead(null)}>
          <div className="relative w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => setWhatsappLead(null)} className="absolute right-4 top-4 text-[#94a3b8]">✕</button>
            <div className="flex items-center gap-3 border-b border-[#eef1f6] pb-4">
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-[#25D366] text-white font-black">W</div>
              <div><p className="text-sm font-bold">{whatsappLead.ownerName}</p><p className="font-mono text-xs text-[#10b981]">{whatsappLead.ownerPhone}</p></div>
            </div>
            <div className="my-4 rounded-2xl bg-[#dcf8c6] p-4 text-sm leading-relaxed">
              {t.waMsg(whatsappLead.ownerName.split(" ")[0], whatsappLead.category.toLowerCase(), whatsappLead.addressFull)}
            </div>
            <button onClick={() => { setWhatsappLead(null); openModal(); }} className="btn-mint w-full py-3.5 text-sm uppercase tracking-wider">{t.activateSend}</button>
          </div>
        </div>
      )}

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0b1220]/60 p-4 backdrop-blur-md" onClick={() => setModalOpen(false)}>
          <div className="relative w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl sm:p-8" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => setModalOpen(false)} className="absolute right-4 top-4 text-[#94a3b8]">✕</button>
            {formSent ? (
              <div className="py-6 text-center">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#e8f9ef] text-[#10b981] text-2xl">✓</div>
                <h3 className="font-display mt-5 text-2xl font-black">{t.received}</h3>
                <p className="mt-3 text-sm text-[#54617a]">{t.receivedSub}</p>
                <button onClick={() => setModalOpen(false)} className="btn-mint mt-6 w-full py-3 text-sm">{t.done}</button>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <span className="rounded bg-[#e8f9ef] px-2.5 py-0.5 text-[10px] font-black text-[#0a8f65]">{t.modalTag}</span>
                  <span className="text-xs text-[#94a3b8]">{t.noLock}</span>
                </div>
                <h3 className="font-display mt-3 text-2xl font-black">{t.modalTitle}</h3>
                <p className="mt-1 text-sm text-[#54617a]">{t.modalSub}</p>
                <form onSubmit={(e) => { e.preventDefault(); setFormSent(true); }} className="mt-6 space-y-3.5">
                  <div>
                    <label className="block text-xs font-bold text-[#54617a]">{t.name}</label>
                    <input required type="text" className="mt-1 w-full rounded-xl border border-[#e2e8f0] bg-[#f8fafc] px-3.5 py-2.5 text-sm outline-none focus:border-[#10b981]" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-[#54617a]">{t.phone}</label>
                    <input required type="tel" className="mt-1 w-full rounded-xl border border-[#e2e8f0] bg-[#f8fafc] px-3.5 py-2.5 text-sm outline-none focus:border-[#10b981]" />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-bold text-[#54617a]">{t.specialty}</label>
                      <select className="mt-1 w-full rounded-xl border border-[#e2e8f0] bg-[#f8fafc] px-3 py-2.5 text-sm outline-none focus:border-[#10b981]">
                        {t.categories.map((c) => <option key={c}>{c}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-bold text-[#54617a]">{t.city}</label>
                      <select className="mt-1 w-full rounded-xl border border-[#e2e8f0] bg-[#f8fafc] px-3 py-2.5 text-sm outline-none focus:border-[#10b981]">
                        <option>New York</option><option>Boston</option><option>Dallas</option><option>Chicago</option><option>{t.other}</option>
                      </select>
                    </div>
                  </div>
                  <button type="submit" className="btn-mint mt-4 w-full py-3.5 text-sm uppercase tracking-wider">{t.confirm}</button>
                  <p className="text-center text-[11px] text-[#94a3b8]">{t.seven}</p>
                </form>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
