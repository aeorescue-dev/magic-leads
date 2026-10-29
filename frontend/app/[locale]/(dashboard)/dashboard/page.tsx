"use client";

// Assinatura: contas sem acesso vigente abrem o modal de checkout (CheckoutModal),
// que coleta o nome da empresa e redireciona para a sessão Stripe do Plano Pro.
export const dynamic = 'force-dynamic';

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  LayoutDashboard, FolderKanban, Star, SlidersHorizontal, Bell,
  CreditCard, Settings, LogOut, Search, MapPin, Building2,
  Sparkles, ChevronRight, Wrench, Hammer, Paintbrush, Waves,
  Trash2, HardHat, CheckCircle2, ArrowUpRight, Clock, Filter,
  X, Sun, Moon, Phone, MessageSquare, Mail, Copy, Check,
  ExternalLink, Lock, BadgeCheck, RefreshCcw, ShieldCheck,
  AlertCircle, Tag, Loader2, BarChart3, History,
  Flame, Zap, Forklift, Droplets, Bug, Droplet, AlertTriangle,
  DoorOpen, AppWindow, Package, Wind,
  TrendingUp, Navigation, Smartphone, FolderOpen, Archive,
  Landmark,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import {
  isBlockedByQuota,
  isFreeLead,
  isUnresolvableLead,
  countLeadsWithoutContact,
  shouldShowAddressWarning,
} from "@/lib/lead-delivery";
import { buildOutreachMessage } from "@/lib/outreach";
import { buildFullAddress } from "@/lib/address";
import { shouldSeedDefaultInterests, toggleInterestKey } from "@/lib/interests";
import CheckoutModal from "@/components/CheckoutModal";
import ReleaseModal from "@/components/ReleaseModal";
import WelcomePopup from "@/components/WelcomePopup";
import { PushNotificationButton } from "@/components/PushNotificationButton";
import PushOnboardingBanner from "@/components/PushOnboardingBanner";
import InterestsNudgeBanner from "@/components/InterestsNudgeBanner";
import { LeadLocationMap } from "@/components/LeadLocationMap";
import { StageBadge } from "@/components/ui/StageBadge";
import { StageGuidePanel } from "@/components/ui/StageGuidePanel";
import { ReserveGuideModal } from "@/components/ui/ReserveGuideModal";
import {
  LeadResponse, LeadStats, Notification, Note, HistoryEvent,
  ContractorMetrics,
  fetchTodayLeads, fetchStats,
  fetchLeadById, toggleFavorite, recordContact, fetchNotes, addNote, deleteNote,
  fetchUserNotifications, fetchUserUnreadCount, markUserNotificationRead, markAllUserNotificationsRead,
  fetchLeadStatus, reserveLead, releaseLead, contactLead, negotiateLead, convertLead,
  fetchLeadHistory, fetchUserInterests, updateUserInterests,
  fetchUserDailyStats, fetchUserSubscriptionStatus, fetchContractorMetrics,
  fetchMyLeadsHistory, MyLeadHistoryItem, MyLeadsHistoryKpis,
  LeadOccurrence, fetchLeadOccurrences,
  fetchDashboardSummary, DashboardSummary,
  fetchScraperStatus, ScraperRunState,
  fetchPublicMetrics, PublicMetrics, EMPTY_PUBLIC_METRICS, RELEASE_REASONS,
  revealPhone, PhoneRevealResult,
  fetchCreditBalance, CreditBalance,
  fetchCreditLedger, CreditLedgerEntry,
} from "@/lib/api-client";

// Tipo enriquecido para o modal de revelação (com histórico e ocorrências)
type EnrichedLead = LeadResponse & {
  _history?: HistoryEvent[];
  _occurrences?: LeadOccurrence[];
};

// Modal automático do ciclo de vida (abre logo após reservar)
type GuideLead = EnrichedLead & {
  stage?: "reserved" | "contacted" | "in_negotiation" | "converted";
  stage_expires_at?: string;
  server_now?: string;
};

type Theme = "dark" | "light";

type Category = {
  key: string;
  labelKey: string;
  icon: any;
  color: string;
  keywords: string[];
};

const CATEGORIES: Category[] = [
  { key: "Roof", labelKey: "dashboard.cat.telhado", icon: HardHat, color: "#6366f1", keywords: ["roof", "structure", "collaps", "foundation", "telhado", "estrutura"] },
  { key: "Structure", labelKey: "dashboard.cat.estrutura", icon: Building2, color: "#6366f1", keywords: ["structure", "collaps", "foundation", "building", "estrutura", "fundacao"] },
  { key: "Plumbing", labelKey: "dashboard.cat.encanamento", icon: Waves, color: "#0ea5e9", keywords: ["plumb", "water", "sewer", "leak", "encanamento", "vazamento"] },
  { key: "Grass", labelKey: "dashboard.cat.mato", icon: Trash2, color: "#22c55e", keywords: ["grass", "weed", "overgrown", "vegetation", "litter", "trash", "debris", "garbage", "dirty", "unsanitary", "rodent", "mato", "entulho"] },
  { key: "Paint", labelKey: "dashboard.cat.pintura", icon: Paintbrush, color: "#f59e0b", keywords: ["paint", "lead", "pintura"] },
  { key: "Permit_Rejected", labelKey: "dashboard.cat.obras", icon: Hammer, color: "#ec4899", keywords: ["permit", "construction", "illegal", "building", "obra", "permissao"] },
  { key: "Heating", labelKey: "dashboard.cat.heating", icon: Flame, color: "#ef4444", keywords: ["heat", "hot water", "heating", "boiler", "radiator", "no heat", "aquecimento"] },
  { key: "Electrical", labelKey: "dashboard.cat.electrical", icon: Zap, color: "#fbbf24", keywords: ["electric", "electrical", "wiring", "outlet", "circuit", "panel", "eletrica"] },
  { key: "Elevator", labelKey: "dashboard.cat.elevator", icon: Forklift, color: "#8b5cf6", keywords: ["elevator", "lift", "elevador"] },
  { key: "Gas", labelKey: "dashboard.cat.gas", icon: Droplets, color: "#f97316", keywords: ["gas", "gas leak", "cooking gas", "gas", "vazamento"] },
  { key: "Rodent", labelKey: "dashboard.cat.rodent", icon: Bug, color: "#84cc16", keywords: ["rodent", "rat", "mouse", "vermin", "roach", "pest", "cockroach", "bed bug", "roedor", "praga"] },
  { key: "Mold", labelKey: "dashboard.cat.mold", icon: Droplet, color: "#06b6d4", keywords: ["mold", "mildew", "fungus", "mofo", "umidade"] },
  { key: "Lead", labelKey: "dashboard.cat.lead", icon: AlertTriangle, color: "#a855f7", keywords: ["lead", "lead paint", "lead hazard", "chumbo"] },
  { key: "Unsanitary", labelKey: "dashboard.cat.unsanitary", icon: Package, color: "#ec4899", keywords: ["unsanitary", "sanitary", "filth", "sewage", "sewer backup", "insanitario", "esgoto"] },
  { key: "Door_Window", labelKey: "dashboard.cat.door_window", icon: DoorOpen, color: "#14b8a6", keywords: ["door", "window", "frame", "sash", "jamb", "porta", "janela"] },
  { key: "Debris", labelKey: "dashboard.cat.debris", icon: Wind, color: "#64748b", keywords: ["debris", "garbage", "trash", "rubbish", "litter", "dumping", "entulho", "lixo"] },
];

// Todas as categorias da plataforma — default dos interesses e valor
// auto-persistido quando o utilizador ainda não tem interesses gravados.
const ALL_CATEGORY_KEYS = CATEGORIES.map((cat) => cat.key);

function matchCategory(lead: LeadResponse, keywords: string[]) {
  const hay = `${lead.issue_category || ""} ${lead.issue_description || ""} ${lead.case_title || ""} ${lead.descriptor || ""} ${lead.department || ""}`.toLowerCase();
  return keywords.some((k) => hay.includes(k));
}

function catOfLead(lead: LeadResponse): Category {
  const c = CATEGORIES.find((cat) => matchCategory(lead, cat.keywords));
  return c || CATEGORIES[0];
}

const DARK = {
  bg: "#0b0d12",
  bg2: "#10121a",
  card: "#10121a",
  sidebar: "#0f1117",
  border: "border-white/10",
  // Divisor mais discreto que a borda de cartao.
  divider: "border-white/5",
  // Superficie de painel/seccao (cartao elevado).
  panel: "bg-[#10121a] border-white/5",
  // Superficie secundaria (faixas, chips, blocos internos).
  subtle: "bg-white/5 border-white/10",
  // Track de barras de progresso.
  track: "bg-white/10",
  // Chip/botao selecionado (nao-primario).
  chipActive: "bg-white/10 text-slate-100 border-white/20",
  // Botao secundario (mapa, copiar).
  ghost: "bg-slate-500/15 text-slate-300 hover:bg-slate-500/25",
  // Botao destrutivo/neutro (largar lead).
  ghostDanger: "bg-white/10 text-slate-300 hover:bg-rose-500/20 hover:text-rose-400",
  // Texto secundario com contraste AA.
  text: "text-slate-100",
  text2: "text-slate-400",
  input: "bg-white/5",
  navHover: "hover:bg-white/5",
  section: "bg-[#10121a] border-white/10",
  header: "bg-[#0b0d12]/90",
};

const LIGHT = {
  bg: "#f8fafc",
  bg2: "#ffffff",
  card: "#ffffff",
  sidebar: "#ffffff",
  border: "border-slate-200",
  divider: "border-slate-200",
  panel: "bg-white border-slate-200 shadow-sm",
  subtle: "bg-slate-50 border-slate-200",
  track: "bg-slate-200",
  chipActive: "bg-slate-200 text-slate-900 border-slate-300",
  ghost: "bg-slate-100 text-slate-700 hover:bg-slate-200",
  ghostDanger: "bg-slate-100 text-slate-700 hover:bg-rose-100 hover:text-rose-600",
  // slate-600 (7:1 sobre branco) em vez de slate-500, que ficava abaixo de AA
  // em superficies cinzentas.
  text: "text-slate-900",
  text2: "text-slate-600",
  input: "bg-slate-100",
  navHover: "hover:bg-slate-100",
  section: "bg-white border-slate-200",
  header: "bg-white/90",
};

function formatRelativeTime(dateStr: string, t: (k: string) => string): string {
  if (!dateStr) return "";
  const now = new Date();
  let iso = dateStr.replace(" ", "T");
  if (!/[Zz]|[+-]\d{2}:?\d{2}$/.test(iso)) iso += "Z";
  const date = new Date(iso);
  if (isNaN(date.getTime())) return dateStr;
  const diffSec = Math.max(0, Math.floor((now.getTime() - date.getTime()) / 1000));
  if (diffSec < 60) return t("dashboard.time.just_now") || "agora mesmo";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) {
    return diffMin === 1
      ? `1 ${t("dashboard.time.min_ago") || "min atrás"}`
      : `${diffMin} ${t("dashboard.time.mins_ago") || "min atrás"}`;
  }
  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) {
    return diffHours === 1
      ? `1 ${t("dashboard.time.hour_ago") || "h atrás"}`
      : `${diffHours} ${t("dashboard.time.hours_ago") || "h atrás"}`;
  }
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays === 1) return t("dashboard.time.yesterday") || "ontem";
  return `${diffDays} ${t("dashboard.time.days_ago") || "dias atrás"}`;
}

// Countdown "Xh Ym" a partir de um ISO/UTC de expiração (Phase 4.2)
// Fallback = 60 min, que é a janela de reserva real do plano. NÃO usar "24h":
// o hold tem 60 minutos e mostrar 24h seria uma promessa falsa ao utilizador.
const HOLD_FALLBACK = "60m";
function countdownLabel(expiresAt: string): string {
  if (!expiresAt) return HOLD_FALLBACK;
  const d = new Date(expiresAt.replace("Z", "+00:00").replace(" ", "T"));
  if (isNaN(d.getTime())) return HOLD_FALLBACK;
  const diffMs = d.getTime() - Date.now();
  if (diffMs <= 0) return "expirado";
  const totalMin = Math.floor(diffMs / 60000);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h >= 1) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}m`;
}

function DashboardPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, subscription, loading: authLoading, signOut, refreshSubscription } = useAuth();
  const { t, lang } = useI18n();

  // DECLARE userId BEFORE ALL HANDLERS
  const userId = user?.id;

  // Tamanho fixo da pagina do feed de oportunidades. Serve para os tres pontos
  // de carregamento (carga inicial, polling e "carregar mais") usarem o MESMO
  // numero e evitarem hasMore divergente.
  const PAGE_SIZE = 50;

  // State
  const [theme, setTheme] = useState<Theme>("dark");
  const [leads, setLeads] = useState<LeadResponse[]>([]);
  const [loadingLeads, setLoadingLeads] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasMoreLeads, setHasMoreLeads] = useState(true);
  // Total do conjunto que o feed do SERVIDOR devolve para os filtros ativos
  // (cidade + tipo + categoria + urgencia + encerrados). Era mostrado
  // `dashboardSummary.total_interested` (6.626 no total), que e um KPI de toda
  // a plataforma e nao o numero de linhas que o feed pode realmente carregar.
  const [feedTotal, setFeedTotal] = useState(0);
  const [stats, setStats] = useState<LeadStats | null>(null);
  const [selectedCity, setSelectedCity] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"overview" | "opportunities" | "favorites" | "interests" | "alerts" | "history">("overview");
  const [interests, setInterests] = useState<Set<string>>(new Set(ALL_CATEGORY_KEYS));
  const [interestsConfigured, setInterestsConfigured] = useState<boolean | null>(null);
  // O utilizador ja' interagiu com as especialidades? Distingue "nunca
  // configurou" (o backend trata como "todas") de "configurou e quer zero".
  // E' um ref (e' nao um estado): o valor e' lido dentro de um callback
  // assincrono, onde um useState seria um snapshot do momento do render.
  const interestsTouchedRef = useRef(false);
  const [dailyStats, setDailyStats] = useState<{ used: number; limit: number; remaining: number; reset_at: string } | null>(null);

  // Historico de casos encerrados. Desligado por omissao: o pool principal e
  // so de leads qualificados (obrigacao legal OU chamado aberto). Ligar este
  // interruptor traz tambem os nao-qualificados, para analise do historico da
  // regiao, sem tocar nos KPIs nem na fileira de oportunidades.
  const [includeClosed, setIncludeClosed] = useState(false);

  // Filter states
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [selectedUrgency, setSelectedUrgency] = useState<string>("all");
  const [selectedType, setSelectedType] = useState<string>("all");
  const [selectedOwnerType, setSelectedOwnerType] = useState<string>("all");
  // Gaveta de filtros em mobile (<lg). Em desktop os filtros ficam inline.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [dashboardSummary, setDashboardSummary] = useState<DashboardSummary | null>(null);
  const [publicMetrics, setPublicMetrics] = useState<PublicMetrics>(EMPTY_PUBLIC_METRICS);
  const [scraperState, setScraperState] = useState<ScraperRunState | null>(null);
  const [shown, setShown] = useState<Set<string>>(new Set());

  const CITIES = ["all", "NYC", "Chicago", "Dallas", "Boston"];
  const CATEGORIES_FILTER = ["all", ...CATEGORIES.map(c => c.key)];
const URGENCIES = ["all", "high", "medium", "low"];

  // Estados que significam que o chamado ja terminou. Espelham a lista usada
  // pelo backend em /api/leads/services. Um lead nestas condicoes aparece
  // apenas quando o utilizador liga "Incluir encerrados", para consultar o
  // historico da regiao: nao e uma oportunidade e nao deve ser reservado.
  const CLOSED_STATUSES = [
    "closed", "resolved", "solved", "archived", "duplicated",
    "completed", "complete", "canceled", "cancelled", "rejected",
  ];
  const isClosedCase = (status?: string | null) =>
    !!status && CLOSED_STATUSES.includes(status.trim().toLowerCase());

  // Regra A, resolucao de endereco e qualidade do lead: calculadas pelo backend em
  // backend/services/lead_rules.py e expostas em cada lead como `corporate`,
  // `address_resolvable` e `unresolvable`. Sao lidas diretamente, sem recalcular
  // aqui: qualquer divergencia entre o que a UI promete e o que a reserva cobra
  // passa a ser impossivel, porque e a mesma avaliacao dos dois lados.
  const isCorporateLead = (lead?: { corporate?: boolean } | null) => !!lead?.corporate;

  const LEAD_TYPES = [
    { value: "all", labelKey: "dashboard.filter.all_types" },
    { value: "legal_obligation", labelKey: "dashboard.lead_type.obligation" },
    { value: "authorized_work", labelKey: "dashboard.lead_type.permit" },
    { value: "open_request", labelKey: "dashboard.lead_type.open" },
  ];

  // Filtro rapido Privado vs Institucional/Governamental. O veredito
  // `institutional` vem calculado do backend (lead_rules.py) e e lido aqui
  // diretamente, sem recalcular a regra em TypeScript.
  const OWNER_TYPES = [
    { value: "all", labelKey: "dashboard.filter.all_owner_types" },
    { value: "private", labelKey: "dashboard.filter.owner_type_private" },
    { value: "institutional", labelKey: "dashboard.filter.owner_type_institutional" },
    { value: "unknown", labelKey: "dashboard.filter.owner_type_unknown" },
  ];

// Handlers para ações do lead (Maps, SMS, WhatsApp)
  const openMaps = (address: string) => {
    const dest = encodeURIComponent(address);
    const isIOS = /iPhone|iPad|iPod/i.test(navigator.userAgent);
    const url = isIOS
      ? `http://maps.apple.com/?daddr=${dest}`
      : `https://www.google.com/maps/dir/?api=1&destination=${dest}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const buildMsgs = (lead: LeadResponse) =>
    buildOutreachMessage({
      owner: lead.owner_name || "",
      company: user?.company_name || "",
      city: lead.city || "",
      category: lead.issue_category || "Other",
    });

  const waHref = (phone: string, m: ReturnType<typeof buildOutreachMessage>) =>
    `https://wa.me/${(phone || "").replace(/\D/g, "")}?text=${encodeURIComponent(m.whatsapp)}`;

  const smsHref = (phone: string, m: ReturnType<typeof buildOutreachMessage>) =>
    `sms:${(phone || "").replace(/\D/g, "")}?body=${encodeURIComponent(m.sms)}`;

  const openSMS = (phone: string) => {
    const clean = (phone || "").replace(/\D/g, "");
    window.open(`sms:${clean}`, "_self");
  };

  const openWhatsApp = (phone: string) => {
    const clean = (phone || "").replace(/\D/g, "");
    window.open(`https://wa.me/${clean}`, "_blank", "noopener,noreferrer");
  };

