// Cliente do painel Admin (/admin).
//
// PT-only e interno. O gate de acesso NÃO vive aqui: cada endpoint
// /api/admin/* valida no backend que a sessão existe E que users.is_admin = 1.
// Este módulo só trata o resultado (200 = ok, 401 = sem sessão, 403 = sem role).
import { AUTH_TOKEN_KEY } from "./api-client";
import type { SystemHealth } from "./system-health";

export type { SystemHealth } from "./system-health";

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
    last_fact_at?: string | null;
    last_created_at?: string | null;
    facts_24h?: number;
    created_24h?: number;
    lead_total?: number;
    age_hours?: number | null;
    state?: "ok" | "warn" | "fail" | "unknown";
    state_reason?: string;
  };
}

export interface AdminSources {
  city_health: AdminCityHealth;
  last_run: AdminOverview["last_scraper_run"];
  freshness?: {
    last_run: {
      id: number;
      started_at: string;
      finished_at: string | null;
      hpd_checked: number;
      hpd_closed: number;
      dob_checked: number;
      dob_closed: number;
      history_refreshed: number;
      status: string;
      errors: string | null;
    } | null;
    age_hours: number | null;
    counts: { ok: number; warn: number; fail: number; unknown: number };
    state: "ok" | "warn" | "fail";
  };
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
  occurrences?: number;
  first_seen?: string | null;
  last_seen?: string | null;
  latest_id?: number | null;
}

// Fase 2 — custo das consultas pagas a Searchbug.
//
// `ghost_charges` é a métrica de dinheiro: consultas que chegaram ao
// provider e NÃO devolveram telefone. `saved_calls` são as que não
// custaram nada por terem sido cortadas por guard ou cache.
export interface AdminSearchbugMetrics {
  days: number;
  today: { calls: number; billed_calls: number; ghost_charges: number; cost_usd: number };
  totals: {
    calls: number;
    billed_calls: number;
    successes: number;
    ghost_charges: number;
    timeouts: number;
    saved_calls: number;
    cost_usd: number;
    transport_errors: number;
    name_mismatches: number;
  };
  success_rate: number | null;
  billed_rate: number | null;
  cost_per_success: number | null;
  latency: {
    avg_ms: number | null;
    p50_ms: number | null;
    p95_ms: number | null;
    max_ms: number | null;
    samples: number;
  };
  by_outcome: { outcome: string; n: number; billed_n: number }[];
  by_city: { city: string; calls: number; billed_calls: number; ghost_charges: number; cost_usd: number }[];
  recent: {
    id: number;
    called_at: string;
    outcome: string;
    billed: number;
    latency_ms: number | null;
    http_status: number | null;
    city: string | null;
    error: string | null;
    cost_usd: number;
    lead_id: number | null;
    owner_class: string | null;
    layer: string | null;
    name_match: number | null;
    transport_error: number;
  }[];
  buffer: { buffered: number; flushed: number; dropped: number; flush_errors: number };
}

// P2 — progresso da amostra por segmento ate' aos 30 que libertam a
// percentagem publica no cartao.
export interface AdminPhoneSampleRow {
  city?: string;
  owner_class: string;
  samples: number;
  successes: number;
  pct: number | null;
  ready: boolean;
  needed: number;
}

export interface AdminPhoneSampleProgress {
  days: number;
  min_samples: number;
  segments: AdminPhoneSampleRow[];
  by_class: AdminPhoneSampleRow[];
  ready_segments: number;
  total_segments: number;
  total_samples: number;
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
    clicks: number;
  };
  accepted_rate: number | null;
  ctr: number | null;
  live_subscriptions: number;
  total_subscriptions: number;
  devices: { user_id: number; active: number }[];
  dlq: { pending: number; dropped: number; oldest_age_seconds: number | null };
  latency: {
    avg_ms: number | null;
    p50_ms: number | null;
    p95_ms: number | null;
    max_ms: number | null;
    samples: number;
  };
  by_outcome: { outcome: string; n: number }[];
  by_kind: { kind: string; n: number; accepted: number; expired: number; clicks: number }[];
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
    notification_id: number | null;
    clicked_at: string | null;
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

export function ackAdminAlert(
  alertId: number
): Promise<{ ok: boolean; alert: AdminAlert }> {
  return adminFetch<{ ok: boolean; alert: AdminAlert }>(
    `/alerts/${alertId}/ack`,
    { method: "POST" }
  );
}

// ------------------------------------------------------ Data Plane (Fase 1)

export interface AdminIngestionRun {
  id: number;
  run_id: string;
  source: string;
  status: string;
  attempt: number;
  http_status: number | null;
  rows_fetched: number;
  rows_parsed: number;
  rows_upserted: number;
  watermark_before: string | null;
  watermark_after: string | null;
  error_code: string | null;
  error_detail: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface AdminIngestionFailure {
  id: number;
  run_id: string;
  source: string;
  url: string | null;
  http_status: number | null;
  error_class: string | null;
  retryable: number;
  next_retry_at: string | null;
  created_at: string;
}

export interface AdminIngestion {
  runs: AdminIngestionRun[];
  failures: AdminIngestionFailure[];
  by_status: Array<{ status: string; n: number }>;
  by_source: Array<{
    source: string;
    status: string;
    n: number;
    last_at: string | null;
  }>;
  scraper_runs: AdminScraperRun[];
  scraper_status: Array<{ status: string; n: number; inserted: number }>;
  last_success: { started_at: string; finished_at: string; source: string } | null;
  last_failure: {
    started_at: string;
    source: string;
    error_code: string | null;
  } | null;
  coverage_note: string;
}

export interface AdminQuarantineEntity {
  id: number;
  entity_id: number;
  reason: string;
  rule_id: string;
  status: string;
  evidence_json: string | null;
  evidence: Record<string, unknown> | null;
  created_at: string;
  legal_name: string | null;
  license: string | null;
  state: string | null;
  city: string | null;
  phone: string | null;
  entity_status: string | null;
}

export interface AdminQualityFinding {
  id: number;
  run_id: string;
  entity_id: number | null;
  company_id: number | null;
  rule_id: string;
  severity: string;
  status: string;
  evidence_json: string | null;
  evidence: Record<string, unknown> | null;
  created_at: string;
  resolved_at: string | null;
}

export interface AdminQuarantine {
  active: AdminQuarantineEntity[];
  active_count: number;
  reason_counts: Array<{ value: string; n: number }>;
  findings: AdminQualityFinding[];
  findings_by_rule: Array<{
    rule_id: string;
    severity: string;
    status: string;
    n: number;
  }>;
  findings_total: number;
  entity_status: Array<{ status: string; n: number }>;
  entity_quarantined_total: number;
  other_quarantined: number;
  note: string;
}

export interface AdminFreshnessRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  hpd_checked: number;
  hpd_closed: number;
  dob_checked: number;
  dob_closed: number;
  history_refreshed: number;
  status: string;
  errors: string | null;
}

