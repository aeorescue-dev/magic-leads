"use client";

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
  TrendingUp, Navigation, Smartphone, FolderOpen,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import CheckoutModal from "@/components/CheckoutModal";
import ReleaseModal from "@/components/ReleaseModal";
import { PushNotificationButton } from "@/components/PushNotificationButton";
import {
  LeadResponse, LeadStats, CityCount, Notification, Note, HistoryEvent,
  ContractorMetrics,
  fetchTodayLeads, fetchStats, fetchCitiesWithCounts,
  fetchLeadById, toggleFavorite, recordContact, fetchNotes, addNote, deleteNote,
  fetchUserNotifications, fetchUserUnreadCount, markUserNotificationRead, markAllUserNotificationsRead,
  fetchLeadStatus, reserveLead, releaseLead, contactLead, negotiateLead, convertLead,
  fetchLeadHistory, fetchUserInterests, updateUserInterests,
  fetchUserDailyStats, fetchUserSubscriptionStatus, fetchContractorMetrics,
  fetchMyLeadsHistory, MyLeadHistoryItem, MyLeadsHistoryKpis,
  LeadOccurrence, fetchLeadOccurrences,
  fetchDashboardSummary, DashboardSummary,
  fetchScraperStatus, ScraperRunState
} from "@/lib/api-client";

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
  text: "text-slate-900",
  text2: "text-slate-500",
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
function countdownLabel(expiresAt: string): string {
  if (!expiresAt) return "24h";
  const d = new Date(expiresAt.replace("Z", "+00:00").replace(" ", "T"));
  if (isNaN(d.getTime())) return "24h";
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
  const { user, subscription, loading: authLoading, signOut } = useAuth();
  const { t, lang } = useI18n();

  // DECLARE userId BEFORE ALL HANDLERS
  const userId = user?.id;

  // State
  const [theme, setTheme] = useState<Theme>("dark");
  const [leads, setLeads] = useState<LeadResponse[]>([]);
  const [loadingLeads, setLoadingLeads] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasMoreLeads, setHasMoreLeads] = useState(true);
  const [stats, setStats] = useState<LeadStats | null>(null);
  const [citiesWithCounts, setCitiesWithCounts] = useState<CityCount[]>([]);
  const [selectedCity, setSelectedCity] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"overview" | "opportunities" | "favorites" | "interests" | "alerts" | "history">("overview");
  const [interests, setInterests] = useState<Set<string>>(new Set(["Roof", "Structure", "Plumbing", "Grass", "Paint", "Permit_Rejected", "Heating", "Electrical", "Elevator", "Gas", "Rodent", "Mold", "Lead", "Unsanitary", "Door_Window", "Debris"]));
  const [dailyStats, setDailyStats] = useState<{ used: number; limit: number; remaining: number; reset_at: string } | null>(null);

  // Filter states
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [selectedUrgency, setSelectedUrgency] = useState<string>("all");
  const [selectedType, setSelectedType] = useState<string>("all");
  const [dashboardSummary, setDashboardSummary] = useState<DashboardSummary | null>(null);
  const [scraperState, setScraperState] = useState<ScraperRunState | null>(null);
  const [shown, setShown] = useState<Set<string>>(new Set());

  const CITIES = ["all", "NYC", "Chicago", "Dallas", "Boston"];
  const CATEGORIES_FILTER = ["all", ...CATEGORIES.map(c => c.key)];