// My Leads / Histórico (tab dedicada)
  const [historyLeads, setHistoryLeads] = useState<MyLeadHistoryItem[]>([]);
  const [historyKpis, setHistoryKpis] = useState<MyLeadsHistoryKpis | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyStatus, setHistoryStatus] = useState<string>("");
  const [historyCategory, setHistoryCategory] = useState<string>("");
  const [historyPeriod, setHistoryPeriod] = useState<string>("");
  const [historySearch, setHistorySearch] = useState("");
  const [historyNeedsAction, setHistoryNeedsAction] = useState(false);

  // Navigation & modals
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const bellRef = useRef<HTMLDivElement>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [showCheckout, setShowCheckout] = useState(false);
  const checkoutAutoOpened = useRef(false);
  const [selectedLead, setSelectedLead] = useState<LeadResponse | null>(null);
  const [showWelcomePopup, setShowWelcomePopup] = useState(false);
  const welcomePopupChecked = useRef(false);

  // Lead details sub-states
  const [leadStatus, setLeadStatus] = useState<string>("available");
  const [leadNotes, setLeadNotes] = useState<Note[]>([]);
  const [leadHistory, setLeadHistory] = useState<HistoryEvent[]>([]);
  const [leadOccurrences, setLeadOccurrences] = useState<LeadOccurrence[]>([]);
  const [noteDraft, setNoteDraft] = useState("");
  const [busyAction, setBusyAction] = useState(false);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [releaseTarget, setReleaseTarget] = useState<LeadResponse | null>(null);
  const [revealTarget, setRevealTarget] = useState<EnrichedLead | null>(null);
  const [guideLead, setGuideLead] = useState<GuideLead | null>(null);
  const [contractorMetrics, setContractorMetrics] = useState<ContractorMetrics | null>(null);
  
  // Phone Reveal (Phase 4)
  const [phoneRevealing, setPhoneRevealing] = useState<{ leadId: string | number; loading: boolean } | null>(null);
  
  // Credit Balance (Phase 4)
  const [creditBalance, setCreditBalance] = useState<CreditBalance | null>(null);
  
  // Toast notifications (fila empilhável + auto-dismiss 4s)
  const [toasts, setToasts] = useState<{ id: number; message: string; type: "success" | "error" | "warning" }[]>([]);

  const showToast = useCallback((message: string, type: "success" | "error" | "warning" = "success") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  // Conta nova/inativa (sem acesso vigente): abre o modal de checkout do Plano Pro
  // assim que o status é conhecido — mesmo fluxo fluido de renovação, sem tela travada.
  useEffect(() => {
    if (subscription && !subscription.can_access && !checkoutAutoOpened.current) {
      checkoutAutoOpened.current = true;
      setShowCheckout(true);
    }
  }, [subscription, setShowCheckout]);

  // Dynamic Greeting based on client local time
  const [greetingKey, setGreetingKey] = useState<string>("dashboard.greeting.morning");

  useEffect(() => {
    const hours = new Date().getHours();
    if (hours >= 5 && hours < 12) {
      setGreetingKey("dashboard.greeting.morning");
    } else if (hours >= 12 && hours < 18) {
      setGreetingKey("dashboard.greeting.afternoon");
    } else {
      setGreetingKey("dashboard.greeting.evening");
    }
  }, []);

  // Theme loading. O primeiro efeito le a preferencia; o segundo so grava
  // DEPOIS dessa leitura. Sem esta guarda, o efeito de gravacao corria com o
  // estado inicial ("dark") e apagava a escolha do utilizador antes de o
  // setTheme chegar ao render (visivel com StrictMode: o tema voltava a dark).
  const [themeLoaded, setThemeLoaded] = useState(false);
  useEffect(() => {
    const saved = localStorage.getItem("pro.theme") as Theme | null;
    if (saved === "light" || saved === "dark") setTheme(saved);
    setThemeLoaded(true);
  }, []);

  useEffect(() => {
    if (!themeLoaded) return;
    localStorage.setItem("pro.theme", theme);
  }, [theme, themeLoaded]);

  // Gaveta de filtros (mobile): bloqueia scroll do fundo, fecha com Escape,
  // move o foco para a folha ao abrir e devolve-o ao botao ao fechar.
  const filtersSheetRef = useRef<HTMLDivElement | null>(null);
  const filtersTriggerRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!filtersOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFiltersOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    filtersSheetRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
      filtersTriggerRef.current?.focus();
    };
  }, [filtersOpen]);

  // Route protection
  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/");
    }
  }, [authLoading, user, router]);

  // Welcome Popup: show once on first login after payment (persistido em localStorage)
  useEffect(() => {
    if (authLoading || !user || welcomePopupChecked.current) return;
    welcomePopupChecked.current = true;

    let dismissedLocally = false;
    try {
      const storageKey = `magic_leads_notice_seen_${user.id}`;
      dismissedLocally = localStorage.getItem(storageKey) === "true";
    } catch (e) {
      console.error("Erro ao ler welcome popup do localStorage:", e);
    }

    if (!dismissedLocally && !user.welcome_popup_shown && user.subscription_status === "active") {
      setShowWelcomePopup(true);
    }
  }, [authLoading, user]);

  // Sync favorites tab from URL param ?fav=1
  useEffect(() => {
    if (searchParams?.get("fav") === "1") {
      setActiveTab("favorites");
    }
  }, [searchParams]);

  // Handle Stripe success return ?paid=1
  useEffect(() => {
    if (searchParams?.get("paid") === "1") {
      refreshSubscription();
      showToast("Pagamento confirmado com sucesso!", "success");
      // Clean URL to avoid re-triggering on refresh
      const url = new URL(window.location.href);
      url.searchParams.delete("paid");
      router.replace(url.pathname + url.search, { scroll: false });
    }
  }, [searchParams, refreshSubscription, router, showToast]);

  // Load user interests
  useEffect(() => {
    if (userId) {
      fetchUserInterests(userId)
        .then((cats) => {
          const hasInterests = Array.isArray(cats) && cats.length > 0;
          setInterestsConfigured(hasInterests);
          if (hasInterests) {
            setInterests(new Set(cats));
          } else if (shouldSeedDefaultInterests(cats, interestsTouchedRef.current)) {
            // Sem interesses gravados: o backend trata o utilizador como "sem
            // configuração" e torna-o elegível a TODAS as categorias (fallback),
            // enviando alertas que ele não escolheu. Persistimos o default
            // (todas) para que o estado do backend fique explícito. Best-effort.
            updateUserInterests(userId, ALL_CATEGORY_KEYS).catch(() => {});
          }
        })
        .catch(() => {});
    }
    // `interestsTouchedRef` e' lido dentro do .then, mas nao pode ser
    // dependencia do efeito: mudar o efeito re-disparava o seed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  // Refresh notifications and unread count
  const refreshNotifications = useCallback(async () => {
    if (!userId) return;
    try {
      const [list, unread] = await Promise.all([
        fetchUserNotifications(userId, "recent", 30),
        fetchUserUnreadCount(userId),
      ]);
      setNotifications(list || []);
      setUnreadCount(unread || 0);
    } catch (e) {
      console.error(e);
    }
  }, [userId]);

  useEffect(() => {
    if (userId) {
      refreshNotifications();
      const interval = setInterval(refreshNotifications, 30000);
      return () => clearInterval(interval);
    }
  }, [userId, refreshNotifications]);

  // Load penalty metrics (Phase 4.2)
  useEffect(() => {
    if (!userId) return;
    fetchContractorMetrics()
      .then(setContractorMetrics)
      .catch(() => {});
  }, [userId]);

  const refreshContractorMetrics = useCallback(async () => {
    if (!userId) return;
    try {
      setContractorMetrics(await fetchContractorMetrics());
    } catch (e) {
      console.error(e);
    }
  }, [userId]);

  // Click outside to close bell dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (bellRef.current && !bellRef.current.contains(event.target as Node)) {
        setBellOpen(false);
      }
    };
    if (bellOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [bellOpen]);

  // Load general initial data: Stats, Cities with Counts, Leads, Dashboard Summary
  useEffect(() => {
    let active = true;
    (async () => {
      setLoadingLeads(true);
      try {
        const [statsData, leadsData, summaryData, scraperData, publicMetricsData] = await Promise.all([
          fetchStats().catch(() => null),
          fetchTodayLeads(
            PAGE_SIZE,
            selectedCity === "all" ? undefined : selectedCity,
            includeClosed,
            1,
            selectedType === "all" ? undefined : selectedType,
            selectedCategory === "all" ? undefined : selectedCategory,
            selectedUrgency === "all" ? undefined : selectedUrgency
          ).catch(() => ({ leads: [], total: 0, page: 1, per_page: PAGE_SIZE })),
          fetchDashboardSummary().catch(() => null),
          fetchScraperStatus().catch(() => null),
          fetchPublicMetrics().catch(() => null),
        ]);
        if (!active) return;
        if (statsData) setStats(statsData);
        if (summaryData) setDashboardSummary(summaryData);
        if (scraperData) setScraperState(scraperData);
        if (publicMetricsData) setPublicMetrics(publicMetricsData);
        const page = leadsData.leads || [];
        setLeads(page);
        setCurrentPage(1);
        setFeedTotal(Number(leadsData.total) || 0);
        // `total` vem do SERVIDOR (a pagina so devolve PAGE_SIZE linhas). Antes
        // usava-se `page.length >= 50`, que nunca soube detectar "ha mais" a
        // partir de filtros de categoria/urgencia aplicados no cliente.
        setHasMoreLeads(leadsData.total > page.length);
      } catch (e) {
        console.error("Erro ao carregar dados do dashboard:", e);
      } finally {
        if (active) setLoadingLeads(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [selectedCity, selectedType, selectedCategory, selectedUrgency, includeClosed]);

  // Real-time polling: refresh leads + KPIs every 30 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      fetchTodayLeads(
        PAGE_SIZE,
        selectedCity === "all" ? undefined : selectedCity,
        includeClosed,
        1,
        selectedType === "all" ? undefined : selectedType,
        selectedCategory === "all" ? undefined : selectedCategory,
        selectedUrgency === "all" ? undefined : selectedUrgency
      )
        .then((data) => {
          const page = data.leads || [];
          setLeads(page);
          setCurrentPage(1);
          setFeedTotal(Number(data.total) || 0);
          setHasMoreLeads(data.total > page.length);
        })
        .catch(() => {});
      fetchDashboardSummary().then(setDashboardSummary).catch(() => {});
      fetchStats().then(setStats).catch(() => {});
      fetchScraperStatus().then(setScraperState).catch(() => {});
      fetchPublicMetrics().then(setPublicMetrics).catch(() => {});
    }, 30000);
    return () => clearInterval(interval);
    // FALTOU selectedType aqui: mudar o seletor "Tipo" recriava o intervalo,
    // mas continuava a pedir o tipo ANTIGO (value stale) nos polls seguintes.
  }, [selectedCity, selectedType, selectedCategory, selectedUrgency, includeClosed]);

  // Fetch daily stats (limit 10/day)
  useEffect(() => {
    if (userId) {
      const fetchDaily = async () => {
        try {
          const stats = await fetchUserDailyStats(userId);
          setDailyStats(stats);
        } catch (e) {
          console.error(e);
        }
      };
      fetchDaily();
      const interval = setInterval(fetchDaily, 60000); // Refresh every minute
      return () => clearInterval(interval);
    }
  }, [userId]);

  // Fetch Credit Balance (Phase 4)
  useEffect(() => {
    if (userId) {
      const fetchCredit = async () => {
        try {
          const balance = await fetchCreditBalance(userId);
          setCreditBalance(balance);
        } catch (e) {
          console.error("Erro ao buscar saldo de créditos:", e);
        }
      };
      fetchCredit();
      const interval = setInterval(fetchCredit, 60000); // Refresh every minute
      return () => clearInterval(interval);
    }
  }, [userId]);

  // Fetch "Meus Leads / Histórico" quando a aba está ativa ou filtros mudam
  useEffect(() => {
    if (activeTab !== "history" || !userId) return;
    let active = true;
    const fetchHistory = async () => {
      setHistoryLoading(true);
      try {
        const res = await fetchMyLeadsHistory({
          status: historyStatus || undefined,
          period: historyPeriod || undefined,
          search: historySearch || undefined,
          needs_action: historyNeedsAction || undefined,
          limit: 200,
        });
        if (!active) return;
        setHistoryLeads(res.leads);
        setHistoryKpis(res.kpis);
      } catch (e) {
        console.error("Erro ao buscar histórico:", e);
        if (active) setHistoryLeads([]);
      } finally {
        if (active) setHistoryLoading(false);
      }
    };
    const t = setTimeout(fetchHistory, historySearch ? 300 : 0);
    return () => {
      active = false;
      clearTimeout(t);
    };
  }, [userId, activeTab, historyStatus, historyPeriod, historySearch, historyNeedsAction]);

  // Ações dentro do histórico (reservar de novo / converter)
  const refreshHistory = useCallback(() => {
    if (activeTab !== "history" || !userId) return;
    fetchMyLeadsHistory({
      status: historyStatus || undefined,
      period: historyPeriod || undefined,
      search: historySearch || undefined,
      needs_action: historyNeedsAction || undefined,
      limit: 200,
    })
      .then((res) => {
        setHistoryLeads(res.leads);
        setHistoryKpis(res.kpis);
      })
      .catch((e) => console.error("Erro ao atualizar histórico:", e));
  }, [userId, activeTab, historyStatus, historyPeriod, historySearch, historyNeedsAction]);

  const handleHistoryReserve = async (lead: MyLeadHistoryItem) => {
    if (busyAction || (subscription && !subscription.can_access)) return;
    if (isBlockedByQuota(lead, dailyStats?.remaining)) {
      showToast(t("dashboard.toast.daily_limit"), "warning");
      return;
    }
    // Consentimento antes de re-revelar os dados do proprietário (conta novamente)
    setRevealTarget(lead);
  };

  const handleHistoryConvert = async (lead: MyLeadHistoryItem) => {
    setBusyAction(true);
    try {
      await convertLead(lead.id);
      showToast(t("dashboard.toast.conversion"), "success");
      if (userId) refreshNotifications();
      refreshHistory();
    } catch (e: any) {
      showToast(e?.message || t("dashboard.toast.conversion_error"), "error");
    } finally {
      setBusyAction(false);
    }
  };

  // Toggle category interest
  const toggleInterest = async (catKey: string) => {
    const prev = interests;
    // Invariante: a selecção nunca fica vazia — no backend "sem categorias"
    // significa "todas as categorias". Sem isto, o utilizador que
    // desmarcasse todas via ver a escolha desaparecer no reload seguinte.
    const next = toggleInterestKey(prev, catKey, ALL_CATEGORY_KEYS);
    setInterests(next);
    interestsTouchedRef.current = true;
    setInterestsConfigured(true);

    if (userId) {
      try {
        await updateUserInterests(userId, Array.from(next));
      } catch (e) {
        console.error(e);
        // Reverte a UI: sem isto o utilizador via a categoria como guardada
        // quando o PUT falhou — e o backend continuava a usar os interesses
        // antigos (ou o fallback "todas"), enviando alertas indesejados.
        setInterests(prev);
        showToast(t("dashboard.interests.save_error"), "error");
      }
    }
  };

  // Unified Notification Click Handler
  const handleNotificationClick = useCallback(async (n: Notification) => {
    if (userId && !n.read) {
      try {
        await markUserNotificationRead(userId, n.id);
        setNotifications((prev) =>
          prev.map((item) => (item.id === n.id ? { ...item, read: true } : item))
        );
        setUnreadCount((prev) => Math.max(0, prev - 1));
      } catch (e) {
        console.error(e);
      }
    }
    setBellOpen(false);

    if (n.lead_id) {
      const match = leads.find((l) => l.id === String(n.lead_id));
      if (match) {
        openLeadDetail(match);
      } else {
        fetchLeadById(String(n.lead_id)).then((found) => {
          if (found) openLeadDetail(found);
        });
      }
    } else {
      setActiveTab("opportunities");
    }
  }, [userId, leads]);

  const handleMarkAllRead = async () => {
    if (!userId) return;
    try {
      await markAllUserNotificationsRead(userId);
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
      setUnreadCount(0);
    } catch (e) {
      console.error(e);
    }
  };

  // Load More Leads (pagination)
  const loadMoreLeads = useCallback(async () => {
    if (loadingMore || !hasMoreLeads) return;
    setLoadingMore(true);
    try {
      const nextPage = currentPage + 1;
      const data = await fetchTodayLeads(
        PAGE_SIZE,
        selectedCity === "all" ? undefined : selectedCity,
        includeClosed,
        nextPage,
        selectedType === "all" ? undefined : selectedType,
        selectedCategory === "all" ? undefined : selectedCategory,
        selectedUrgency === "all" ? undefined : selectedUrgency
      );
      if (data.leads && data.leads.length > 0) {
        setLeads((prev) => [...prev, ...data.leads]);
        setCurrentPage(nextPage);
        setFeedTotal(Number(data.total) || 0);
        // O servidor ja devolveu o total do conjunto filtrado; nao faz sentido
        // depender do tamanho da pagina (que fica truncado em PAGE_SIZE).
        setHasMoreLeads(nextPage * PAGE_SIZE < data.total);
      } else {
        setHasMoreLeads(false);
      }
    } catch (e) {
      console.error("Erro ao carregar mais leads:", e);
    } finally {
      setLoadingMore(false);
    }
    // includeClosed FALTOU: alternar o interruptor de historico nao recriava o
    // callback, por isso "carregar mais" continuava a pagina sem o parametro.
  }, [currentPage, hasMoreLeads, loadingMore, selectedCity, selectedType, selectedCategory, selectedUrgency, includeClosed]);

  // O lead já está em "Meus Leads" (revelado por mim: reservado, em negociação,
  // convertido, liberado ou com hold expirado). Nesse estado o botão
  // "Reservar (1 hora)" não deve aparecer — o lead já foi adquirido e
  // não pode ser "comprado" de novo pela mesma via.
  const leadAlreadyMine = (lead: LeadResponse | null): boolean => {
    if (!lead) return false;
    if (lead.visibility_status === "reserved_by_me") return true;
    if (lead.revealed) return true;
    return !!lead.my_status && lead.my_status !== "available";
  };

  // Phone Reveal Handler (Phase 4)
  const revealPhoneForLead = async (lead: LeadResponse) => {
    if (!lead.owner_name || lead.owner_phone) return;
    if (phoneRevealing?.loading) return;
    
    setPhoneRevealing({ leadId: lead.id, loading: true });
    setBusyAction(true);
    try {
      const result = await revealPhone(lead.id);
      if (result.success && result.phone) {
        // Update lead in list with the revealed phone
        setLeads((prev) => prev.map((l) =>
          l.id === lead.id ? { ...l, owner_phone: result.phone } : l
        ));
        // Update selected lead if it's open in modal
        if (selectedLead?.id === lead.id) {
          setSelectedLead((prev) => prev ? { ...prev, owner_phone: result.phone } : null);
        }
        showToast(t("dashboard.toast.phone_revealed") || "Telefone revelado com sucesso", "success");
      } else {
        showToast(result.error || t("dashboard.toast.phone_reveal_failed"), "warning");
      }
    } catch (e: any) {
      showToast(e?.message || t("dashboard.toast.phone_reveal_error"), "error");
    } finally {
      setPhoneRevealing(null);
      setBusyAction(false);
    }
  };

  // Open Lead Detail
  const openLeadDetail = async (lead: LeadResponse) => {
    // CORREÇÃO CRÍTICA: antes de abrir o modal analítico com dados vazios,
    // verifica se o utilizador já possui acesso ao lead. Se não possui,
    // o clique DEVE abrir apenas o consentimento (handleQuickReserve), nunca
    // a tela analítica preliminar com "sem dados".
    if (!leadAlreadyMine(lead)) {
      await handleQuickReserve(lead);
      return;
    }
    setSelectedLead(lead);
    setActionSuccess(null);
    setNoteDraft("");
    try {
      const [statusInfo, notesList, historyList, occurrencesList] = await Promise.all([
        fetchLeadStatus(lead.id).catch(() => null),
        fetchNotes(lead.id).catch(() => []),
        fetchLeadHistory(lead.id).catch(() => []),
        fetchLeadOccurrences(lead.id).catch(() => []),
      ]);
      setLeadStatus(statusInfo?.lead_status || lead.status || "available");
      setLeadNotes(notesList || []);
      setLeadHistory(historyList || []);
      setLeadOccurrences(occurrencesList || []);
    } catch (e) {
      console.error(e);
    }
  };

  // Deep link das notificações push: `/dashboard?lead=<id>` abre o modal do
  // lead. O Service Worker navega para este URL no clique da notificação; sem
  // este efeito o parâmetro chegava mas era ignorado e o utilizador ficava no
  // dashboard principal (o bug reportado).
  const pushLeadHandled = useRef<string | null>(null);
  useEffect(() => {
    const leadParam = searchParams?.get("lead");
    if (!leadParam || authLoading || !user) return;
    if (pushLeadHandled.current === leadParam) return;
    pushLeadHandled.current = leadParam;

    const match = leads.find(
      (l) => String(l.id) === leadParam || l.id === leadParam
    );
    if (match) {
      openLeadDetail(match);
    } else {
      fetchLeadById(leadParam)
        .then((found) => {
          if (found) openLeadDetail(found);
        })
        .catch((e) => console.error("Falha ao abrir lead do deep link:", e));
    }

    // Limpa o parâmetro para não reabrir o lead num refresh manual.
    const url = new URL(window.location.href);
    url.searchParams.delete("lead");
    router.replace(url.pathname + url.search, { scroll: false });
  }, [searchParams, authLoading, user, leads, openLeadDetail, router]);

  // Lead actions inside modal
  const handleLeadAction = async (fn: () => Promise<any>, successText: string) => {
    if (!selectedLead) return;
    setBusyAction(true);
    setActionSuccess(null);
    try {
      await fn();
      setActionSuccess(successText);
      // Refresca o lead completo (stage/stage_expires_at/server_now atualizados
      // pelo backend) para o painel do ciclo de vida e os badges reagirem já.
      const [updated, updatedHistory] = await Promise.all([
        fetchLeadById(selectedLead.id).catch(() => null),
        fetchLeadHistory(selectedLead.id).catch(() => []),
      ]);
      if (updated) {
        setSelectedLead((prev) => (prev ? { ...prev, ...updated } : prev));
        setLeads((prev) =>
          prev.map((l) => (l.id === selectedLead.id ? { ...l, ...updated } : l))
        );
      }
      setLeadHistory(updatedHistory || []);
      if (userId) refreshNotifications();
    } catch (e: any) {
      setActionSuccess(e?.message || t("dashboard.action.err"));
    } finally {
      setBusyAction(false);
    }
  };

  const handleAddNote = async () => {
    if (!selectedLead || !noteDraft.trim()) return;
    try {
      const note = await addNote(selectedLead.id, noteDraft.trim());
      setLeadNotes((prev) => [note, ...prev]);
      setNoteDraft("");
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteNote = async (noteId: number) => {
    if (!selectedLead) return;
    try {
      await deleteNote(selectedLead.id, noteId);
      setLeadNotes((prev) => prev.filter((n) => n.id !== noteId));
    } catch (e) {
      console.error(e);
    }
  };

  const handleToggleFav = async (lead: LeadResponse, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    try {
      const updated = await toggleFavorite(lead.id);
      setLeads((prev) => prev.map((l) => (l.id === lead.id ? { ...l, favorited: updated.favorited } : l)));
      if (selectedLead?.id === lead.id) {
        setSelectedLead((prev) => (prev ? { ...prev, favorited: updated.favorited } : null));
      }
    } catch (err) {
      console.error(err);
    }
  };

  const copyToClipboard = (text: string, field: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  };

  // Phase 4.2: release com motivo (abre modal de penalidades)
  const openReleaseModal = (lead: LeadResponse) => {
    setReleaseTarget(lead);
  };
  const closeReleaseModal = () => {
    if (busyAction) return;
    setReleaseTarget(null);
  };
  const handleQuickReserve = async (lead: LeadResponse) => {
    if (busyAction || (subscription && !subscription.can_access)) return;
    if (isBlockedByQuota(lead, dailyStats?.remaining)) {
      showToast(t("dashboard.toast.daily_limit"), "warning");
      return;
    }
    // Buscar histórico e ocorrências antes de abrir o modal
    setBusyAction(true);
    try {
      const [history, occurrences] = await Promise.all([
        fetchLeadHistory(lead.id).catch(() => []),
        fetchLeadOccurrences(lead.id).catch(() => []),
      ]);
      // Enriquecer o lead com dados extras para o modal
      const enrichedLead = {
        ...lead,
        _history: history,
        _occurrences: occurrences,
      } as LeadResponse & {
        _history: HistoryEvent[];
        _occurrences: LeadOccurrence[];
      };
      // O consentimento e a UNICA coisa que o utilizador deve ver ao reservar.
      // Fechar o modal analitico impede mapa/Contactar/Negociar/Liberar por baixo.
      setSelectedLead(null);
      setRevealTarget(enrichedLead);
    } catch (e) {
      console.error("Erro ao buscar detalhes do lead:", e);
      setSelectedLead(null);
      setRevealTarget(lead); // fallback para o lead original
    } finally {
      setBusyAction(false);
    }
  };
  const closeRevealModal = () => {
    if (busyAction) return;
    setRevealTarget(null);
  };
  const closeGuide = (openAnalytic: boolean) => {
    const l = guideLead;
    setGuideLead(null);
    if (openAnalytic && l) setSelectedLead(l as LeadResponse);
  };

  // Modais do dashboard: foco no painel ao abrir e Escape para fechar. Sem
  // isto, o teclado ficava preso atras do overlay e o Escape nao fazia nada.
  const detailDialogRef = useRef<HTMLDivElement | null>(null);
  const revealDialogRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (selectedLead) detailDialogRef.current?.focus();
  }, [selectedLead]);
  useEffect(() => {
    if (revealTarget) revealDialogRef.current?.focus();
  }, [revealTarget]);
  useEffect(() => {
    if (!selectedLead && !revealTarget) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (revealTarget) {
        closeRevealModal();
      } else if (selectedLead) {
        setSelectedLead(null);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLead, revealTarget, busyAction]);
  const confirmReveal = async () => {
    if (!revealTarget || busyAction) return;
    if (subscription && !subscription.can_access) {
      showToast(subscription.message || "Acesso negado", "error");
      return;
    }
    if (isBlockedByQuota(revealTarget, dailyStats?.remaining)) {
      showToast(t("dashboard.toast.daily_limit"), "warning");
      return;
    }
    setBusyAction(true);
    try {
      const idKey = `u${userId}:l${revealTarget.id}:${new Date().toISOString().slice(0, 10)}`;
      const res = await reserveLead(revealTarget.id, 60, { consent: true, idempotency: idKey });
      showToast(
        res?.incomplete_delivery
          ? t("dashboard.toast.free_reserved_incomplete")
          : res?.corporate
            ? t("dashboard.toast.corporate_reserved")
            : res?.message || "Dados revelados — reserva de 1 hora ativa",
        "success"
      );
      if (dailyStats) {
        try {
          const stats = await fetchUserDailyStats(userId!);
          setDailyStats(stats);
        } catch (e) {
          console.error(e);
        }
      }
      const revealedFields: Partial<LeadResponse> = {
        owner_name: res?.owner?.name ?? revealTarget.owner_name,
        owner_phone: res?.owner?.phone ?? revealTarget.owner_phone,
        owner_email: res?.owner?.email ?? revealTarget.owner_email,
        mailing_address: res?.owner?.mailing_address ?? revealTarget.mailing_address,
        my_status: "reserved" as const,
        status: "reserved",
        visibility_status: "reserved_by_me" as const,
        reserved_by_me: { expires_at: res?.expires_at },
        revealed: true,
        stage: "reserved",
        stage_expires_at: res?.stage_expires_at ?? res?.expires_at,
        server_now: res?.server_now,
      };
      setLeads((prev) =>
        prev.map((l) => (l.id === revealTarget.id ? { ...l, ...revealedFields } : l))
      );
      // Só agora, com a reserva confirmada, se abre o modal do ciclo de vida.
      // O guia fecha-se com "Ver pipeline completo" -> abre o modal analítico
      // (selectedLead). Antes este era um no-op: selectedLead estava a null (o
      // consentimento fechou-o), portanto "prev && ..." avaliava sempre para
      // null e o utilizador ficava sem ecra apos reservar. Constroi-se a partir
      // do revealTarget, que ja traz _history/_occurrences.
      setGuideLead({
        ...revealTarget,
        ...revealedFields,
      } as GuideLead);
      if (userId) refreshNotifications();
      refreshHistory();
    } catch (e: any) {
      // Handle already-reserved case gracefully
      if (e?.error === "already_reserved" || e?.status === 409) {
        // Use lead data from the 409 response body if available
        const leadData = e?.responseBody?.lead;
        if (leadData) {
          const revealedFields = {
            owner_name: leadData.owner_name,
            owner_phone: leadData.owner_phone,
            owner_email: leadData.owner_email,
            mailing_address: leadData.mailing_address,
            my_status: "reserved" as const,
            status: "reserved",
            visibility_status: "reserved_by_me" as const,
            reserved_by_me: { expires_at: leadData.reserved_by_me?.expires_at },
            revealed: true,
          };
          setLeads((prev) => prev.map((l) => (l.id === revealTarget.id ? { ...l, ...revealedFields } : l)));
          setSelectedLead({ ...revealTarget, ...revealedFields } as LeadResponse);
          showToast("Lead já reservado por você", "warning");
        } else {
          // Fallback: fetch fresh data if not in response
          try {
            const fresh = await fetchLeadById(revealTarget.id);
            if (fresh) {
              setLeads((prev) => prev.map((l) => (l.id === revealTarget.id ? { ...l, ...fresh } : l)));
              setSelectedLead({ ...revealTarget, ...fresh } as LeadResponse);
            }
          } catch { }
          showToast("Lead já reservado por você", "warning");
        }
      } else if (e?.status === 422 || e?.responseBody?.error === "incomplete_lead_data") {
        // Backend falhou closed: nenhum crédito foi descontado e nada foi reservado.
        // Não marcar o lead como revelado — ele continua disponível para o pool.
        // Distinguir "endereço incompleto, dono não é encontrável" de "procurámos e
        // não confirmámos": a mensagem antiga acusava falta de telefone, o que num
        // lead corporativo (morada, sem telefone) é enganador.
        showToast(
          isUnresolvableLead(revealTarget)
            ? t("dashboard.toast.reveal_no_address")
            : t("dashboard.toast.reveal_incomplete"),
          "warning"
        );
      } else {
        showToast(e?.message || "Erro ao revelar lead", "error");
      }
    } finally {
      setBusyAction(false);
      setRevealTarget(null);
    }
  };
  const confirmRelease = async (reason: string, note?: string) => {
    if (!releaseTarget) return;
    setBusyAction(true);
    setActionSuccess(null);
    try {
      const res = await releaseLead(releaseTarget.id, reason, note);
      const statusInfo = await fetchLeadStatus(releaseTarget.id).catch(() => null);
      if (statusInfo?.lead_status) {
        setLeadStatus(statusInfo.lead_status);
        setLeads((prev) =>
          prev.map((l) => (l.id === releaseTarget.id ? { ...l, status: statusInfo.lead_status! } : l))
        );
      }
      const msg = res?.message || "Lead liberado com motivo registrado";
      if (/suspens/i.test(msg)) {
        showToast(msg, "error");
      } else if (/alerta|prioridade/i.test(msg)) {
        showToast(msg, "warning");
      } else {
        showToast(msg, "success");
      }
      setReleaseTarget(null);
      refreshContractorMetrics();
      if (userId) refreshNotifications();
    } catch (e: any) {
      showToast(e?.message || "Erro ao liberar lead", "error");
    } finally {
      setBusyAction(false);
    }
  };

  // Normalize city name for comparison (handles NYC/New York, case differences)
  const normalizeCity = (city: string): string => {
    const normalized = city.toLowerCase().trim();
    // Map known variations
    if (normalized === "nyc" || normalized === "new york" || normalized === "new york city") return "nyc";
    if (normalized === "boston") return "boston";
    if (normalized === "dallas") return "dallas";
    return normalized;
  };

  // Filtered Leads
  const filteredLeads = useMemo(() => {
    const selectedCityNorm = normalizeCity(selectedCity);
    return leads.filter((lead) => {
      // Tab filter
      if (activeTab === "favorites" && !lead.favorited) return false;

      // City filter (case-insensitive with name variations)
      if (selectedCity !== "all") {
        const leadCityNorm = normalizeCity(lead.city);
        if (leadCityNorm !== selectedCityNorm) {
          return false;
        }
      }

      // Category filter
      if (selectedCategory !== "all") {
        const cat = catOfLead(lead);
        if (cat.key !== selectedCategory) {
          return false;
        }
      }

      // Urgency filter
      if (selectedUrgency !== "all") {
        if (lead.urgency_level !== selectedUrgency) {
          return false;
        }
      }

      // Type filter (P0-B: signal_type, nao source_type)
      if (selectedType !== "all") {
        const typeList = selectedType.split(",");
        const st = lead.signal_type;
        if (!st || !typeList.includes(st)) {
          return false;
        }
      }

      // Owner type filter (Privado vs Institucional/Governamental vs Desconhecido)
      if (selectedOwnerType !== "all") {
        const oc = (lead as any).owner_class;
        if (oc) {
          if (selectedOwnerType !== oc) return false;
        } else {
          const isInstitutional = !!lead.institutional;
          if (selectedOwnerType === "institutional" && !isInstitutional) return false;
          if (selectedOwnerType === "private" && isInstitutional) return false;
          if (selectedOwnerType === "unknown" && lead.owner_name) return false;
        }
      }

      // Interest category filter (when in overview or opportunities)
      // Bypass when a specific lead type is selected (show all API results)
      if (activeTab === "overview" && selectedType === "all") {
        const cat = catOfLead(lead);
        if (!interests.has(cat.key)) return false;
      }

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesAddress = (lead.address || "").toLowerCase().includes(q);
        const matchesOwner = (lead.owner_name || "").toLowerCase().includes(q);
        const matchesDesc = (lead.issue_description || "").toLowerCase().includes(q);
        const matchesCat = (lead.issue_category || "").toLowerCase().includes(q);
        if (!matchesAddress && !matchesOwner && !matchesDesc && !matchesCat) {
          return false;
        }
      }

      // EXCLUDE RESERVED LEADS FROM GENERAL OPPORTUNITIES
      // Leads reserved by me or others should not appear in general opportunities
      if (lead.my_status === "reserved" || 
          lead.visibility_status === "reserved_by_me" || 
          lead.visibility_status === "reserved_by_other") {
        return false;
      }

      return true;
    });
  }, [leads, activeTab, selectedCity, selectedCategory, selectedUrgency, selectedType, selectedOwnerType, interests, searchQuery]);

  // New alerts (not yet viewed)
  const newAlerts = useMemo(
    () => filteredLeads.filter((l) => !shown.has(l.id)),
    [filteredLeads, shown]
  );