export interface AdminFreshness {
  runs: AdminFreshnessRun[];
  last_run: AdminFreshnessRun | null;
  last_age_hours: number | null;
  by_status: Array<{ status: string; n: number }>;
  geocode: Array<{ status: string; n: number }>;
  geocode_total: number;
  health_remediations: Array<Record<string, unknown>>;
  health_remediations_count: number;
  health_remediations_implemented: boolean;
  sanitizer_runs: Array<{
    id: number;
    run_id: string;
    mode: string;
    findings_count: number;
    quarantined_count: number;
    started_at: string;
    finished_at: string | null;
  }>;
}

export interface AdminScoreBucket {
  bucket: number;
  label: string;
  n: number;
}

export interface AdminScoreSummary {
  total: number;
  min: number;
  max: number;
  avg: number;
  distinct_scores: number;
  updated_at: string | null;
  buckets: AdminScoreBucket[];
  snapshots: number;
  snapshots_without_components: number;
  last_run: {
    id: number;
    version: string;
    status: string;
    processed: number;
    errors: number;
    source_watermark: string | null;
    started_at: string;
    finished_at: string | null;
    summary_json: string | null;
  } | null;
}

export interface AdminDataPlane {
  generated_at: string;
  ingestion: AdminIngestion;
  quarantine: AdminQuarantine;
  freshness: AdminFreshness;
  score: AdminScoreSummary;
}

export interface AdminScoreDetail {
  id: number;
  company_name: string;
  score: number;
  trade: string | null;
  city: string | null;
  state: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  license_number: string | null;
  permit_count: number | null;
  permit_value_usd: number | null;
  years_active: number | null;
  employee_estimate: number | null;
  status: string | null;
  updated_at: string | null;
  snapshot: {
    company_id: number;
    score: number;
    version: string;
    components: Record<string, number> | null;
    quality_penalty: number;
    computed_at: string;
    source_event_id: string | null;
  } | null;
}

export function fetchAdminDataPlane(): Promise<AdminDataPlane> {
  return adminFetch<AdminDataPlane>("/data-plane");
}

export function fetchAdminDataPlaneIngestion(
  limit = 50
): Promise<AdminIngestion> {
  return adminFetch<AdminIngestion>(`/data-plane/ingestion?limit=${limit}`);
}

export function fetchAdminDataPlaneQuarantine(
  limit = 200
): Promise<AdminQuarantine> {
  return adminFetch<AdminQuarantine>(`/data-plane/quarantine?limit=${limit}`);
}

export function fetchAdminDataPlaneFreshness(
  limit = 50
): Promise<AdminFreshness> {
  return adminFetch<AdminFreshness>(`/data-plane/freshness?limit=${limit}`);
}

export function fetchVoiceScoreDistribution(): Promise<AdminScoreSummary> {
  return adminFetch<AdminScoreSummary>("/voice/score-distribution");
}

export function fetchVoiceCompanyScore(
  companyId: number
): Promise<AdminScoreDetail> {
  return adminFetch<AdminScoreDetail>(`/voice/companies/${companyId}/score`);
}

export function fetchAdminSearchbug(days = 7, recentLimit = 50): Promise<AdminSearchbugMetrics> {
  return adminFetch(`/searchbug?days=${days}&recent_limit=${recentLimit}`);
}

export function fetchAdminPhoneSampleProgress(days = 90): Promise<AdminPhoneSampleProgress> {
  return adminFetch(`/phone-sample-progress?days=${days}`);
}

export interface AdminDigestAb {
  days: number;
  min_samples: number;
  arms: {
    variant: string;
    sent: number;
    pushed: number;
    clicks: number;
    ctr: number | null;
    sample_ok: boolean;
  }[];
  leader: string | null;
}

export function fetchAdminDigestAb(days = 30): Promise<AdminDigestAb> {
  return adminFetch(`/digest-ab?days=${days}`);
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
  sendable_recipients: number;
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
  remaining_today: number;
  warmup_state: string;
  warmup_days: number;
  last_send_at?: string | null;
  paused_at?: string | null;
  paused_reason?: string | null;
  auto_ramp_enabled?: number;
  auto_ramp_cap?: number;
  auto_ramp_max?: number;
  auto_ramp_stage?: number;
  auto_ramp_last_step_at?: string | null;
  auto_ramp_hold_reason?: string | null;
  sent_48h?: number;
  failed_48h?: number;
  skipped_48h?: number;
  last_error?: string | null;
}

export interface AdminOutboundQueueBlocker {
  reason: string;
  detail: string;
  retry_at?: string | null;
}