const URGENCIES = ["all", "high", "medium", "low"];
const LEAD_TYPES = [
  { value: "all", labelKey: "dashboard.filter.all_types" },
  { value: "dob_violation", labelKey: "dashboard.lead_type.obligation" },
  { value: "permit", labelKey: "dashboard.lead_type.permit" },
  { value: "311", labelKey: "dashboard.lead_type.open" },
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

  const openSMS = (phone: string) => {
    const clean = phone.replace(/\D/g, "");
    window.open(`sms:${clean}`, "_self");
  };

  const openWhatsApp = (phone: string) => {
    const clean = phone.replace(/\D/g, "");
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
  const [selectedLead, setSelectedLead] = useState<LeadResponse | null>(null);

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
  const [contractorMetrics, setContractorMetrics] = useState<ContractorMetrics | null>(null);
  
  // Toast notifications (fila empilhável + auto-dismiss 4s)
  const [toasts, setToasts] = useState<{ id: number; message: string; type: "success" | "error" | "warning" }[]>([]);

  const showToast = useCallback((message: string, type: "success" | "error" | "warning" = "success") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

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

  // Theme loading
  useEffect(() => {
    const saved = localStorage.getItem("pro.theme") as Theme | null;
    if (saved === "light" || saved === "dark") setTheme(saved);
  }, []);

  useEffect(() => {
    localStorage.setItem("pro.theme", theme);
  }, [theme]);

  // Route protection
  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/");
    }
  }, [authLoading, user, router]);

  // Sync favorites tab from URL param ?fav=1
  useEffect(() => {
    if (searchParams?.get("fav") === "1") {
      setActiveTab("favorites");
    }
  }, [searchParams]);

  // Load user interests
  useEffect(() => {
    if (userId) {
      fetchUserInterests(userId)
        .then((cats) => {
          if (cats && cats.length > 0) {
            setInterests(new Set(cats));
          }
        })
        .catch(() => {});
    }
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
        const [statsData, citiesData, leadsData, summaryData, scraperData] = await Promise.all([
          fetchStats().catch(() => null),
          fetchCitiesWithCounts().catch(() => []),
          fetchTodayLeads(50, selectedCity === "all" ? undefined : selectedCity, false, 1, selectedType === "all" ? undefined : selectedType).catch(() => ({ leads: [], total: 0, page: 1, per_page: 50 })),
          fetchDashboardSummary().catch(() => null),
          fetchScraperStatus().catch(() => null),
        ]);
        if (!active) return;
        if (statsData) setStats(statsData);
        if (Array.isArray(citiesData) && citiesData.length > 0) {
          setCitiesWithCounts(citiesData);
        }
        if (summaryData) setDashboardSummary(summaryData);
        if (scraperData) setScraperState(scraperData);
        setLeads(leadsData.leads || []);
        setCurrentPage(1);
        setHasMoreLeads((leadsData.leads?.length || 0) >= 50);
      } catch (e) {
        console.error("Erro ao carregar dados do dashboard:", e);
      } finally {
        if (active) setLoadingLeads(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [selectedCity, selectedType]);

  // Real-time polling: refresh leads + KPIs every 30 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      fetchTodayLeads(50, selectedCity === "all" ? undefined : selectedCity, false, 1, selectedType === "all" ? undefined : selectedType)
        .then((data) => {
          setLeads(data.leads || []);
          setCurrentPage(1);
          setHasMoreLeads((data.leads?.length || 0) >= 50);
        })
        .catch(() => {});
      fetchDashboardSummary().then(setDashboardSummary).catch(() => {});
      fetchStats().then(setStats).catch(() => {});
      fetchCitiesWithCounts().then(setCitiesWithCounts).catch(() => {});
      fetchScraperStatus().then(setScraperState).catch(() => {});
    }, 30000);
    return () => clearInterval(interval);
  }, [selectedCity]);

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
    if (dailyStats && dailyStats.remaining === 0) {
      showToast(`Limite de 10 leads/dia atingido. Reset em ${dailyStats.reset_at ? formatRelativeTime(dailyStats.reset_at, t) : "breve"}`, "warning");
      return;
    }
    setBusyAction(true);
    try {
      const res = await reserveLead(lead.id);
      showToast(res?.message || "Lead reservado com exclusividade", "success");
      if (dailyStats) {
        try {
          setDailyStats(await fetchUserDailyStats(userId!));
        } catch (e) {
          console.error(e);
        }
      }
      refreshHistory();
      if (userId) refreshNotifications();
    } catch (e: any) {
      showToast(e?.message || "Erro ao reservar lead", "error");
    } finally {
      setBusyAction(false);
    }
  };

  const handleHistoryConvert = async (lead: MyLeadHistoryItem) => {
    setBusyAction(true);
    try {
      await convertLead(lead.id);
      showToast("Conversão registrada. Parabéns!", "success");
      if (userId) refreshNotifications();
      refreshHistory();
    } catch (e: any) {
      showToast(e?.message || "Erro ao registrar conversão", "error");
    } finally {
      setBusyAction(false);
    }
  };

  // Toggle category interest
  const toggleInterest = async (catKey: string) => {
    const next = new Set(interests);
    if (next.has(catKey)) next.delete(catKey);
    else next.add(catKey);
    setInterests(next);

    if (userId) {
      try {
        await updateUserInterests(userId, Array.from(next));
      } catch (e) {
        console.error(e);
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
      const data = await fetchTodayLeads(50, selectedCity === "all" ? undefined : selectedCity, false, nextPage, selectedType === "all" ? undefined : selectedType);
      if (data.leads && data.leads.length > 0) {
        setLeads((prev) => [...prev, ...data.leads]);
        setCurrentPage(nextPage);
        setHasMoreLeads(data.leads.length >= 50);
      } else {
        setHasMoreLeads(false);
      }
    } catch (e) {
      console.error("Erro ao carregar mais leads:", e);
    } finally {
      setLoadingMore(false);
    }
  }, [currentPage, hasMoreLeads, loadingMore, selectedCity, selectedType]);

  // Open Lead Detail
  const openLeadDetail = async (lead: LeadResponse) => {
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

  // Lead actions inside modal
  const handleLeadAction = async (fn: () => Promise<any>, successText: string) => {
    if (!selectedLead) return;
    setBusyAction(true);
    setActionSuccess(null);
    try {
      await fn();
      setActionSuccess(successText);
      const [updatedStatus, updatedHistory] = await Promise.all([
        fetchLeadStatus(selectedLead.id).catch(() => null),
        fetchLeadHistory(selectedLead.id).catch(() => []),
      ]);
      if (updatedStatus?.lead_status) {
        setLeadStatus(updatedStatus.lead_status);
        setLeads((prev) =>
          prev.map((l) => (l.id === selectedLead.id ? { ...l, status: updatedStatus.lead_status! } : l))
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
    if (dailyStats && dailyStats.remaining === 0) {
      showToast(`Limite de 10 leads/dia atingido. Reset em ${dailyStats.reset_at ? formatRelativeTime(dailyStats.reset_at, t) : "breve"}`, "warning");
      return;
    }
    setBusyAction(true);
    try {
      const res = await reserveLead(lead.id);
      showToast(res?.message || "Lead reservado com exclusividade", "success");
      if (dailyStats) {
        try {
          const stats = await fetchUserDailyStats(userId!);
          setDailyStats(stats);
        } catch (e) {
          console.error(e);
        }
      }
      setLeads((prev) =>
        prev.map((l) =>
          l.id === lead.id
            ? { ...l, status: "reserved", reserved_by_me: { expires_at: res?.expires_at } }
            : l
        )
      );
      if (userId) refreshNotifications();
    } catch (e: any) {
      showToast(e?.message || "Erro ao reservar lead", "error");
    } finally {
      setBusyAction(false);
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
    if (normalized === "norfolk") return "norfolk";
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

      // Type filter
      if (selectedType !== "all") {
        if (lead.source_type !== selectedType) {
          return false;
        }
      }

      // Interest category filter (when in overview or opportunities)
      if (activeTab === "overview") {
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

      return true;
    });
  }, [leads, activeTab, selectedCity, selectedCategory, selectedUrgency, selectedType, interests, searchQuery]);

  // New alerts (not yet viewed)
  const newAlerts = useMemo(
    () => filteredLeads.filter((l) => !shown.has(l.id)),
    [filteredLeads, shown]
  );

  // Use Dashboard Summary for real KPIs (falls back to stats if summary not loaded)
  const realTotalLeads = dashboardSummary?.total_interested ?? (stats?.total ?? stats?.total_leads ?? 1249);
  const new24h = dashboardSummary?.new_24h ?? 0;
  const urgentCount = dashboardSummary?.urgent ?? 0;

  const T = theme === "dark" ? DARK : LIGHT;
  const isDark = theme === "dark";

  return (
    <div className="flex min-h-screen transition-colors duration-200" style={{ backgroundColor: T.bg, color: isDark ? "#f8fafc" : "#0f172a" }}>
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
            { id: "opportunities", icon: FolderKanban, label: t("dashboard.nav.opportunities"), badge: String(realTotalLeads) },
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
                    active ? "bg-indigo-500 text-white" : "bg-white/10 text-slate-400"
                  }`}>
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}

          <div className="pt-4 mt-4 border-t border-white/5 space-y-1">
            <button
              onClick={() => setShowCheckout(true)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition ${T.text2} ${T.navHover}`}
            >
              <CreditCard className="h-4 w-4 text-emerald-500" />
              <span className="flex-1 text-left">{t("dashboard.nav.plans")}</span>
              <span className="text-[10px] font-bold bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full">
                $79/sem
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
            className="lg:hidden p-2 rounded-lg text-slate-400 hover:bg-white/5"
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
              className="flex items-center gap-1.5 bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 font-semibold text-xs md:text-sm px-3.5 py-2 rounded-xl shadow-md shadow-emerald-500/20 transition"
            >
              <CreditCard className="h-4 w-4" />
              <span>{t("dashboard.trial.scribe")}</span>
            </button>
          </div>
        </header>

        {/* MAIN BODY CONTAINER */}
        <main className="flex-1 p-4 md:p-6 space-y-6 max-w-7xl mx-auto w-full">
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
                        <p className="text-sm font-semibold text-rose-400">Acesso pausado · Renove para voltar a receber leads</p>
                        <p className="text-xs text-slate-400">Sua assinatura expirou. Reative por $79/semana para voltar a receber oportunidades exclusivas.</p>
                      </>
                    );
                  }
                  if (expiringSoon) {
                    return (
                      <>
                        <p className="text-sm font-semibold text-amber-400">⚠ Falta {days} dia{days > 1 ? "s" : ""} para expirar — Renove agora</p>
                        <p className="text-xs text-slate-400">Continue recebendo as melhores oportunidades antes da concorrência. Renove por $79/semana.</p>
                      </>
                    );
                  }
                  // Ativo com dias restantes
                  return (
                    <>
                      <p className="text-sm font-semibold text-emerald-400">Acesso Completo • Renovação em {days} dia{days > 1 ? "s" : ""}</p>
                      <p className="text-xs text-slate-400">Sua assinatura renova automaticamente. $79/semana para oportunidades exclusivas 24h antes da concorrência.</p>
                    </>
                  );
                })()}
              </div>
            </div>
          </div>

          {/* DAILY LIMIT BAR (10 leads/dia) */}
          <div className="rounded-xl border bg-white/5 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-amber-500/20 text-amber-400 flex items-center justify-center shrink-0">
                <BarChart3 className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm font-semibold text-amber-400">
                  Limite Diário: {dailyStats?.used ?? 0} de {dailyStats?.limit ?? 10} leads usados hoje
                </p>
                <div className="w-full max-w-xs h-2 bg-white/10 rounded-full overflow-hidden mt-1">
                  <div 
                    className="h-full bg-amber-500 transition-all duration-300" 
                    style={{ width: dailyStats && dailyStats.limit > 0 ? `${Math.min(100, (dailyStats.used / dailyStats.limit) * 100)}%` : '0%' }}
                  />
                </div>
              </div>
            </div>
            {dailyStats && dailyStats.remaining === 0 && (
              <div className="text-xs text-red-400 font-medium">
                Limite atingido. Reset em {dailyStats.reset_at ? formatRelativeTime(dailyStats.reset_at, t) : "breve"}
              </div>
            )}
          </div>

          {/* FILTER BAR */}
          <div className={`flex flex-wrap items-center gap-3 p-4 rounded-xl border ${theme === "dark" ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-medium ${T.text2}`}>{t("dashboard.filter.city") || "📍 Cidade:"}</span>
              <select
                value={selectedCity}
                onChange={(e) => setSelectedCity(e.target.value)}
                className={`px-3 py-1.5 rounded-lg text-sm border ${theme === "dark" ? "bg-[#0b0d1a] border-white/10 text-white" : "bg-white border-slate-200"}`}
              >
                {CITIES.map((c) => <option key={c} value={c}>{c === "all" ? t("dashboard.filter.all_cities") || "Todas" : c}</option>)}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-medium ${T.text2}`}>{t("dashboard.filter.category") || "🔧 Categoria:"}</span>
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className={`px-3 py-1.5 rounded-lg text-sm border ${theme === "dark" ? "bg-[#0b0d1a] border-white/10 text-white" : "bg-white border-slate-200"}`}
              >
                {CATEGORIES_FILTER.map((c) => <option key={c} value={c}>{c === "all" ? t("dashboard.filter.all_categories") || "Todas" : t(CATEGORIES.find(x => x.key === c)?.labelKey || c)}</option>)}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-medium ${T.text2}`}>{t("dashboard.filter.urgency") || "⚡ Urgência:"}</span>
              <select
                value={selectedUrgency}
                onChange={(e) => setSelectedUrgency(e.target.value)}
                className={`px-3 py-1.5 rounded-lg text-sm border ${theme === "dark" ? "bg-[#0b0d1a] border-white/10 text-white" : "bg-white border-slate-200"}`}
              >
                {URGENCIES.map((u) => <option key={u} value={u}>{u === "all" ? t("dashboard.filter.all_urgency") || "Todas" : t(`dashboard.feed.urgency.${u}`) || u.charAt(0).toUpperCase() + u.slice(1)}</option>)}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-medium ${T.text2}`}>{t("dashboard.filter.type") || "Tipo:"}</span>
              <select
                value={selectedType}
                onChange={(e) => setSelectedType(e.target.value)}
                className={`px-3 py-1.5 rounded-lg text-sm border ${theme === "dark" ? "bg-[#0b0d1a] border-white/10 text-white" : "bg-white border-slate-200"}`}
              >
                {LEAD_TYPES.map((lt) => <option key={lt.value} value={lt.value}>{t(lt.labelKey)}</option>)}
              </select>
            </div>
            <div className="flex-1" />
            <div className="flex items-center gap-2 text-xs" style={{ color: theme === "dark" ? "#94a3b8" : "#64748b" }}>
              <span>{filteredLeads.length} {t("dashboard.filter.showing") || "oportunidades"}</span>
              <span>·</span>
              <span>{newAlerts.length} {t("dashboard.filter.new") || "novas"}</span>
            </div>
          </div>

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
              { label: t("dashboard.kpi.new_24h") || "Novas 24h", value: dashboardSummary?.new_24h ?? 0, delta: t("dashboard.kpi.today") || "entraram hoje", icon: TrendingUp, color: "#22c55e" },
              { label: t("dashboard.kpi.with_contact") || "Com contato", value: dashboardSummary?.with_contact ?? 0, delta: t("dashboard.kpi.ready_call") || "prontas p/ ligar", icon: Phone, color: "#f59e0b" },
              { label: t("dashboard.kpi.urgent") || "Urgentes", value: dashboardSummary?.urgent ?? 0, delta: t("dashboard.kpi.need_action") || "precisam ação", icon: AlertCircle, color: "#ef4444" },
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
              {t("dashboard.feed.all_cities")} ({realTotalLeads})
            </button>
            {(() => {
              // Fixed list of all 4 cities - always show all
              const allCities = ["NYC", "Chicago", "Dallas", "Boston"];
              // Build lookup from API data
              const apiCounts: Record<string, number> = {};
              citiesWithCounts.forEach((c) => { apiCounts[c.city.toLowerCase()] = c.count; });
              // Fallback counts for when API doesn't have a city
              const fallbackCounts: Record<string, number> = { "nyc": 1125, "chicago": 277, "dallas": 346, "boston": 25 };
              return allCities.map((city) => {
                const key = city.toLowerCase();
                const count = apiCounts[key] ?? fallbackCounts[key] ?? 0;
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
                    {city} ({count})
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
                    {unreadCount > 0
                      ? `${unreadCount} notificaç${unreadCount > 1 ? "ões" : "ão"} não lida${unreadCount > 1 ? "s" : ""}`
                      : "Todas as notificações estão em dia"}
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
                  Só o que precisa de ação hoje
                </button>
              </div>

              {/* KPIs do histórico */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
                <div className={`border rounded-2xl p-4 transition ${isDark ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
                  <div className={`text-xs font-medium ${T.text2}`}>Usados hoje</div>
                  <div className="text-2xl md:text-3xl font-bold mt-1 text-indigo-400">
                    {historyKpis?.today_used ?? 0} <span className="text-base font-semibold text-slate-500">/ {historyKpis?.today_limit ?? 10}</span>
                  </div>
                  <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden mt-2">
                    <div className="h-full bg-indigo-500 transition-all duration-300" style={{ width: historyKpis && historyKpis.today_limit > 0 ? `${Math.min(100, ((historyKpis.today_used || 0) / historyKpis.today_limit) * 100)}%` : "0%" }} />
                  </div>
                </div>

                <div className={`border rounded-2xl p-4 transition ${isDark ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
                  <div className={`text-xs font-medium ${T.text2}`}>Total reservado</div>
                  <div className="text-2xl md:text-3xl font-bold mt-1 text-emerald-400">
                    {historyKpis?.total_reserved ?? 0}
                  </div>
                  <div className={`text-[11px] mt-2 ${T.text2}`}>desde o início</div>
                </div>

                <div className={`border rounded-2xl p-4 transition ${isDark ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
                  <div className={`text-xs font-medium ${T.text2}`}>Convertidos</div>
                  <div className="text-2xl md:text-3xl font-bold mt-1 text-emerald-500">
                    {historyKpis?.converted ?? 0}
                  </div>
                  <div className="text-[11px] mt-2 text-emerald-400 font-medium">
                    {historyKpis?.conversion_rate ?? 0}% de aproveitamento
                  </div>
                </div>

                <div className="border rounded-2xl p-4 transition border-amber-500/20 bg-amber-500/5">
                  <div className="text-xs font-medium text-amber-300">Precisam de ação</div>
                  <div className="text-2xl md:text-3xl font-bold mt-1 text-amber-400">
                    {historyKpis?.needs_action ?? 0}
                  </div>
                  <div className="text-[11px] mt-2 text-amber-300/80">
                    reservados/negociação em aberto
                  </div>
                </div>
              </div>

              {/* Filtros */}
              <div className="space-y-2.5">
                <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none">
                  {[
                    { value: "", label: "Todos" },
                    { value: "reserved", label: "Reservado" },
                    { value: "negotiating", label: "Em negociação" },
                    { value: "hold_expired", label: "Hold expirou" },
                    { value: "converted", label: "Convertido" },
                    { value: "released", label: "Liberado" },
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
                      { value: "", label: "Todo período" },
                      { value: "today", label: "Hoje" },
                      { value: "7d", label: "7 dias" },
                      { value: "month", label: "Mês" },
                    ].map((opt) => (
                      <button
                        key={opt.value}
                        onClick={() => setHistoryPeriod(opt.value)}
                        className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold shrink-0 transition border ${
                          historyPeriod === opt.value
                            ? "bg-white/10 text-slate-100 border-white/20"
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
                    <option value="">Todas as categorias</option>
                    {CATEGORIES.map((c) => (
                      <option key={c.key} value={c.key}>{t(c.labelKey)}</option>
                    ))}
                  </select>

                  <div className="relative flex-1 min-w-[180px]">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
                    <input
                      value={historySearch}
                      onChange={(e) => setHistorySearch(e.target.value)}
                      placeholder="Buscar por endereço ou dono..."
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
                      ? "Nenhum lead corresponde aos filtros"
                      : "Nenhum lead aqui ainda"}
                  </div>
                  <p className={`text-xs mt-1 ${T.text2}`}>
                    {historyStatus || historyCategory || historyPeriod || historySearch || historyNeedsAction
                      ? "Ajuste os filtros para ver mais resultados."
                      : "Reserve seus primeiros leads para eles aparecerem aqui."}
                  </p>
                </div>
              ) : (
                <div className={`border rounded-2xl overflow-hidden divide-y ${T.border}`}>
                  {historyLeads.filter((l) => !historyCategory || catOfLead(l).key === historyCategory).map((lead) => {
                    const cat = catOfLead(lead);
                    const CatIcon = cat.icon;
                    const badge =
                      lead.my_status === "reserved"
                        ? { label: `Seu · ${lead.hold_expires_at ? countdownLabel(lead.hold_expires_at) : "24h"}`, cls: "bg-rose-500/15 text-rose-400", icon: <Lock className="h-3 w-3" /> }
                        : lead.my_status === "negotiating"
                          ? { label: "Em negociação", cls: "bg-amber-500/15 text-amber-400", icon: <MessageSquare className="h-3 w-3" /> }
                          : lead.my_status === "hold_expired"
                            ? { label: "Hold expirou", cls: "bg-slate-500/15 text-slate-400", icon: <Clock className="h-3 w-3" /> }
                            : lead.my_status === "converted"
                              ? { label: "Convertido", cls: "bg-emerald-500/15 text-emerald-400", icon: <BadgeCheck className="h-3 w-3" /> }
                              : lead.my_status === "released"
                                ? { label: "Liberado", cls: "bg-slate-500/15 text-slate-400", icon: <RefreshCcw className="h-3 w-3" /> }
                                : { label: "Disponível", cls: "bg-sky-500/15 text-sky-400", icon: <CheckCircle2 className="h-3 w-3" /> };
                    return (
                      <div
                        key={lead.id}
                        onClick={() => openLeadDetail(lead)}
                        className={`px-5 py-4 cursor-pointer transition ${T.navHover}`}
                      >
                        <div className="flex items-center gap-2 mb-2 flex-wrap">
                          <span className="text-[10px] font-semibold uppercase tracking-wider flex items-center gap-1.5 px-2.5 py-1 rounded-full" style={{ backgroundColor: `${cat.color}1a`, color: cat.color }}>
                            <CatIcon className="h-3 w-3" /> {t(cat.labelKey)}
                          </span>

                          {(lead.source_type && (() => {
                            const st = lead.source_type;
                            if (st === "dob_violation") return <span className="text-[10px] font-semibold uppercase tracking-wider bg-amber-500/15 text-amber-400 px-2.5 py-1 rounded-full flex items-center gap-1"><AlertTriangle className="h-3 w-3" /> {t("dashboard.lead_type.obligation")}</span>;
                            if (st === "permit") return <span className="text-[10px] font-semibold uppercase tracking-wider bg-sky-500/15 text-sky-400 px-2.5 py-1 rounded-full flex items-center gap-1"><HardHat className="h-3 w-3" /> {t("dashboard.lead_type.permit")}</span>;
                            return <span className="text-[10px] font-semibold uppercase tracking-wider bg-slate-500/15 text-slate-400 px-2.5 py-1 rounded-full flex items-center gap-1"><FolderOpen className="h-3 w-3" /> {t("dashboard.lead_type.open")}</span>;
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
                                Reservado em {lead.held_at ? formatRelativeTime(lead.held_at, t) : "—"}
                              </span>
                              {lead.my_status === "reserved" && lead.hold_expires_at && (
                                <span className="text-rose-400 font-semibold">Expira em {countdownLabel(lead.hold_expires_at)}</span>
                              )}
                              {lead.hold_released_at && (
                                <span>Liberado em {formatRelativeTime(lead.hold_released_at, t)}</span>
                              )}
                              {lead.converted_at && (
                                <span className="text-emerald-400">Convertido em {formatRelativeTime(lead.converted_at, t)}</span>
                              )}
                              {(lead.contact_count ?? 0) > 0 && (
                                <span className="flex items-center gap-1">
                                  <Phone className="h-3 w-3" /> {lead.contact_count} contato(s)
                                </span>
                              )}
                            </div>
                            {lead.release_reason && (
                              <div className="text-[11px] mt-1 text-slate-500">
                                Motivo: {lead.release_reason}
                              </div>
                            )}
                          </div>

                          <div className="flex flex-col items-end gap-2 shrink-0">
                            {lead.my_status === "reserved" && (
                              <button
                                onClick={(e) => { e.stopPropagation(); openReleaseModal(lead); }}
                                disabled={busyAction}
                                className="inline-flex items-center gap-1.5 text-[11px] font-semibold bg-white/10 hover:bg-rose-500/20 text-slate-300 hover:text-rose-400 px-3 py-1.5 rounded-lg transition disabled:opacity-50"
                              >
                                <RefreshCcw className="h-3 w-3" /> Largar
                              </button>
                            )}
                            {lead.my_status === "negotiating" && (
                              <button
                                onClick={(e) => { e.stopPropagation(); handleHistoryConvert(lead); }}
                                disabled={busyAction}
                                className="inline-flex items-center gap-1.5 text-[11px] font-bold bg-emerald-500 hover:bg-emerald-400 text-slate-950 px-3 py-1.5 rounded-lg transition disabled:opacity-50"
                              >
                                <BadgeCheck className="h-3 w-3" /> Registrar conversão
                              </button>
                            )}
                            {(lead.my_status === "hold_expired" || lead.my_status === "released" || lead.my_status === "available") && (
                              <button
                                onClick={(e) => { e.stopPropagation(); handleHistoryReserve(lead); }}
                                disabled={busyAction || (subscription && !subscription.can_access) || (dailyStats?.remaining === 0)}
                                className="inline-flex items-center gap-1.5 text-[11px] font-bold bg-indigo-500 hover:bg-indigo-400 text-white px-3 py-1.5 rounded-lg transition disabled:opacity-50"
                              >
                                <Lock className="h-3 w-3" /> Re-reservar
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
            <section className={`border rounded-2xl p-5 space-y-4 transition ${isDark ? "bg-[#10121a] border-white/5" : "bg-white border-slate-200 shadow-sm"}`}>
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
                        <div className={`text-[11px] ${T.text2}`}>Alerta ativo em tempo real</div>
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
                      {filteredLeads.length} de {realTotalLeads}
                    </span>
                  </h2>
                  <p className={`text-xs ${T.text2}`}>{t("dashboard.feed.filtered_sub")}</p>
                </div>
                <Filter className={`h-4 w-4 ${T.text2}`} />
              </div>

              <div className={`flex-1 overflow-y-auto max-h-[640px] divide-y ${T.border}`}>
                {loadingLeads ? (
                  <div className="flex flex-col items-center justify-center py-16 gap-2">
                    <Loader2 className="h-6 w-6 animate-spin text-indigo-500" />
                    <span className={`text-xs ${T.text2}`}>{t("dashboard.feed.loading")}</span>
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
                    {filteredLeads.map((lead) => {
                      const cat = catOfLead(lead);
                      const CatIcon = cat.icon;
                      const vis = lead.visibility_status || (lead.status === "reserved" ? "reserved_by_other" : "available");
                      const reservedUntil = lead.reserved_by_me?.expires_at || lead.reserved_by_other?.expires_at;
                      const isMine = vis === "reserved_by_me";
                      return (
                        <div
                          key={lead.id}
                          onClick={() => openLeadDetail(lead)}
                          className={`px-5 py-4 cursor-pointer transition ${T.navHover} group ${vis === "reserved_by_other" ? "opacity-60" : ""}`}
                        >
                          <div className="flex items-center gap-2 mb-2 flex-wrap">
                            <span
                              className="text-[10px] font-semibold uppercase tracking-wider flex items-center gap-1.5 px-2.5 py-1 rounded-full"
                              style={{ backgroundColor: `${cat.color}1a`, color: cat.color }}
                            >
                              <CatIcon className="h-3 w-3" /> {t(cat.labelKey)}
                            </span>

                            {(lead.source_type && (() => {
                              const st = lead.source_type;
                              if (st === "dob_violation") return <span className="text-[10px] font-semibold uppercase tracking-wider bg-amber-500/15 text-amber-400 px-2.5 py-1 rounded-full flex items-center gap-1"><AlertTriangle className="h-3 w-3" /> {t("dashboard.lead_type.obligation")}</span>;
                              if (st === "permit") return <span className="text-[10px] font-semibold uppercase tracking-wider bg-sky-500/15 text-sky-400 px-2.5 py-1 rounded-full flex items-center gap-1"><HardHat className="h-3 w-3" /> {t("dashboard.lead_type.permit")}</span>;
                              return <span className="text-[10px] font-semibold uppercase tracking-wider bg-slate-500/15 text-slate-400 px-2.5 py-1 rounded-full flex items-center gap-1"><FolderOpen className="h-3 w-3" /> {t("dashboard.lead_type.open")}</span>;
                            })())}

                            {lead.owner_name && (
                              <span className="text-[10px] font-semibold uppercase bg-emerald-500/15 text-emerald-400 px-2.5 py-1 rounded-full flex items-center gap-1">
                                <CheckCircle2 className="h-3 w-3" /> Dono identificado
                              </span>
                            )}

                            {vis === "available" && (
                              <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-500/15 text-emerald-400 px-2.5 py-1 rounded-full flex items-center gap-1">
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" /> Disponível
                              </span>
                            )}
                            {isMine && (
                              <span className="text-[10px] font-bold uppercase tracking-wider bg-rose-500/15 text-rose-400 px-2.5 py-1 rounded-full flex items-center gap-1">
                                <Lock className="h-3 w-3" /> Seu · {reservedUntil ? countdownLabel(reservedUntil) : "24h"}
                              </span>
                            )}
                            {vis === "reserved_by_other" && (
                              <span className="text-[10px] font-bold uppercase tracking-wider bg-slate-500/15 text-slate-400 px-2.5 py-1 rounded-full flex items-center gap-1">
                                <Lock className="h-3 w-3" /> Reservado
                              </span>
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
                              <div className={`flex items-center gap-3 text-[11px] mt-2 flex-wrap ${T.text2}`}>
                                {lead.owner_name && (
                                  <>
                                    <span className="font-medium text-slate-300">
                                      Proprietário: {lead.owner_name}
                                    </span>
                                    {lead.mailing_address && (
                                      <span className="text-slate-400">📬 {lead.mailing_address}</span>
                                    )}
                                  </>
                                )}
                                <span>·</span>
                                <span>{formatRelativeTime(lead.date_reported, t)}</span>
                              </div>

                              {vis === "available" && (
                                <div className="flex items-center gap-2 mt-3 flex-wrap">
                                  <button
                                    onClick={(e) => { e.stopPropagation(); handleQuickReserve(lead); }}
                                    disabled={busyAction || (subscription && !subscription.can_access) || (dailyStats?.remaining === 0)}
                                    className={`flex items-center gap-1.5 text-[11px] font-bold bg-indigo-500 hover:bg-indigo-400 text-white px-3 py-1.5 rounded-lg transition shadow-sm disabled:opacity-50 ${
                                      (subscription && !subscription.can_access) || (dailyStats && dailyStats.remaining === 0) ? "opacity-30 cursor-not-allowed" : ""
                                    }`}
                                  >
                                    <Lock className="h-3 w-3" /> Reservar 15min
                                  </button>
                                  <button
                                    onClick={() => openMaps(lead.address)}
                                    className="flex items-center gap-1.5 text-[11px] font-semibold bg-slate-500/15 text-slate-300 px-3 py-1.5 rounded-lg hover:bg-slate-500/25 transition"
                                  >
                                    <Navigation className="h-3 w-3" /> Mapa
                                  </button>
                                  <button
                                    onClick={() => lead.owner_phone ? openSMS(lead.owner_phone!) : alert("Telefone não disponível")}
                                    disabled={!lead.owner_phone}
                                    className={`flex items-center gap-1.5 text-[11px] font-semibold px-3 py-1.5 rounded-lg transition ${
                                      lead.owner_phone
                                        ? "bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25"
                                        : "bg-slate-500/10 text-slate-500 cursor-not-allowed opacity-50"
                                    }`}
                                  >
                                    <Smartphone className="h-3 w-3" /> SMS
                                  </button>
                                  <button
                                    onClick={() => lead.owner_phone ? openWhatsApp(lead.owner_phone!) : alert("Telefone não disponível")}
                                    disabled={!lead.owner_phone}
                                    className={`flex items-center gap-1.5 text-[11px] font-semibold px-3 py-1.5 rounded-lg transition ${
                                      lead.owner_phone
                                        ? "bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25"
                                        : "bg-slate-500/10 text-slate-500 cursor-not-allowed opacity-50"
                                    }`}
                                  >
                                    <MessageSquare className="h-3 w-3" /> WhatsApp
                                  </button>
                                </div>
                              )}
                              {isMine && (
                                <div className="flex items-center gap-2 mt-3">
                                  <button
                                    onClick={(e) => { e.stopPropagation(); openReleaseModal(lead); }}
                                    disabled={busyAction}
                                    className="flex items-center gap-1.5 text-[11px] font-semibold bg-white/10 hover:bg-rose-500/20 text-slate-300 hover:text-rose-400 px-3 py-1.5 rounded-lg transition disabled:opacity-50"
                                  >
                                    <RefreshCcw className="h-3 w-3" /> Largar
                                  </button>
                                  {lead.owner_phone && (
                                    <a
                                      href={`https://wa.me/${lead.owner_phone.replace(/\D/g, "")}`}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      onClick={(e) => e.stopPropagation()}
                                      className="flex items-center gap-1.5 text-[11px] font-semibold bg-emerald-500/15 text-emerald-400 px-3 py-1.5 rounded-lg hover:bg-emerald-500/25 transition"
                                    >
                                      WhatsApp
                                    </a>
                                  )}
                                </div>
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
                      <div className="px-5 py-4 border-t border-white/5">
                        <button
                          onClick={loadMoreLeads}
                          disabled={loadingMore}
                          className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl border border-white/10 text-sm font-medium text-slate-300 hover:bg-white/5 transition disabled:opacity-50"
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
            className={`relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border p-6 shadow-2xl space-y-6 animate-scale-in ${
              isDark ? "bg-[#14161d] border-white/10 text-slate-100" : "bg-white border-slate-200 text-slate-900"
            }`}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-3 border-b pb-4 border-white/10">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-indigo-500/20 text-indigo-400">
                    {selectedLead.issue_category}
                  </span>
                  <span className="text-xs text-slate-400 font-medium">
                    {selectedLead.city}
                  </span>
                </div>
                <h2 className="text-xl font-bold mt-1.5">{selectedLead.address}</h2>
              </div>
              <button
                onClick={() => setSelectedLead(null)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

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
                  <span className="text-xs text-slate-400 block">{t("dashboard.col.date")}</span>
                  <span className="font-semibold" suppressHydrationWarning>
                    {selectedLead.date_reported ? new Date(selectedLead.date_reported).toLocaleDateString("pt-BR") : "—"}
                  </span>
                </div>
                {selectedLead.mailing_address && (
                  <div className="sm:col-span-2">
                    <span className="text-xs text-slate-400 block">{t("dashboard.field.mailing_address") || "Endereço de correspondência"}</span>
                    <span className="font-semibold">📬 {selectedLead.mailing_address}</span>
                  </div>
                )}
              </div>

              {/* Action Contact Links */}
              {selectedLead.owner_phone && (
                <div className="flex flex-wrap gap-2 pt-2">
                  <a
                    href={`https://wa.me/${selectedLead.owner_phone.replace(/\D/g, "")}`}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500 text-slate-950 text-xs font-bold hover:bg-emerald-400 transition"
                  >
                    <MessageSquare className="h-3.5 w-3.5" /> WhatsApp
                  </a>
                  <a
                    href={`tel:${selectedLead.owner_phone}`}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-500 text-white text-xs font-bold hover:bg-sky-400 transition"
                  >
                    <Phone className="h-3.5 w-3.5" /> Ligar
                  </a>
                  <a
                    href={`sms:${selectedLead.owner_phone.replace(/\D/g, "")}?body=${encodeURIComponent(
                      (t("dashboard.detail.sms") || "Oi {owner}! Vi seu imóvel em {address}. Posso ajudar com a reforma?")
                        .replace("{owner}", selectedLead.owner_name || "proprietário")
                        .replace("{address}", selectedLead.address)
                    )}`}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-600 text-white text-xs font-bold hover:bg-green-500 transition"
                  >
                    <MessageSquare className="h-3.5 w-3.5" /> SMS
                  </a>
                  {selectedLead.owner_email && (
                    <a
                      href={`mailto:${selectedLead.owner_email}?subject=${encodeURIComponent(
                        t("dashboard.detail.email_subject") || "Orçamento de Reforma"
                      )}&body=${encodeURIComponent(
                        (t("dashboard.detail.email_body") || "Olá {owner},\n\nVi o seu imóvel em {address} e gostaria de oferecer meus serviços de reforma.\n\nAtenciosamente,\n{company}")
                          .replace("{owner}", selectedLead.owner_name || "proprietário")
                          .replace("{address}", selectedLead.address)
                          .replace("{company}", user?.company_name || "Sua Empresa")
                      )}`}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-bold hover:bg-blue-500 transition"
                    >
                      <Mail className="h-3.5 w-3.5" /> E-mail
                    </a>
                  )}
                  <a
                    href={`https://maps.google.com/?q=${encodeURIComponent(selectedLead.address + ", " + selectedLead.city)}`}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500 text-slate-950 text-xs font-bold hover:bg-amber-400 transition"
                  >
                    <MapPin className="h-3.5 w-3.5" /> {t("dashboard.action.map") || "Abrir Mapa"}
                  </a>
                  <button
                    onClick={() => copyToClipboard(selectedLead.owner_phone!, "phone")}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-white/10 text-xs text-slate-300 hover:bg-white/5 transition"
                  >
                    {copiedField === "phone" ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                    Copiar telefone
                  </button>
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
                  Aberto em {formatRelativeTime(selectedLead.date_reported, t)}
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
                  Fechado em {formatRelativeTime(selectedLead.closed_dt, t)}
                </div>
              )}
              {(selectedLead.resolution_description || selectedLead.closure_reason) && (
                <div className="text-xs leading-relaxed text-emerald-300/90">
                  <BadgeCheck className="h-3.5 w-3.5 inline mr-1" />
                  Resolução: {selectedLead.resolution_description || selectedLead.closure_reason}
                </div>
              )}
            </div>

            {/* Historical Events */}
            {leadHistory.length > 0 && (
              <div className="space-y-3 pt-2 border-t border-white/10">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <Clock className="h-3.5 w-3.5" />
                  {t("dashboard.detail.history")}
                </h4>
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {leadHistory.map((event) => (
                    <div key={event.id} className="p-3 rounded-xl border border-white/5 bg-white/5 flex items-start gap-3">
                      <div className="h-8 w-8 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center shrink-0">
                        <Clock className="h-4 w-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-slate-300">{event.detail || event.event_type}</p>
                        <div className="flex items-center gap-2 text-[10px] text-slate-500 mt-1">
                          <span>{formatRelativeTime(event.created_at, t)}</span>
                          {event.user_id && <span>· Por usuário #{event.user_id}</span>}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Ocorrências do imóvel (histórico 311 - Parte B) */}
            {leadOccurrences.length > 0 && (
              <div className="space-y-3 pt-2 border-t border-white/10">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <Building2 className="h-3.5 w-3.5" />
                  Histórico de ocorrências do imóvel
                </h4>
                <div className="space-y-2 max-h-60 overflow-y-auto">
                  {leadOccurrences.map((oc) => (
                    <div key={oc.id || oc.external_id || `${oc.case_title}-${oc.opened_at}`} className="p-3 rounded-xl border border-white/5 bg-white/5">
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
                          Resolução: {oc.resolution_description || oc.closure_reason}
                        </div>
                      )}
                      {oc.closed_at && (
                        <div className="text-[11px] text-slate-500 mt-1">Fechado em {formatRelativeTime(oc.closed_at, t)}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Pipeline Actions */}
            <div className="space-y-3 pt-2 border-t border-white/10">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                {t("dashboard.detail.routing")}
              </h4>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={async () => {
                    // Check subscription first
                    if (subscription && !subscription.can_access) {
                      showToast(subscription.message || "Acesso negado", "error");
                      return;
                    }
                    // Check daily limit
                    if (dailyStats && dailyStats.remaining === 0) {
                      showToast(`Limite de 10 leads/dia atingido. Reset em ${dailyStats.reset_at ? formatRelativeTime(dailyStats.reset_at, t) : "breve"}`, "warning");
                      return;
                    }
                    await handleLeadAction(() => reserveLead(selectedLead.id), t("dashboard.action.reserve_ok"));
                    if (dailyStats) {
                      // Refresh daily stats after successful reserve
                      try {
                        const stats = await fetchUserDailyStats(userId!);
                        setDailyStats(stats);
                      } catch (e) {
                        console.error(e);
                      }
                    }
                  }}
                  disabled={busyAction || (subscription && !subscription.can_access) || (dailyStats?.remaining === 0)}
                  className={`flex items-center gap-1.5 text-xs font-bold bg-indigo-500 hover:bg-indigo-400 text-white px-3.5 py-2 rounded-xl transition shadow-sm disabled:opacity-50 ${
                    (subscription && !subscription.can_access) || (dailyStats && dailyStats.remaining === 0) ? "opacity-30 cursor-not-allowed" : ""
                  }`}
                >
                  <Lock className="h-3.5 w-3.5" /> {t("dashboard.action.reserve")} (15min)
                </button>
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
                  className="flex items-center gap-1.5 text-xs font-semibold bg-white/10 hover:bg-rose-500/20 text-slate-300 hover:text-rose-400 px-3 py-2 rounded-xl transition"
                >
                  <RefreshCcw className="h-3.5 w-3.5" /> {t("dashboard.action.release")}
                </button>
              </div>
              {actionSuccess && (
                <p className="text-xs font-semibold text-emerald-400 mt-1">{actionSuccess}</p>
              )}
            </div>

            {/* Internal Notes Section */}
            <div className="space-y-3 pt-2 border-t border-white/10">
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
                  className="px-4 py-2 rounded-xl bg-indigo-500 text-white text-xs font-bold hover:bg-indigo-400 transition disabled:opacity-50"
                >
                  {t("dashboard.detail.save")}
                </button>
              </div>

              <div className="space-y-2 max-h-44 overflow-y-auto">
                {leadNotes.length === 0 ? (
                  <p className="text-xs text-slate-500 py-2">{t("dashboard.detail.no_notes")}</p>
                ) : (
                  leadNotes.map((n) => (
                    <div key={n.id} className="p-3 rounded-xl border border-white/5 bg-white/5 flex items-start justify-between gap-2">
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

      {/* CHECKOUT / PLANS MODAL */}
      <CheckoutModal
        open={showCheckout}
        onClose={() => setShowCheckout(false)}
        onActivated={() => window.location.reload()}
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
              {subscription.status === "trial_expired" ? "Seu teste grátis terminou" : "Seu plano expirou"}
            </h2>
            <p className={`text-sm mt-2 ${T.text2}`}>
              {subscription.message || "Assine $79/semana para continuar acessando os leads com exclusividade."}
            </p>
            <button
              onClick={() => setShowCheckout(true)}
              className="mt-6 inline-flex items-center justify-center gap-2 w-full px-5 py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 font-bold transition"
            >
              <CreditCard className="h-4 w-4" />
              Assinar $79/semana
            </button>
            <button
              onClick={() => signOut()}
              className="mt-3 text-xs font-medium text-slate-400 hover:text-slate-200 underline underline-offset-2"
            >
              Sair da conta
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
