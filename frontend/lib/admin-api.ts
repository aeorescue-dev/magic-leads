// Cliente do painel Admin (/admin).
//
// PT-only e interno. O gate de acesso NÃO vive aqui: cada endpoint
// /api/admin/* valida no backend que a sessão existe E que users.is_admin = 1.
// Este módulo só trata o resultado (200 = ok, 401 = sem sessão, 403 = sem role).
import { AUTH_TOKEN_KEY } from "./api-client";

const API_URL = (
  (typeof window !== "undefined" && (window as any).__NEXT_PUBLIC_API_URL) ||
  process.env.NEXT_PUBLIC_API_URL ||
  "https://magic-leads-production.up.railway.app"
).replace(/\/$/, "");

export type AdminAccess = "ok" | "unauthenticated" | "forbidden" | "error";

export class AdminApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function authHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = window.localStorage.getItem(AUTH_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function adminFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}/api/admin${path}`, {
    credentials: "include",
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* resposta sem JSON (ex.: 502 do proxy) */
    }
    throw new AdminApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

// --------------------------------------------------------------- tipos

export interface AdminOverview {
  generated_at: string;
  today: string;
  leads: { total: number; today: number; last_24h: number };
  users: { total: number; today: number };
  reveals: { today: number; active: number; returned_to_pool: number };
  credits: { used_today: number; refunded_today: number };
  alerts: { unacknowledged: number };
  last_scraper_run: {
    run_id: string;
    started_at: string;
    finished_at: string;
    status: string;
    inserted: number;
    cities_covered: number;
    error: string | null;
  } | null;
}

export interface AdminCityHealth {
  [city: string]: {
    failure_count?: number;
    circuit_open_until?: string | null;
    last_success_at?: string | null;
    anomaly_counter?: number;
  };
}

export interface AdminSources {
  city_health: AdminCityHealth;
  last_run: AdminOverview["last_scraper_run"];
}

export interface AdminScraperRun {
  run_id: string;
  trigger: string;
  started_at: string;
  finished_at: string;
  status: string;
  inserted: number;
  total_raw: number;
  cities_covered: number;
  error: string | null;
  note: string | null;
}

export interface AdminReveal {
  id: number;
  lead_id: number;
  user_id: number;
  revealed_at: string;
  revealed_date: string;
  returned_to_pool: number;
  contact_flagged: number;
  refunded: number;
  refund_reason: string | null;
  refunded_at: string | null;
  address: string | null;
  city: string | null;
  owner_name: string | null;
  has_phone: number;
}

export interface AdminAlert {
  id: number;
  level: string;
  code: string;
  message: string;
  context: string | null;
  acknowledged: number;
  created_at: string;
}

// --------------------------------------------------------------- calls

export function fetchAdminOverview(): Promise<AdminOverview> {
  return adminFetch<AdminOverview>("/overview");
}

export function fetchAdminSources(): Promise<AdminSources> {
  return adminFetch<AdminSources>("/sources");
}

export function fetchAdminScraperRuns(limit = 20): Promise<{ runs: AdminScraperRun[]; count: number }> {
  return adminFetch(`/scraper/runs?limit=${limit}`);
}

export function fetchAdminReveals(
  limit = 50,
  returnedOnly = false
): Promise<{ reveals: AdminReveal[]; count: number }> {
  const q = returnedOnly ? "&returned_only=true" : "";
  return adminFetch(`/reveals?limit=${limit}${q}`);
}

export function fetchAdminAlerts(limit = 50): Promise<{ alerts: AdminAlert[]; count: number }> {
  return adminFetch(`/alerts?limit=${limit}`);
}