export interface AdminOutboundStatus {
  send_enabled: boolean;
  enrich_enabled: boolean;
  quiet_hours_now: boolean;
  day: string;
  queued: number;
  queue_oldest_at?: string | null;
  queue_oldest_age_hours?: number | null;
  queue_oldest_city?: string;
  mailbox_remaining_today?: number;
  mailbox_cap_total?: number;
  mailbox_sent_today?: number;
  queue_blocker?: AdminOutboundQueueBlocker | null;
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
  batch_size?: number;
  max_spend_per_batch_usd?: number;
  city?: string | null;
}): Promise<AdminOutboundConfigUpdateResult> {
  return adminFetch<AdminOutboundConfigUpdateResult>("/outbound/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export interface AdminOutboundBatchRow {
  id: number;
  city: string;
  name: string;
  status: string;
  dry_run: number;
  contact_count: number;
  queued: number;
  sent: number;
  skipped: number;
  failed: number;
  sending: number;
  total: number;
  created_at: string;
  previewed_at: string | null;
}

export interface AdminOutboundMessageRow {
  id: number;
  to_email: string;
  subject: string;
  status: string;
  provider_id: string | null;
  queued_at: string;
  sent_at: string | null;
  error: string;
  from_addr: string;
  company_name: string;
  sequence_step: number;
  next_step_at: string | null;
  contact_id: number | null;
  replied_at: string;
  reply_sentiment?: string | null;
}

export function fetchAdminOutboundBatches(limit = 10): Promise<{ batches: AdminOutboundBatchRow[] }> {
  return adminFetch<{ batches: AdminOutboundBatchRow[] }>(`/outbound/batches?limit=${limit}`);
}

export function fetchAdminOutboundMessages(
  batchId: number,
  limit = 100
): Promise<{ batch_id: number; messages: AdminOutboundMessageRow[] }> {
  return adminFetch<{ batch_id: number; messages: AdminOutboundMessageRow[] }>(
    `/outbound/messages?batch_id=${batchId}&limit=${limit}`
  );
}

export function triggerAdminInboxSync(): Promise<Record<string, unknown>> {
  return adminFetch<Record<string, unknown>>("/outbound/inbox/sync", { method: "POST" });
}

export interface AdminOutboundHealth {
  checks: Array<{ check_name: string; status: string; detail: string; checked_at?: string }>;
  digest: string;
}

export function fetchAdminOutboundHealth(): Promise<AdminOutboundHealth> {
  return adminFetch<AdminOutboundHealth>("/outbound/health");
}

export function markAdminOutboundReplied(
  contactId: number
): Promise<{ status: string; contact_id: number; replied_at: string }> {
  return adminFetch<{ status: string; contact_id: number; replied_at: string }>(
    `/outbound/replied?contact_id=${contactId}`,
    { method: "POST" }
  );
}

export interface AdminBillingFunnel {
  funnel: {
    sessions_created: number;
    sessions_with_email: number;
    sessions_completed: number;
    sessions_expired: number;
    sessions_open: number;
    sessions_recovered: number;
    email_capture_rate: number;
    conversion_rate: number;
  };
  recovery: {
    enabled: boolean;
    channel_configured: boolean;
    after_minutes: number;
    max_reminders: number;
  };
  open_sessions: number;
}

export function fetchAdminBillingFunnel(): Promise<AdminBillingFunnel> {
  return adminFetch<AdminBillingFunnel>("/billing/funnel");
}

export function fetchAdminOutboundStatus(): Promise<AdminOutboundStatus> {
  return adminFetch<AdminOutboundStatus>("/outbound/status");
}

export interface AdminOutboundReadiness {
  city: string;
  niche: string;
  total: number;
  valid: number;
  confirmed: number;
  ready: number;
  quarantined: number;
  capacity_today: number;
  queue_blocker?: AdminOutboundQueueBlocker | null;
  by_niche: Array<{ niche_key: string; c: number }>;
}

export interface AdminContractorCityStats {
  counts: {
    city: string;
    total: number;
    by_status: Record<string, number>;
  };
  state: {
    city: string;
    day: string;
    jobs_today: number;
    last_entity_id?: number;
    last_run_at?: string | null;
  };
  enrich_enabled: boolean;
  quota?: number;
}

export interface AdminContractorStats {
  day: string;
  cities: Record<string, AdminContractorCityStats>;
}

export function fetchAdminContractorStats(
  city?: string | null
): Promise<AdminContractorStats> {
  const qs = city ? `?city=${encodeURIComponent(city)}` : "";
  return adminFetch<AdminContractorStats>(`/contractors/stats${qs}`);
}

export function runAdminContractorEnrichment(
  city?: string | null
): Promise<{ status: string; processed: number; cities: Record<string, unknown> }> {
  const qs = city ? `?city=${encodeURIComponent(city)}` : "";
  return adminFetch(`/contractors/run${qs}`, { method: "POST" });
}

export interface AdminOutboundCapacity {
  window_days: number;
  mailboxes_enabled: number;
  capacity_per_day: number;
  ready_now: number;
  produced: number;
  produced_per_day: number;
  days_of_cover: number | null;
  cities: Array<{
    city: string;
    ready_now: number;
    produced: number;
    produced_per_day: number;
    sent: number;
    sent_per_day: number;
  }>;
}

export function fetchAdminOutboundCapacity(
  days = 7
): Promise<AdminOutboundCapacity> {
  return adminFetch<AdminOutboundCapacity>(`/outbound/capacity?days=${days}`);
}

export interface AdminOutboundMetrics {
  days: number;
  mailboxes: Array<{
    id: number;
    email: string;
    sent: number;
    failed: number;
    bounced: number;
    complaints: number;
    replies: number;
    positive: number;
    bounce_rate: number;
    reply_rate: number;
    positive_rate: number;
  }>;
  totals: {
    sent: number;
    failed: number;
    bounced: number;
    complaints: number;
    replies: number;
    positive: number;
    bounce_rate: number;
    reply_rate: number;
    positive_rate: number;
  };
  by_email_source: Array<{
    source: string;
    contacts: number;
    replies: number;
    positive: number;
    reply_rate: number;
    positive_rate: number;
  }>;
  by_copy_variant: Array<{
    variant: string;
    sent: number;
    replies: number;
    positive: number;
    reply_rate: number;
    positive_rate: number;
  }>;
  copy_variants: {
    enabled: boolean;
    min_sends: number;
    sent_today: number;
    active: boolean;
    arms: string[];
  };
}

export function fetchAdminOutboundMetrics(
  days = 30
): Promise<AdminOutboundMetrics> {
  return adminFetch<AdminOutboundMetrics>(`/outbound/metrics?days=${days}`);
}

export function setAdminReplySentiment(
  contactId: number,
  sentiment: "positive" | "neutral" | "negative" | null
): Promise<{ status: string; contact_id: number; sentiment: string | null }> {
  const qs = new URLSearchParams({ contact_id: String(contactId) });
  if (sentiment) qs.set("sentiment", sentiment);
  return adminFetch(`/outbound/reply-sentiment?${qs.toString()}`, {
    method: "POST",
  });
}

export function fetchAdminOutboundReadiness(
  city: string,
  niche?: string | null
): Promise<AdminOutboundReadiness> {
  const qs = new URLSearchParams({ city });
  if (niche) qs.set("niche", niche);
  return adminFetch<AdminOutboundReadiness>(`/outbound/readiness?${qs.toString()}`);
}

export interface AdminMailboxControlsResult {
  status: string;
  mailbox: AdminOutboundStatusMailbox;
}

export function updateAdminMailboxControls(
  mailboxId: number,
  payload: {
    daily_cap?: number;
    auto_ramp_enabled?: boolean;
    auto_ramp_max?: number;
  }
): Promise<AdminMailboxControlsResult> {
  return adminFetch<AdminMailboxControlsResult>(
    `/outbound/mailboxes/${mailboxId}/controls`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function pauseAdminMailbox(
  mailboxId: number,
  reason = "manual"
): Promise<{ status: string; paused_reason: string }> {
  return adminFetch<{ status: string; paused_reason: string }>(
    `/outbound/mailboxes/${mailboxId}/pause`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }
  );
}

export function resumeAdminMailbox(
  mailboxId: number
): Promise<{ status: string }> {
  return adminFetch<{ status: string }>(
    `/outbound/mailboxes/${mailboxId}/resume`,
    { method: "POST" }
  );
}

export function triggerAdminOutboundWorker(limit?: number): Promise<AdminOutboundWorkerResult> {
  const qs = limit ? `?limit=${limit}` : "";
  return adminFetch<AdminOutboundWorkerResult>(`/outbound/worker${qs}`, { method: "POST" });
}

export interface AdminEnrichmentEnqueueResult {
  city: string;
  niche: string;
  candidates_found: number;
  jobs_created: number;
  pending_total: number;
}

export interface AdminEnrichmentQueueStatus {
  city: string | null;
  by_status: Record<string, number>;
  total: number;
  outbound_contacts: number;
}

/** Enfileira enriquecimento (descoberta + validacao RCPT via VPS). Nao bloqueia. */
export function enqueueAdminEnrichment(
  city: string,
  niche?: string,
  limit = 200
): Promise<AdminEnrichmentEnqueueResult> {
  const qs = new URLSearchParams({ city, limit: String(limit) });
  if (niche) qs.set("nicho", niche);
  return adminFetch<AdminEnrichmentEnqueueResult>(`/outbound/enrich/jobs?${qs}`, {
    method: "POST",
  });
}

export function fetchAdminEnrichmentStatus(
  city?: string
): Promise<AdminEnrichmentQueueStatus> {
  const qs = city ? `?city=${encodeURIComponent(city)}` : "";
  return adminFetch<AdminEnrichmentQueueStatus>(`/outbound/enrich/jobs/status${qs}`);
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

// ------------------------------------------------------------------
// Sessões ativas (A2) — listar e revogar
// ------------------------------------------------------------------
export interface AdminSession {
  id: number;
  user_id: number;
  email: string;
  company_name?: string | null;
  is_admin?: number;
  device_info?: string | null;
  ip_address?: string | null;
  created_at?: string | null;
  last_active_at?: string | null;
  expires_at?: string | null;
}

export function fetchAdminSessions(
  limit = 100
): Promise<{ sessions: AdminSession[]; count: number }> {
  return adminFetch<{ sessions: AdminSession[]; count: number }>(
    `/sessions?limit=${limit}`
  );
}

export function revokeAdminSession(
  sessionId: number
): Promise<{ revoked: boolean; session_id: number }> {
  return adminFetch<{ revoked: boolean; session_id: number }>(
    `/sessions/${sessionId}`,
    { method: "DELETE" }
  );
}

export function revokeAdminUserSessions(
  userId: number
): Promise<{ revoked_count: number; user_id: number }> {
  return adminFetch<{ revoked_count: number; user_id: number }>(
    `/users/${userId}/sessions`,
    { method: "DELETE" }
  );
}

// ------------------------------------------------------------------
// Concessão manual de acesso (cortesia)
// ------------------------------------------------------------------
export interface AdminAccessLookup {
  user: {
    id: number;
    email: string;
    company_name?: string | null;
    plan?: string | null;
    subscription_status?: string | null;
    plan_until?: string | null;
    is_admin: boolean;
    created_at?: string | null;
  };
  access: {
    status: string;
    is_active: boolean;
    can_access: boolean;
    days_remaining?: number;
    hours_remaining?: number;
    expires_at?: string | null;
    message: string;
    action?: string | null;
    access_source?: "admin_grant" | "subscription";
  };
}

export interface AdminAccessGrantResult {
  audit_id: number;
  duplicate?: boolean;
  user: { id: number; email: string };
  before: { plan?: string | null; subscription_status?: string | null; plan_until?: string | null };
  after: { plan: string; subscription_status: string; plan_until: string };
  days: number;
  reason: string;
}

export interface AdminAccessAuditEntry {
  id: number;
  created_at: string;
  admin_user_id: number;
  admin_email: string | null;
  action: "grant_access" | "revoke_access";
  target_user_id: number;
  target_email: string | null;
  days: number | null;
  reason: string | null;
  note: string | null;
  before_json: string | null;
  after_json: string | null;
  reversible: boolean;
  revoked: number;
}

export function lookupAdminUser(email: string): Promise<AdminAccessLookup> {
  return adminFetch<AdminAccessLookup>(
    `/users/lookup?email=${encodeURIComponent(email)}`
  );
}

export function grantAdminAccess(body: {
  email: string;
  days: number;
  reason: string;
  note?: string;
  idempotency_key?: string;
}): Promise<AdminAccessGrantResult> {
  return adminFetch<AdminAccessGrantResult>("/access/grant", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function revokeAdminAccess(
  auditId: number,
  reason?: string
): Promise<{ audit_id: number; related_audit_id: number }> {
  return adminFetch<{ audit_id: number; related_audit_id: number }>(
    "/access/revoke",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audit_id: auditId, reason }),
    }
  );
}

export function fetchAdminAccessAudit(
  limit = 50
): Promise<{ entries: AdminAccessAuditEntry[]; count: number }> {
  return adminFetch<{ entries: AdminAccessAuditEntry[]; count: number }>(
    `/access/audit?limit=${limit}`
  );
}

export interface AdminAnalyticsCard {
  value: number;
  delta_pct: number | null;
  spark: number[];
}

export interface AdminAnalyticsSource {
  source: string;
  medium: string;
  visits: number;
  visitors: number;
  pageviews: number;
  cta_clicks: number;
  form_submits: number;
}

export interface AdminAnalyticsGeo {
  country: string;
  region: string;
  city: string;
  visits: number;
  visitors: number;
  cta_clicks: number;
  form_submits: number;
}

export interface AdminAnalyticsCampaign {
  source: string;
  medium: string;
  campaign: string;
  content: string;
  visits: number;
  visitors: number;
  cta_clicks: number;
  form_submits: number;
  form_rate: number;
  cta_rate: number;
}

export interface AdminAnalyticsAttribution {
  visits: number;
  cta_clicks: number;
  form_submits: number;
  form_rate: number;
  rows: Array<{
    campaign: string;
    content: string;
    city: string;
    visits: number;
    visitors: number;
    cta_clicks: number;
    form_submits: number;
    form_rate: number;
    cta_rate: number;
  }>;
}

export interface AdminAnalytics {
  generated_at: string;
  range: string;
  start: string;
  end: string;
  window_start: string;
  window_end: string;
  overall: {
    score: number;
    status: "ok" | "warn" | "fail";
    status_label: string;
    reasons: string[];
    volume: number;
    engagement: number;
    conversion: number;
  };
  cards: Record<string, AdminAnalyticsCard>;
  series: Array<{
    t: string;
    visits: number;
    visitors: number;
    pageviews: number;
    cta: number;
    forms: number;
  }>;
  sources: AdminAnalyticsSource[];
  campaigns: AdminAnalyticsCampaign[];
  email_attribution: AdminAnalyticsAttribution;
  geo: AdminAnalyticsGeo[];
  funnel: Array<{ step: string; count: number; rate: number }>;
  events: Array<{ name: string; count: number; sessions: number }>;
  devices: Array<{ device: string; visits: number }>;
  locales: Array<{ locale: string; visits: number }>;
  recent: Array<{
    ts: string;
    name: string;
    path: string | null;
    label: string | null;
    source: string;
    medium: string;
    campaign: string;
    content: string;
    city: string;
  }>;
}

export function fetchAdminAnalytics(
  range = "7d",
  start?: string,
  end?: string
): Promise<AdminAnalytics> {
  const params = new URLSearchParams({ range });
  if (start && end) {
    params.set("start", start);
    params.set("end", end);
  }
  return adminFetch<AdminAnalytics>(`/analytics?${params.toString()}`);
}

export interface InvestorPriceBridge {
  ticket_weekly: number;
  monthly_factor: number;
  mrr_per_pass: number;
  arr_per_pass: number;
  access_passes: number;
  pro_active: number;
  weekly_run_rate_access: number;
  mrr_normalized_access: number;
  arr_normalized_access: number;
  weekly_run_rate_pro: number;
  mrr_normalized_pro: number;
  arr_normalized_pro: number;
}

export interface InvestorClaim {
  id: string;
  topic: string;
  title: string;
  our_position: string;
  competitor_position: string;
  competitor: string;
  source_title: string;
  source_publisher: string;
  source_url: string;
  source_date: string;
  captured_at: string;
  status: "verified" | "estimate" | "pending_legal";
  quote: string;
  note?: string;
}

export interface InvestorCompetitiveRow {
  dimension: string;
  magic: string;
  angi: string;
  edge: "magic" | "neutral" | "angi";
  source_ids: string[];
}

export interface InvestorRoom {
  generated_at: string;
  version: string;
  checksum: string;
  viewer_email: string;
  nda_accepted: boolean;
  nda_version: string;
  price_bridge: InvestorPriceBridge;
  reconciliation: {
    access_passes: number;
    pro_active: number;
    verified_paid_passes: number;
    completed_checkouts: number;
    stripe_completed_events: number;
    cash_30d: number | null;
    cash_total: number | null;
    cash_status: string;
    cash_mode: string | null;
    status: string;
    details: string;
  };
  asset: {
    owners: number;
    fresh7: number;
    data_low: number;
    data_high: number;
    ip_low: number;
    ip_high: number;
    compliance_low: number;
    compliance_high: number;
    floor_low: number;
    floor_high: number;
    basis: string;
  };
  going_concern: {
    access_arr: number;
    pro_arr: number;
    access_ev: { low: number; base: number; high: number };
    pro_ev: { low: number; base: number; high: number };
    multiple_ranges: { low: number; base: number; high: number };
  };
  proof: {
    truth_score: number;
    confidence: string;
    owner_coverage_pct: number;
    address_coverage_pct: number;
    fresh7_pct: number;
    fresh7: number;
    provenance_pct: number;
    phone: {
      status: string;
      calls: number;
      success: number;
      success_pct: number;
      error: number;
      error_billed: number;
      error_pct: number;
      no_results: number;
      name_mismatch: number;
      transport_error: number;
      cost_30d: number;
      cost_per_success: number | null;
    };
    email: {
      sent: number;
      bounces: number;
      bounce_rate_pct: number;
      replies_30d: number;
      suppressions: number;
      status: string;
    };
    operations: {
      health_status: string;
      health_score: number;
      captured_at: string;
      ingestion: string;
    };
    cost_per_owner_cash: number | null;
    cost_per_owner_loaded: number | null;
    anti_angi: { status: string; note: string };
  };
  metrics: Record<string, any>;
  analytics: Record<string, number>;
  assumptions: Record<string, any>;
  code_inventory: {
    python_lines: number;
    typescript_lines: number;
    pytest_tests: number;
    vitest_tests: number;
    test_files: number;
    docs: number;
    coverage_backend_pct: number | null;
    coverage_measured_at: string | null;
    ci: string;
    portability: string;
    known_debt: string[];
  };
  claims_register: {
    version: string;
    captured_at: string;
    items: InvestorClaim[];
  };
  competitive: InvestorCompetitiveRow[];
}

export interface InvestorSimulation {
  contractors: number;
  weekly_revenue: number;
  mrr_normalized: number;
  arr_normalized: number;
  searchbug_month: number;
  payment_fees_month: number;
  infra_month: number;
  cogs_month: number;
  gross_margin_pct: number;
  net_margin_pct: number;
  monthly_churn_pct: number;
  ltv: number | null;
  valuation: { low: number; base: number; high: number };
  asset_floor_low: number;
  asset_floor_high: number;
  ev_low: number;
  ev_high: number;
  notes: string[];
}

export function fetchInvestorRoom(): Promise<InvestorRoom> {
  return adminFetch<InvestorRoom>("/investor");
}

export function refreshInvestorRoom(): Promise<{ ok: boolean; snapshot: InvestorRoom }> {
  return adminFetch<{ ok: boolean; snapshot: InvestorRoom }>("/investor/refresh", {
    method: "POST",
  });
}

export function acceptInvestorNda(): Promise<{ ok: boolean; version: string }> {
  return adminFetch<{ ok: boolean; version: string }>("/investor/nda", {
    method: "POST",
  });
}

export function simulateInvestor(
  inputs: Record<string, number>
): Promise<InvestorSimulation> {
  return adminFetch<InvestorSimulation>("/investor/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inputs),
  });
}

export async function downloadInvestorCsv(): Promise<Blob> {
  const res = await fetch(`${API_URL}/api/admin/investor/export.csv`, {
    credentials: "include",
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new AdminApiError(res.status, res.statusText || "export failed");
  }
  return await res.blob();
}

export interface VoiceEligibility {
  allowed: boolean;
  reasons: string[];
  reason_labels: string[];
  checks: Record<string, boolean>;
  local_time: string;
}

export interface VoiceCompany {
  id: number;
  company_name: string;
  contact_name: string | null;
  phone: string;
  email: string | null;
  website: string | null;
  city: string | null;
  state: string;
  zip_code: string | null;
  license_number: string | null;
  license_status: string | null;
  trade: string | null;
  permit_count: number;
  permit_value_usd: number;
  years_active: number | null;
  employee_estimate: number | null;
  entity_type: string;
  consent_basis: string;
  status: string;
  score: number;
  last_attempt_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  eligibility: VoiceEligibility;
}

export interface VoiceQueue {
  items: VoiceCompany[];
  generated_at: string;
  limit: number;
  offset?: number;
  total: number;
  callable: number;
  include_blocked: boolean;
  filters?: {
    city: string;
    trade: string;
    state: string;
    score_min?: number | null;
    score_max?: number | null;
    status?: string;
    date_from?: string;
    date_to?: string;
  };
}

export interface VoiceGroup {
  name: string;
  total: number;
  callable: number;
  blocked: number;
}

export interface VoiceCampaign {
  campaign_id: string;
  calls: number;
  showcases: number;
  intents: number;
}

export interface VoiceStats {
  total: number;
  callable: number;
  blocked: number;
  attempts_today: number;
  meetings: number;
  dnc_listed: number;
  dnc_checked: number;
  suppressed: number;
  generated_at: string;
  pilot_state: string;
  pilot_states?: string[];
  staging_mode?: boolean;
  calling_window: string;
  dnc_max_age_days: number;
  max_attempts_7d: number;
  by_city?: VoiceGroup[];
  by_trade?: VoiceGroup[];
  campaigns?: VoiceCampaign[];
}

export interface VoiceImportResult {
  ok: boolean;
  source_id?: number;
  imported: number;
  updated?: number;
  skipped: number;
  total: number;
  listed?: number;
  cleaned?: number;
  format?: string;
  errors?: Array<{ row: number; reason: string }>;
}

export interface VoiceQueueFilters {
  city?: string;
  trade?: string;
  state?: string;
  scoreMin?: number | null;
  scoreMax?: number | null;
  status?: string;
  dateFrom?: string;
  dateTo?: string;
}

export function fetchVoiceQueue(
  includeBlocked = false,
  limit = 100,
  cityOrFilters: string | VoiceQueueFilters = "",
  trade = "",
  offset = 0
): Promise<VoiceQueue> {
  const filters: VoiceQueueFilters =
    typeof cityOrFilters === "string"
      ? { city: cityOrFilters, trade }
      : cityOrFilters;
  const params = new URLSearchParams({
    include_blocked: includeBlocked ? "1" : "0",
    limit: String(limit),
    offset: String(offset),
  });
  if (filters.city) params.set("city", filters.city);
  if (filters.trade) params.set("trade", filters.trade);
  if (filters.state) params.set("state", filters.state);
  if (filters.scoreMin !== null && filters.scoreMin !== undefined) {
    params.set("score_min", String(filters.scoreMin));
  }
  if (filters.scoreMax !== null && filters.scoreMax !== undefined) {
    params.set("score_max", String(filters.scoreMax));
  }
  if (filters.status) params.set("status", filters.status);
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  return adminFetch<VoiceQueue>(`/voice/queue?${params.toString()}`);
}

export function fetchVoiceStats(): Promise<VoiceStats> {
  return adminFetch<VoiceStats>("/voice/stats");
}

export function importVoiceLicenses(
  csv: string,
  sourceName: string,
  sourceUrl: string
): Promise<VoiceImportResult> {
  return adminFetch<VoiceImportResult>("/voice/import/licenses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ csv, source_name: sourceName, source_url: sourceUrl }),
  });
}

export function importVoiceDnc(
  csv: string,
  source: string
): Promise<VoiceImportResult> {
  return adminFetch<VoiceImportResult>("/voice/import/dnc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: csv, source }),
  });
}

