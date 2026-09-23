// Em produção, chama /api/leads do próprio domínio (Vercel serverless).
// Em dev local, aponta para o backend local via NEXT_PUBLIC_API_URL.
const API_URL = (
  (typeof window !== "undefined" && (window as any).__NEXT_PUBLIC_API_URL) ||
  process.env.NEXT_PUBLIC_API_URL ||
  "https://magic-leads-production.up.railway.app"
).replace(/\/$/, "");

// ------------------------------------------------------------------
// Sessão (token) — armazenada em httpOnly cookie (definido pelo backend)
// Mantido localStorage para compatibilidade com fluxos existentes
// ------------------------------------------------------------------
export const AUTH_TOKEN_KEY = "garimpador.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(AUTH_TOKEN_KEY, token);
  else window.localStorage.removeItem(AUTH_TOKEN_KEY);
}

// O middleware (frontend/middleware.ts) exige o cookie garimpador_auth para
// liberar /dashboard. Qualquer login/registro real precisa sincronizar o cookie.
export function setAuthCookie(value = "1", days = 30) {
  if (typeof document === "undefined") return;
  const exp = new Date(Date.now() + days * 86400000).toUTCString();
  // Secure só em HTTPS (produção). Em dev local (HTTP) o cookie com Secure
  // seria descartado — o que quebraria o login local.
  const secure = window.location.protocol === "https:" ? "; secure" : "";
  document.cookie = `garimpador_auth=${value}; path=/; expires=${exp}; samesite=lax${secure}`;
}

export function clearAuthCookie() {
  if (typeof document === "undefined") return;
  document.cookie = "garimpador_auth=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}

function authHeaders(): HeadersInit {
  // Envia token via Authorization header para compatibilidade
  // O cookie httpOnly é enviado automaticamente pelo browser
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface LeadResponse {
  id: string;
  external_id: string;
  source_type?: string;
  address: string;
  city: string;
  issue_category: string;
  issue_description: string;
  owner_name?: string;
  owner_phone?: string;
  owner_email?: string;
  date_reported: string;
  urgency_level: string;
  status: string;
  favorited: boolean;
  // Freshness fields (WS1 dual labels)
  first_seen?: string;
  last_synced?: string;
  // Address details
  address_unit?: string;
  address_type?: string;
  address_street?: string;
  address_city?: string;
  address_state?: string;
  address_zip?: string;
  // Historical details from 311 systems
  case_title?: string;
  subject?: string;
  reason?: string;
  type?: string;
  queue?: string;
  department?: string;
  closure_reason?: string;
  case_status?: string;
  on_time?: string;
  sla_target_dt?: string;
  closed_dt?: string;
  submitted_photo?: string;
  closed_photo?: string;
  source?: string;
  neighborhood?: string;
  ward?: string;
  precinct?: string;
  descriptor?: string;
  resolution_description?: string;
  resolution_action_updated_date?: string;
  // Owner mailing address
  mailing_address?: string;
  // Visibility (Phase 4.2)
  visibility_status?: "available" | "reserved_by_me" | "reserved_by_other";
  reserved_by_me?: { created_at?: string; expires_at?: string; hours_remaining?: number };
  reserved_by_other?: { contractor_id?: number; contractor_name?: string; expires_at?: string };
  // Reveal por consentimento: true = dados do proprietário liberados para o usuário
  revealed?: boolean;
}

export interface LeadsListResponse {
  total: number;
  page: number;
  per_page: number;
  leads: LeadResponse[];
}

export interface LeadStats {
  total: number;
  reported_today: number;
  contacted: number;
  favorited: number;
  by_category: Record<string, number>;
  total_leads?: number;
  leads_with_owner?: number;
  with_owner?: number;
  cities?: { city: string; count: number }[];
}

export interface Note {
  id: number;
  lead_id: number;
  note: string;
  created_at: string;
}

function toErrorMessage(detail: any): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "string" ? d : d?.msg || d?.message || JSON.stringify(d)))
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    return (
      detail?.msg ||
      detail?.message ||
      detail?.detail ||
      String(detail?.error || "")
    );
  }
  return "Erro na requisição";
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: any = "";
    try {
      const j = await res.json();
      detail = j?.detail ?? j;
    } catch {
      detail = await res.text();
    }
    // Sessão expirada por login concorrente (limite de 2 sessões por usuário)
    if (detail && typeof detail === "object" && detail?.error === "session_expired_concurrent_login") {
      handleSessionExpired();
      throw new Error(toErrorMessage(detail));
    }
    throw new Error(toErrorMessage(detail));
  }
  return res.json() as Promise<T>;
}

