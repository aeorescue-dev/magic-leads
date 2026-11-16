"use client";

import { getToken } from "@/lib/api-client";

const API_PROXY_MODE = process.env.NEXT_PUBLIC_API_PROXY === "true";
const API_URL = API_PROXY_MODE
  ? ""
  : (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8011").replace(/\/$/, "");

export interface CreditPack {
  code: string;
  price_cents: number;
  credits_cents: number;
  bonus_cents: number;
  label: string;
  sort_order?: number;
}

export interface Wallet {
  balance_cents: number;
  reserved_cents: number;
  available_cents: number;
  balance_usd: number;
}

export interface CreditLead {
  id: number;
  city: string;
  trade_code: string;
  zone: string;
  date_reported?: string;
  title: string;
  address_masked: string;
  owner_masked: string;
  mailing_ready: boolean;
  signal_ready: boolean;
  phone_ready: boolean;
  signal_price_cents: number;
  phone_price_cents: number;
  exclusive: boolean;
  exclusive_mine: boolean;
  exclusive_until?: string | null;
}

export interface RevealPayload {
  lead_id: number;
  type: string;
  trade_code: string;
  address: string;
  city: string;
  state?: string;
  zip_code?: string;
  owner_name: string;
  mailing_address: string;
  phone: string | null;
  exclusive_until: string;
  price_cents: number;
}

export interface RevealResult {
  duplicate: boolean;
  reveal_id: number;
  payload: RevealPayload;
  wallet: Wallet;
  balance_after_cents?: number;
}

export interface LedgerEntry {
  id: number;
  created_at: string;
  event_type: string;
  amount: number;
  balance_after: number | null;
  reference_type?: string;
  reference_id?: string;
  metadata?: string;
}

export interface CheckoutResult {
  mock: boolean;
  purchase_id: number;
  checkout_url?: string | null;
  pack?: CreditPack;
  message?: string;
}

export class CreditsApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
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
    throw new CreditsApiError(message, res.status, detail?.error);
  }
  return body as T;
}

export function getPacks() {
  return request<{ packs: CreditPack[]; signal_price_cents: number; phone_price_cents: number; phone_enabled: boolean }>(
    "/api/credits/packs"
  );
}

export function getWallet() {
  return request<Wallet>("/api/credits/wallet");
}

export function getLeads(params: { trade_code?: string; city?: string; limit?: number } = {}) {
  const q = new URLSearchParams();
  if (params.trade_code) q.set("trade_code", params.trade_code);
  if (params.city) q.set("city", params.city);
  if (params.limit) q.set("limit", String(params.limit));
  return request<{ leads: CreditLead[] }>(`/api/credits/leads?${q.toString()}`);
}

export function getPreview(leadId: number, tradeCode?: string) {
  const q = tradeCode ? `?trade_code=${encodeURIComponent(tradeCode)}` : "";
  return request<{ masked: boolean; already_revealed: boolean; lead?: CreditLead; reveal?: RevealPayload; blocked_reason?: string | null }>(
    `/api/credits/leads/${leadId}${q}`
  );
}

export function revealSignal(leadId: number, tradeCode: string, idempotencyKey: string) {
  return request<RevealResult>("/api/credits/reveal", {
    method: "POST",
    body: JSON.stringify({
      type: "signal",
      lead_id: leadId,
      trade_code: tradeCode,
      idempotency_key: idempotencyKey,
    }),
  });
}

export function createCreditCheckout(packCode: string, locale: string) {
  return request<CheckoutResult>("/api/credits/checkout", {
    method: "POST",
    body: JSON.stringify({ pack_code: packCode, locale }),
  });
}

export function mockPay(purchaseId: number) {
  return request<{ ok: boolean; duplicate?: boolean; wallet?: Wallet }>("/api/credits/mock-pay", {
    method: "POST",
    body: JSON.stringify({ purchase_id: purchaseId }),
  });
}

export function mockWebhook(purchaseId: number, eventId: string) {
  return request<{ ok: boolean; duplicate?: boolean; wallet?: Wallet }>("/api/credits/mock-webhook", {
    method: "POST",
    body: JSON.stringify({ purchase_id: purchaseId, event_id: eventId }),
  });
}

export function getLedger(limit = 50) {
  return request<{ entries: LedgerEntry[] }>(`/api/credits/ledger?limit=${limit}`);
}
