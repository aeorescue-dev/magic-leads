/**
 * Feature flag e cliente HTTP do widget de captação da landing page.
 *
 * `NEXT_PUBLIC_LP_WIDGET` é o interruptor público e fica **desligado por
 * omissão**. O widget nunca é montado na LP oficial enquanto a flag não for
 * `true`. A rota de pré-visualização usa `LP_WIDGET_PREVIEW` (server-side)
 * para permitir validação em staging sem ligar o widget na produção.
 */

export const LP_WIDGET_ENABLED =
  process.env.NEXT_PUBLIC_LP_WIDGET === "true";

/** Só deve ser lido em Server Components. */
export function isLpWidgetPreviewEnabled(): boolean {
  return process.env.LP_WIDGET_PREVIEW === "true" || LP_WIDGET_ENABLED;
}

export type LpIntent = "vs_ads" | "vs_angi" | "phones" | "price" | "area" | "question";

export interface LpThreadCreatePayload {
  intent: LpIntent;
  message: string;
  email: string;
  name?: string;
  company?: string;
  city?: string;
  trade?: string;
  trade_code?: string;
  lead_source?: string;
  consent_email: boolean;
  locale?: string;
  source_section?: string;
  /** Honeypot: deve ficar sempre vazio. */
  website?: string;
}

export interface LpThreadMessage {
  id: number;
  role: "lead" | "team";
  text: string;
  created_at: string;
}

export interface LpThread {
  id: number;
  status: string;
  created_at: string;
  sla_hours?: number;
  messages: LpThreadMessage[];
  attachments?: LpAttachment[];
}

export interface LpAttachment {
  id: number;
  message_id?: number | null;
  direction: "inbound" | "outbound";
  filename: string;
  content_type: string | null;
  size_bytes: number;
  created_at: string;
}

export interface LpAvailability {
  status: "online" | "offline";
  next_open_at: string | null;
  timezone: string;
  business_start: number;
  business_end: number;
  business_days: number[];
}

export interface LpThreadCreateResult {
  ok: boolean;
  token: string;
  thread_id: number;
  sla_hours: number;
  availability?: LpAvailability;
}

export class LpWidgetApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status = 0, code = "request_failed") {
    super(message);
    this.name = "LpWidgetApiError";
    this.status = status;
    this.code = code;
  }
}

const API_URL = (
  process.env.NEXT_PUBLIC_LP_WIDGET_API_URL || ""
).replace(/\/$/, "");

function endpoint(path: string): string {
  return `${API_URL}${path}`;
}

async function request<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(endpoint(path), {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers || {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new LpWidgetApiError(
      "Não foi possível contactar o servidor. Tente novamente.",
      0,
      "network_error"
    );
  }

  const raw = await response.text();
  let body: unknown = null;
  try {
    body = raw ? JSON.parse(raw) : null;
  } catch {
    body = null;
  }

  if (!response.ok) {
    const detail = body as { detail?: string; message?: string } | null;
    throw new LpWidgetApiError(
      detail?.detail || detail?.message || "Pedido recusado.",
      response.status,
      "http_error"
    );
  }

  return body as T;
}

export async function createLpThread(
  payload: LpThreadCreatePayload
): Promise<LpThreadCreateResult> {
  return request<LpThreadCreateResult>("/api/public/lp/threads", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchLpAvailability(): Promise<LpAvailability> {
  return request<LpAvailability>("/api/public/lp/availability");
}

export async function fetchLpThread(token: string): Promise<LpThread> {
  return request<LpThread>(
    `/api/public/lp/threads/${encodeURIComponent(token)}`
  );
}

export async function sendLpFollowUp(
  token: string,
  message: string
): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(
    `/api/public/lp/threads/${encodeURIComponent(token)}/messages`,
    {
      method: "POST",
      body: JSON.stringify({ message }),
    }
  );
}

export async function uploadLpAttachment(
  token: string,
  file: File
): Promise<LpAttachment> {
  const form = new FormData();
  form.append("file", file);
  let response: Response;
  try {
    response = await fetch(
      endpoint(`/api/public/lp/threads/${encodeURIComponent(token)}/attachments`),
      { method: "POST", body: form, cache: "no-store" }
    );
  } catch {
    throw new LpWidgetApiError(
      "Não foi possível anexar o ficheiro.",
      0,
      "network_error"
    );
  }
  if (!response.ok) {
    throw new LpWidgetApiError(
      "O ficheiro não foi aceite (máx. 10 MB).",
      response.status,
      "upload_failed"
    );
  }
  return (await response.json()) as LpAttachment;
}

export function lpAttachmentUrl(token: string, attachmentId: number): string {
  return endpoint(
    `/api/public/lp/threads/${encodeURIComponent(token)}/attachments/${attachmentId}`
  );
}

/** Eventos leves, sem dependência de fornecedor. */
export function trackLpWidget(
  event: string,
  payload: Record<string, unknown> = {}
): void {
  if (typeof window === "undefined") return;
  try {
    const w = window as unknown as {
      gtag?: (...args: unknown[]) => void;
      dataLayer?: unknown[];
      dispatchEvent?: (e: Event) => boolean;
    };
    if (typeof w.gtag === "function") {
      w.gtag("event", event, payload);
    } else if (Array.isArray(w.dataLayer)) {
      w.dataLayer.push({ event, ...payload });
    }
    w.dispatchEvent?.(
      new CustomEvent("lp-widget", { detail: { event, ...payload } })
    );
  } catch {
    // Analytics nunca pode quebrar a conversa.
  }
}