// Limita a 2 sessões simultâneas por usuário (backend 401 session_expired_concurrent_login).
// Registrada globalmente para acessar de qualquer módulo.
export function handleSessionExpired(reason: "fifo_evicted" | "session_expired" = "fifo_evicted") {
  setToken(null);
  clearAuthCookie();
  if (typeof document !== "undefined") {
    document.cookie = "garimpador_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  }
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/auth")) {
    window.location.href = `/auth?reason=${reason}`;
  }
}

export async function fetchLeads(params: {
  city: string;
  category?: string;
  type?: string;
  page?: number;
  per_page?: number;
}): Promise<LeadsListResponse> {
  const q = new URLSearchParams();
  q.append("city", params.city);
  if (params.category) q.append("category", params.category);
  if (params.type) q.append("type", params.type);
  q.append("page", String(params.page || 1));
  q.append("per_page", String(params.per_page || 20));

  return handle<LeadsListResponse>(await fetch(`${API_URL}/api/leads?${q}`, { headers: { ...authHeaders() } }));
}

export async function fetchTodayLeads(limit: number = 60, city?: string, includeIncomplete: boolean = false, page: number = 1, type?: string): Promise<LeadsListResponse> {
  const q = new URLSearchParams({ limit: String(limit), page: String(page) });
  if (city && city !== "Todas") q.set("city", city);
  if (includeIncomplete) q.set("include_incomplete", "true");
  if (type) q.set("type", type);
  return handle<LeadsListResponse>(await fetch(`${API_URL}/api/leads/today?${q.toString()}`, { headers: { ...authHeaders() } }));
}

export interface DashboardSummary {
  total_interested: number;
  last_scrape: string;
  with_contact: number;
  urgent: number;
  by_category: Record<string, number>;
  by_city: Record<string, number>;
  by_urgency: Record<string, number>;
}

export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  return handle<DashboardSummary>(await fetch(`${API_URL}/api/leads/dashboard-summary`, { headers: { ...authHeaders() } }));
}

export interface PublicMetrics {
  total_leads: number;
  leads_with_owner: number;
  cities: string[];
  cities_count: number;
  last_scrape: {
    inserted: number;
    started_at?: string | null;
    finished_at?: string | null;
    status?: string | null;
    captured_24h: number;
    floor: number;
    novas_oportunidades: number;
  };
}

export const EMPTY_PUBLIC_METRICS: PublicMetrics = {
  total_leads: 0,
  leads_with_owner: 0,
  cities: [],
  cities_count: 0,
  last_scrape: {
    inserted: 0,
    started_at: null,
    finished_at: null,
    status: null,
    captured_24h: 0,
    floor: 0,
    novas_oportunidades: 0,
  },
};

function toPublicMetrics(value: any): PublicMetrics {
  const safe = value && typeof value === "object" ? value : {};
  const lastScrape = safe.last_scrape && typeof safe.last_scrape === "object" ? safe.last_scrape : {};
  const cities = Array.isArray(safe.cities) ? safe.cities.filter((c: any) => typeof c === "string") : [];
  return {
    total_leads: Number.isFinite(safe.total_leads) ? safe.total_leads : 0,
    leads_with_owner: Number.isFinite(safe.leads_with_owner) ? safe.leads_with_owner : 0,
    cities,
    cities_count: Number.isFinite(safe.cities_count) ? safe.cities_count : cities.length,
    last_scrape: {
      inserted: Number.isFinite(lastScrape.inserted) ? lastScrape.inserted : 0,
      started_at: typeof lastScrape.started_at === "string" ? lastScrape.started_at : null,
      finished_at: typeof lastScrape.finished_at === "string" ? lastScrape.finished_at : null,
      status: typeof lastScrape.status === "string" ? lastScrape.status : null,
      captured_24h: Number.isFinite(lastScrape.captured_24h) ? lastScrape.captured_24h : 0,
      floor: Number.isFinite(lastScrape.floor) ? lastScrape.floor : 0,
      novas_oportunidades: Number.isFinite(lastScrape.novas_oportunidades) ? lastScrape.novas_oportunidades : 0,
    },
  };
}

