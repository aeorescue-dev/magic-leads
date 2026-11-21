"use client";

import { getToken } from "@/lib/api-client";

const API_PROXY_MODE = process.env.NEXT_PUBLIC_API_PROXY === "true";
const API_URL = API_PROXY_MODE
  ? ""
  : (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8011").replace(/\/$/, "");

export interface SubscriptionPlan {
  code: string;
  name: string;
  price_cents: number;
  daily_phone_limit: number;
  daily_letter_limit: number;
  weekly_phone_total: number;
}

export interface AddonPack {
  code: string;
  phone_count: number;
  price_cents: number;
}

export interface Usage {
  date: string;
  plan: string;
  phone_limit: number;
  phone_used: number;
  phone_remaining: number;
  letter_limit: number;
  letter_used: number;
  letter_remaining: number;
  reset_at: string;
  addon_remaining: number;
  addon_expires_at: string | null;
  status?: string;
  can_access?: boolean;
  plan_until?: string | null;
  free_unlocks?: {
    enabled: boolean;
    granted: boolean;
    status?: string | null;
    phone: { total: number; used: number; remaining: number };
    letter: { total: number; used: number; remaining: number };
  };
}

export interface SubscriptionInfo {
  plan: string | null;
  status: string;
  can_access: boolean;
  plan_until: string | null;
  daily_phone_limit: number;
  daily_letter_limit: number;
  stripe_subscription_id: string | null;
  stripe_customer_id: string | null;
}

export interface LetterPayload {
  lead_id: number;
  type: "letter";
  trade_code: string;
  owner_name: string;
  address: string;
  city: string;
  state?: string;
  zip_code?: string;
  mailing_address: string | null;
  price_cents: number;
}

export interface PhonePayload {
  lead_id: number;
  type: "phone";
  trade_code: string;
  phone: string;
  /** true apenas com parcela exacta + nome compatível + camada L2. */
  verified?: boolean;
  /** owner_verified | property_phone_unverified | entity_phone_unverified */
  label?: string;
  owner_name: string;
  address: string;
  city: string;
  state?: string;
  zip_code?: string;
  price_cents: number;
}

export interface LetterResult {
  duplicate: boolean;
  reveal_id?: number;
  payload: LetterPayload;
  usage: Usage;
}

export interface PhoneResult {
  success: boolean;
  /** ready = número entregue; in_progress = job aceite (cache fria). */
  state?: "ready" | "in_progress" | "no_phone";
  duplicate?: boolean;
  reveal_id?: number;
  payload?: PhonePayload;
  usage?: Usage;
  error?: string;
  message?: string;
  quota_preserved?: boolean;
  verified?: boolean;
  label?: string;
}

export class SubscriptionApiError extends Error {
  status: number;
  code?: string;
  detail?: unknown;
  constructor(message: string, status: number, code?: string, detail?: unknown) {
    super(message);
    this.name = "SubscriptionApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
  const text = await res.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { detail: text };
  }
  if (!res.ok) {
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message || detail?.error || `HTTP ${res.status}`;
    throw new SubscriptionApiError(message, res.status, detail?.error, detail);
  }
  return body as T;
}

export function getBillingPlans() {
  return request<{ plans: SubscriptionPlan[]; addons: AddonPack[]; billing_mock: boolean; billing_model: string }>(
    "/api/billing/plans"
  );
}

export function getSubscriptionUsage() {
  return request<Usage>("/api/subscription/usage");
}

export function getSubscriptionInfo() {
  return request<SubscriptionInfo>("/api/billing/subscription");
}

export function revealLetter(leadId: number) {
  return request<LetterResult>(`/api/subscription/leads/${leadId}/reveal-letter`, {
    method: "POST",
    body: "{}",
  });
}

export function revealPhone(leadId: number, idempotencyKey: string, tradeCode?: string) {
  return request<PhoneResult>(`/api/subscription/leads/${leadId}/reveal-phone`, {
    method: "POST",
    body: JSON.stringify({
      idempotency_key: idempotencyKey,
      trade_code: tradeCode || undefined,
    }),
  });
}

export function createPlanCheckout(planCode: string, locale: string) {
  return request<{ mock: boolean; checkout_url: string | null; plan_code: string; plan: SubscriptionPlan }>(
    "/api/billing/checkout",
    { method: "POST", body: JSON.stringify({ plan_code: planCode, locale }) }
  );
}

export function createAddonCheckout(packCode: string, locale: string) {
  return request<{ mock: boolean; checkout_url: string | null; pack: AddonPack }>(
    "/api/billing/addons/checkout",
    { method: "POST", body: JSON.stringify({ pack_code: packCode, locale }) }
  );
}

export function createBillingPortal(locale: string) {
  return request<{ url: string }>("/api/billing/portal", {
    method: "POST",
    body: JSON.stringify({ locale }),
  });
}

/** Staging-only: ativa plano sem Stripe quando BILLING_MOCK=1. */
export function mockPlanCheckout(planCode: string) {
  return request<{ mock: boolean; plan: string; daily_phone_limit: number; daily_letter_limit: number }>(
    "/api/billing/mock-checkout",
    { method: "POST", body: JSON.stringify({ plan_code: planCode }) }
  );
}

/** Staging-only: injeta add-on quando ADDONS_MOCK=1. */
export function mockAddonPay(packCode: string) {
  return request<{ mock: boolean; addon: AddonPack; usage: Usage }>(
    "/api/billing/addons/mock-pay",
    { method: "POST", body: JSON.stringify({ pack_code: packCode }) }
  );
}
