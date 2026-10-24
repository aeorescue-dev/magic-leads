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

async function adminFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const { headers: optHeaders, ...rest } = options ?? {};
  const res = await fetch(`${API_URL}/api/admin${path}`, {
    credentials: "include",
    cache: "no-store",
    ...rest,
    headers: { ...authHeaders(), ...(optHeaders as Record<string, string> | undefined) },
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

// Fase 2 — custo das consultas pagas a Searchbug.
//
// `ghost_charges` é a métrica de dinheiro: consultas que chegaram ao
// provider e NÃO devolveram telefone. `saved_calls` são as que não
// custaram nada por terem sido cortadas por guard ou cache.
export interface AdminSearchbugMetrics {
  days: number;
  today: { calls: number; billed_calls: number; ghost_charges: number };
  totals: {
    calls: number;
    billed_calls: number;
    successes: number;
    ghost_charges: number;
    timeouts: number;
    saved_calls: number;
  };
  success_rate: number | null;
  latency: {
    avg_ms: number | null;
    p50_ms: number | null;
    p95_ms: number | null;
    max_ms: number | null;
    samples: number;
  };
  by_outcome: { outcome: string; n: number; billed_n: number }[];
  by_city: { city: string; calls: number; billed_calls: number; ghost_charges: number }[];
  recent: {
    id: number;
    called_at: string;
    outcome: string;
    billed: number;
    latency_ms: number | null;
    http_status: number | null;
    city: string | null;
    error: string | null;
  }[];
  buffer: { buffered: number; flushed: number; dropped: number; flush_errors: number };
}

// Fase 2 — saúde das entregas de push notification.
//
// `accepted` NÃO é entrega: é o serviço de push a aceitar a mensagem.
// `expired` (404/410) é o número que importa, porque uma alta contagem
// significa que parte do que enviamos estava a ir para o vazio.
export interface AdminPushMetrics {
  days: number;
  today: { deliveries: number; accepted: number; expired: number };
  totals: {
    deliveries: number;
    accepted: number;
    expired: number;
    rejected: number;
    rejected_dead: number;
    rate_limited: number;
    timeouts: number;
    errors: number;
    not_configured: number;
    no_subscriptions: number;
    retried: number;
  };
  accepted_rate: number | null;
  live_subscriptions: number;
  dlq: { pending: number; dropped: number; oldest_age_seconds: number | null };
  latency: {
    avg_ms: number | null;
    p50_ms: number | null;
    p95_ms: number | null;
    max_ms: number | null;
    samples: number;
  };
  by_outcome: { outcome: string; n: number }[];
  by_kind: { kind: string; n: number; accepted: number; expired: number }[];
  recent: {
    id: number;
    sent_at: string;
    outcome: string;
    attempts: number;
    latency_ms: number | null;
    http_status: number | null;
    kind: string | null;
    user_id: number | null;
    error: string | null;
  }[];
  buffer: { buffered: number; flushed: number; dropped: number; flush_errors: number };
}

// Alert Planner — orçamento diário de alertas (in-app + push) e excedente.
//
// `alerts_today` é o consumo combinado do dia (1 alerta = 1 unidade);
// `users_at_cap` são os utilizadores que esgotaram o teto `limit`;
// `digests_today` é o excedente enviado como digest (NÃO conta para o teto).
export interface AdminPlannerMetrics {
  day: string;
  limit: number;
  alerts_today: number;
  users_active: number;
  users_at_cap: number;
  digests_today: number;
  by_category: { category: string; alerts: number }[];
}

// Fase 3 — ledger append-only de créditos.
//
// event_type:
//   grant_daily       quota diária concedida (amount = +leads_limit)
//   grant_plan        acesso via Stripe concedeu dias (amount = +dias*limit)
//   consume_reveal    reveal com charge_credit=True (amount = -1)
//   refund_reveal     estorno devolve crédito (amount = +1)
//   searchbug_cost    chamada billed (amount = 0, metadata: custo)
//   stripe_payment    pagamento Stripe concedeu dias (amount = 0, metadata: dias)
//
// balance_after: saldo corrente derivado (soma de amounts até este evento)
// reference_id + reference_type: idempotência por evento origem
export interface AdminCreditLedgerEvent {
  id: number;
  created_at: string;
  user_id: number;
  event_type: "grant_daily" | "grant_plan" | "consume_reveal" | "refund_reveal" | "searchbug_cost" | "stripe_payment";
  amount: number;
  balance_after: number;
  reference_id: number | null;
  reference_type: string | null;
  metadata: Record<string, unknown> | null;
}

export interface AdminCreditBalance {
  balance: number;
  by_type: Record<string, { count: number; total_amount: number }>;
}

export interface AdminCreditLedgerResponse {
  user_id: number;
  ledger: AdminCreditLedgerEvent[];
  balance: AdminCreditBalance;
}

export interface AdminCreditReconcileResponse {
  discrepancies: Array<{
    user_id: number;
    type: string;
    detail: string;
    severity: "warning" | "error";
  }>;
  checked_users: number;
}

export interface AdminCreditBackfillResponse {
  status: "ok" | "error";
  counts?: Record<string, number>;
  detail?: string;
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

export function fetchAdminSearchbug(days = 7, recentLimit = 50): Promise<AdminSearchbugMetrics> {
  return adminFetch(`/searchbug?days=${days}&recent_limit=${recentLimit}`);
}

export function fetchAdminPush(days = 7, recentLimit = 50): Promise<AdminPushMetrics> {
  return adminFetch(`/push?days=${days}&recent_limit=${recentLimit}`);
}

export function fetchAdminPlanner(day?: string): Promise<AdminPlannerMetrics> {
  const q = day ? `?day=${day}` : "";
  return adminFetch(`/planner${q}`);
}

export function fetchAdminCreditLedger(
  userId: number,
  limit = 100,
  offset = 0
): Promise<AdminCreditLedgerResponse> {
  return adminFetch(`/credit-ledger?user_id=${userId}&limit=${limit}&offset=${offset}`);
}

export function fetchAdminCreditBalance(userId: number): Promise<AdminCreditBalance> {
  return adminFetch(`/credit-balance?user_id=${userId}`);
}

export function fetchAdminCreditBackfill(): Promise<AdminCreditBackfillResponse> {
  return adminFetch(`/credit-backfill`, { method: "POST" });
}

export function fetchAdminCreditReconcile(userId = 0): Promise<AdminCreditReconcileResponse> {
  const q = userId > 0 ? `?user_id=${userId}` : "";
  return adminFetch(`/credit-reconcile${q}`, { method: "POST" });
}

// ------------------------------------------------- Outbound (frio) — Fase 2
//
// O motor de envio REAL existe (Snov + Gmail API) mas continua fail-closed:
// só envia com `send_enabled=1`. Estes endpoints servem o selector por cidade,
// a simulação dry-run, os toggles do admin (config), o estado operacional
// (fila/tetos/warm-up) e o envio real. Todo o copy é SEMPRE inglês comercial
// americano (en-US), independentemente do idioma da plataforma.
export interface OutboundConfig {
  [key: string]: string;
}

export interface OutboundNiche {
  key: string;
  label: string;
  categories: string[];
}

export interface AdminOutboundConfigResponse {
  cities: string[];
  global: OutboundConfig;
  per_city: Record<string, OutboundConfig>;
  send_enabled: boolean;
  niches: OutboundNiche[];
  default_niche: string;
  language: string;
}

export interface AdminOutboundCostEstimate {
  batch_size: number;
  scrape_cost_usd: number;
  snov_emails: number;
  snov_per_email_usd: number;
  snov_fallback_rate: number;
  snov_cost_usd: number;
  total_usd: number;
}

export interface AdminOutboundBatch {
  id: number;
  city: string | null;
  name: string | null;
  kind: string;
  status: string;
  contact_count: number;
  est_cost_usd: number;
  actual_cost_usd: number;
  dry_run: number;
  created_by: number | null;
  created_at: string;
  previewed_at: string | null;
}

export interface AdminOutboundRecipientSample {
  id: number;
  company_name: string | null;
  contact_name: string | null;
  email: string | null;
  state: string | null;
}

export interface AdminOutboundOpportunitySample {
  owner_name: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  issue_category: string | null;
}

export interface AdminOutboundPreview {
  city: string;
  niche: string;
  niche_label: string;
  language: string;
  count: number;
  template: { subject: string; body: string };
  placeholders: string[];
  context: Record<string, string>;
  sample_source: "enriched_contact" | "lead_owner_fallback";
  recipient_sample: AdminOutboundRecipientSample | null;
  opportunity_sample: AdminOutboundOpportunitySample | null;
  preview: { subject: string; body: string };
}

export interface AdminOutboundSimulation extends Omit<AdminOutboundPreview, "city" | "count"> {
  city: string;
  qualified_available: number;
  batch_size: number;
  configured_batch_size: number;
  config: OutboundConfig;
  cost_estimate: AdminOutboundCostEstimate;
  over_budget: boolean;
  max_spend_per_batch_usd: string | number;
  send_enabled: boolean;
  batch: AdminOutboundBatch | null;
  dry_run: boolean;
}

export interface AdminOutboundQueuedResult {
  status: string;
  batch_id: number;
  queued: number;
  skipped: number;
  no_email: number;
  spend_usd: number;
  total_leads: number;
  batch: AdminOutboundBatch | null;
}

export interface AdminOutboundStatusMailbox {
  id: number;
  email: string;
  city: string;
  enabled: number;
  daily_cap: number;
  effective_cap: number;
  sent_today: number;
  warmup_state: string;
  warmup_days: number;
}

export interface AdminOutboundStatus {
  send_enabled: boolean;
  enrich_enabled: boolean;
  quiet_hours_now: boolean;
  day: string;
  queued: number;
  sent_today: number;
  enriched_today: number;
  spend_today_usd: number;
  enrichment_configured: boolean;
  enrichment_provider?: string;
  mailboxes: AdminOutboundStatusMailbox[];
  config: OutboundConfig;
}

export interface AdminOutboundConfigUpdateResult {
  status: string;
  city: string | null;
  send_enabled: boolean;
  enrich_enabled: boolean;
  config: OutboundConfig;
}

export interface AdminOutboundWorkerResult {
  status: string;
  sent: number;
  skipped?: number;
  failed?: number;
}

export function fetchAdminOutboundConfig(): Promise<AdminOutboundConfigResponse> {
  return adminFetch<AdminOutboundConfigResponse>("/outbound/config");
}

export function updateAdminOutboundConfig(payload: {
  send_enabled?: boolean;
  enrich_enabled?: boolean;
  city?: string | null;
}): Promise<AdminOutboundConfigUpdateResult> {
  return adminFetch<AdminOutboundConfigUpdateResult>("/outbound/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function fetchAdminOutboundStatus(): Promise<AdminOutboundStatus> {
  return adminFetch<AdminOutboundStatus>("/outbound/status");
}

export function triggerAdminOutboundWorker(limit?: number): Promise<AdminOutboundWorkerResult> {
  const qs = limit ? `?limit=${limit}` : "";
  return adminFetch<AdminOutboundWorkerResult>(`/outbound/worker${qs}`, { method: "POST" });
}

export function generateAdminOutboundPreview(
  city: string,
  niche?: string
): Promise<AdminOutboundPreview> {
  return adminFetch<AdminOutboundPreview>("/outbound/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ city, niche: niche ?? null }),
  });
}

export function simulateAdminOutbound(
  city: string,
  batchSize?: number,
  niche?: string
): Promise<AdminOutboundSimulation> {
  return adminFetch<AdminOutboundSimulation>("/outbound/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ city, batch_size: batchSize ?? null, niche: niche ?? null }),
  });
}

export function sendAdminOutbound(
  batchId: number,
  city?: string
): Promise<AdminOutboundQueuedResult> {
  return adminFetch<AdminOutboundQueuedResult>("/outbound/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ batch_id: batchId, city: city ?? null }),
  });
}

export interface AdminOutboundImportItem {
  email: string;
  company_name: string;
  city: string;
  category?: string;
  contact_name?: string;
  domain?: string;
  state?: string;
}

export interface AdminOutboundImportResult {
  status: string;
  imported: number;
  failed: number;
  total: number;
}

export function importAdminB2BLeads(leads: AdminOutboundImportItem[]): Promise<AdminOutboundImportResult> {
  return adminFetch<AdminOutboundImportResult>("/outbound/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ leads }),
  });
}

export interface AdminPushTestResult {
  status: "ok";
  sent: number;
  subscriptions: number;
  configured: boolean;
}

export function sendAdminTestPush(body?: {
  title?: string;
  body?: string;
  url?: string;
}): Promise<AdminPushTestResult> {
  return adminFetch<AdminPushTestResult>("/push/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}