export async function fetchPublicMetrics(): Promise<PublicMetrics> {
  try {
    const res = await fetch(`${API_URL}/api/metrics/public`);
    if (!res.ok) {
      return EMPTY_PUBLIC_METRICS;
    }
    const json = await res.json();
    return toPublicMetrics(json);
  } catch {
    return EMPTY_PUBLIC_METRICS;
  }
}

export async function fetchStats(): Promise<LeadStats> {
  return handle<LeadStats>(await fetch(`${API_URL}/api/leads/stats`));
}

export async function fetchCities(): Promise<string[]> {
  return handle<string[]>(await fetch(`${API_URL}/api/leads/cities`));
}

export interface CityCount {
  city: string;
  count: number;
}
export async function fetchCitiesWithCounts(filtered = true): Promise<CityCount[]> {
  return handle<CityCount[]>(await fetch(`${API_URL}/api/leads/cities-with-counts?filtered=${filtered}`));
}

export interface ScraperRunState {
  active: boolean;
  running: Record<string, {
    run_id: string;
    running: boolean;
    started_at: string;
    inserted: number;
    total_raw: number;
    status: string;
    error: string | null;
  }>;
  last_run: {
    run_id: string;
    running: boolean;
    started_at: string;
    finished_at?: string;
    inserted: number;
    total_raw: number;
    status: string;
    error: string | null;
    note?: string;
    cities_covered?: number;
  } | null;
}
export async function fetchScraperStatus(): Promise<ScraperRunState> {
  return handle<ScraperRunState>(await fetch(`${API_URL}/api/scraper/status`));
}

export interface InterestCountResponse {
  count: number;
  categories: string[];
}
export async function fetchUserInterestCount(userId: number): Promise<InterestCountResponse> {
  return handle<InterestCountResponse>(await fetch(`${API_URL}/api/users/${userId}/interest-count`, {
    headers: { ...authHeaders() },
  }));
}

export interface FeedStatsResponse {
  today: number;
  week: number;
  cities: CityCount[];
  selected_city: string | null;
}
export async function fetchFeedStats(city?: string): Promise<FeedStatsResponse> {
  const q = new URLSearchParams();
  if (city && city !== "Todas") q.set("city", city);
  return handle<FeedStatsResponse>(await fetch(`${API_URL}/api/leads/stats/feed?${q.toString()}`));
}

export interface LeadService {
  service: string;
  count: number;
}
export interface LeadServicesResponse {
  categories: Record<string, LeadService[]>;
  counts: Record<string, number>;
}
export async function fetchLeadServices(limit = 50): Promise<LeadServicesResponse> {
  return handle<LeadServicesResponse>(await fetch(`${API_URL}/api/leads/services?limit=${limit}`));
}

export interface LocationHierarchy {
  [country: string]: {
    name: string;
    states: Record<string, {
      name: string;
      cities: Record<string, { name: string; count: number }>;
      count: number;
    }>;
  };
}

export async function fetchLocationsHierarchy(): Promise<LocationHierarchy> {
  return handle<LocationHierarchy>(await fetch(`${API_URL}/api/leads/locations`));
}

export async function searchLeads(q: string): Promise<LeadsListResponse> {
  const params = new URLSearchParams({ q, per_page: "50" });
  return handle<LeadsListResponse>(
    await fetch(`${API_URL}/api/leads/search?${params}`, { headers: { ...authHeaders() } })
  );
}

export async function fetchLeadById(id: string): Promise<LeadResponse | null> {
  try {
    return handle<LeadResponse>(await fetch(`${API_URL}/api/leads/${id}`, {
      headers: authHeaders(),
    }));
  } catch {
    return null;
  }
}

export async function updateLeadStatus(id: string, status: string): Promise<LeadResponse> {
  return handle<LeadResponse>(
    await fetch(`${API_URL}/api/leads/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ status }),
    })
  );
}

export async function updateOwnerPhone(id: string, phone: string): Promise<LeadResponse> {
  return handle<LeadResponse>(
    await fetch(`${API_URL}/api/leads/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ owner_phone: phone }),
    })
  );
}