export function stagingClearDnc(): Promise<{
  ok: boolean;
  cleared: number;
  mode: string;
  segments: number;
}> {
  return adminFetch("/voice/dnc/staging-clear", { method: "POST" });
}

export function scrubDnc(
  text: string,
  source: string
): Promise<{
  ok: boolean;
  import: VoiceImportResult;
  scrub: {
    ok: boolean;
    prospects: number;
    listed: number;
    cleared: number;
    dnc_numbers: number;
  };
  segments: number;
}> {
  return adminFetch("/voice/dnc/scrub", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, source }),
  });
}

export function checkVoiceDnc(
  phone: string,
  listed: boolean,
  source: string
): Promise<{ ok: boolean; phone: string; listed: boolean }> {
  return adminFetch<{ ok: boolean; phone: string; listed: boolean }>(
    "/voice/dnc/check",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, listed, source }),
    }
  );
}

export function logVoiceCall(
  companyId: number,
  payload: { outcome: string; notes?: string; callback_at?: string | null }
): Promise<{ ok: boolean; status: string }> {
  return adminFetch<{ ok: boolean; status: string }>(
    `/voice/contacts/${companyId}/call`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function suppressVoicePhone(
  phone: string,
  reason: string
): Promise<{ ok: boolean; phone: string; reason: string }> {
  return adminFetch<{ ok: boolean; phone: string; reason: string }>(
    "/voice/suppress",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, reason }),
    }
  );
}

