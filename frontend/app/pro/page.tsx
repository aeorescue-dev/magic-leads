'use client';

import { useEffect, useMemo, useState } from "react";
import {
  LayoutDashboard, FolderKanban, Bell, SlidersHorizontal, Users,
  Search, MapPin, Building2, Sparkles, ChevronRight, Wrench,
  Home as HomeIcon, Hammer, Paintbrush, Waves, Trash2, HardHat,
  CheckCircle2, ArrowUpRight, Clock, Filter, X, Sun, Moon,
  Flame, Zap, Forklift, Droplets, Bug, Droplet, AlertTriangle,
  DoorOpen, AppWindow, Package, Wind,
  AlertCircle, MapPin as MapPinIcon, Phone, TrendingUp,
} from "lucide-react";
import { fetchTodayLeads, fetchDashboardSummary, LeadResponse, DashboardSummary } from "@/lib/api-client";
import { maskAddress } from "@/lib/mask";

type Theme = "dark" | "light";

type Category = {
  key: string;
  label: string;
  icon: any;
  color: string;
  keywords: string[];
};

const CATEGORIES: Category[] = [
  { key: "telhado", label: "Telhado & Estrutura", icon: HardHat, color: "#6366f1", keywords: ["roof", "structure", "collaps", "foundation"] },
  { key: "encanamento", label: "Encanamento", icon: Waves, color: "#0ea5e9", keywords: ["plumb", "water", "sewer", "leak"] },
  { key: "mato", label: "Mato & Entulho", icon: Trash2, color: "#22c55e", keywords: ["grass", "weed", "overgrown", "vegetation", "litter", "trash", "debris", "garbage", "dirty", "unsanitary", "rodent"] },
  { key: "pintura", label: "Pintura", icon: Paintbrush, color: "#f59e0b", keywords: ["paint", "lead"] },
  { key: "obras", label: "Obras & Permissões", icon: Hammer, color: "#ec4899", keywords: ["permit", "construction", "illegal", "building"] },
  { key: "heating", label: "Aquecimento & Água Quente", icon: Flame, color: "#ef4444", keywords: ["heat", "hot water", "heating", "boiler", "radiator", "no heat"] },
  { key: "electrical", label: "Elétrica", icon: Zap, color: "#fbbf24", keywords: ["electric", "electrical", "wiring", "outlet", "circuit", "panel"] },
  { key: "elevator", label: "Elevadores", icon: Forklift, color: "#8b5cf6", keywords: ["elevator", "lift"] },
  { key: "gas", label: "Gás & Vazamentos", icon: Droplets, color: "#f97316", keywords: ["gas", "gas leak", "cooking gas"] },
  { key: "rodent", label: "Roedores & Pragas", icon: Bug, color: "#84cc16", keywords: ["rodent", "rat", "mouse", "vermin", "roach", "pest", "cockroach", "bed bug"] },
  { key: "mold", label: "Mofo & Umidade", icon: Droplet, color: "#06b6d4", keywords: ["mold", "mildew", "fungus"] },
  { key: "lead", label: "Chumbo & Tinta", icon: AlertTriangle, color: "#a855f7", keywords: ["lead", "lead paint", "lead hazard"] },
  { key: "unsanitary", label: "Insanitário & Esgoto", icon: Package, color: "#ec4899", keywords: ["unsanitary", "sanitary", "filth", "sewage", "sewer backup"] },
  { key: "door_window", label: "Portas & Janelas", icon: DoorOpen, color: "#14b8a6", keywords: ["door", "window", "frame", "sash", "jamb"] },
  { key: "debris", label: "Entulho & Lixo", icon: Wind, color: "#64748b", keywords: ["debris", "garbage", "trash", "rubbish", "litter", "dumping"] },
];

function matchCategory(lead: LeadResponse, keywords: string[]) {
  const hay = `${lead.issue_category} ${lead.issue_description} ${lead.case_title} ${lead.descriptor} ${lead.department}`.toLowerCase();
  return keywords.some((k) => hay.includes(k));
}

function catOfLead(lead: LeadResponse) {
  const c = CATEGORIES.find((c) => matchCategory(lead, c.keywords));
  return c || CATEGORIES[0];
}

const DARK = {
  bg: "#0b0d12",
  bg2: "#10121a",
  card: "#10121a",
  sidebar: "#0f1117",
  border: "border-white/5",
  text: "text-slate-100",
  text2: "text-slate-500",
  input: "bg-white/5",
  navHover: "hover:bg-white/5",
  section: "bg-[#10121a] border-white/5",
  header: "bg-[#0b0d12]/80",
};