export async function toggleFavorite(id: string): Promise<LeadResponse> {
  return handle<LeadResponse>(
    await fetch(`${API_URL}/api/leads/${id}/favorite`, {
      method: "POST",
      headers: authHeaders(),
    })
  );
}

export async function recordContact(id: string, channel: string): Promise<{ status: string; channel: string }> {
  return handle<{ status: string; channel: string }>(
    await fetch(`${API_URL}/api/leads/${id}/contact`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ channel }),
    })
  );
}

export async function fetchNotes(id: string): Promise<Note[]> {
  return handle<Note[]>(await fetch(`${API_URL}/api/leads/${id}/notes`, {
    headers: authHeaders(),
  }));
}

export async function addNote(id: string, note: string): Promise<Note> {
  const params = new URLSearchParams({ note });
  return handle<Note>(
    await fetch(`${API_URL}/api/leads/${id}/notes?${params}`, {
      method: "POST",
      headers: authHeaders(),
    })
  );
}

export async function deleteNote(id: string, noteId: number): Promise<{ status: string }> {
  return handle<{ status: string }>(
    await fetch(`${API_URL}/api/leads/${id}/notes/${noteId}`, {
      method: "DELETE",
      headers: authHeaders(),
    })
  );
}

export async function enrichLeads(city: string = "NYC", limit: number = 500): Promise<{ status: string; processed: number; owners_found: number }> {
  return handle<{ status: string; processed: number; owners_found: number }>(
    await fetch(`${API_URL}/api/scraper/enrich?city=${city}&limit=${limit}`, {
      method: "POST",
      headers: authHeaders(),
    })
  );
}

export interface Notification {
  id: number;
  type: "new_lead" | "owner_enriched" | "contact_made" | "status_change" | "system";
  title: string;
  message: string;
  lead_id?: number;
  created_at: string;
  read: boolean;
}

export type NotificationFilter = "recent" | "unread" | "all";

export async function fetchNotifications(filter: NotificationFilter = "recent"): Promise<Notification[]> {
  return handle<Notification[]>(
    await fetch(`${API_URL}/api/notifications?filter=${filter}`, {
      headers: authHeaders(),
    })
  );
}

// ------------------------------------------------------------------
// Autenticação
// ------------------------------------------------------------------
export interface AuthUser {
  id: number;
  email: string;
  company_name?: string;
  plan?: string;
  subscription_status?: string;
  plan_until?: string;
  score: number;
  leads_taken: number;
  conversions: number;
  push_enabled?: boolean;
  created_at?: string;
}

export interface AuthResponse {
  token: string;
  user: AuthUser;
}

export async function registerUser(data: {
  email: string;
  password: string;
  company_name: string;
  locale?: string;
}): Promise<AuthResponse> {
  const res = await fetch(`${API_URL}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const out = await handle<AuthResponse>(res);
  setToken(out.token);
  setAuthCookie();
  return out;
}

export async function loginUser(data: { email: string; password: string }): Promise<AuthResponse> {
  const res = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const out = await handle<AuthResponse>(res);
  setToken(out.token);
  setAuthCookie();
  return out;
}

export async function logoutUser(): Promise<void> {
  try {
    await fetch(`${API_URL}/api/auth/logout`, {
      method: "POST",
      headers: { ...authHeaders() },
    });
  } catch {
    // ignora falha de rede no logout
  }
  setToken(null);
  clearAuthCookie();
}

export async function requestPasswordReset(email: string): Promise<{ message?: string }> {
  return handle<{ message?: string }>(
    await fetch(`${API_URL}/api/auth/forgot-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    }),
  );
}