export async function downloadVoiceTemplate(): Promise<Blob> {
  const res = await fetch(`${API_URL}/api/admin/voice/template.csv`, {
    credentials: "include",
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new AdminApiError(res.status, res.statusText || "template failed");
  }
  return await res.blob();
}

export interface ShowcaseStats {
  pages: number;
  links: number;
  visits: number;
  checkouts: number;
  completed: number;
  revenue_cents: number;
}

export interface ShowcaseBuildResult {
  ok: boolean;
  published: number;
  combos: number;
  min_items: number;
  window_days: number;
  built_at: string;
}

export interface ShowcaseSendResult {
  ok: boolean;
  reason?: string;
  link?: { link_id: number; url: string; token: string };
  email?: { sent: boolean; dry_run?: boolean; reason?: string; link_url?: string };
  page?: { count: number; title: string };
}

export function buildShowcasePages(): Promise<ShowcaseBuildResult> {
  return adminFetch<ShowcaseBuildResult>("/showcase/build", { method: "POST" });
}

export function fetchShowcaseStats(): Promise<ShowcaseStats> {
  return adminFetch<ShowcaseStats>("/showcase/stats");
}

export function sendVoiceShowcase(
  companyId: number,
  payload: { city?: string; trade?: string; campaign_id?: string } = {}
): Promise<ShowcaseSendResult> {
  return adminFetch<ShowcaseSendResult>(`/voice/contacts/${companyId}/showcase`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function dialVoiceContact(
  companyId: number,
  payload: { city?: string; trade?: string; campaign_id?: string } = {}
): Promise<{
  ok: boolean;
  dry_run?: boolean;
  voice_call_id?: number;
  status?: string;
  reason?: string;
  reason_labels?: string[];
}> {
  return adminFetch(`/voice/contacts/${companyId}/dial`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export interface VoiceSegment {
  city: string;
  state: string;
  trade: string;
  total: number;
  callable: number;
  blocked: number;
  showcase_mode: "dedicated" | "city_fallback" | "no_showcase";
  showcase_exact: number;
  showcase_city_total: number;
  page_path: string;
}

export interface VoiceCampaign {
  id: number;
  name: string;
  city: string | null;
  trade: string | null;
  status: string;
  max_calls: number;
  quota_total?: number;
  batch_size?: number;
  include_fallback?: number;
  dry_run?: number;
  budget_total_usd?: number;
  budget_daily_usd?: number;
  max_days?: number;
  start_hour_et?: number;
  call_interval_seconds?: number;
  batch_plan?: string | null;
  plan_index?: number;
  calls_started: number;
  showcases_sent: number;
  skipped: number;
  error: string | null;
  next_batch_at?: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface VoiceMetricsGroup {
  city: string;
  trade: string;
  state?: string;
  dialed: number;
  answered: number;
  engaged: number;
  accepts?: number;
  clicks: number;
  checkouts: number;
  answer_rate: number;
  accept_rate?: number;
  engagement_rate: number;
  showcase_ctr: number;
  checkout_rate: number;
  subscription_rate?: number;
  avg_listen_seconds: number;
  revenue_usd: number;
  revenue_per_accept_usd?: number;
  cost_usd: number;
  net_usd: number;
}

export interface VoiceRetentionBucket {
  seconds: number;
  count: number;
  pct_of_answered: number;
}

export interface VoiceMetrics {
  days: number;
  generated_at: string;
  summary: {
    dialed: number;
    answered: number;
    unanswered: number;
    engaged: number;
    accepts: number;
    clicks: number;
    checkouts: number;
    answer_rate: number;
    drop_rate: number;
    engagement_rate: number;
    accept_rate: number;
    showcase_ctr: number;
    checkout_rate: number;
    subscription_rate: number;
    avg_listen_seconds: number;
    revenue_usd: number;
    revenue_per_accept_usd: number;
    cost_usd: number;
    net_usd: number;
  };
  retention: VoiceRetentionBucket[];
  funnel: {
    dialed: number;
    answered: number;
    engaged: number;
    accepts: number;
    clicks: number;
    checkouts: number;
    revenue_usd: number;
  };
  by_state: VoiceMetricsGroup[];
  by_city: VoiceMetricsGroup[];
  by_trade: VoiceMetricsGroup[];
  by_city_trade: VoiceMetricsGroup[];
}

export interface VoiceLiveCall {
  id: number;
  company_id: number | null;
  company: string;
  phone: string;
  city: string;
  trade: string;
  status: string;
  amd_result: string;
  elapsed_seconds: number;
  listen_seconds: number;
  started_at?: string | null;
  answered_at?: string | null;
}

export interface VoiceLive {
  generated_at: string;
  campaign: {
    id: number;
    name: string;
    status: string;
    city: string;
    quota_total: number;
    calls_started: number;
    next_batch_at: string | null;
    error: string | null;
    include_fallback: number;
    start_hour_et: number;
    call_interval_seconds: number;
  } | null;
  summary: {
    dialed: number;
    answered: number;
    unanswered: number;
    human: number;
    voicemail: number;
    not_sure: number;
    optouts: number;
    disconnected: number;
    failed: number;
    real_attended: number;
    avg_listen_seconds: number;
    answer_rate: number;
    human_rate: number;
    voicemail_rate: number;
    optout_rate: number;
    cost_usd: number;
  };
  thermometer: {
    red: number;
    yellow: number;
    green: number;
    total: number;
    red_pct: number;
    yellow_pct: number;
    green_pct: number;
    basis: string;
    thresholds: { red: number; green: number };
  };
  day_cycle: {
    city: string;
    planned_calls: number;
    calls_done: number;
    calls_remaining: number;
    start_hour_et: number;
    started_at: string | null;
    finished_at: string | null;
    call_interval_seconds: number;
    pause_every: number;
    pause_seconds: number;
    estimated_finish_at: string;
    estimated_finish_earliest: string;
    estimated_finish_latest: string;
  };
  active_calls: VoiceLiveCall[];
  recent_calls: Array<Record<string, any>>;
}

export interface VoiceLiquidityRow {
  city: string;
  state: string;
  trade: string;
  total: number;
  callable: number;
  used_7d: number;
  available: number;
  exact: boolean;
  scope: "exact" | "city_fallback";
  showcase_items: number;
  built_at: string | null;
  age_hours: number | null;
}

export interface VoiceLiquidity {
  generated_at: string;
  cities: string[];
  exact_available: number;
  rows: VoiceLiquidityRow[];
}

export interface VoiceSource {
  id: number;
  name: string;
  kind: string;
  url: string | null;
  enabled: number;
  last_sync_at: string | null;
  last_status: string | null;
  last_error: string | null;
  created_at: string;
}

export interface VoiceIngestResult {
  ok: boolean;
  import: VoiceImportResult;
  showcase: ShowcaseBuildResult;
  segments: VoiceSegment[];
}

export function ingestVoice(
  csv: string,
  sourceName: string,
  sourceUrl: string
): Promise<VoiceIngestResult> {
  return adminFetch<VoiceIngestResult>("/voice/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ csv, source_name: sourceName, source_url: sourceUrl }),
  });
}

export function fetchVoiceSegments(
  city = "",
  trade = "",
  state = ""
): Promise<{ segments: VoiceSegment[] }> {
  const params = new URLSearchParams();
  if (city) params.set("city", city);
  if (trade) params.set("trade", trade);
  if (state) params.set("state", state);
  const qs = params.toString();
  return adminFetch<{ segments: VoiceSegment[] }>(
    `/voice/segments${qs ? `?${qs}` : ""}`
  );
}

export function startVoiceCampaign(payload: {
  name?: string;
  city?: string;
  trade?: string;
  max_calls?: number;
  quota_total?: number;
  batch_size?: number;
  include_fallback?: boolean;
  dry_run?: boolean;
  budget_total_usd?: number;
  budget_daily_usd?: number;
  max_days?: number;
  start_hour_et?: number;
  call_interval_seconds?: number;
  batch_plan?: number[];
}): Promise<{ ok: boolean; campaign: VoiceCampaign }> {
  return adminFetch<{ ok: boolean; campaign: VoiceCampaign }>(
    "/voice/campaigns/start",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function resumeVoiceCampaign(
  campaignId: number
): Promise<{ ok: boolean; campaign_id: number }> {
  return adminFetch<{ ok: boolean; campaign_id: number }>(
    `/voice/campaigns/${campaignId}/resume`,
    { method: "POST" }
  );
}

export function fetchVoiceMetrics(
  days = 30,
  city = "",
  trade = ""
): Promise<VoiceMetrics> {
  const params = new URLSearchParams({ days: String(days) });
  if (city) params.set("city", city);
  if (trade) params.set("trade", trade);
  return adminFetch<VoiceMetrics>(`/voice/metrics?${params.toString()}`);
}

export function fetchVoiceLive(
  campaignId?: number
): Promise<VoiceLive> {
  const params = new URLSearchParams();
  if (campaignId) params.set("campaign_id", String(campaignId));
  const qs = params.toString();
  return adminFetch<VoiceLive>(`/voice/live${qs ? `?${qs}` : ""}`);
}

export function fetchVoiceLiquidity(
  city = "",
  trade = ""
): Promise<VoiceLiquidity> {
  const params = new URLSearchParams();
  if (city) params.set("city", city);
  if (trade) params.set("trade", trade);
  const qs = params.toString();
  return adminFetch<VoiceLiquidity>(`/voice/liquidity${qs ? `?${qs}` : ""}`);
}

export function fetchVoiceSources(): Promise<{ sources: VoiceSource[] }> {
  return adminFetch<{ sources: VoiceSource[] }>("/voice/sources");
}

export function createVoiceSource(payload: {
  name: string;
  kind: string;
  url: string;
  enabled?: boolean;
}): Promise<{ ok: boolean; source: VoiceSource }> {
  return adminFetch<{ ok: boolean; source: VoiceSource }>("/voice/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function syncVoiceSource(
  sourceId: number
): Promise<{ ok: boolean; source_id: number; error?: string }> {
  return adminFetch<{ ok: boolean; source_id: number; error?: string }>(
    `/voice/sources/${sourceId}/sync`,
    { method: "POST" }
  );
}

export function syncLicensingSources(): Promise<{
  ok: boolean;
  source_id: number;
  import?: VoiceImportResult;
  segments?: number;
  error?: string;
}> {
  return adminFetch("/voice/sources/bridge-licensing", { method: "POST" });
}

export function fetchVoiceCampaigns(
  limit = 20
): Promise<{ campaigns: VoiceCampaign[] }> {
  return adminFetch<{ campaigns: VoiceCampaign[] }>(
    `/voice/campaigns?limit=${limit}`
  );
}

export function stopVoiceCampaign(
  campaignId: number
): Promise<{ ok: boolean; campaign: VoiceCampaign }> {
  return adminFetch<{ ok: boolean; campaign: VoiceCampaign }>(
    `/voice/campaigns/${campaignId}/stop`,
    { method: "POST" }
  );
}

export interface VoiceTestCallResult {
  ok: boolean;
  voice_call_id: number;
  provider_call_id?: string;
  status?: string;
  suppression_cleared?: number;
}

export function startVoiceTestCall(payload: {
  phone: string;
  city?: string;
  state?: string;
  trade?: string;
  company_name?: string;
}): Promise<VoiceTestCallResult> {
  return adminFetch<VoiceTestCallResult>("/voice/test-call", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true, ...payload }),
  });
}

export interface VoiceScript {
  trade_code: string;
  version: number;
  status: string;
  body: string;
  disclosure: string | null;
  voice_id: string | null;
  assistant_id: string | null;
  approved_by: number | null;
  approved_at: string | null;
  updated_at: string;
}

export interface VoiceScriptPreview {
  trade_code: string;
  version: number;
  status: string;
  assistant_id: string;
  body: string;
  disclosure: string;
  variables: Record<string, string>;
}

export function fetchVoiceScripts(): Promise<{ scripts: VoiceScript[] }> {
  return adminFetch<{ scripts: VoiceScript[] }>("/voice/scripts");
}

export function saveVoiceScript(
  tradeCode: string,
  payload: {
    body: string;
    disclosure?: string;
    assistant_id?: string;
    voice_id?: string;
  }
): Promise<{ ok: boolean; script: VoiceScript }> {
  return adminFetch<{ ok: boolean; script: VoiceScript }>(
    `/voice/scripts/${tradeCode}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function approveVoiceScript(
  tradeCode: string
): Promise<{ ok: boolean; script: VoiceScript }> {
  return adminFetch<{ ok: boolean; script: VoiceScript }>(
    `/voice/scripts/${tradeCode}/approve`,
    { method: "POST" }
  );
}

export function approveAllVoiceScripts(sync = true): Promise<{
  ok: boolean;
  approved: number;
  total: number;
  trades: string[];
  sync: {
    ok: boolean;
    status: string;
    synced: number;
    total?: number;
    errors: Array<{ trade_code: string; error: string }>;
  } | null;
}> {
  return adminFetch("/voice/scripts/approve-all", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sync }),
  });
}

export function syncAllVoiceScripts(): Promise<{
  ok: boolean;
  status: string;
  synced: number;
  total?: number;
  errors: Array<{ trade_code: string; error: string }>;
}> {
  return adminFetch("/voice/scripts/sync-all", { method: "POST" });
}

export function previewVoiceScript(
  tradeCode: string,
  payload: { company?: string; city?: string; permit_count?: number }
): Promise<VoiceScriptPreview> {
  return adminFetch<VoiceScriptPreview>(
    `/voice/scripts/${tradeCode}/preview`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export function syncVoiceScript(
  tradeCode: string
): Promise<{ ok: boolean; mode: string; assistant_id: string }> {
  return adminFetch(`/voice/scripts/${tradeCode}/sync-telnyx`, {
    method: "POST",
  });
}

/** Snapshot read-only do System Health (7 camadas + score 0–100). */
export function fetchSystemHealth(windowHours = 24): Promise<SystemHealth> {
  return adminFetch<SystemHealth>(
    `/system-health?window=${encodeURIComponent(String(windowHours))}`
  );
}