// Use Dashboard Summary for real KPIs (falls back to stats if summary not loaded)
  const realTotalLeads = dashboardSummary?.total_interested ?? (stats?.total ?? stats?.total_leads ?? 0);
  const lastScrapeText = String(dashboardSummary?.last_scrape ?? "");
  const scrapeCount = Number(lastScrapeText.match(/\d+/)?.[0] || 0);
  const lastScrapeDisplay = lastScrapeText || "Aguardando dados...";
  const urgentCount = dashboardSummary?.urgent ?? 0;

  const T = theme === "dark" ? DARK : LIGHT;
  const isDark = theme === "dark";

  // Motivo de liberação legível. `reveal_timeout` é gerado pelo watchdog
  // (não escolhido pelo utilizador) e aparecia CRU em "Meus Leads" — foi
  // assim que um cliente leu um código técnico como se fosse um erro do
  // sistema. Motivos desconhecidos continuam visíveis em vez de sumirem.
  const releaseReasonLabel = (reason: string) => {
    const known = RELEASE_REASONS.find((r) => r.value === reason);
    if (known) return t(known.key) || known.label;
    if (reason === "reveal_timeout") return t("release.reason.reveal_timeout");
    return reason;
  };

  // Modal action buttons for corporate vs regular leads
  const getModalActionButtons = () => {
    if (!selectedLead) return null;
    if (isCorporateLead(selectedLead)) {
      // Corporate lead: no phone, show badge and limited actions
      return (
        <div className="flex flex-wrap gap-2 pt-2">
          <span className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold ${selectedLead.institutional ? "bg-cyan-500/15 text-cyan-400" : "bg-purple-500/15 text-purple-400"}`}>
            {selectedLead.institutional
              ? <><Landmark className="h-3.5 w-3.5" /> {t("dashboard.badge.institutional")} · {t("dashboard.badge.institutional_channel")}</>
              : <><Building2 className="h-3.5 w-3.5" /> {t("dashboard.badge.corporate")}</>}
          </span>
          {selectedLead.owner_email && (
            <a
              href={`mailto:${selectedLead.owner_email}?subject=${encodeURIComponent(
                buildMsgs(selectedLead).emailSubject
              )}&body=${encodeURIComponent(buildMsgs(selectedLead).emailBody)}`}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-bold hover:bg-blue-500 transition"
            >
              <Mail className="h-3.5 w-3.5" /> E-mail
            </a>
          )}
          <a
            href={`https://maps.google.com/?q=${encodeURIComponent(buildFullAddress(selectedLead.address, selectedLead.city))}`}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500 text-slate-950 text-xs font-bold hover:bg-amber-400 transition"
          >
            <MapPin className="h-3.5 w-3.5" /> {t("dashboard.action.map")}
          </a>
        </div>
      );
    }
    // Lead NAO corporativo SEM telefone (owner_phone = null).
    // O `!` do TypeScript e apagado em runtime: quando o reveal expira
    // (reveal_timeout / virada do dia UTC) a API volta a mascarar
    // owner_phone para null e `waHref(null)` rebentava com
    // "Cannot read properties of null (reading 'replace')".
    // Decidir pelo campo real, nunca pela presuncao de que "regular => tem telefone".
    if (!selectedLead.owner_phone) {
      return (
        <div className="flex flex-wrap gap-2 pt-2 items-center">
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/15 text-amber-400 text-xs font-semibold">
            <Phone className="h-3.5 w-3.5" /> {t("dashboard.detail.no_phone")}
          </span>
          {selectedLead.owner_email && (
            <a
              href={`mailto:${selectedLead.owner_email}?subject=${encodeURIComponent(
                buildMsgs(selectedLead).emailSubject
              )}&body=${encodeURIComponent(buildMsgs(selectedLead).emailBody)}`}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-bold hover:bg-blue-500 transition"
            >
              <Mail className="h-3.5 w-3.5" /> {t("dashboard.detail.email")}
            </a>
          )}
          <a
            href={`https://maps.google.com/?q=${encodeURIComponent(buildFullAddress(selectedLead.address, selectedLead.city))}`}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500 text-slate-950 text-xs font-bold hover:bg-amber-400 transition"
          >
            <MapPin className="h-3.5 w-3.5" /> {t("dashboard.action.map")}
          </a>
        </div>
      );
    }

    // Regular lead WITH phone (owner_phone verificado acima)
    return (
      <div className="flex flex-wrap gap-2 pt-2">
        <a
          href={waHref(selectedLead.owner_phone!, buildMsgs(selectedLead))}
          target="_blank"
          rel="noreferrer"
          onClick={() => recordContact(selectedLead.id, "whatsapp").catch(() => {})}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500 text-slate-950 text-xs font-bold hover:bg-emerald-400 transition"
        >
          <MessageSquare className="h-3.5 w-3.5" /> WhatsApp
        </a>
        <a
          href={`tel:${selectedLead.owner_phone!}`}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-500 text-white text-xs font-bold hover:bg-sky-400 transition"
        >
          <Phone className="h-3.5 w-3.5" /> Ligar
        </a>
        <a
          href={smsHref(selectedLead.owner_phone!, buildMsgs(selectedLead))}
          onClick={() => recordContact(selectedLead.id, "sms").catch(() => {})}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-600 text-white text-xs font-bold hover:bg-green-500 transition"
        >
          <MessageSquare className="h-3.5 w-3.5" /> SMS
        </a>
        {selectedLead.owner_email && (
          <a
            href={`mailto:${selectedLead.owner_email}?subject=${encodeURIComponent(
              buildMsgs(selectedLead).emailSubject
            )}&body=${encodeURIComponent(buildMsgs(selectedLead).emailBody)}`}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-bold hover:bg-blue-500 transition"
          >
            <Mail className="h-3.5 w-3.5" /> E-mail
          </a>
        )}
        <a
          href={`https://maps.google.com/?q=${encodeURIComponent(buildFullAddress(selectedLead.address, selectedLead.city))}`}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500 text-slate-950 text-xs font-bold hover:bg-amber-400 transition"
        >
<MapPin className="h-3.5 w-3.5" /> {t("dashboard.action.map")}
          </a>
          <button
            onClick={() => copyToClipboard(selectedLead.owner_phone!, "phone")}
          className={`flex items-center gap-1 px-3 py-1.5 rounded-lg border text-xs transition ${T.border} ${T.text} ${T.navHover}`}
        >
          {copiedField === "phone" ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
          Copiar telefone
        </button>
      </div>
    );
  };

  const modalActionButtons = selectedLead ? getModalActionButtons() : null;

  // ---- Filtros: uma unica definicao usada inline (desktop) e na gaveta mobile.
  const selectCls = `px-3 py-1.5 rounded-lg text-sm border outline-none transition ${
    isDark
      ? "bg-[#0b0d1a] border-white/10 text-white"
      : "bg-white border-slate-200 text-slate-900"
  }`;
  const activeFilterCount = [
    selectedCity !== "all",
    selectedCategory !== "all",
    selectedUrgency !== "all",
    selectedOwnerType !== "all",
    selectedType !== "all",
    includeClosed,
  ].filter(Boolean).length;
  const clearFilters = () => {
    setSelectedCity("all");
    setSelectedCategory("all");
    setSelectedUrgency("all");
    setSelectedOwnerType("all");
    setSelectedType("all");
    setIncludeClosed(false);
  };

  const filterControls = (
    <>
      <label className="flex items-center gap-2 min-w-0">
        <span className={`text-xs font-medium whitespace-nowrap ${T.text2}`}>
          {t("dashboard.filter.city") || "📍 Cidade:"}
        </span>
        <select
          value={selectedCity}
          onChange={(e) => setSelectedCity(e.target.value)}
          className={`${selectCls} flex-1 lg:flex-none`}
        >
          {CITIES.map((c) => (
            <option key={c} value={c}>
              {c === "all" ? t("dashboard.filter.all_cities") || "Todas" : c}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-2 min-w-0">
        <span className={`text-xs font-medium whitespace-nowrap ${T.text2}`}>
          {t("dashboard.filter.category") || "🔧 Categoria:"}
        </span>
        <select
          value={selectedCategory}
          onChange={(e) => setSelectedCategory(e.target.value)}
          className={`${selectCls} flex-1 lg:flex-none`}
        >
          {CATEGORIES_FILTER.map((c) => (
            <option key={c} value={c}>
              {c === "all"
                ? t("dashboard.filter.all_categories") || "Todas"
                : t(CATEGORIES.find((x) => x.key === c)?.labelKey || c)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-2 min-w-0">
        <span className={`text-xs font-medium whitespace-nowrap ${T.text2}`}>
          {t("dashboard.filter.urgency") || "⚡ Urgência:"}
        </span>
        <select
          value={selectedUrgency}
          onChange={(e) => setSelectedUrgency(e.target.value)}
          className={`${selectCls} flex-1 lg:flex-none`}
        >
          {URGENCIES.map((u) => (
            <option key={u} value={u}>
              {u === "all"
                ? t("dashboard.filter.all_urgency") || "Todas"
                : t(`dashboard.feed.urgency.${u}`) || u.charAt(0).toUpperCase() + u.slice(1)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-2 min-w-0">
        <span className={`text-xs font-medium whitespace-nowrap ${T.text2}`}>
          {t("dashboard.filter.owner_type") || "👤 Proprietário:"}
        </span>
        <select
          value={selectedOwnerType}
          onChange={(e) => setSelectedOwnerType(e.target.value)}
          className={`${selectCls} flex-1 lg:flex-none`}
        >
          {OWNER_TYPES.map((ot) => {
            const count =
              ot.value === "all"
                ? realTotalLeads
                : ot.value === "institutional"
                  ? (dashboardSummary?.by_owner_type?.institutional ?? 0)
                  : ot.value === "private"
                    ? (dashboardSummary?.by_owner_type?.private ?? 0)
                    : (dashboardSummary?.by_owner_type as any)?.unknown ?? 0;
            return (
              <option key={ot.value} value={ot.value}>
                {t(ot.labelKey) || ot.value}
                {ot.value !== "all" ? ` (${count})` : ""}
              </option>
            );
          })}
        </select>
      </label>
      <label className="flex items-center gap-2 min-w-0">
        <span className={`text-xs font-medium whitespace-nowrap ${T.text2}`}>
          {t("dashboard.filter.type") || "Tipo:"}
        </span>
        <select
          value={selectedType}
          onChange={(e) => {
            const newType = e.target.value;
            setSelectedType(newType);
            if (newType !== "all") {
              setSelectedCategory("all");
            }
          }}
          className={`${selectCls} flex-1 lg:flex-none`}
        >
          {LEAD_TYPES.map((lt) => (
            <option key={lt.value} value={lt.value}>
              {t(lt.labelKey)}
            </option>
          ))}
        </select>
      </label>
      <button
        onClick={() => setIncludeClosed((v) => !v)}
        aria-pressed={includeClosed}
        title={t("dashboard.badge.closed_hint")}
        className={`flex items-center justify-center gap-1.5 text-[11px] font-semibold px-2.5 py-2 rounded-lg border transition ${
          includeClosed
            ? isDark
              ? "bg-slate-500/20 border-slate-400/40 text-slate-200"
              : "bg-slate-200 border-slate-300 text-slate-900"
            : isDark
              ? "bg-transparent border-white/10 text-slate-400 hover:text-slate-200"
              : "bg-white border-slate-200 text-slate-600 hover:text-slate-900"
        }`}
      >
        <Archive className="h-3.5 w-3.5" /> {t("dashboard.filter.include_closed")}
      </button>
    </>
  );

  return (
    <div
      data-theme={theme}
      className="flex min-h-screen transition-colors duration-200"
      style={{ backgroundColor: T.bg, color: isDark ? "#f8fafc" : "#0f172a" }}
    >
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 bg-black/60 lg:hidden backdrop-blur-sm" onClick={() => setSidebarOpen(false)} />
      )}

      {/* SIDEBAR */}
      <aside
        className={`fixed lg:sticky top-0 z-50 h-screen w-64 shrink-0 flex flex-col border-r transition-all duration-300 lg:translate-x-0 ${T.border} ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        style={{ backgroundColor: T.sidebar }}
      >
        <div className={`flex items-center gap-2.5 px-5 h-16 border-b ${T.border}`}>
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-indigo-500 via-indigo-600 to-fuchsia-600 flex items-center justify-center shadow-md shadow-indigo-500/20">
            <Sparkles className="h-4 w-4 text-white" />
          </div>
          <div>
            <div className={`font-bold text-[15px] leading-tight ${isDark ? "text-white" : "text-slate-900"}`}>
              {t("dashboard.sidebar.brand")}
            </div>
            <div className={`text-[10px] ${T.text2}`}>{t("dashboard.sidebar.sub")}</div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {[
            { id: "overview", icon: LayoutDashboard, label: t("dashboard.nav.overview") },
            { id: "opportunities", icon: FolderKanban, label: t("dashboard.nav.opportunities"),               badge: realTotalLeads.toLocaleString() },
            { id: "favorites", icon: Star, label: t("dashboard.nav.favorites"), badge: String(leads.filter((l) => l.favorited).length || "") },
            { id: "interests", icon: SlidersHorizontal, label: t("dashboard.nav.interests"), badge: String(interests.size) },
            { id: "alerts", icon: Bell, label: t("dashboard.nav.alerts"), badge: unreadCount > 0 ? String(unreadCount) : undefined },
            { id: "history", icon: History, label: t("dashboard.nav.history"), badge: undefined },
          ].map((item) => {
            const active = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => {
                  setActiveTab(item.id as any);
                  setSidebarOpen(false);
                }}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition ${
                  active
                    ? "bg-gradient-to-r from-indigo-500/20 to-fuchsia-500/10 text-indigo-400 border border-indigo-500/30 shadow-sm"
                    : `${T.text2} ${T.navHover} ${isDark ? "hover:text-slate-200" : "hover:text-slate-900"}`
                }`}
              >
                <item.icon className="h-4 w-4" />
                <span className="flex-1 text-left">{item.label}</span>
                {item.badge && (
                  <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                    active ? "bg-indigo-500 text-white" : `${T.chipActive}`
                  }`}>
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}

          <div className={`pt-4 mt-4 border-t space-y-1 ${T.divider}`}>
            <button
              onClick={() => setShowCheckout(true)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition ${T.text2} ${T.navHover}`}
            >
              <CreditCard className="h-4 w-4 text-emerald-500" />
              <span className="flex-1 text-left">{t("dashboard.nav.plans")}</span>
              <span className="text-[10px] font-bold bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full">
                  {t("dashboard.trial.week_badge")}
              </span>
            </button>
            <Link
              href="/dashboard/settings"
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition ${T.text2} ${T.navHover}`}
            >
              <Settings className="h-4 w-4" />
              <span className="flex-1 text-left">{t("dashboard.nav.settings")}</span>
            </Link>
          </div>
        </nav>

        {/* Credit Balance Display (Phase 4) */}
          {creditBalance && (
            <div className={`px-3 py-2 border-t ${T.border}`}>
              <div className="text-[10px] font-semibold uppercase tracking-wider mb-1.5" style={{ color: "var(--text-muted)" }}>
                {t("dashboard.sidebar.credit_balance") || "Saldo de Créditos"}
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="h-7 w-7 rounded-lg bg-emerald-500/20 text-emerald-400 flex items-center justify-center">
                    <TrendingUp className="h-3.5 w-3.5" />
                  </div>
                  <div>
                    <div className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
                      {creditBalance.balance}
                    </div>
                    <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                      {t("dashboard.sidebar.credits_available") || "créditos disponíveis"}
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] font-medium" style={{ color: "var(--text-muted)" }}>
                    {t("dashboard.sidebar.today_used") || "Hoje"}
                  </div>
                  <div className="text-sm font-bold text-amber-400">
                    {creditBalance.counts?.consume_reveal?.count ?? 0} / {dailyStats?.limit ?? 10}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* User Card in Sidebar */}
        <div className={`p-3 border-t ${T.border}`}>
          <div className={`flex items-center gap-3 px-2 py-2 rounded-xl transition ${T.navHover}`}>
            <div className="h-9 w-9 rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center text-xs font-bold text-white shadow-sm">
              {(user?.company_name || user?.email || "U").slice(0, 2).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <div className={`text-sm font-semibold truncate ${isDark ? "text-white" : "text-slate-900"}`}>
                {user?.company_name || "Contratante Pro"}
              </div>
              <div className="text-[11px] text-emerald-400 font-medium capitalize">
                {user?.plan ? `Plano ${user.plan}` : "Teste Grátis (7d)"}
              </div>
            </div>
            <button
              onClick={() => signOut()}
              title={t("dashboard.sidebar.logout")}
              className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* MAIN CONTENT AREA */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* TOPBAR */}
        <header
          className={`sticky top-0 z-30 h-16 flex items-center gap-3 px-4 md:px-6 backdrop-blur border-b transition-colors duration-200 ${T.border}`}
          style={{ backgroundColor: isDark ? "rgba(11,13,18,0.85)" : "rgba(255,255,255,0.85)" }}
        >
          <button
            className={`lg:hidden p-2 rounded-lg transition ${T.text2} ${T.navHover}`}
            onClick={() => setSidebarOpen(true)}
            aria-label="Abrir menu"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>

          <div className="flex-1 max-w-md hidden sm:block">
            <div className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm border ${T.border} ${T.input}`}>
              <Search className="h-4 w-4 text-slate-400" />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t("dashboard.topbar.search_placeholder")}
                className={`bg-transparent outline-none flex-1 text-sm ${isDark ? "text-slate-100 placeholder:text-slate-500" : "text-slate-900 placeholder:text-slate-400"}`}
              />
              {searchQuery && (
                <button onClick={() => setSearchQuery("")} className="text-slate-400 hover:text-slate-200">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>

          <div className="ml-auto flex items-center gap-2 md:gap-3">
            {/* Theme Toggle */}
            <button
              data-testid="theme-toggle"
              onClick={() => setTheme((p) => (p === "dark" ? "light" : "dark"))}
              className={`p-2 rounded-xl border ${T.border} ${T.text2} ${T.navHover} transition`}
              title={t("dashboard.topbar.theme")}
            >
              {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>

            {/* Notification Bell Dropdown */}
            <div className="relative" ref={bellRef}>
              <button
                onClick={() => setBellOpen(!bellOpen)}
                className={`relative p-2 rounded-xl border ${T.border} ${T.text2} ${T.navHover} transition`}
                aria-label={t("dashboard.topbar.notifications")}
              >
                <Bell className="h-4 w-4" />
                {unreadCount > 0 && (
                  <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-indigo-500 text-[10px] font-bold text-white shadow-md">
                    {unreadCount > 9 ? "9+" : unreadCount}
                  </span>
                )}
              </button>

              {bellOpen && (
                <div
                  className={`absolute right-0 top-full mt-2 w-80 md:w-96 rounded-2xl border shadow-2xl z-50 overflow-hidden ${
                    isDark ? "bg-[#14161d] border-white/10" : "bg-white border-slate-200"
                  }`}
                >
                  <div className={`flex items-center justify-between px-4 py-3 border-b ${T.border}`}>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{t("dashboard.topbar.notifications")}</span>
                      {unreadCount > 0 && (
                        <span className="text-[10px] bg-indigo-500/20 text-indigo-400 px-2 py-0.5 rounded-full font-bold">
                          {unreadCount} novas
                        </span>
                      )}
                    </div>
                    {notifications.some((n) => !n.read) && (
                      <button
                        onClick={handleMarkAllRead}
                        className="text-xs text-indigo-400 hover:text-indigo-300 transition"
                      >
                        {t("dashboard.topbar.mark_all_read")}
                      </button>
                    )}
                  </div>

                  <div className="max-h-96 overflow-y-auto divide-y divide-white/5">
                    {notifications.length === 0 ? (
                      <div className={`px-4 py-8 text-center text-sm ${T.text2}`}>
                        {t("dashboard.topbar.no_notifications")}
                      </div>
                    ) : (
                      notifications.slice(0, 15).map((n) => (
                        <div
                          key={n.id}
                          onClick={() => handleNotificationClick(n)}
                          className={`px-4 py-3 cursor-pointer transition ${T.navHover} ${
                            !n.read ? "bg-indigo-500/5 font-medium" : "opacity-80"
                          }`}
                        >
                          <div className="flex items-start gap-2.5">
                            <span className="mt-1 h-2 w-2 rounded-full shrink-0 bg-indigo-500" style={{ opacity: n.read ? 0.3 : 1 }} />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center justify-between gap-1">
                                <span className={`text-xs font-semibold uppercase tracking-wider ${!n.read ? "text-indigo-400" : "text-slate-400"}`}>
                                  {n.type === "new_lead" ? t("dashboard.notification.new_lead.title") : n.type}
                                </span>
                                <span className="text-[10px] text-slate-500">
                                  {formatRelativeTime(n.created_at, t)}
                                </span>
                              </div>
                              <p className={`text-sm mt-0.5 line-clamp-2 ${isDark ? "text-slate-200" : "text-slate-800"}`}>
                                {n.message || n.title}
                              </p>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Push Notification Button */}
              <PushNotificationButton />

              {/* Trial CTA button */}
            <button
              onClick={() => setShowCheckout(true)}
              className="flex items-center gap-1.5 shrink-0 whitespace-nowrap bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 font-semibold text-xs md:text-sm px-3.5 py-2 rounded-xl shadow-md shadow-emerald-500/20 transition"
            >
              <CreditCard className="h-4 w-4" />
              <span>{t("dashboard.trial.scribe")}</span>
            </button>
          </div>
        </header>

        {/* MAIN BODY CONTAINER */}
        <main className="flex-1 p-4 md:p-6 space-y-6 max-w-7xl mx-auto w-full">
          {/* Push Notification Button */}
          <PushOnboardingBanner />

          {/* Nudge: utilizadores sem especialidades definidas */}
          <InterestsNudgeBanner
            show={interestsConfigured === false}
            onSetup={() => {
              setActiveTab("interests");
              setTimeout(() => {
                document.getElementById("interests-config")?.scrollIntoView({
                  behavior: "smooth",
                  block: "start",
                });
              }, 50);
            }}
          />

          {/* GREETING */}
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <p className={`text-xs font-medium tracking-wide uppercase ${isDark ? "text-emerald-400" : "text-emerald-600"}`}>
                {t("dashboard.greeting.kicker")}
              </p>
              <h1 className={`text-2xl md:text-3xl font-extrabold tracking-tight ${isDark ? "text-white" : "text-slate-950"}`}>
                {t(greetingKey)}
              </h1>
              <p className={`mt-1 text-sm ${isDark ? "text-slate-300" : "text-slate-600"}`}>
                {t("dashboard.greeting.sub")}
              </p>
            </div>
          </div>

          {/* SUBSCRIPTION BANNER + DAILY LIMIT BAR */}
          <div className="rounded-2xl border border-emerald-500/30 bg-gradient-to-r from-emerald-500/10 via-teal-500/5 to-transparent p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                {(() => {
                  const days = subscription?.days_remaining ?? 0;
                  const expired = subscription?.status === "trial_expired" || subscription?.status === "subscription_expired" || days <= 0;
                  const expiringSoon = days > 0 && days <= 3;
                  if (expired) {
                    return (
                      <>
                        <p className="text-sm font-semibold text-rose-400">{t("dashboard.trial.paused")}</p>
                        <p className="text-xs text-slate-400">{t("dashboard.trial.expired_body")}</p>
                      </>
                    );
                  }
                  if (expiringSoon) {
                    return (
                      <>
                        <p className="text-sm font-semibold text-amber-400">{t("dashboard.trial.expiring_soon", { days })}</p>
                        <p className="text-xs text-slate-400">{t("dashboard.trial.expiring_body")}</p>
                      </>
                    );
                  }
                  // Ativo com dias restantes
                  return (
                    <>
                      <p className="text-sm font-semibold text-emerald-400">{t("dashboard.trial.active", { days })}</p>
                      <p className="text-xs text-slate-400">{t("dashboard.trial.active_body")}</p>
                    </>
                  );
                })()}
              </div>
            </div>
          </div>

          {/* DAILY LIMIT BAR (10 leads/dia) */}
          <div className={`rounded-xl border p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${T.subtle}`}>
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-amber-500/20 text-amber-400 flex items-center justify-center shrink-0">
                <BarChart3 className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm font-semibold text-amber-400">
                  {t("dashboard.trial.daily_limit_label", { used: dailyStats?.used ?? 0, limit: dailyStats?.limit ?? 10 })}
                </p>
                <div className={`w-full max-w-xs h-2 rounded-full overflow-hidden mt-1 ${T.track}`}>
                  <div 
                    className="h-full bg-amber-500 transition-all duration-300" 
                    style={{ width: dailyStats && dailyStats.limit > 0 ? `${Math.min(100, (dailyStats.used / dailyStats.limit) * 100)}%` : '0%' }}
                  />
                </div>
              </div>
            </div>
            {dailyStats && dailyStats.remaining === 0 && (
              <div className="text-xs text-red-400 font-medium">
                {t("dashboard.trial.daily_limit_exceeded").replace("{reset_at}", dailyStats.reset_at ? formatRelativeTime(dailyStats.reset_at, t) : "breve")}
                <div className={`text-xs font-normal mt-0.5 ${T.text2}`}>
                  {t("dashboard.trial.corporate_still_free")}
                </div>
              </div>
            )}
          </div>

          {/* FILTER BAR — inline em desktop, gaveta (sheet) em mobile */}
          <div className={`hidden lg:flex flex-wrap items-center gap-3 p-4 rounded-xl border ${T.panel}`}>
            {filterControls}
            <div className="flex-1" />
            <div className={`flex items-center gap-2 text-xs ${T.text2}`}>
              <span>{filteredLeads.length} {t("dashboard.filter.showing") || "oportunidades"}</span>
              <span>·</span>
              <span>{newAlerts.length} {t("dashboard.filter.new") || "novas"}</span>
            </div>
          </div>

          <div className="lg:hidden flex items-center gap-2">
            <button
              ref={filtersTriggerRef}
              type="button"
              onClick={() => setFiltersOpen(true)}
              aria-haspopup="dialog"
              aria-controls="filters-sheet"
              aria-expanded={filtersOpen}
              className={`flex items-center gap-2 px-3.5 py-2.5 rounded-xl border text-sm font-semibold transition ${T.panel} ${T.text}`}
            >
              <SlidersHorizontal className="h-4 w-4" />
              {t("dashboard.filter.open") || "Filtros"}
              {activeFilterCount > 0 && (
                <span className="inline-flex items-center justify-center h-5 min-w-5 px-1.5 rounded-full bg-indigo-500 text-white text-[10px] font-bold">
                  {activeFilterCount}
                </span>
              )}
            </button>
            <span className={`ml-auto text-xs ${T.text2}`}>
              {filteredLeads.length} {t("dashboard.filter.showing") || "oportunidades"}
            </span>
          </div>

          {filtersOpen && (
            <div
              className="lg:hidden fixed inset-0 z-[80]"
              role="dialog"
              aria-modal="true"
              aria-labelledby="filters-sheet-title"
            >
              <div
                className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                onClick={() => setFiltersOpen(false)}
              />
              <div
                ref={filtersSheetRef}
                id="filters-sheet"
                tabIndex={-1}
                onKeyDown={(e) => {
                  // Focus trap simples: Tab circula apenas dentro da folha.
                  if (e.key !== "Tab") return;
                  const nodes = filtersSheetRef.current?.querySelectorAll<HTMLElement>(
                    'button, select, a[href], input, [tabindex]:not([tabindex="-1"])'
                  );
                  if (!nodes || nodes.length === 0) return;
                  const first = nodes[0];
                  const last = nodes[nodes.length - 1];
                  if (e.shiftKey && document.activeElement === first) {
                    e.preventDefault();
                    last.focus();
                  } else if (!e.shiftKey && document.activeElement === last) {
                    e.preventDefault();
                    first.focus();
                  }
                }}
                className={`absolute bottom-0 left-0 right-0 max-h-[85vh] overflow-y-auto rounded-t-2xl border-t p-5 pb-8 space-y-4 animate-slide-up outline-none ${
                  isDark
                    ? "bg-[#14161d] border-white/10 text-slate-100"
                    : "bg-white border-slate-200 text-slate-900 shadow-2xl"
                }`}
              >
                <div className="flex items-center justify-between">
                  <h3 id="filters-sheet-title" className="text-sm font-bold">
                    {t("dashboard.filter.open") || "Filtros"}
                  </h3>
                  <button
                    type="button"
                    onClick={() => setFiltersOpen(false)}
                    aria-label={t("dashboard.filter.close") || "Fechar"}
                    className={`p-1.5 rounded-lg transition ${isDark ? "hover:bg-white/10 text-slate-400" : "hover:bg-slate-100 text-slate-600"}`}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                <div className="flex flex-col gap-3">{filterControls}</div>
                <div className="flex gap-2 pt-2">
                  <button
                    type="button"
                    onClick={clearFilters}
                    className={`flex-1 px-4 py-2.5 rounded-xl border text-sm font-semibold transition ${T.border} ${T.text2} ${T.navHover}`}
                  >
                    {t("dashboard.filter.clear") || "Limpar"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setFiltersOpen(false)}
                    className="flex-1 px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                  >
                    {t("dashboard.filter.apply") || "Aplicar"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* DATA FRESHNESS BADGE */}
          <div className="flex items-center justify-end mb-3">
            <div className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs border ${theme === "dark" ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"} ${T.text2}`}>
              {scraperState?.active ? (
                <>
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                  </span>
                  <span>{t("dashboard.freshness.updating") || "Atualizando dados…"}</span>
                </>
              ) : scraperState?.last_run?.finished_at ? (
                <>
                  <span className="inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                  <span>{`${t("dashboard.freshness.updated") || "Dados atualizados"}: ${formatRelativeTime(scraperState.last_run.finished_at, t)}`}</span>
                </>
              ) : (
                <span>{t("dashboard.freshness.warmup") || "Coletando dados…"}</span>
              )}
            </div>
          </div>

          {/* KPI CARDS - Real stats from Dashboard Summary */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
            {[
              { label: t("dashboard.kpi.interested") || "No seu interesse", value: dashboardSummary?.total_interested ?? 0, delta: t("dashboard.kpi.opportunities") || "oportunidades reais", icon: Building2, color: "#6366f1" },
              // Card "Última varredura": número canónico e ESTÁVEL do último lote
              // concluído do scraper — a MESMA fonte da landing
              // (`/api/metrics/public` → last_scrape.novas_oportunidades).
              // Antes usava `recent_count` (janela móvel de 2h sobre `updated_at`,
              // reescrito por cada re-scrape) e oscilava >5000 ↔ 1100 ↔ 1.
              // Agora ambos (dashboard e landing) exibem exatamente o mesmo valor.
              { label: t("dashboard.kpi.last_scrape"), value: publicMetrics?.last_scrape?.novas_oportunidades ?? dashboardSummary?.recent_count ?? scrapeCount, delta: t("dashboard.kpi.updated_now"), icon: TrendingUp, color: "#22c55e" },
              // `with_contact` conta leads COM PROPRIETÁRIO IDENTIFICADO — não
              // telefone (as validações de ligações só acontecem na reserva, de
              // propósito: o número é pago). "prontas p/ ligar" era mentira.
              { label: t("dashboard.kpi.with_contact") || "Com contato", value: dashboardSummary?.with_contact ?? 0, delta: t("dashboard.kpi.owner_identified") || "com proprietário identificado", icon: Phone, color: "#f59e0b" },
              { label: t("dashboard.kpi.urgent") || "Urgentes", value: dashboardSummary?.urgent ?? 0, delta: t("dashboard.kpi.need_action") || "precisam ação", icon: AlertCircle, color: "#ef4444" },
            ].map((k) => (
              <div key={k.label} className={`border rounded-xl p-4 transition-colors ${theme === "dark" ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
                <div className="flex items-center gap-2">
                  <div className={`text-xs ${T.text2}`}>{k.label}</div>
                  <k.icon className="h-4 w-4" style={{ color: k.color }} />
                </div>
                <div className="text-2xl md:text-3xl font-bold mt-1" style={{ color: k.color }}>{Number(k.value ?? 0).toLocaleString()}</div>
                <div className={`text-[11px] mt-2 flex items-center gap-1 ${T.text2}`}>
                  <span>{k.delta}</span>
                </div>
              </div>
            ))}
          </div>

          {/* DYNAMIC CITY FILTER BAR - Always show all 4 cities fixed */}
          <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none">
            <span className={`text-xs font-medium uppercase tracking-wider shrink-0 mr-1 ${T.text2}`}>
              <MapPin className="h-3.5 w-3.5 inline mr-1" />
              {t("db.city")}:
            </span>
            <button
              onClick={() => setSelectedCity("all")}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold shrink-0 transition border ${
                selectedCity === "all"
                  ? "bg-indigo-500 text-white border-indigo-500"
                  : `${T.border} ${T.navHover} ${T.text2}`
              }`}
            >
              {t("dashboard.feed.all_cities")} ({realTotalLeads.toLocaleString()})
            </button>
            {(() => {
              // Fixed list of all 4 cities - always show all
              const allCities = ["NYC", "Chicago", "Dallas", "Boston"];
              // Mesma base canônica do totalizador (dashboardSummary.by_city):
              // garante soma(cidades) == totalizador por identidade matemática.
              const byCity = dashboardSummary?.by_city ?? {};
              const apiCounts: Record<string, number> = {};
              Object.entries(byCity).forEach(([name, n]) => { apiCounts[name.trim().toUpperCase()] = n; });
              return allCities.map((city) => {
                const key = city.toLowerCase();
                const count = apiCounts[city.toUpperCase()] ?? 0;
                return (
                  <button
                    key={city}
                    onClick={() => setSelectedCity(city)}
                    className={`px-3 py-1.5 rounded-xl text-xs font-semibold shrink-0 transition border ${
                      selectedCity.toLowerCase() === key
                        ? "bg-indigo-500 text-white border-indigo-500"
                        : `${T.border} ${T.navHover} ${T.text2}`
                    }`}
                  >
                    {city} ({count.toLocaleString()})
                  </button>
                );
              });
            })()}
          </div>

          {/* ALERTS TAB: NOTIFICAÇÕES */}
          {activeTab === "alerts" ? (
            <section className="space-y-5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-bold flex items-center gap-2">
                    <Bell className="h-5 w-5 text-indigo-400" />
                    {t("dashboard.nav.alerts") || "Alertas"}
                  </h2>
                  <p className={`text-xs mt-0.5 ${T.text2}`}>
                    {unreadCount > 1
                      ? t("dashboard.notifications.unread_plural").replace("{count}", String(unreadCount))
                      : unreadCount === 1
                        ? t("dashboard.notifications.unread_singular").replace("{count}", "1")
                        : t("dashboard.notifications.all_read")}
                  </p>
                </div>
                {notifications.some((n) => !n.read) && (
                  <button
                    onClick={handleMarkAllRead}
                    className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/30 transition shrink-0"
                  >
                    <BadgeCheck className="h-3.5 w-3.5" />
                    Marcar todas como lidas
                  </button>
                )}
              </div>

              {notifications.length === 0 ? (
                <div className={`rounded-2xl border p-8 text-center ${isDark ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200"}`}>
                  <Bell className="w-10 h-10 text-slate-400 mx-auto mb-3" />
                  <h3 className="font-semibold mb-1">{t("dashboard.topbar.no_notifications") || "Sem notificações"}</h3>
                  <p className={`text-sm ${T.text2}`}>Você receberá alertas de novas oportunidades e atualizações aqui.</p>
                </div>
              ) : (
                <div className={`border rounded-2xl overflow-hidden divide-y ${T.border}`}>
                  {notifications.slice(0, 30).map((n) => (
                    <div
                      key={n.id}
                      onClick={() => handleNotificationClick(n)}
                      className={`px-4 py-3 cursor-pointer transition ${T.navHover} ${
                        !n.read ? "bg-indigo-500/5 font-medium" : "opacity-80"
                      }`}
                    >
                      <div className="flex items-start gap-2.5">
                        <span className="mt-1 h-2 w-2 rounded-full shrink-0 bg-indigo-500" style={{ opacity: n.read ? 0.3 : 1 }} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-1">
                            <span className={`text-xs font-semibold uppercase tracking-wider ${!n.read ? "text-indigo-400" : "text-slate-400"}`}>
                              {n.type === "new_lead" ? t("dashboard.notification.new_lead.title") : n.type}
                            </span>
                            <span className="text-[10px] text-slate-500">
                              {formatRelativeTime(n.created_at, t)}
                            </span>
                          </div>
                          <p className={`text-sm mt-0.5 line-clamp-2 ${isDark ? "text-slate-200" : "text-slate-800"}`}>
                            {n.message || n.title}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          ) : null}

          {/* HISTORY TAB: MEUS LEADS / HISTÓRICO */}
          {activeTab === "history" ? (
            <section className="space-y-5">
              {/* Header + filtro de ação */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-bold flex items-center gap-2">
                    <History className="h-5 w-5 text-indigo-400" />
                    {t("dashboard.history.title") || "Meus Leads / Histórico"}
                  </h2>
                  <p className={`text-xs mt-0.5 ${T.text2}`}>
                    {t("dashboard.history.sub") || "Todos os leads que você pegou — reservados, em negociação, convertidos, liberados e holds expirados."}
                  </p>
                </div>
                <button
                  onClick={() => setHistoryNeedsAction(!historyNeedsAction)}
                  className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold border transition shrink-0 ${
                    historyNeedsAction
                      ? "bg-amber-500 text-slate-950 border-amber-500"
                      : `${T.border} ${T.navHover} ${T.text2}`
                  }`}
                >
                  <AlertCircle className="h-3.5 w-3.5" />
                  {t("dashboard.only_needs_action")}
                </button>
              </div>

              {/* KPIs do histórico */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
                <div className={`border rounded-2xl p-4 transition ${isDark ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
                  <div className={`text-xs font-medium ${T.text2}`}>{t("dashboard.history.used_today")}</div>
                  <div className="text-2xl md:text-3xl font-bold mt-1 text-indigo-400">
                    {historyKpis?.today_used ?? 0} <span className="text-base font-semibold text-slate-500">/ {historyKpis?.today_limit ?? 10}</span>
                  </div>
                  <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden mt-2">
                    <div className="h-full bg-indigo-500 transition-all duration-300" style={{ width: historyKpis && historyKpis.today_limit > 0 ? `${Math.min(100, ((historyKpis.today_used || 0) / historyKpis.today_limit) * 100)}%` : "0%" }} />
                  </div>
                </div>

                <div className={`border rounded-2xl p-4 transition ${isDark ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
                  <div className={`text-xs font-medium ${T.text2}`}>{t("dashboard.history.total_reserved")}</div>
                  <div className="text-2xl md:text-3xl font-bold mt-1 text-emerald-400">
                    {historyKpis?.total_reserved ?? 0}
                  </div>
                  <div className={`text-[11px] mt-2 ${T.text2}`}>{t("dashboard.history.since_start")}</div>
                </div>

                <div className={`border rounded-2xl p-4 transition ${isDark ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
                  <div className={`text-xs font-medium ${T.text2}`}>{t("dashboard.history.converted")}</div>
                  <div className="text-2xl md:text-3xl font-bold mt-1 text-emerald-500">
                    {historyKpis?.converted ?? 0}
                  </div>
                  <div className="text-[11px] mt-2 text-emerald-400 font-medium">
                    {t("dashboard.history.conversion_rate").replace("{rate}", String(historyKpis?.conversion_rate ?? 0))}
                  </div>
                </div>

                <div className="border rounded-2xl p-4 transition border-amber-500/20 bg-amber-500/5">
                  <div className="text-xs font-medium text-amber-300">{t("dashboard.history.needs_action")}</div>
                  <div className="text-2xl md:text-3xl font-bold mt-1 text-amber-400">
                    {historyKpis?.needs_action ?? 0}
                  </div>
                  <div className="text-[11px] mt-2 text-amber-300/80">
                    {t("dashboard.history.needs_action_sub")}
                  </div>
                </div>
              </div>

              {/* Filtros */}
              <div className="space-y-2.5">
                <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none">
                  {[
                    { value: "", label: t("dashboard.history.filter_all") },
                    { value: "reserved", label: t("dashboard.history.filter_reserved") },
                    { value: "negotiating", label: t("dashboard.history.filter_negotiating") },
                    { value: "hold_expired", label: t("dashboard.history.filter_hold_expired") },
                    { value: "converted", label: t("dashboard.history.filter_converted") },
                    { value: "released", label: t("dashboard.history.filter_released") },
                  ].map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setHistoryStatus(opt.value)}
                      className={`px-3 py-1.5 rounded-xl text-xs font-semibold shrink-0 transition border ${
                        historyStatus === opt.value
                          ? "bg-indigo-500 text-white border-indigo-500"
                          : `${T.border} ${T.navHover} ${T.text2}`
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex items-center gap-1.5 overflow-x-auto scrollbar-none">
                    {[
                      { value: "", label: t("dashboard.history.period_all") },
                      { value: "today", label: t("dashboard.history.period_today") },
                      { value: "7d", label: t("dashboard.history.period_7d") },
                      { value: "month", label: t("dashboard.history.period_month") },
                    ].map((opt) => (
                      <button
                        key={opt.value}
                        onClick={() => setHistoryPeriod(opt.value)}
                        className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold shrink-0 transition border ${
                          historyPeriod === opt.value
                            ? `${T.chipActive}`
                            : `${T.border} ${T.navHover} ${T.text2}`
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>

                  <select
                    value={historyCategory}
                    onChange={(e) => setHistoryCategory(e.target.value)}
                    className={`text-xs font-medium rounded-lg px-2.5 py-1.5 border outline-none ${T.border} ${isDark ? "bg-[#151822] text-slate-200" : "bg-white text-slate-800"}`}
                  >
                    <option value="">{t("dashboard.history.all_categories")}</option>
                    {CATEGORIES.map((c) => (
                      <option key={c.key} value={c.key}>{t(c.labelKey)}</option>
                    ))}
                  </select>

                  <div className="relative flex-1 min-w-[180px]">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
                    <input
                      value={historySearch}
                      onChange={(e) => setHistorySearch(e.target.value)}
                      placeholder={t("dashboard.search.placeholder")}
                      className={`w-full pl-8 pr-3 py-1.5 rounded-lg text-xs border outline-none ${T.border} ${isDark ? "bg-white/5 text-slate-200" : "bg-slate-100 text-slate-800"}`}
                    />
                  </div>
                </div>
              </div>

              {/* Lista */}
              {historyLoading ? (
                <div className="flex flex-col items-center justify-center py-16 gap-2">
                  <Loader2 className="h-6 w-6 animate-spin text-indigo-500" />
                  <span className={`text-xs ${T.text2}`}>Carregando seu histórico...</span>
                </div>
              ) : historyLeads.filter((l) => !historyCategory || catOfLead(l).key === historyCategory).length === 0 ? (
                <div className={`text-center py-16 border rounded-2xl ${T.border}`}>
                  <div className="text-4xl mb-3">📋</div>
                  <div className={`text-sm font-medium ${isDark ? "text-slate-300" : "text-slate-700"}`}>
                    {historyStatus || historyCategory || historyPeriod || historySearch || historyNeedsAction
                      ? t("dashboard.history.empty")
                      : t("dashboard.history.empty")}
                  </div>
                  <p className={`text-xs mt-1 ${T.text2}`}>
                    {historyStatus || historyCategory || historyPeriod || historySearch || historyNeedsAction
                      ? t("dashboard.history.adjust_filters")
                      : t("dashboard.history.reserve_first")}
                  </p>
                </div>
              ) : (
                <div className={`border rounded-2xl overflow-hidden divide-y ${T.border}`}>
                  {historyLeads.filter((l) => !historyCategory || catOfLead(l).key === historyCategory).map((lead) => {
                    const cat = catOfLead(lead);
                    const CatIcon = cat.icon;
                    const badge =
                      lead.my_status === "reserved"
                        ? { label: `Seu · ${lead.hold_expires_at ? countdownLabel(lead.hold_expires_at) : HOLD_FALLBACK}`, cls: "bg-rose-500/15 text-rose-400", icon: <Lock className="h-3 w-3" /> }
                        : lead.my_status === "negotiating"
                          ? { label: t("dashboard.status.negotiation"), cls: "bg-amber-500/15 text-amber-400", icon: <MessageSquare className="h-3 w-3" /> }
                          : lead.my_status === "hold_expired"
                            ? { label: t("dashboard.history.filter_hold_expired"), cls: `${isDark ? "bg-slate-500/15 text-slate-400" : "bg-slate-200 text-slate-600"}`, icon: <Clock className="h-3 w-3" /> }
                            : lead.my_status === "converted"
                              ? { label: t("dashboard.status.converted"), cls: "bg-emerald-500/15 text-emerald-400", icon: <BadgeCheck className="h-3 w-3" /> }
                              : lead.my_status === "released"
                                ? { label: t("dashboard.history.filter_released"), cls: `${isDark ? "bg-slate-500/15 text-slate-400" : "bg-slate-200 text-slate-600"}`, icon: <RefreshCcw className="h-3 w-3" /> }
                                : { label: t("dashboard.status.available"), cls: "bg-sky-500/15 text-sky-400", icon: <CheckCircle2 className="h-3 w-3" /> };
                    return (
                      <div
                        key={lead.id}
                        data-testid="history-row"
                        role="button"
                        tabIndex={0}
                        aria-label={`${lead.address}, ${lead.city}`}
                        onClick={() => openLeadDetail(lead)}
                        onKeyDown={(e) => {
                          if (e.target !== e.currentTarget) return;
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            openLeadDetail(lead);
                          }
                        }}
                        className={`px-5 py-4 cursor-pointer transition ${T.navHover} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/70 focus-visible:ring-inset`}
                      >
                        <div className="flex items-center gap-2 mb-2 flex-wrap">
                          <span className="text-[10px] font-semibold uppercase tracking-wider flex items-center gap-1.5 px-2.5 py-1 rounded-full" style={{ backgroundColor: `${cat.color}1a`, color: cat.color }}>
                            <CatIcon className="h-3 w-3" /> {t(cat.labelKey)}
                          </span>

                          {(lead.signal_type && (() => {
                            const st = lead.signal_type;
                            if (st === "legal_obligation") return <span className="text-[10px] font-semibold uppercase tracking-wider bg-amber-500/15 text-amber-400 px-2.5 py-1 rounded-full flex items-center gap-1"><AlertTriangle className="h-3 w-3" /> {t("dashboard.lead_type.obligation")}</span>;
                            if (st === "authorized_work") return <span className="text-[10px] font-semibold uppercase tracking-wider bg-sky-500/15 text-sky-400 px-2.5 py-1 rounded-full flex items-center gap-1"><HardHat className="h-3 w-3" /> {t("dashboard.lead_type.permit")}</span>;
                            return <span className={`text-[10px] font-semibold uppercase tracking-wider px-2.5 py-1 rounded-full flex items-center gap-1 ${isDark ? "bg-slate-500/15 text-slate-400" : "bg-slate-100 text-slate-600"}`}><FolderOpen className="h-3 w-3" /> {t("dashboard.lead_type.open")}</span>;
                          })())}

                          <span className={`text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-full flex items-center gap-1 ${badge.cls}`}>
                            {badge.icon} {badge.label}
                          </span>
                          <span className={`ml-auto text-xs flex items-center gap-1 font-medium capitalize ${T.text2}`}>
                            <MapPin className="h-3.5 w-3.5" /> {lead.city}
                          </span>
                        </div>

                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            <h3 className="font-semibold text-base leading-snug">{lead.address}</h3>
                            <div className={`flex items-center gap-3 text-[11px] mt-1.5 flex-wrap ${T.text2}`}>
                              {lead.owner_name && <span className="font-medium">{lead.owner_name}</span>}
                              <span className="flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                {t("dashboard.history.reserved_on")} {lead.held_at ? formatRelativeTime(lead.held_at, t) : "—"}
                              </span>
                              {lead.stage && lead.stage !== "converted" && (
                                <StageBadge stage={lead.stage} stageExpiresAt={lead.stage_expires_at} serverNow={lead.server_now} />
                              )}
                              {lead.hold_released_at && (
                                <span>{t("dashboard.history.released_on")} {formatRelativeTime(lead.hold_released_at, t)}</span>
                              )}
                              {lead.converted_at && (
                                <span className="text-emerald-400">{t("dashboard.history.converted_on")} {formatRelativeTime(lead.converted_at, t)}</span>
                              )}
                              {(lead.contact_count ?? 0) > 0 && (
                                <span className="flex items-center gap-1">
                                  <Phone className="h-3 w-3" /> {t("dashboard.history.contacts").replace("{count}", String(lead.contact_count))}
                                </span>
                              )}
                            </div>
                            {lead.release_reason && (
                              <div className={`text-[11px] mt-1 ${T.text2}`}>
                                {t("dashboard.field.reason")}:{" "}
                                {releaseReasonLabel(lead.release_reason)}
                              </div>
                            )}
                          </div>

                          <div className="flex flex-col items-end gap-2 shrink-0">
                            {lead.my_status === "reserved" && (
                              <button
                                onClick={(e) => { e.stopPropagation(); openReleaseModal(lead); }}
                                disabled={busyAction}
                                className={`inline-flex items-center gap-1.5 text-[11px] font-semibold ${T.ghostDanger} px-3 py-1.5 rounded-lg transition disabled:opacity-50`}
                              >
                                <RefreshCcw className="h-3 w-3" /> {t("dashboard.action.drop")}
                              </button>
                            )}
                            {lead.my_status === "negotiating" && (
                              <button
                                onClick={(e) => { e.stopPropagation(); handleHistoryConvert(lead); }}
                                disabled={busyAction}
                                className="inline-flex items-center gap-1.5 text-[11px] font-bold bg-emerald-500 hover:bg-emerald-400 text-slate-950 px-3 py-1.5 rounded-lg transition disabled:opacity-50"
                              >
                                <BadgeCheck className="h-3 w-3" /> {t("dashboard.action.record_conversion")}
                              </button>
                            )}
                            {(lead.my_status === "hold_expired" || lead.my_status === "released" || lead.my_status === "available") && (
                              <button
                                onClick={(e) => { e.stopPropagation(); handleHistoryReserve(lead); }}
                                disabled={busyAction || (subscription && !subscription.can_access) || isBlockedByQuota(lead, dailyStats?.remaining)}
                                className="inline-flex items-center gap-1.5 text-[11px] font-bold bg-indigo-500 hover:bg-indigo-400 text-white px-3 py-1.5 rounded-lg transition disabled:opacity-50"
                              >
                                <Lock className="h-3 w-3" /> {t("dashboard.action.rereserve")}
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          ) : (
          <>
          {/* GRID: INTERESTS CONFIG + OPPORTUNITIES FEED */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* INTERESTS SECTION */}
            <section id="interests-config" className={`border rounded-2xl p-5 space-y-4 transition ${isDark ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="font-bold text-base">{t("dashboard.interests.title")}</h2>
                  <p className={`text-xs ${T.text2}`}>{t("dashboard.interests.sub")}</p>
                </div>
                <SlidersHorizontal className={`h-4 w-4 ${T.text2}`} />
              </div>

              <div className="space-y-2">
                {CATEGORIES.map((cat) => {
                  const active = interests.has(cat.key);
                  const Icon = cat.icon;
                  return (
                    <button
                      key={cat.key}
                      onClick={() => toggleInterest(cat.key)}
                      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border transition ${
                        active
                          ? "bg-white/5 shadow-sm"
                          : "opacity-60 hover:opacity-100"
                      } ${isDark ? "border-white/10" : "border-slate-200"}`}
                      style={active ? { borderColor: `${cat.color}66`, backgroundColor: `${cat.color}10` } : {}}
                    >
                      <div
                        className="h-9 w-9 rounded-xl flex items-center justify-center shrink-0"
                        style={{ backgroundColor: `${cat.color}22` }}
                      >
                        <Icon className="h-4 w-4" style={{ color: cat.color }} />
                      </div>
                      <div className="flex-1 text-left">
                        <div className="text-sm font-semibold">{t(cat.labelKey)}</div>
                        <div className={`text-[11px] ${T.text2}`}>{t("dashboard.interests.live_alert")}</div>
                      </div>
                      <div
                        className={`h-5 w-5 rounded-md flex items-center justify-center border transition ${
                          active ? "text-white" : "text-transparent border-slate-400"
                        }`}
                        style={active ? { backgroundColor: cat.color, borderColor: cat.color } : {}}
                      >
                        <CheckCircle2 className="h-4 w-4" />
                      </div>
                    </button>
                  );
                })}
              </div>

              <div className={`rounded-xl border p-3 text-xs leading-relaxed ${isDark ? "bg-indigo-500/10 border-indigo-500/20 text-slate-300" : "bg-indigo-50 border-indigo-200 text-slate-700"}`}>
                {t("dashboard.interests.tip")}
              </div>
            </section>

            {/* OPPORTUNITIES FEED */}
            <section className={`lg:col-span-2 border rounded-2xl overflow-hidden flex flex-col transition ${isDark ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
              <div className={`px-5 py-4 border-b flex items-center justify-between ${T.border}`}>
                <div>
                  <h2 className="font-bold text-base flex items-center gap-2">
                    <span>{t("dashboard.feed.all_title")}</span>
                    {/* ACCURATE COUNT INDICATOR */}
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-400">
                      {filteredLeads.length.toLocaleString()} de {feedTotal.toLocaleString()}
                    </span>
                  </h2>
                  <p className={`text-xs ${T.text2}`}>{t("dashboard.feed.filtered_sub")}</p>
                </div>
                <Filter className={`h-4 w-4 ${T.text2}`} />
              </div>

              <div className={`flex-1 overflow-y-auto max-h-[640px] divide-y ${T.border}`}>
                {loadingLeads ? (
                  // Skeletons: preservam a altura dos cartoes reais para evitar
                  // salto de layout quando os dados chegam.
                  <div aria-busy="true" aria-live="polite">
                    <span className="sr-only">{t("dashboard.feed.loading")}</span>
                    {[0, 1, 2, 3].map((i) => (
                      <div
                        key={i}
                        aria-hidden="true"
                        className={`px-5 py-4 animate-pulse ${i > 0 ? `border-t ${T.border}` : ""}`}
                      >
                        <div className="flex items-center gap-2 mb-3 flex-wrap">
                          <div className={`h-5 w-24 rounded-full ${T.track}`} />
                          <div className={`h-5 w-20 rounded-full ${T.track}`} />
                          <div className={`h-5 w-16 rounded-full ${T.track}`} />
                        </div>
                        <div className={`h-4 w-2/3 rounded ${T.track}`} />
                        <div className={`h-3 w-1/2 rounded mt-2 ${T.track}`} />
                        <div className={`h-8 w-28 rounded-lg mt-4 ${T.track}`} />
                      </div>
                    ))}
                  </div>
                ) : filteredLeads.length === 0 ? (
                  <div className="p-12 text-center">
                    <div className="text-4xl mb-3">🧰</div>
                    <div className={`text-sm font-medium ${isDark ? "text-slate-300" : "text-slate-700"}`}>
                      {t("dashboard.feed.empty")}
                    </div>
                    <div className={`text-xs mt-1 ${T.text2}`}>
                      {t("dashboard.feed.empty_hint")}
                    </div>
                  </div>
                ) : (
                  <>
                    {/* Resumo agregado do contacto. Substitui o aviso repetido em
                        cada cartao: em producao essentially todos os leads sao
                        "incomplete_delivery", e um aviso em 100% dos cartoes
                        informava zero. Aqui diz quantos e o que isso permite. */}
                    {countLeadsWithoutContact(filteredLeads) > 0 && (
                      <div className="flex items-start gap-2 px-5 py-2.5 bg-amber-500/5 border-b border-amber-500/20">
                        <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0 text-amber-500/80" />
                        <span className="text-[11px] text-amber-500/90 leading-snug">
                          {t("dashboard.badge.contact_summary")
                            .replace("{count}", String(countLeadsWithoutContact(filteredLeads)))
                            .replace("{total}", String(filteredLeads.length))}
                        </span>
                      </div>
                    )}
                    {filteredLeads.map((lead) => {
                      const cat = catOfLead(lead);
                      const CatIcon = cat.icon;
                      const vis = lead.visibility_status || (lead.status === "reserved" ? "reserved_by_other" : "available");
                      const reservedUntil = lead.reserved_by_me?.expires_at || lead.reserved_by_other?.expires_at;
                      const isMine = vis === "reserved_by_me";
                      return (
                        <div
                          key={lead.id}
                          data-testid="lead-card"
                          data-lead-id={lead.id}
                          role="button"
                          tabIndex={0}
                          aria-label={`${lead.address}, ${lead.city}`}
                          onClick={() => openLeadDetail(lead)}
                          onKeyDown={(e) => {
                            // Só quando o foco está no próprio cartão: Enter num
                            // botão/anchor filho não pode abrir o detalhe.
                            if (e.target !== e.currentTarget) return;
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              openLeadDetail(lead);
                            }
                          }}
                          className={`px-5 py-4 cursor-pointer transition ${T.navHover} group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/70 focus-visible:ring-inset ${vis === "reserved_by_other" ? "opacity-60" : ""}`}
                        >
                          <div className="flex items-center gap-2 mb-2 flex-wrap">
                            <span
                              className="text-[10px] font-semibold uppercase tracking-wider flex items-center gap-1.5 px-2.5 py-1 rounded-full"
                              style={{ backgroundColor: `${cat.color}1a`, color: cat.color }}
                            >
                              <CatIcon className="h-3 w-3" /> {t(cat.labelKey)}
                            </span>

                            {(lead.signal_type && (() => {
                              const st = lead.signal_type;
                              if (st === "legal_obligation") return <span className="text-[10px] font-semibold uppercase tracking-wider bg-amber-500/15 text-amber-400 px-2.5 py-1 rounded-full flex items-center gap-1"><AlertTriangle className="h-3 w-3" /> {t("dashboard.lead_type.obligation")}</span>;
                              if (st === "authorized_work") return <span className="text-[10px] font-semibold uppercase tracking-wider bg-sky-500/15 text-sky-400 px-2.5 py-1 rounded-full flex items-center gap-1"><HardHat className="h-3 w-3" /> {t("dashboard.lead_type.permit")}</span>;
                              return <span className={`text-[10px] font-semibold uppercase tracking-wider px-2.5 py-1 rounded-full flex items-center gap-1 ${isDark ? "bg-slate-500/15 text-slate-400" : "bg-slate-100 text-slate-600"}`}><FolderOpen className="h-3 w-3" /> {t("dashboard.lead_type.open")}</span>;
                            })())}

                            {lead.phone_confidence === "verified" && (
                              <span className="text-[10px] font-semibold uppercase tracking-wider bg-emerald-500/15 text-emerald-400 px-2.5 py-1 rounded-full flex items-center gap-1">
                                <Phone className="h-3 w-3" /> {t("dashboard.phone.verified")}
                              </span>
                            )}
                            {lead.phone_confidence === "high" && (
                              <span
                                className="text-[10px] font-semibold uppercase tracking-wider bg-sky-500/15 text-sky-400 px-2.5 py-1 rounded-full flex items-center gap-1"
                                title={
                                  lead.phone_success_pct != null
                                    ? t("dashboard.phone.pct_hint").replace(
                                        "{n}",
                                        String(lead.phone_sample_size ?? 0)
                                      )
                                    : undefined
                                }
                              >
                                <Phone className="h-3 w-3" /> {t("dashboard.phone.high")}
                                {lead.phone_success_pct != null && (
                                  <span className="font-bold"> · {lead.phone_success_pct}%</span>
                                )}
                              </span>
                            )}

                            {(lead.signal_status === "closed" || isClosedCase(lead.case_status)) && (
                              <span
                                className={`text-[10px] font-semibold uppercase tracking-wider px-2.5 py-1 rounded-full flex items-center gap-1 ${
                                  isDark
                                    ? "bg-slate-500/20 text-slate-300"
                                    : "bg-slate-200 text-slate-600"
                                }`}
                                title={t("dashboard.badge.closed_hint")}
                              >
                                <Archive className="h-3 w-3" /> {t("dashboard.badge.closed")}
                              </span>
                            )}

                            {lead.institutional ? (
                              <span
                                className="text-[10px] font-semibold uppercase bg-cyan-500/15 text-cyan-400 px-2.5 py-1 rounded-full flex items-center gap-1"
                                title={t("dashboard.badge.institutional_hint")}
                              >
                                <Landmark className="h-3 w-3" /> {t("dashboard.badge.institutional")} · {t("dashboard.badge.institutional_channel")}
                              </span>
                            ) : isCorporateLead(lead) ? (
                              <span className="text-[10px] font-semibold uppercase bg-purple-500/15 text-purple-400 px-2.5 py-1 rounded-full flex items-center gap-1">
                                <Building2 className="h-3 w-3" /> {t("dashboard.badge.private_corporate")}
                              </span>
                            ) : lead.owner_name && (
                              <span className="text-[10px] font-semibold uppercase bg-emerald-500/15 text-emerald-400 px-2.5 py-1 rounded-full flex items-center gap-1">
                                <CheckCircle2 className="h-3 w-3" /> {t("dashboard.badge.private_person")}
                              </span>
                            )}

{vis === "available" && (
                                <>
                                  <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-500/15 text-emerald-400 px-2.5 py-1 rounded-full flex items-center gap-1">
                                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" /> {t("dashboard.status.available")}
                                  </span>
                                  {lead.owner_name && !lead.owner_phone && (
                                    <button
                                      onClick={(e) => { e.stopPropagation(); revealPhoneForLead(lead); }}
                                      disabled={busyAction || phoneRevealing?.loading || phoneRevealing?.leadId === lead.id}
                                      className="flex items-center gap-1.5 text-[11px] font-bold border border-violet-500/40 text-violet-400 hover:bg-violet-500/10 px-3 py-1.5 rounded-lg transition disabled:opacity-50"
                                    >
                                      <Smartphone className="h-3 w-3" /> {t("dashboard.action.reveal_phone") || "Revelar Telefone"}
                                    </button>
                                  )}
                                  {shouldShowAddressWarning(lead) && (
                                    <span className="text-[10px] text-amber-500/90 flex items-center gap-1">
                                      <AlertTriangle className="h-3 w-3" /> {t("dashboard.badge.address_unresolvable")}
                                    </span>
                                  )}
                                </>
                              )}
                            {isMine && (
                              <>
                                <span className="text-[10px] font-bold uppercase tracking-wider bg-rose-500/15 text-rose-400 px-2.5 py-1 rounded-full flex items-center gap-1">
                                  <Lock className="h-3 w-3" /> {t("dashboard.badge.yours").replace("{time}", reservedUntil ? countdownLabel(reservedUntil) : HOLD_FALLBACK)}
                                </span>
                                <StageBadge stage={lead.stage} stageExpiresAt={lead.stage_expires_at} serverNow={lead.server_now} />
                                <div className="flex items-center gap-2 mt-2 flex-wrap">
                                  {lead.owner_phone && (
                                    <a
                                      href={waHref(lead.owner_phone, buildMsgs(lead))}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        recordContact(lead.id, "whatsapp").catch(() => {});
                                      }}
                                      className="flex items-center gap-1.5 text-[11px] font-semibold bg-emerald-500/15 text-emerald-400 px-3 py-1.5 rounded-lg hover:bg-emerald-500/25 transition"
                                    >
                                      <MessageSquare className="h-3.5 w-3.5" /> {t("dashboard.detail.whatsapp")}
                                    </a>
                                  )}
                                  {lead.owner_phone && (
                                    <a
                                      href={smsHref(lead.owner_phone, buildMsgs(lead))}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        recordContact(lead.id, "sms").catch(() => {});
                                      }}
                                      className="flex items-center gap-1.5 text-[11px] font-semibold bg-green-500/15 text-green-400 px-3 py-1.5 rounded-lg hover:bg-green-500/25 transition"
                                    >
                                      <MessageSquare className="h-3.5 w-3.5" /> {t("dashboard.detail.sms")}
                                    </a>
                                  )}
                                  {lead.owner_email && (
                                    <a
                                      href={`mailto:${lead.owner_email}?subject=${encodeURIComponent(buildMsgs(lead).emailSubject)}&body=${encodeURIComponent(buildMsgs(lead).emailBody)}`}
                                      onClick={(e) => e.stopPropagation()}
                                      className="flex items-center gap-1.5 text-[11px] font-semibold bg-blue-500/15 text-blue-400 px-3 py-1.5 rounded-lg hover:bg-blue-500/25 transition"
                                    >
                                      <Mail className="h-3.5 w-3.5" /> {t("dashboard.detail.email")}
                                    </a>
                                  )}
                                  <button
                                    onClick={(e) => { e.stopPropagation(); openMaps(lead.address); }}
                                    className={`flex items-center gap-1.5 text-[11px] font-semibold px-3 py-1.5 rounded-lg transition ${T.ghost}`}
                                  >
                                    <Navigation className="h-3.5 w-3.5" /> {t("dashboard.action.map")}
                                  </button>
                                  <button
                                    onClick={(e) => { e.stopPropagation(); copyToClipboard(lead.owner_phone || '', 'phone'); }}
                                    className={`flex items-center gap-1.5 text-[11px] font-semibold px-3 py-1.5 rounded-lg transition ${T.ghost}`}
                                  >
                                    <Copy className="h-3.5 w-3.5" /> {t("dashboard.detail.copy_phone")}
                                  </button>
                                </div>
                              </>
                            )}

                            <span className={`ml-auto text-xs flex items-center gap-1 font-medium capitalize ${T.text2}`}>
                              <MapPin className="h-3.5 w-3.5" /> {lead.city}
                            </span>
                          </div>

                          <div className="flex items-start justify-between gap-3">
                            <div className="flex-1 min-w-0">
                              <h3 className="font-semibold text-base leading-snug">{lead.address}</h3>
                              <p className={`text-xs mt-1 line-clamp-2 ${T.text2}`}>
                                {lead.issue_description || lead.case_title || t("dashboard.feed.address_fallback")}
                              </p>
                              {((lead.repeat_365 ?? 0) > 1 || (lead.oldest_open_days ?? 0) > 0) && (
                                <div className={`flex items-center gap-2 text-[11px] mt-1 ${T.text2} flex-wrap`}>
                                  {(lead.repeat_365 ?? 0) > 1 && (
                                    <span>
                                      {t("dashboard.why.repeat").replace("{count}", String(lead.repeat_365))}
                                    </span>
                                  )}
                                  {(lead.oldest_open_days ?? 0) > 0 && (
                                    <span>
                                      {t("dashboard.why.open").replace("{days}", String(lead.oldest_open_days))}
                                    </span>
                                  )}
                                </div>
                              )}
                              <div className={`flex items-center gap-3 text-[11px] mt-2 flex-wrap ${T.text2}`}>
                                {lead.owner_name && (
                                  <>
                                    <span className={`font-medium ${T.text}`}>
                                      {t("dashboard.field.owner")}: {lead.owner_name}
                                    </span>
                                    {lead.mailing_address && (
                                      <span className={T.text2}>📬 {lead.mailing_address}</span>
                                    )}
                                  </>
                                )}
                                <span>·</span>
                                <span>{t("dashboard.freshness.reported")}: {formatRelativeTime(lead.date_reported, t)}</span>
                                {lead.last_synced && (
                                  <>
                                    <span>·</span>
                                    <span>{t("dashboard.freshness.synced")}: {formatRelativeTime(lead.last_synced, t)}</span>
                                  </>
                                )}
                              </div>

                              {vis === "available" && (
                                <div className="flex items-center gap-2 mt-3 flex-wrap">
                                  <button
                                    onClick={(e) => { e.stopPropagation(); handleQuickReserve(lead); }}
                                    disabled={busyAction || (subscription && !subscription.can_access) || isBlockedByQuota(lead, dailyStats?.remaining)}
                                    className={`flex items-center gap-1.5 text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2.5 rounded-xl transition shadow-md shadow-indigo-600/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:opacity-50 ${
                                      (subscription && !subscription.can_access) || isBlockedByQuota(lead, dailyStats?.remaining) ? "opacity-30 cursor-not-allowed" : ""
                                    }`}
                                  >
                                    <Lock className="h-3.5 w-3.5" /> {isFreeLead(lead) ? t("dashboard.action.reserve_corporate") : t("dashboard.action.reserve_1h")}
                                  </button>
                                  <span className={`text-[10px] flex items-center gap-1 ${T.text2}`}>
                                    <ShieldCheck className="h-3 w-3" /> {t("dashboard.data_protected")}
                                  </span>
                                  {shouldShowAddressWarning(lead) && (
                                    <span className="text-[10px] text-amber-500/90 flex items-center gap-1">
                                      <AlertTriangle className="h-3 w-3" /> {t("dashboard.badge.address_unresolvable")}
                                    </span>
                                  )}
                                </div>
                              )}
                              {isMine && (
                                <>
                                <div className="flex items-center gap-2 mt-3 flex-wrap">
                                  <span className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider bg-emerald-500/15 text-emerald-400 px-2.5 py-1 rounded-full">
                                    <BadgeCheck className="h-3 w-3" /> {t("dashboard.action.revealed")}
                                  </span>
                                  {/* Reveal Phone button - for my leads with owner_name but no owner_phone */}
                                  {lead.owner_name && !lead.owner_phone && (
                                    <button
                                      onClick={(e) => { e.stopPropagation(); revealPhoneForLead(lead); }}
                                      disabled={busyAction || phoneRevealing?.loading || phoneRevealing?.leadId === lead.id}
                                      className="flex items-center gap-1.5 text-[11px] font-bold border border-violet-500/40 text-violet-400 hover:bg-violet-500/10 px-3 py-1.5 rounded-lg transition disabled:opacity-50"
                                    >
                                      <Smartphone className="h-3 w-3" /> {t("dashboard.action.reveal_phone") || "Revelar Telefone"}
                                    </button>
                                  )}
                                  <button
                                    onClick={(e) => { e.stopPropagation(); openMaps(lead.address); }}
                                    className={`flex items-center gap-1.5 text-[11px] font-semibold px-3 py-1.5 rounded-lg transition ${T.ghost}`}
                                  >
                                    <Navigation className="h-3 w-3" /> {t("dashboard.action.map")}
                                  </button>
                                  {lead.owner_phone && (
                                    <a
                                      href={waHref(lead.owner_phone, buildMsgs(lead))}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        recordContact(lead.id, "whatsapp").catch(() => {});
                                      }}
                                      className="flex items-center gap-1.5 text-[11px] font-semibold bg-emerald-500/15 text-emerald-400 px-3 py-1.5 rounded-lg hover:bg-emerald-500/25 transition"
                                    >
                                      {t("dashboard.detail.whatsapp")}
                                    </a>
                                  )}
                                  {lead.owner_phone && (
                                    <a
                                      href={smsHref(lead.owner_phone, buildMsgs(lead))}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        recordContact(lead.id, "sms").catch(() => {});
                                      }}
                                      className="flex items-center gap-1.5 text-[11px] font-semibold bg-green-500/15 text-green-400 px-3 py-1.5 rounded-lg hover:bg-green-500/25 transition"
                                    >
                                      <MessageSquare className="h-3 w-3" /> {t("dashboard.detail.sms")}
                                    </a>
                                  )}
                                  <button
                                    onClick={(e) => { e.stopPropagation(); openReleaseModal(lead); }}
                                    disabled={busyAction}
                                    className={`flex items-center gap-1.5 text-[11px] font-semibold ${T.ghostDanger} px-3 py-1.5 rounded-lg transition disabled:opacity-50`}
                                  >
<RefreshCcw className="h-3 w-3" /> {t("dashboard.action.drop")}
                                  </button>
                                </div>
                                {/* Embedded map + navigation buttons */}
                                {lead.address && (
                                  <div className="mt-3">
                                    <LeadLocationMap
                                      address={lead.address}
                                      city={lead.city}
                                      compact
                                      isDark={isDark}
                                      mapLabel={t("dashboard.action.map") || "Mapa"}
                                      googleLabel={t("dashboard.map.google") || "Google Maps"}
                                      appleLabel={t("dashboard.map.apple") || "Apple Maps"}
                                    />
                                  </div>
                                )}
                                </>
                              )}
                            </div>

                            <div className="flex flex-col items-end gap-2 shrink-0">
                              <button
                                onClick={(e) => handleToggleFav(lead, e)}
                                className={`p-2 rounded-xl border ${T.border} transition ${
                                  lead.favorited ? "text-amber-400 bg-amber-400/10 border-amber-400/20" : `${T.text2} hover:text-amber-400`
                                }`}
                                title={t("dashboard.fav.title")}
                              >
                                <Star className={`h-4 w-4 ${lead.favorited ? "fill-amber-400" : ""}`} />
                              </button>
                              <span className="flex items-center gap-1 text-xs font-semibold text-indigo-400 group-hover:translate-x-0.5 transition">
                                Ver análise <ArrowUpRight className="h-3.5 w-3.5" />
                              </span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                    {hasMoreLeads && (
                      <div className={`px-5 py-4 border-t ${T.divider}`}>
                        <button
                          onClick={loadMoreLeads}
                          disabled={loadingMore}
                          className={`w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl border text-sm font-medium transition disabled:opacity-50 ${T.border} ${T.text} ${T.navHover}`}
                        >
                          {loadingMore ? (
                            <>
                              <Loader2 className="h-4 w-4 animate-spin" />
                              Carregando...
                            </>
                          ) : (
                            <>
                              <ArrowUpRight className="h-4 w-4" />
                              {t("dashboard.feed.load_more") || "Carregar mais oportunidades"}
                            </>
                          )}
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            </section>
          </div>
          </>
          )}
        </main>
      </div>

      {/* LEAD DETAIL MODAL */}
      {selectedLead && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={() => setSelectedLead(null)}>
          <div
            ref={detailDialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="lead-detail-title"
            tabIndex={-1}
            className={`relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border p-6 shadow-2xl space-y-6 animate-scale-in outline-none ${
              isDark ? "bg-[#14161d] border-white/10 text-slate-100" : "bg-white border-slate-200 text-slate-900"
            }`}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className={`flex items-start justify-between gap-3 border-b pb-4 ${T.border}`}>
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-indigo-500/20 text-indigo-400">
                    {selectedLead.issue_category}
                  </span>
                  <span className={`text-xs font-medium ${T.text2}`}>
                    {selectedLead.city}
                  </span>
                </div>
                <h2 id="lead-detail-title" className="text-xl font-bold mt-1.5">{selectedLead.address}</h2>
              </div>
              <button
                onClick={() => setSelectedLead(null)}
                aria-label={t("dashboard.filter.close") || "Fechar"}
                className={`p-1.5 rounded-lg transition ${isDark ? "text-slate-400 hover:text-white hover:bg-white/10" : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"}`}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Painel sticky do ciclo de vida (fases 1h/48h/48h) */}
            {selectedLead.stage && selectedLead.visibility_status === "reserved_by_me" && (
              <StageGuidePanel
                stage={selectedLead.stage}
                stageExpiresAt={selectedLead.stage_expires_at}
                serverNow={selectedLead.server_now}
                isDark={isDark}
              />
            )}

            {/* Owner Connection Info */}
            <div className={`p-4 rounded-xl border ${isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"} space-y-3`}>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                {t("dashboard.detail.direct")}
              </h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                <div>
                  <span className="text-xs text-slate-400 block">{t("dashboard.field.owner")}</span>
                  <span className="font-semibold">{selectedLead.owner_name || t("dashboard.detail.no_data")}</span>
                </div>
                <div>
                  <span className="text-xs text-slate-400 block">{t("dashboard.field.phone")}</span>
                  <span className="font-mono font-semibold">{selectedLead.owner_phone || t("dashboard.detail.no_phone")}</span>
                </div>
                <div>
                  <span className="text-xs text-slate-400 block">{t("dashboard.field.email")}</span>
                  <span className="font-semibold truncate">{selectedLead.owner_email || t("dashboard.detail.no_data")}</span>
                </div>
                <div>
                  <span className="text-xs text-slate-400 block">{t("db.col.date")}</span>
                  <span className="font-semibold" suppressHydrationWarning>
                    {selectedLead.date_reported ? new Date(selectedLead.date_reported).toLocaleDateString(lang === "en" ? "en-US" : lang === "es" ? "es-ES" : "pt-BR") : "—"}
                  </span>
                </div>
                {selectedLead.last_synced && (
                  <div>
                    <span className="text-xs text-slate-400 block">{t("dashboard.freshness.synced")}</span>
                    <span className="font-semibold" suppressHydrationWarning>
                      {new Date(selectedLead.last_synced).toLocaleDateString(lang === "en" ? "en-US" : lang === "es" ? "es-ES" : "pt-BR")}
                    </span>
                  </div>
                )}
                {selectedLead.mailing_address && (
                  <div className="sm:col-span-2">
                    <span className="text-xs text-slate-400 block">{t("dashboard.field.mailing_address")}</span>
                    <span className="font-semibold">📬 {selectedLead.mailing_address}</span>
                  </div>
                )}
              </div>

              {/* Action Contact Links */}
              {modalActionButtons}

              {/* Embedded map + navigation buttons */}
              {selectedLead.address && (
                <div className="pt-1">
                  <LeadLocationMap
                    address={selectedLead.address}
                    city={selectedLead.city}
                    isDark={isDark}
                    mapLabel={t("dashboard.action.map") || "Mapa"}
                    googleLabel={t("dashboard.map.google") || "Google Maps"}
                    appleLabel={t("dashboard.map.apple") || "Apple Maps"}
                  />
                </div>
              )}
            </div>

            {/* Description & Case Info */}
            <div className="space-y-2.5">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                {t("dashboard.detail.data")}
              </h4>

              {/* Motivo de abertura (descriptor > subject > reason > case_title) */}
              {(() => {
                const motivo =
                  selectedLead.descriptor ||
                  selectedLead.subject ||
                  selectedLead.reason ||
                  selectedLead.case_title;
                if (!motivo) return null;
                return (
                  <div className="text-sm leading-relaxed text-slate-300">
                    <span className="font-semibold text-slate-400">Motivo de abertura:</span>{" "}
                    {motivo}
                    {selectedLead.case_title && motivo !== selectedLead.case_title && (
                      <span className="text-slate-500"> ({selectedLead.case_title})</span>
                    )}
                  </div>
                );
              })()}

              <p className="text-sm leading-relaxed text-slate-300">
                {selectedLead.issue_description || selectedLead.case_title || "Registro oficial de manutenção pública."}
              </p>

              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
                {selectedLead.department && (
                  <span>
                    <Building2 className="h-3.5 w-3.5 inline mr-1" />
                    {selectedLead.department}
                  </span>
                )}
                {selectedLead.case_status && (
                  <span>
                    <Tag className="h-3.5 w-3.5 inline mr-1" />
                    Status: {selectedLead.case_status}
                  </span>
                )}
              </div>

              {selectedLead.date_reported && (
                <div className="text-xs text-slate-400">
                  <Clock className="h-3.5 w-3.5 inline mr-1" />
                  {t("dashboard.freshness.reported")}: {formatRelativeTime(selectedLead.date_reported, t)}
                </div>
              )}
              {selectedLead.last_synced && (
                <div className="text-xs text-slate-400">
                  <Clock className="h-3.5 w-3.5 inline mr-1" />
                  {t("dashboard.freshness.synced")}: {formatRelativeTime(selectedLead.last_synced, t)}
                </div>
              )}
              {selectedLead.sla_target_dt && (
                <div className="text-xs text-amber-300/90">
                  <Clock className="h-3.5 w-3.5 inline mr-1" />
                  SLA: {formatRelativeTime(selectedLead.sla_target_dt, t)}
                </div>
              )}
              {selectedLead.closed_dt && (
                <div className="text-xs text-slate-400">
                  <BadgeCheck className="h-3.5 w-3.5 inline mr-1" />
                  {t("dashboard.reveal.closed_on")} {formatRelativeTime(selectedLead.closed_dt, t)}
                </div>
              )}
              {(selectedLead.resolution_description || selectedLead.closure_reason) && (
                <div className="text-xs leading-relaxed text-emerald-300/90">
                  <BadgeCheck className="h-3.5 w-3.5 inline mr-1" />
                  {t("dashboard.field.resolution")}: {selectedLead.resolution_description || selectedLead.closure_reason}
                </div>
              )}
            </div>

            {/* Historical Events */}
            {leadHistory.length > 0 && (
              <div className={`space-y-3 pt-2 border-t ${T.border}`}>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <Clock className="h-3.5 w-3.5" />
                  {t("dashboard.detail.history")}
                </h4>
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {leadHistory.map((event) => (
                    <div key={event.id} className={`p-3 rounded-xl border ${T.subtle} flex items-start gap-3`}>
                      <div className="h-8 w-8 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center shrink-0">
                        <Clock className="h-4 w-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-slate-300">{event.detail || event.event_type}</p>
                        <div className="flex items-center gap-2 text-[10px] text-slate-500 mt-1">
                          <span>{formatRelativeTime(event.created_at, t)}</span>
{event.user_id && <span>· {t("dashboard.reveal.by_user")} #{event.user_id}</span>}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Ocorrências do imóvel (histórico 311 - Parte B) */}
            {leadOccurrences.length > 0 && (
              <div className={`space-y-3 pt-2 border-t ${T.border}`}>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <Building2 className="h-3.5 w-3.5" />
                  {t("dashboard.reveal.section_prop_history")}
                </h4>
                <div className="space-y-2 max-h-60 overflow-y-auto">
                  {leadOccurrences.map((oc) => (
                    <div key={oc.id || oc.external_id || `${oc.case_title}-${oc.opened_at}`} className={`p-3 rounded-xl border ${T.subtle}`}>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-semibold text-slate-200">{oc.case_title || "Ocorrência"}</span>
                        {oc.case_status && (
                          <span
                            className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${
                              oc.case_status.toLowerCase() === "closed"
                                ? "bg-emerald-500/15 text-emerald-400"
                                : oc.case_status.toLowerCase() === "open"
                                  ? "bg-rose-500/15 text-rose-400"
                                  : "bg-amber-500/15 text-amber-400"
                            }`}
                          >
                            {oc.case_status}
                          </span>
                        )}
                        {oc.opened_at && (
                          <span className="ml-auto text-[10px] text-slate-500">{formatRelativeTime(oc.opened_at, t)}</span>
                        )}
                      </div>
                      {oc.descriptor && <p className="text-sm text-slate-300 mt-1">{oc.descriptor}</p>}
                      {oc.department && <div className="text-[11px] text-slate-500 mt-0.5">{oc.department}</div>}
                      {(oc.resolution_description || oc.closure_reason) && (
                        <div className="text-[11px] text-emerald-300/90 mt-1">
                          {t("dashboard.field.resolution")}: {oc.resolution_description || oc.closure_reason}
                        </div>
                      )}
                      {oc.closed_at && (
                        <div className="text-[11px] text-slate-500 mt-1">{t("dashboard.reveal.closed_on")} {formatRelativeTime(oc.closed_at, t)}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Pipeline Actions */}
            <div className={`space-y-3 pt-2 border-t ${T.border}`}>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                {t("dashboard.detail.routing")}
              </h4>
              <div className="flex flex-wrap gap-2">
                {!leadAlreadyMine(selectedLead) && (
                  <button
                    onClick={() => handleQuickReserve(selectedLead)}
                    disabled={busyAction || (subscription && !subscription.can_access) || (!isFreeLead(selectedLead) && dailyStats?.remaining === 0)}
                    className={`flex items-center gap-1.5 text-xs font-bold bg-indigo-500 hover:bg-indigo-400 text-white px-3.5 py-2 rounded-xl transition shadow-sm disabled:opacity-50 ${
                      (subscription && !subscription.can_access) || isBlockedByQuota(selectedLead, dailyStats?.remaining) ? "opacity-30 cursor-not-allowed" : ""
                    }`}
                  >
                    <Lock className="h-3.5 w-3.5" /> {isFreeLead(selectedLead) ? t("dashboard.action.reserve_corporate") : t("dashboard.action.reserve_1h")}
                  </button>
                )}
                <button
                  onClick={() => handleLeadAction(() => contactLead(selectedLead.id, "sms"), t("dashboard.action.contact_ok"))}
                  disabled={busyAction}
                  className="flex items-center gap-1.5 text-xs font-bold bg-sky-500 hover:bg-sky-400 text-white px-3.5 py-2 rounded-xl transition shadow-sm disabled:opacity-50"
                >
                  <Phone className="h-3.5 w-3.5" /> {t("dashboard.action.contact")}
                </button>
                <button
                  onClick={() => handleLeadAction(() => negotiateLead(selectedLead.id), t("dashboard.action.negotiate_ok"))}
                  disabled={busyAction}
                  className="flex items-center gap-1.5 text-xs font-bold bg-amber-500 hover:bg-amber-400 text-white px-3.5 py-2 rounded-xl transition shadow-sm disabled:opacity-50"
                >
                  <MessageSquare className="h-3.5 w-3.5" /> {t("dashboard.action.negotiate")}
                </button>
                <button
                  onClick={() => handleLeadAction(() => convertLead(selectedLead.id), t("dashboard.action.convert_ok"))}
                  disabled={busyAction}
                  className="flex items-center gap-1.5 text-xs font-bold bg-emerald-500 hover:bg-emerald-400 text-slate-950 px-3.5 py-2 rounded-xl transition shadow-sm disabled:opacity-50"
                >
                  <BadgeCheck className="h-3.5 w-3.5" /> {t("dashboard.action.convert")}
                </button>
                <button
                  onClick={() => openReleaseModal(selectedLead)}
                  disabled={busyAction}
                  className={`flex items-center gap-1.5 text-xs font-semibold ${T.ghostDanger} px-3 py-2 rounded-xl transition`}
                >
                  <RefreshCcw className="h-3.5 w-3.5" /> {t("dashboard.action.release")}
                </button>
              </div>
              {actionSuccess && (
                <p className="text-xs font-semibold text-emerald-400 mt-1">{actionSuccess}</p>
              )}
            </div>

            {/* Internal Notes Section */}
            <div className={`space-y-3 pt-2 border-t ${T.border}`}>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                {t("dashboard.detail.notes")}
              </h4>
              <div className="flex gap-2">
                <input
                  value={noteDraft}
                  onChange={(e) => setNoteDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleAddNote(); }}
                  placeholder={t("dashboard.detail.note_placeholder")}
                  className={`flex-1 text-sm rounded-xl px-3 py-2 border outline-none ${T.border} ${isDark ? "bg-white/5 text-slate-200" : "bg-slate-100 text-slate-800"}`}
                />
                <button
                  onClick={handleAddNote}
                  disabled={!noteDraft.trim()}
                  className={`px-4 py-2 rounded-xl text-xs font-bold transition disabled:cursor-not-allowed ${
                    noteDraft.trim()
                      ? "bg-indigo-500 text-white hover:bg-indigo-400"
                      : isDark
                        ? "bg-white/10 text-slate-400"
                        : "bg-slate-200 text-slate-600"
                  }`}
                >
                  {t("dashboard.detail.save")}
                </button>
              </div>

              <div className="space-y-2 max-h-44 overflow-y-auto">
                {leadNotes.length === 0 ? (
                  <p className="text-xs text-slate-500 py-2">{t("dashboard.detail.no_notes")}</p>
                ) : (
                  leadNotes.map((n) => (
                    <div key={n.id} className={`p-3 rounded-xl border ${T.subtle} flex items-start justify-between gap-2`}>
                      <div>
                        <p className="text-xs text-slate-300">{n.note}</p>
                        <span className="text-[10px] text-slate-500 mt-1 block">
                          {formatRelativeTime(n.created_at, t)}
                        </span>
                      </div>
                      <button
                        onClick={() => handleDeleteNote(n.id)}
                        className="text-slate-500 hover:text-rose-400 p-1"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
</div>
                   ))
                 )}
               </div>
             </div>
           </div>
         </div>
       )}

      {/* RELEASE MODAL (Phase 4.2) */}
<ReleaseModal
         open={!!releaseTarget}
         lead={releaseTarget}
         busy={busyAction}
         isDark={isDark}
         suspiciousCount={contractorMetrics?.suspicious_releases || 0}
         onClose={closeReleaseModal}
         onRelease={confirmRelease}
       />

       {/* CICLO DE VIDA — guia automático após reservar (fases 1h/48h/48h) */}
       {guideLead && (
         <ReserveGuideModal lead={guideLead} isDark={isDark} onClose={closeGuide} />
       )}

      {/* REVEAL CONSENT MODAL (dados do proprietário protegidos) */}
      {revealTarget && (
        <div
          className="fixed inset-0 z-[85] flex items-center justify-center p-4"
          style={{ backgroundColor: isDark ? "rgba(11,13,18,0.85)" : "rgba(248,250,252,0.9)" }}
          onClick={closeRevealModal}
          onKeyDown={(e) => {
            if (e.key === "Escape") closeRevealModal();
          }}
        >
          <div
            ref={revealDialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="reveal-modal-title"
            tabIndex={-1}
            className={`w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl border p-6 shadow-2xl outline-none ${isDark ? "bg-[#10121a] border-white/10" : "bg-white border-slate-200"}`}
            onClick={(e) => e.stopPropagation()}
          >
            {/* HEADER */}
            <div className="flex items-start gap-3">
              <div className="h-11 w-11 rounded-xl bg-indigo-500/20 flex items-center justify-center shrink-0">
                <ShieldCheck className="h-6 w-6 text-indigo-400" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <h2 id="reveal-modal-title" className="text-lg font-bold" style={{ color: isDark ? "#fff" : "#0f172a" }}>
                    {t("dashboard.reveal.title")}
                  </h2>
                    {(() => {
                      const isObligation = revealTarget.signal_type === "legal_obligation";
                      const isPermit = revealTarget.signal_type === "authorized_work";
                      return (
                        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${isObligation ? "bg-amber-500/15 text-amber-400" : isPermit ? "bg-sky-500/15 text-sky-400" : isDark ? "bg-slate-500/15 text-slate-400" : "bg-slate-100 text-slate-600"}`}>
                          {isObligation ? t("dashboard.lead_type.obligation") : isPermit ? t("dashboard.lead_type.permit") : t("dashboard.lead_type.open")}
                        </span>
                      );
                    })()}
                </div>
                <p className={`text-sm ${T.text2}`}>
                  {t("dashboard.reveal.authorize_prefix")} <span className="font-semibold">{t("dashboard.reveal.authorize_hours")}</span>{t("dashboard.reveal.authorize_suffix")}
                </p>
              </div>
            </div>

            {/* ENDEREÇO + CATEGORIA */}
            <div className={`mt-4 p-3 rounded-xl border ${T.subtle}`}>
              <p className={`text-xs font-semibold ${T.text2}`}>
                {buildFullAddress(revealTarget.address, revealTarget.city)}
              </p>
              <p className={`text-xs mt-0.5 ${T.text2}`}>
                {revealTarget.issue_category || revealTarget.issue_description}
              </p>
            </div>

            {/* SECTION 1: Detalhes da Ocorrência */}
            {(revealTarget.department || revealTarget.case_status || revealTarget.descriptor || revealTarget.neighborhood || revealTarget.ward || revealTarget.precinct) && (
              <div className="mt-4 space-y-1.5">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <Building2 className="h-3.5 w-3.5" />
                  {t("dashboard.reveal.section_occ")}
                </h4>
                <div className="rounded-lg border bg-muted/40 p-3 space-y-1.5 text-sm">
                  {revealTarget.department && (
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">{t("dashboard.field.department")}</span>
                      <span className="font-medium truncate">{revealTarget.department}</span>
                    </div>
                  )}
                  {revealTarget.case_status && (
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">{t("dashboard.field.case_status")}</span>
                      <span className="font-medium truncate">{revealTarget.case_status}</span>
                    </div>
                  )}
                  {revealTarget.descriptor && (
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">{t("dashboard.field.descriptor")}</span>
                      <span className="font-medium truncate">{revealTarget.descriptor}</span>
                    </div>
                  )}
                  {(revealTarget.neighborhood || revealTarget.ward || revealTarget.precinct) && (
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">{t("dashboard.reveal.location")}</span>
                      <span className="font-medium truncate">
                        {[revealTarget.neighborhood, revealTarget.ward && revealTarget.ward.replace(/^\d+\s*/, ""), revealTarget.precinct && revealTarget.precinct.replace("Precinct ", "Pct ")]
                          .filter(Boolean)
                          .join(", ") || "—"
                      }
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* SECTION 2: Detalhes do Chamado */}
            {(revealTarget.case_title || revealTarget.subject || revealTarget.reason || revealTarget.type || revealTarget.queue || revealTarget.closure_reason || revealTarget.resolution_description || revealTarget.sla_target_dt || revealTarget.closed_dt) && (
              <div className="mt-4 space-y-1.5">
<h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <FolderOpen className="h-3.5 w-3.5" />
                  {t("dashboard.reveal.section_case")}
                </h4>
                <div className="rounded-lg border bg-muted/40 p-3 space-y-1.5 text-sm">
                  {revealTarget.case_title && (
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-muted-foreground shrink-0">{t("dashboard.field.subject")}</span>
                      <span className="font-medium truncate">{revealTarget.case_title}</span>
                    </div>
                  )}
                  {revealTarget.subject && (
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-muted-foreground shrink-0">{t("dashboard.field.subject")}</span>
                      <span className="font-medium truncate">{revealTarget.subject}</span>
                    </div>
                  )}
                  {revealTarget.reason && (
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-muted-foreground shrink-0">{t("dashboard.field.reason")}</span>
                      <span className="font-medium truncate">{revealTarget.reason}</span>
                    </div>
                  )}
                  {revealTarget.type && (
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">{t("dashboard.field.type")}</span>
                      <span className="font-medium truncate">{revealTarget.type}</span>
                    </div>
                  )}
                  {revealTarget.queue && (
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">{t("dashboard.field.queue")}</span>
                      <span className="font-medium truncate">{revealTarget.queue}</span>
                    </div>
                  )}
                  {(revealTarget.resolution_description || revealTarget.closure_reason) && (
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-muted-foreground shrink-0">{t("dashboard.field.resolution")}</span>
                      <span className="font-medium truncate text-emerald-300/90">{revealTarget.resolution_description || revealTarget.closure_reason}</span>
                    </div>
                  )}
                  {revealTarget.sla_target_dt && (
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">SLA</span>
                      <span className="font-medium truncate text-amber-300/90">{formatRelativeTime(revealTarget.sla_target_dt, t)}</span>
                    </div>
                  )}
                  {revealTarget.closed_dt && (
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">{t("dashboard.reveal.closed_on")}</span>
                      <span className="font-medium truncate">{formatRelativeTime(revealTarget.closed_dt, t)}</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* SECTION 3: Histórico do Lead (eventos) */}
            {revealTarget._history && revealTarget._history.length > 0 && (
              <div className="mt-4 space-y-1.5">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <Clock className="h-3.5 w-3.5" />
                  {t("dashboard.reveal.section_lead_history")}
                </h4>
                <div className="rounded-lg border bg-muted/40 p-3 space-y-2 max-h-48 overflow-y-auto">
                  {revealTarget._history.map((event) => (
                    <div key={event.id} className={`p-2 rounded border ${T.subtle}`}>
                      <p className="text-sm text-slate-300">{event.detail || event.event_type}</p>
                      <div className="flex items-center gap-2 text-[10px] text-slate-500 mt-1">
                        <span>{formatRelativeTime(event.created_at, t)}</span>
                        {event.user_id && <span>· {t("dashboard.reveal.by_user")} #{event.user_id}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* SECTION 4: Ocorrências do Imóvel (Parte B) */}
            {revealTarget._occurrences && revealTarget._occurrences.length > 0 && (
              <div className="mt-4 space-y-1.5">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <Building2 className="h-3.5 w-3.5" />
                  {t("dashboard.reveal.section_prop_history")}
                </h4>
                <div className="rounded-lg border bg-muted/40 p-3 space-y-2 max-h-60 overflow-y-auto">
                  {revealTarget._occurrences.map((oc) => (
                    <div key={oc.id || oc.external_id || `${oc.case_title}-${oc.opened_at}`} className={`p-2 rounded border ${T.subtle}`}>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-semibold text-slate-200">{oc.case_title || "Ocorrência"}</span>
                        {oc.case_status && (
                          <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${
                            oc.case_status.toLowerCase() === "closed" ? "bg-emerald-500/15 text-emerald-400"
                            : oc.case_status.toLowerCase() === "open" ? "bg-rose-500/15 text-rose-400"
                            : "bg-amber-500/15 text-amber-400"
                          }`}>
                            {oc.case_status}
                          </span>
                        )}
                        {oc.opened_at && (
                          <span className="ml-auto text-[10px] text-slate-500">{formatRelativeTime(oc.opened_at, t)}</span>
                        )}
                      </div>
                      {oc.descriptor && <p className="text-sm text-slate-300 mt-1">{oc.descriptor}</p>}
                      {oc.department && <div className="text-[11px] text-slate-500 mt-0.5">{oc.department}</div>}
                      {(oc.resolution_description || oc.closure_reason) && (
                        <div className="text-[11px] text-emerald-300/90 mt-1">{t("dashboard.field.resolution")}: {oc.resolution_description || oc.closure_reason}</div>
                      )}
                      {oc.closed_at && (
                        <div className="text-[11px] text-slate-500 mt-1">{t("dashboard.reveal.closed_on")} {formatRelativeTime(oc.closed_at, t)}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* CONSENT CHECKBOX + BOTÕES */}
            <div className="mt-4">
              <div className={`mt-3 rounded-xl border ${T.subtle} p-3`}>
                <label className={`flex items-start gap-2.5 text-sm cursor-pointer ${isDark ? "text-slate-200" : "text-slate-700"}`}>
                  <input
                    type="checkbox"
                    defaultChecked
                    className="mt-0.5 h-4 w-4 accent-indigo-500"
                  />
<span>
                    <span className="font-semibold">{isCorporateLead(revealTarget)
                      ? t("dashboard.reveal.consent_corporate")
                      : t("dashboard.reveal.consent", { used: dailyStats?.used ?? 1, limit: dailyStats?.limit ?? 10 })}</span>
                    <span className={`block text-xs mt-1 ${T.text2}`}>
                      {t("dashboard.reveal.timeout", { title: t("dashboard.opportunities.title") })}
                    </span>
                  </span>
                </label>
              </div>
            </div>

            <div className="mt-5 flex gap-2">
              <button
                onClick={confirmReveal}
                disabled={busyAction || (subscription && !subscription.can_access) || isBlockedByQuota(revealTarget, dailyStats?.remaining)}
                className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-500 hover:bg-indigo-400 text-white text-sm font-bold transition disabled:opacity-50"
              >
                {busyAction ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
                {isCorporateLead(revealTarget) ? t("dashboard.reveal.confirm_corporate") : t("dashboard.reveal.confirm")}
              </button>
              <button
                onClick={closeRevealModal}
                disabled={busyAction}
                className={`px-4 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-50 ${isDark ? "bg-white/10 text-slate-300 hover:bg-white/20" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
              >
                {t("dashboard.detail.close")}
              </button>
            </div>
            {dailyStats && dailyStats.remaining > 0 && dailyStats.remaining <= 2 && (
              <p className="text-[11px] text-amber-400 mt-2 text-center">
                {t("dashboard.reveal.remaining", { remaining: dailyStats.remaining, limit: dailyStats.limit })}
              </p>
            )}
          </div>
        </div>
      )}

      {/* CHECKOUT / PLANS MODAL */}
      <CheckoutModal
        open={showCheckout}
        onClose={() => setShowCheckout(false)}
        onActivated={() => window.location.reload()}
        isDark={isDark}
        mode={subscription?.status === "expired" || subscription?.status === "pending_payment" ? "new" : "reactivate"}
      />
      {/* WELCOME POPUP (First login after payment) */}
      <WelcomePopup
        open={showWelcomePopup}
        onClose={() => setShowWelcomePopup(false)}
        isDark={isDark}
      />
      {/* LOCK SCREEN: período (trial/plano) expirado */}
      {subscription && !subscription.can_access && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center p-4" style={{ backgroundColor: isDark ? "rgba(11,13,18,0.85)" : "rgba(248,250,252,0.9)" }}>
          <div className={`w-full max-w-md rounded-2xl border p-8 text-center shadow-2xl ${isDark ? "bg-[#10121a] border-white/10" : "bg-white border-slate-200"}`}>
            <div className="mx-auto h-14 w-14 rounded-2xl bg-rose-500/15 flex items-center justify-center">
              <Lock className="h-7 w-7 text-rose-500" />
            </div>
            <h2 className="text-xl font-bold mt-5" style={{ color: isDark ? "#fff" : "#0f172a" }}>
              {subscription.status === "trial_expired"
                ? t("dashboard.trial.ended")
                : subscription.status === "expired" || subscription.status === "pending_payment"
                  ? t("dashboard.subscription.expired")
                  : t("dashboard.subscription.expired")}
            </h2>
            <p className={`text-sm mt-2 ${T.text2}`}>
              {subscription.message || t("dashboard.trial.subscribe")}
            </p>
            <button
              onClick={() => setShowCheckout(true)}
              className="mt-6 inline-flex items-center justify-center gap-2 w-full px-5 py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 font-bold transition"
            >
              <CreditCard className="h-4 w-4" />
              {t("dashboard.trial.cta")}
            </button>
            <button
              onClick={() => signOut()}
              className="mt-3 text-xs font-medium text-slate-400 hover:text-slate-200 underline underline-offset-2"
            >
              {t("dashboard.lock.logout")}
            </button>
          </div>
        </div>
      )}

      {/* Toast Notifications (fila empilhável) */}
      {toasts.length > 0 && (
        <div className="fixed bottom-6 right-6 z-[90] flex flex-col gap-2 items-end">
          {toasts.map((t) => (
            <div
              key={t.id}
              className={`animate-slide-in ${t.type === "error" ? "bg-red-500" : t.type === "warning" ? "bg-amber-500" : "bg-emerald-500"} text-white px-5 py-3 rounded-xl shadow-lg flex items-center gap-3`}
            >
              <span className="font-medium">{t.message}</span>
              <button
                onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
                className="ml-3 text-white/80 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center min-h-screen" style={{ backgroundColor: DARK.bg }}>
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    }>
      <DashboardPageInner />
    </Suspense>
  );
}