export async function resetPassword(
  token: string,
  new_password: string,
  confirm_password: string,
): Promise<{ message?: string }> {
  return handle<{ message?: string }>(
    await fetch(`${API_URL}/api/auth/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, new_password, confirm_password }),
    }),
  );
}

export async function demoLogin(): Promise<AuthUser> {
  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";
  const res = await fetch(`${API_BASE}/api/auth/demo`, { method: "POST" });
  if (!res.ok) throw new Error("Demo login failed");
  const data = await res.json();
  setToken(data.token);
  setAuthCookie(data.token);
  return data.user;
}

// ------------------------------------------------------------------
// Billing: checkout Stripe (ou mock local) + ativação de semana
// ------------------------------------------------------------------
export interface CheckoutPlan {
  name: string;
  interval: string;
  amount_cents: number;
  amount_usd: number;
  annual_usd: number;
  price_id: string;
}

export interface CheckoutResponse {
  mock: boolean;
  checkout_url: string | null;
  plan: CheckoutPlan;
}

export interface ActivateWeekResponse {
  status: string;
  mock: boolean;
  plan?: string;
  subscription_status?: string;
  plan_until?: string;
}

export async function createCheckoutSession(): Promise<CheckoutResponse> {
  return handle<CheckoutResponse>(
    await fetch(`${API_URL}/api/billing/checkout`, {
      method: "POST",
      headers: { ...authHeaders() },
    })
  );
}

export async function activateWeekMock(): Promise<ActivateWeekResponse> {
  return handle<ActivateWeekResponse>(
    await fetch(`${API_URL}/api/billing/mock-activate`, {
      method: "POST",
      headers: { ...authHeaders() },
    })
  );
}

export async function fetchMe(): Promise<AuthUser> {
  return handle<AuthUser>(
    await fetch(`${API_URL}/api/auth/me`, { headers: { ...authHeaders() } })
  );
}

export async function updateCompanyName(userId: number, company_name: string): Promise<AuthUser> {
  return handle<AuthUser>(
    await fetch(`${API_URL}/api/users/${userId}/company`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ company_name }),
    })
  );
}

export async function updateUserLocale(userId: number, locale: string): Promise<AuthUser> {
  return handle<AuthUser>(
    await fetch(`${API_URL}/api/users/${userId}/locale`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ locale }),
    })
  );
}

export async function setPushEnabled(enabled: boolean): Promise<{ status: string; push_enabled: boolean }> {
  return handle<{ status: string; push_enabled: boolean }>(
    await fetch(`${API_URL}/api/push/enabled`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ enabled }),
    })
  );
}

export async function fetchPushEnabled(): Promise<boolean> {
  try {
    const r = await handle<{ subscriptions: { endpoint: string }[] }>(
      await fetch(`${API_URL}/api/push/subscriptions`, { headers: { ...authHeaders() } })
    );
    return (r.subscriptions?.length ?? 0) > 0;
  } catch {
    return false;
  }
}

// ------------------------------------------------------------------
// Interesses por usuário (categorias de alerta)
// ------------------------------------------------------------------
export async function fetchUserInterests(userId: number): Promise<string[]> {
  const r = await handle<{ categories: string[] }>(
    await fetch(`${API_URL}/api/users/${userId}/interests`, { headers: { ...authHeaders() } })
  );
  return r.categories;
}

export async function updateUserInterests(userId: number, categories: string[]): Promise<string[]> {
  const r = await handle<{ categories: string[] }>(
    await fetch(`${API_URL}/api/users/${userId}/interests`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ categories }),
    })
  );
  return r.categories;
}

// ------------------------------------------------------------------
// Notificações por usuário (sino)
// ------------------------------------------------------------------
export async function fetchUserNotifications(
  userId: number,
  filter: NotificationFilter = "recent",
  limit = 50
): Promise<Notification[]> {
  return handle<Notification[]>(
    await fetch(`${API_URL}/api/users/${userId}/notifications?filter=${filter}&limit=${limit}`, {
      headers: { ...authHeaders() },
    })
  );
}

export async function fetchUserUnreadCount(userId: number): Promise<number> {
  const r = await handle<{ unread: number }>(
    await fetch(`${API_URL}/api/users/${userId}/notifications/unread-count`, {
      headers: { ...authHeaders() },
    })
  );
  return r.unread;
}

export async function markUserNotificationRead(userId: number, notificationId: number): Promise<void> {
  await handle<{ status: string }>(
    await fetch(`${API_URL}/api/users/${userId}/notifications/${notificationId}/read`, {
      method: "POST",
      headers: { ...authHeaders() },
    })
  );
}

export async function markAllUserNotificationsRead(userId: number): Promise<number> {
  const r = await handle<{ status: string; marked: number }>(
    await fetch(`${API_URL}/api/users/${userId}/notifications/read-all`, {
      method: "POST",
      headers: { ...authHeaders() },
    })
  );
  return r.marked;
}

export interface SubscriptionStatus {
  status: string;
  is_active: boolean;
  can_access: boolean;
  message: string;
  days_remaining?: number;
  hours_remaining?: number;
  expires_at?: string;
  action?: string | null;
}

export interface DailyStats {
  used: number;
  limit: number;
  remaining: number;
  reset_at: string;
  reset_in_hours?: number;
}

export async function fetchUserSubscriptionStatus(userId: number): Promise<SubscriptionStatus> {
  return handle<SubscriptionStatus>(
    await fetch(`${API_URL}/api/users/${userId}/subscription-status`, {
      headers: { ...authHeaders() },
    })
  );
}

export async function fetchUserDailyStats(userId: number): Promise<DailyStats> {
  return handle<DailyStats>(
    await fetch(`${API_URL}/api/users/${userId}/daily-stats`, {
      headers: { ...authHeaders() },
    })
  );
}

export async function startUserTrial(userId: number): Promise<{ status: string; message: string }> {
  return handle<{ status: string; message: string }>(
    await fetch(`${API_URL}/api/users/${userId}/start-trial`, {
      method: "POST",
      headers: { ...authHeaders() },
    })
  );
}

// ------------------------------------------------------------------
// Status / Hold (reserva exclusiva) / pipeline
// ------------------------------------------------------------------
export interface LeadStatusInfo {
  id: number;
  external_id: string;
  address?: string;
  city?: string;
  issue_category?: string;
  lead_status?: string;
  reserved_by?: number;
  reserved_until?: string;
  contact_count: number;
  converted_by?: number;
  converted_at?: string;
  created_at?: string;
}

export interface HoldResult {
  reserved: boolean;
  status: string;
  expires_at?: string;
  message?: string;
  revealed?: boolean;
  counted_again?: boolean;
  used?: number;
  limit?: number;
  remaining?: number;
  reset_at?: string;
  owner?: {
    name?: string | null;
    phone?: string | null;
    email?: string | null;
    mailing_address?: string | null;
    address?: string | null;
    city?: string | null;
  };
}

export interface HistoryEvent {
  id: number;
  lead_id: number;
  event_type: string;
  detail?: string;
  created_at: string;
  user_id?: number;
}

export async function fetchLeadStatus(leadId: string | number): Promise<LeadStatusInfo> {
  return handle<LeadStatusInfo>(
    await fetch(`${API_URL}/api/leads/${leadId}/status`, { headers: { ...authHeaders() } })
  );
}

export async function reserveLead(
  leadId: string | number,
  minutes = 60,
  opts: { consent?: boolean; idempotency?: string } = {}
): Promise<HoldResult> {
  return handle<HoldResult>(
    await fetch(`${API_URL}/api/leads/${leadId}/reserve`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ minutes, consent: opts.consent ?? false, idempotency: opts.idempotency }),
    })
  );
}

export async function releaseLead(
  leadId: string | number,
  reason?: string,
  note?: string
): Promise<HoldResult> {
  return handle<HoldResult>(
    await fetch(`${API_URL}/api/leads/${leadId}/release`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ reason, note }),
    })
  );
}

export async function contactLead(leadId: string | number, channel = "sms"): Promise<{ status: string; channel: string; contact_count: number }> {
  return handle<{ status: string; channel: string; contact_count: number }>(
    await fetch(`${API_URL}/api/leads/${leadId}/contact`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ channel }),
    })
  );
}

export async function negotiateLead(leadId: string | number): Promise<{ status: string; lead_status: string }> {
  return handle<{ status: string; lead_status: string }>(
    await fetch(`${API_URL}/api/leads/${leadId}/negotiate`, {
      method: "POST",
      headers: { ...authHeaders() },
    })
  );
}

export async function convertLead(leadId: string | number): Promise<{ status: string; lead_status: string }> {
  return handle<{ status: string; lead_status: string }>(
    await fetch(`${API_URL}/api/leads/${leadId}/convert`, {
      method: "POST",
      headers: { ...authHeaders() },
    })
  );
}

export async function rejectLead(leadId: string | number, reason?: string): Promise<{ status: string; lead_status: string }> {
  return handle<{ status: string; lead_status: string }>(
    await fetch(`${API_URL}/api/leads/${leadId}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ reason }),
    })
  );
}