const LIGHT = {
  bg: "#f6f7fb",
  bg2: "#ffffff",
  card: "#ffffff",
  sidebar: "#ffffff",
  border: "border-slate-200",
  text: "text-slate-900",
  text2: "text-slate-500",
  input: "bg-slate-100",
  navHover: "hover:bg-slate-100",
  section: "bg-white border-slate-200",
  header: "bg-white/80",
};

export default function ProDashboard() {
  const [leads, setLeads] = useState<LeadResponse[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [interests, setInterests] = useState<Set<string>>(new Set(["telhado", "encanamento", "mato", "pintura", "obras", "heating", "electrical", "elevator", "gas", "rodent", "mold", "lead", "unsanitary", "door_window", "debris"]));
  const [shown, setShown] = useState<Set<string>>(new Set());
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>("dark");
  
  // Filter states
  const [selectedCity, setSelectedCity] = useState<string>("Todas");
  const [selectedCategory, setSelectedCategory] = useState<string>("Todas");
  const [selectedUrgency, setSelectedUrgency] = useState<string>("Todas");

  const CITIES = ["Todas", "NYC", "Chicago", "Dallas", "Boston"];
  const CATEGORIES_FILTER = ["Todas", ...CATEGORIES.map(c => c.key)];
  const URGENCIES = ["Todas", "high", "medium", "low"];

  useEffect(() => {
    const saved = localStorage.getItem("pro.theme") as Theme | null;
    if (saved === "light" || saved === "dark") setTheme(saved);
  }, []);

  useEffect(() => {
    localStorage.setItem("pro.theme", theme);
  }, [theme]);

  // Fetch data when filters change
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const [leadsData, summaryData] = await Promise.all([
          fetchTodayLeads(200, selectedCity !== "Todas" ? selectedCity : undefined),
          fetchDashboardSummary(),
        ]);
        if (!cancelled) {
          setLeads(leadsData.leads || []);
          setSummary(summaryData);
        }
      } catch (e) {
        console.error(e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedCity]);

  const T = theme === "dark" ? DARK : LIGHT;

  const toggleInterest = (k: string) => {
    setInterests((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  // Apply all filters (city from API, category/urgency from interests + local filter)
  const filtered = useMemo(
    () => leads.filter((l) => {
      if (!interests.has(catOfLead(l).key)) return false;
      if (selectedCategory !== "Todas" && catOfLead(l).key !== selectedCategory) return false;
      if (selectedUrgency !== "Todas" && l.urgency_level !== selectedUrgency) return false;
      return true;
    }),
    [leads, interests, selectedCategory, selectedUrgency]
  );

  const newAlerts = useMemo(
    () => filtered.filter((l) => !shown.has(l.id)),
    [filtered, shown]
  );

  // Use real stats from backend summary
  const totalInterested = summary?.total_interested ?? 0;
const lastScrapeText = String(summary?.last_scrape ?? "");
const scrapeCount = Number(lastScrapeText.match(/\d+/)?.[0] || 0);
const lastScrapeCount = scrapeCount || (summary?.by_city?.NYC || summary?.total_interested || 0);
  const withContact = summary?.with_contact ?? 0;
  const urgent = summary?.urgent ?? 0;

  // Category stats from backend
  const interestCounts = useMemo(() => {
    const m: Record<string, number> = {};
    if (summary?.by_category) {
      const catMap: Record<string, string> = {
        "Roof": "telhado", "Plumbing": "encanamento", "Grass": "mato",
        "Paint": "pintura", "Permit_Rejected": "obras", "Heating": "heating",
        "Electrical": "electrical", "Elevator": "elevator", "Gas": "gas",
        "Rodent": "rodent", "Mold": "mold", "Lead": "lead",
        "Unsanitary": "unsanitary", "Door_Window": "door_window", "Debris": "debris"
      };
      Object.entries(summary.by_category).forEach(([dbCat, count]) => {
        const key = catMap[dbCat];
        if (key) m[key] = count;
      });
    }
    return m;
  }, [summary]);

  // Urgency stats from backend
  const urgencyCounts = useMemo(() => {
    if (summary?.by_urgency) {
      return {
        high: summary.by_urgency.high || 0,
        medium: summary.by_urgency.medium || 0,
        low: summary.by_urgency.low || 0,
      };
    }
    return { high: 0, medium: 0, low: 0 };
  }, [summary]);

  // City stats from backend
  const cityCounts = useMemo(() => {
    if (summary?.by_city) return summary.by_city;
    return {};
  }, [summary]);

  return (
    <div className="flex min-h-screen transition-colors duration-300" style={{ backgroundColor: T.bg, color: theme === "dark" ? "#e2e8f0" : "#0f172a" }}>
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 bg-black/50 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* SIDEBAR */}
      <aside className={`fixed lg:sticky top-0 z-50 h-screen w-64 shrink-0 flex flex-col border-r transition-all duration-300 lg:translate-x-0 ${T.border} ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}`} style={{ backgroundColor: T.sidebar }}>
        <div className="flex items-center gap-2 px-5 h-16 border-b ${T.border}">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-indigo-500 to-fuchsia-500 flex items-center justify-center">
            <Sparkles className="h-4 w-4 text-white" />
          </div>
          <div>
            <div className={`font-bold text-[15px] leading-none ${theme === "dark" ? "text-white" : "text-slate-900"}`}>Oportuniz</div>
            <div className={`text-[10px] mt-0.5 ${T.text2}`}>Workspace SaaS</div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {[
            { icon: LayoutDashboard, label: "Visão geral", active: true },
            { icon: FolderKanban, label: "Oportunidades", active: false },
            { icon: SlidersHorizontal, label: "Meus interesses", badge: `${interests.size}`, active: false },
            { icon: Bell, label: "Alertas", badge: `${newAlerts.length}`, active: false },
            { icon: Users, label: "Minha equipe", active: false },
          ].map((item) => (
            <button
              key={item.label}
              onClick={() => setSidebarOpen(false)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition ${
                item.active
                  ? "bg-gradient-to-r from-indigo-500/15 to-fuchsia-500/10 text-white border border-indigo-500/20"
                  : `${T.text2} ${T.navHover} ${theme === "dark" ? "hover:text-white" : "hover:text-slate-900"}`
              }`}
            >
              <item.icon className="h-4 w-4" />
              <span className="flex-1 text-left">{item.label}</span>
              {item.badge && (
                <span className="text-[10px] font-semibold bg-indigo-500/20 text-indigo-500 px-1.5 py-0.5 rounded-full">
                  {item.badge}
                </span>
              )}
            </button>
          ))}
        </nav>

        <div className={`p-3 border-t ${T.border}`}>
          <div className={`flex items-center gap-3 px-2 py-2 rounded-lg cursor-pointer ${T.navHover}`}>
            <div className="h-9 w-9 rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center text-sm font-bold text-white">
              CF
            </div>
            <div className="flex-1 min-w-0">
              <div className={`text-sm font-medium truncate ${theme === "dark" ? "text-white" : "text-slate-900"}`}>Contratante Demo</div>
              <div className="text-[11px] text-emerald-500">Plano Pro</div>
            </div>
            <ChevronRight className={`h-4 w-4 ${T.text2}`} />
          </div>
        </div>
      </aside>

      {/* MAIN */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* TOPBAR */}
        <header className={`sticky top-0 z-30 h-16 flex items-center gap-4 px-4 md:px-6 backdrop-blur border-b transition-colors duration-300 ${T.border}`} style={{ backgroundColor: theme === "dark" ? "rgba(11,13,18,0.8)" : "rgba(255,255,255,0.8)" }}>
          <button className="lg:hidden text-slate-500" onClick={() => setSidebarOpen(true)}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>

          <div className="flex-1 max-w-lg hidden sm:block">
            <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${T.text2} ${T.input}`}>
              <Search className="h-4 w-4" />
              <input
                placeholder="Buscar oportunidade, ruas, categorias…"
                className={`bg-transparent outline-none flex-1 placeholder:${theme === "dark" ? "text-slate-500" : "text-slate-400"} ${theme === "dark" ? "text-slate-200" : "text-slate-800"}`}
              />
              <kbd className="text-[10px] bg-white/10 px-1.5 py-0.5 rounded text-slate-500">⌘K</kbd>
            </div>
          </div>

          <div className="ml-auto flex items-center gap-2 md:gap-3">
            {/* THEME TOGGLE */}
            <button
              onClick={() => setTheme((p) => (p === "dark" ? "light" : "dark"))}
              className={`relative p-2 rounded-lg transition ${T.text2} ${T.navHover}`}
              aria-label="Alternar tema"
            >
              {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </button>

            <div className="relative">
              <button
                onClick={() => setBellOpen(!bellOpen)}
                className={`relative p-2 rounded-lg transition ${T.text2} ${T.navHover}`}
              >
                <Bell className="h-5 w-5" />
                {newAlerts.length > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-[9px] font-bold text-white animate-pulse">
                    {newAlerts.length}
                  </span>
                )}
              </button>

              {bellOpen && (
                <div className={`absolute right-0 top-full mt-2 w-80 md:w-96 border shadow-2xl z-50 overflow-hidden animate-scale-in rounded-xl ${theme === "dark" ? "bg-[#14161d] border-white/10" : "bg-white border-slate-200"}`}>
                  <div className={`flex items-center justify-between px-4 py-3 border-b ${T.border}`}>
                    <span className="font-semibold text-sm">Novas oportunidades</span>
                    <button onClick={() => setBellOpen(false)} className={T.text2}>✕</button>
                  </div>
                  <div className={`max-h-96 overflow-y-auto divide-y ${T.border}`}>
                    {newAlerts.length === 0 ? (
                      <div className={`px-4 py-8 text-center text-sm ${T.text2}`}>
                        Nenhum alerta novo nas suas categorias.
                      </div>
                    ) : (
                      newAlerts.slice(0, 8).map((l) => {
                        const c = catOfLead(l);
                        return (
                          <div key={l.id} className={`px-4 py-3 ${T.navHover} flex items-start gap-3`}>
                            <div className="h-8 w-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5" style={{ backgroundColor: c.color + "22" }}>
                              <c.icon className="h-4 w-4" style={{ color: c.color }} />
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className={`text-sm font-medium truncate ${theme === "dark" ? "text-white" : "text-slate-900"}`}>{l.address}</div>
                              <div className={`text-xs truncate ${T.text2}`}>{c.label} · {l.city}</div>
                              <div className="flex items-center gap-1 text-[11px] mt-1">
                                <span className="text-emerald-500 flex items-center gap-1"><ArrowUpRight className="h-3 w-3" />Nova</span>
                                <span className={T.text2}>·</span>
                                <span className={T.text2}>{l.case_status || "recent"}</span>
                              </div>
                              <button
                                onClick={() => setShown((p) => new Set(p).add(l.id))}
                                className="text-[11px] text-indigo-500 hover:text-indigo-600 mt-1"
                              >
                                Marcar como vista
                              </button>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              )}
            </div>

            <button className="hidden md:flex items-center gap-2 bg-gradient-to-r from-indigo-500 to-fuchsia-500 text-white text-sm font-medium px-3 py-2 rounded-lg hover:opacity-90 transition">
              <Sparkles className="h-4 w-4" /> Nova oportunidade
            </button>
          </div>
        </header>

        <main className="flex-1 p-4 md:p-6 space-y-6">
          {/* GREETING */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div>
              <div className="text-[11px] uppercase tracking-widest text-indigo-500 font-semibold">Workspace · Contratante Demo</div>
              <h1 className="text-2xl md:text-3xl font-bold mt-1">Bom dia, vamos garimpar oportunidades ✦</h1>
              <p className={`text-sm mt-1 ${T.text2}`}>
                Você será alertado instantaneamente quando surgir nova oportunidade nas categorias do seu interesse.
              </p>
            </div>
          </div>

          {/* FILTER BAR */}
          <div className={`flex flex-wrap items-center gap-3 p-4 rounded-xl border ${theme === "dark" ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-medium ${T.text2}`}>📍 Cidade:</span>
              <select
                value={selectedCity}
                onChange={(e) => setSelectedCity(e.target.value)}
                className={`px-3 py-1.5 rounded-lg text-sm border ${theme === "dark" ? "bg-[#0b0d1a] border-white/10 text-white" : "bg-white border-slate-200"}`}
              >
                {CITIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-medium ${T.text2}`}>🔧 Categoria:</span>
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className={`px-3 py-1.5 rounded-lg text-sm border ${theme === "dark" ? "bg-[#0b0d1a] border-white/10 text-white" : "bg-white border-slate-200"}`}
              >
                {CATEGORIES_FILTER.map((c) => <option key={c} value={c}>{c === "Todas" ? "Todas" : CATEGORIES.find(x => x.key === c)?.label || c}</option>)}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-medium ${T.text2}`}>⚡ Urgência:</span>
              <select
                value={selectedUrgency}
                onChange={(e) => setSelectedUrgency(e.target.value)}
                className={`px-3 py-1.5 rounded-lg text-sm border ${theme === "dark" ? "bg-[#0b0d1a] border-white/10 text-white" : "bg-white border-slate-200"}`}
              >
                {URGENCIES.map((u) => <option key={u} value={u}>{u === "Todas" ? "Todas" : u.charAt(0).toUpperCase() + u.slice(1)}</option>)}
              </select>
            </div>
            <div className="flex-1" />
            <div className="flex items-center gap-2 text-xs" style={{ color: theme === "dark" ? "#94a3b8" : "#64748b" }}>
              <span>{filtered.length} oportunidades</span>
              <span>·</span>
              <span>{newAlerts.length} novas</span>
            </div>
          </div>

          {/* KPI CARDS */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
            {[
              { label: "No seu interesse", value: totalInterested, delta: "oportunidades reais", icon: Building2, color: "#6366f1" },
              { label: "Última varredura", value: lastScrapeCount, delta: "entraram hoje", icon: TrendingUp, color: "#22c55e" },
              { label: "Com contato", value: withContact, delta: "prontas p/ ligar", icon: Phone, color: "#f59e0b" },
              { label: "Urgentes", value: urgent, delta: "precisam ação", icon: AlertCircle, color: "#ef4444" },
            ].map((k) => (
              <div key={k.label} className={`border rounded-xl p-4 transition-colors ${theme === "dark" ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
                <div className="flex items-center gap-2">
                  <div className={`text-xs ${T.text2}`}>{k.label}</div>
                  <k.icon className="h-4 w-4" style={{ color: k.color }} />
                </div>
                <div className="text-2xl md:text-3xl font-bold mt-1" style={{ color: k.color }}>{k.value}</div>
                <div className={`text-[11px] mt-2 flex items-center gap-1 ${T.text2}`}>
                  <span>{k.delta}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* INTERESTS PANEL */}
            <section className={`border rounded-xl p-5 space-y-4 transition-colors ${theme === "dark" ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="font-semibold">Meus interesses</h2>
                  <p className={`text-xs ${T.text2}`}>Escolha o que você busca. Receba alerta só disso.</p>
                </div>
<SlidersHorizontal className={`h-4 w-4 ${T.text2}`} />
              </div>

              <div className="space-y-2">
                {CATEGORIES.map((c) => {
                  const active = interests.has(c.key);
                  return (
                    <button
                      key={c.key}
                      onClick={() => toggleInterest(c.key)}
                      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border transition ${
                        active ? "bg-white/5" : "opacity-70"
                      } ${theme === "dark" ? "border-white/10" : "border-slate-200"}`}
                      style={active ? { borderColor: c.color + "66", backgroundColor: c.color + "12" } : {}}
                    >
                      <div className="h-9 w-9 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: c.color + "22" }}>
                        <c.icon className="h-4 w-4" style={{ color: c.color }} />
                      </div>
                      <div className="flex-1 text-left">
                        <div className="text-sm font-medium">{c.label}</div>
                        <div className={`text-[11px] ${T.text2}`}>{interestCounts[c.key] || 0} oportunidades</div>
                      </div>
                      <div
                        className={`h-5 w-5 rounded-md flex items-center justify-center border transition ${
                          active ? "text-white" : "text-transparent border-slate-300"
                        }`}
                        style={active ? { backgroundColor: c.color, borderColor: c.color } : {}}
                      >
                        <CheckCircle2 className="h-4 w-4" />
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* URGENCY BREAKDOWN */}
              <div className="pt-2 border-t">
                <h3 className="font-medium text-xs mb-2">Urgência</h3>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { label: "Alta", count: urgencyCounts.high, color: "#ef4444" },
                    { label: "Média", count: urgencyCounts.medium, color: "#f59e0b" },
                    { label: "Baixa", count: urgencyCounts.low, color: "#22c55e" },
                  ].map((u) => (
                    <div key={u.label} className="text-center p-2 rounded-lg" style={{ backgroundColor: u.color + "15" }}>
                      <div className="text-xl font-bold" style={{ color: u.color }}>{u.count}</div>
                      <div className="text-[10px] text-slate-500">{u.label}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* CITY BREAKDOWN */}
              <div className="pt-2 border-t">
                <h3 className="font-medium text-xs mb-2">Por cidade</h3>
                <div className="space-y-1 max-h-40 overflow-y-auto">
                  {Object.entries(cityCounts).slice(0, 6).map(([city, count]) => (
                    <div key={city} className="flex items-center justify-between text-sm px-2 py-1 rounded" style={{ backgroundColor: theme === "dark" ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.02)" }}>
                      <span className="flex items-center gap-1">
                        <MapPinIcon className="h-3 w-3" style={{ color: "#6366f1" }} />
                        {city}
                      </span>
                      <span className="font-medium text-indigo-500">{count}</span>
                    </div>
                  ))}
                  {Object.keys(cityCounts).length > 6 && (
                    <div className="text-center text-[11px] text-slate-500 pt-1">
                      +{Object.keys(cityCounts).length - 6} mais
                    </div>
                  )}
                </div>
              </div>

              <div className={`rounded-lg border p-3 text-xs ${theme === "dark" ? "bg-indigo-500/10 border-indigo-500/20 text-slate-300" : "bg-indigo-50 border-indigo-200 text-slate-600"}`}>
                ✦ Ative novas categorias para ampliar as oportunidades que você recebe em tempo real.
              </div>
            </section>

            {/* OPPORTUNITIES FEED */}
            <section className={`lg:col-span-2 border rounded-xl overflow-hidden flex flex-col transition-colors ${theme === "dark" ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
              <div className={`px-5 py-4 border-b flex items-center justify-between ${T.border}`}>
                <div>
                  <h2 className="font-semibold">Oportunidades para você</h2>
                  <p className={`text-xs ${T.text2}`}>Filtradas pelas suas categorias de interesse</p>
                </div>
                <Filter className={`h-4 w-4 ${T.text2}`} />
              </div>

              <div className={`flex-1 overflow-y-auto max-h-[560px] divide-y ${T.border}`}>
                {loading ? (
                  <div className={`p-10 text-center text-sm ${T.text2}`}>Carregando oportunidades…</div>
                ) : filtered.length === 0 ? (
                  <div className="p-10 text-center">
                    <div className="text-4xl mb-2">🧰</div>
                    <div className={`text-sm ${theme === "dark" ? "text-slate-400" : "text-slate-500"}`}>Nenhuma oportunidade nas categorias ativas.</div>
                    <div className={`text-xs mt-1 ${T.text2}`}>Ative mais categorias ao lado para ver mais.</div>
                  </div>
                ) : (
                  filtered.map((lead) => {
                    const c = catOfLead(lead);
                    const isNew = !shown.has(lead.id);
                    return (
                      <div key={lead.id} className={`px-5 py-4 group transition ${T.navHover}`}>
                        <div className="flex items-center gap-2 mb-2 flex-wrap">
                          <span className="text-[10px] font-semibold uppercase tracking-wide flex items-center gap-1.5 px-2 py-1 rounded-full" style={{ backgroundColor: c.color + "1a", color: c.color }}>
                            <c.icon className="h-3 w-3" /> {c.label}
                          </span>
                          {isNew && (
                            <span className="text-[10px] font-semibold uppercase bg-emerald-500/15 text-emerald-500 px-2 py-1 rounded-full flex items-center gap-1">
                              <Sparkles className="h-3 w-3" /> Nova
                            </span>
                          )}
                          <span className={`ml-auto text-[11px] flex items-center gap-1 capitalize ${T.text2}`}>
                            <MapPin className="h-3 w-3" /> {lead.city}
                          </span>
                        </div>

                        <div className="flex items-start gap-3">
                          <div className="h-10 w-10 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: c.color + "1a" }}>
                            <Building2 className="h-5 w-5" style={{ color: c.color }} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="font-medium text-[15px]">{maskAddress(lead.address)}</div>
                            <div className={`text-sm mt-0.5 ${T.text2}`}>
                              {lead.issue_description || lead.case_title || "Oportunidade de serviço"}
                            </div>
                            <div className={`flex items-center gap-3 text-[11px] mt-2 flex-wrap ${T.text2}`}>
                              {lead.department && <span className="flex items-center gap-1"><Building2 className="h-3 w-3" />{lead.department}</span>}
                              <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{lead.case_status || "Aguardando"}</span>
                              <span className="flex items-center gap-1"><Wrench className="h-3 w-3" />Contrato potencial</span>
                            </div>
                          </div>
                          <div className="flex flex-col gap-2 items-end shrink-0">
                            <button
                              onClick={() => setShown((p) => new Set(p).add(lead.id))}
                              className="text-[11px] text-indigo-500 hover:text-indigo-600"
                            >
                              {isNew ? "Visto" : "Visto ✓"}
                            </button>
                            <button className="flex items-center gap-1 text-[11px] font-medium bg-white/10 text-slate-100 px-2.5 py-1.5 rounded-lg transition hover:bg-indigo-500/20">
                              Aplicar <ArrowUpRight className="h-3 w-3" />
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