export async function fetchLeadHistory(leadId: string | number): Promise<HistoryEvent[]> {
  return handle<HistoryEvent[]>(
    await fetch(`${API_URL}/api/leads/${leadId}/history`, { headers: { ...authHeaders() } })
  );
}

export async function fetchLeadOccurrences(leadId: string | number): Promise<LeadOccurrence[]> {
  return handle<LeadOccurrence[]>(
    await fetch(`${API_URL}/api/leads/${leadId}/occurrences`, { headers: { ...authHeaders() } })
  );
}

// ------------------------------------------------------------------
// Histórico de ocorrências por imóvel (Parte B)
// ------------------------------------------------------------------
export interface LeadOccurrence {
  id?: number;
  lead_id?: number;
  external_id?: string;
  case_title?: string;
  descriptor?: string;
  subject?: string;
  reason?: string;
  case_status?: string;
  department?: string;
  opened_at?: string;
  closed_at?: string;
  resolution_description?: string;
  closure_reason?: string;
  source?: string;
  source_url?: string;
}

// ------------------------------------------------------------------
// Penalidades / métricas do contractor (Phase 4.2)
// ------------------------------------------------------------------
export const RELEASE_REASONS = [
  { value: "no_answer", key: "release.reason.no_answer", label: "Não respondeu", acceptable: true },
  { value: "declined", key: "release.reason.declined", label: "Cliente recusou o serviço", acceptable: true },
  { value: "out_of_area", key: "release.reason.out_of_area", label: "Fora da área de atendimento", acceptable: true },
  { value: "personal_emergency", key: "release.reason.personal_emergency", label: "Emergência pessoal", acceptable: true },
  { value: "changed_mind", key: "release.reason.changed_mind", label: "Mudei de ideia (sem motivo)", suspicious: true },
  { value: "lazy", key: "release.reason.lazy", label: "Peguei sem ter tempo", suspicious: true },
] as const;

export interface ContractorMetrics {
  contractor_id: number;
  releases_this_month: number;
  suspicious_releases: number;
  penalty_level: number;
  penalty_until?: string;
  last_penalty_reason?: string;
}

export async function fetchContractorMetrics(): Promise<ContractorMetrics> {
  return handle<ContractorMetrics>(
    await fetch(`${API_URL}/api/contractor/metrics`, { headers: { ...authHeaders() } })
  );
}

export async function fetchMyTakenLeads(limit = 100): Promise<LeadsListResponse> {
  return handle<LeadsListResponse>(
    await fetch(`${API_URL}/api/me/taken-leads?limit=${limit}`, { headers: { ...authHeaders() } })
  );
}

// ------------------------------------------------------------------
// Meus Leads / Histórico (histórico completo por usuário)
// ------------------------------------------------------------------
export type MyLeadStatus =
  | "reserved"
  | "negotiating"
  | "hold_expired"
  | "converted"
  | "released"
  | "available";

export interface MyLeadHistoryItem extends LeadResponse {
  my_status: MyLeadStatus;
  hold_status?: string;
  held_at?: string;
  hold_expires_at?: string;
  hold_released_at?: string;
  release_reason?: string;
  contact_count?: number;
  converted_at?: string;
  reserved_until?: string;
}

export interface MyLeadsHistoryKpis {
  total_reserved: number;
  converted: number;
  conversion_rate: number;
  today_used: number;
  today_limit: number;
  needs_action: number;
}

export interface MyLeadsHistoryResponse {
  kpis: MyLeadsHistoryKpis;
  leads: MyLeadHistoryItem[];
}

export async function fetchMyLeadsHistory(params: {
  status?: string;
  category?: string;
  period?: string;
  search?: string;
  needs_action?: boolean;
  limit?: number;
} = {}): Promise<MyLeadsHistoryResponse> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.category) qs.set("category", params.category);
  if (params.period) qs.set("period", params.period);
  if (params.search) qs.set("search", params.search);
  if (params.needs_action) qs.set("needs_action", "true");
  if (params.limit) qs.set("limit", String(params.limit));
  const q = qs.toString();
  return handle<MyLeadsHistoryResponse>(
    await fetch(`${API_URL}/api/me/history${q ? `?${q}` : ""}`, { headers: { ...authHeaders() } })
  );
}
