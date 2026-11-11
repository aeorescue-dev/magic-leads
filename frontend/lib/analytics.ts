// Beacon de Web Analytics first-party (Fase 29).
//
// Sem cookies, sem fingerprint, sem scripts de terceiros. Os eventos ficam em
// memória e são enviados em lote para `/api/track` (same-origin) depois do
// primeiro render útil; nenhum request bloqueia o LCP.

export type AnalyticsEventName =
  | "pageview"
  | "cta_click"
  | "form_start"
  | "form_submit"
  | "checkout_started"
  | "scroll"
  | "outbound_click"
  | "language_switch"
  | "pricing_view";

interface SessionState {
  id: string;
  started_at: string;
  last_seen_at: string;
  landing_path: string;
  referrer: string;
  utm: Record<string, string>;
  locale: string;
  pageviews: number;
  engagement_ms: number;
  scroll_pct: number;
}

interface QueuedEvent {
  uid: string;
  name: AnalyticsEventName;
  ts: string;
  path: string;
  label?: string;
  value?: number;
}

const STORAGE_KEY = "ml.analytics.session.v1";
const SESSION_MAX_MS = 30 * 60 * 1000;

type TrackFn = (
  name: AnalyticsEventName,
  label?: string,
  value?: number
) => void;
let activeTrack: TrackFn | null = null;

/** Enfileira um evento no beacon ativo (no-op se o beacon não estiver montado). */
export function trackEvent(
  name: AnalyticsEventName,
  label?: string,
  value?: number
): void {
  try {
    activeTrack?.(name, label, value);
  } catch {
    /* analytics nunca deve quebrar a UI */
  }
}

export function isTrackablePath(pathname: string): boolean {
  if (!pathname) return false;
  return !(
    pathname.startsWith("/admin") ||
    pathname.startsWith("/dashboard") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/_next")
  );
}

export function parseUtm(search: string): Record<string, string> {
  try {
    const params = new URLSearchParams(search || "");
    const out: Record<string, string> = {};
    for (const key of ["source", "medium", "campaign", "content", "term"]) {
      const value = params.get(`utm_${key}`);
      if (value) out[key] = value.slice(0, 80);
    }
    return out;
  } catch {
    return {};
  }
}

export function sessionExpired(lastSeenAt: string, nowMs = Date.now()): boolean {
  const ts = Date.parse(lastSeenAt);
  if (Number.isNaN(ts)) return true;
  return nowMs - ts > SESSION_MAX_MS;
}

function randomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function loadSession(): SessionState | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SessionState;
    if (!parsed?.id || sessionExpired(parsed.last_seen_at)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function saveSession(session: SessionState): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    /* private mode / quota */
  }
}

function newSession(): SessionState {
  const now = new Date().toISOString();
  const path = isTrackablePath(location.pathname) ? location.pathname : "/";
  let referrer = "";
  try {
    referrer = document.referrer ? new URL(document.referrer).origin : "";
  } catch {
    referrer = "";
  }
  const locale =
    (document.documentElement.lang || path.split("/")[1] || "en").slice(0, 2);
  return {
    id: randomId(),
    started_at: now,
    last_seen_at: now,
    landing_path: path,
    referrer,
    utm: parseUtm(location.search),
    locale,
    pageviews: 0,
    engagement_ms: 0,
    scroll_pct: 0,
  };
}

export function startAnalytics(): () => void {
  if (typeof window === "undefined") return () => undefined;
  if (navigator.doNotTrack === "1") return () => undefined;
  if ((window as any).globalPrivacyControl === true) return () => undefined;
  if (!isTrackablePath(location.pathname)) return () => undefined;

  let session = loadSession() || newSession();
  session.pageviews += 1;
  session.last_seen_at = new Date().toISOString();

  const queue: QueuedEvent[] = [];
  let dirty = true;
  let stopped = false;
  let lastTick = performance.now();
  const seenForms = new Set<string>();
  const scrollThresholds = new Set<number>();

  const enqueue = (
    name: AnalyticsEventName,
    label?: string,
    value?: number
  ) => {
    queue.push({
      uid: randomId(),
      name,
      ts: new Date().toISOString(),
      path: location.pathname,
      ...(label ? { label: label.slice(0, 80) } : {}),
      ...(value !== undefined ? { value } : {}),
    });
    dirty = true;
  };

  activeTrack = enqueue;

  const flush = () => {
    if (stopped) return;
    if (!queue.length && !dirty) return;
    session.last_seen_at = new Date().toISOString();
    saveSession(session);
    const payload = JSON.stringify({
      session,
      events: queue.splice(0, 20),
      context: { referrer: session.referrer },
    });
    dirty = false;
    try {
      const blob = new Blob([payload], { type: "application/json" });
      if (navigator.sendBeacon && navigator.sendBeacon("/api/track", blob)) {
        return;
      }
    } catch {
      /* fallback */
    }
    try {
      void fetch("/api/track", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
        keepalive: true,
      });
    } catch {
      /* nunca rebenta a página */
    }
  };

  enqueue("pageview");

  const onClick = (event: MouseEvent) => {
    const target = event.target as Element | null;
    if (!target) return;
    const tracked = target.closest("[data-track]");
    if (tracked) {
      enqueue("cta_click", tracked.getAttribute("data-track") || "");
      return;
    }
    const anchor = target.closest("a[href]") as HTMLAnchorElement | null;
    if (!anchor) return;
    try {
      const url = new URL(anchor.href, location.href);
      if (/^https?:$/.test(url.protocol) && url.origin !== location.origin) {
        enqueue("outbound_click", url.host);
      }
    } catch {
      /* href inválido */
    }
  };

  const onFocusIn = (event: FocusEvent) => {
    const target = event.target as Element | null;
    const form = target?.closest("form[data-track-form]") as HTMLFormElement | null;
    if (!form) return;
    const label = form.getAttribute("data-track-form") || "form";
    if (seenForms.has(label)) return;
    seenForms.add(label);
    enqueue("form_start", label);
  };

  const onSubmit = (event: Event) => {
    const form = event.target as HTMLFormElement | null;
    if (!form) return;
    const label = form.getAttribute("data-track-form");
    if (!label) return;
    enqueue("form_submit", label);
    flush();
  };

  const onScroll = () => {
    if (stopped) return;
    const doc = document.documentElement;
    const max = doc.scrollHeight - window.innerHeight;
    const pct = max > 0 ? Math.min(100, Math.round((window.scrollY / max) * 100)) : 100;
    session.scroll_pct = Math.max(session.scroll_pct, pct);
    dirty = true;
    for (const threshold of [25, 50, 75, 100]) {
      if (pct >= threshold && !scrollThresholds.has(threshold)) {
        scrollThresholds.add(threshold);
        enqueue("scroll", undefined, threshold);
      }
    }
  };

  const onVisibility = () => {
    if (document.visibilityState === "hidden") {
      const delta = performance.now() - lastTick;
      if (delta > 0) session.engagement_ms += Math.min(delta, 60_000);
      dirty = true;
      flush();
    } else {
      lastTick = performance.now();
    }
  };

  const onPageHide = () => {
    const delta = performance.now() - lastTick;
    if (document.visibilityState === "visible" && delta > 0) {
      session.engagement_ms += Math.min(delta, 60_000);
      dirty = true;
    }
    flush();
  };

  const timer = window.setInterval(() => {
    if (document.visibilityState !== "visible") return;
    const now = performance.now();
    session.engagement_ms += Math.min(now - lastTick, 60_000);
    lastTick = now;
    dirty = true;
    flush();
  }, 15_000);

  // Primeiro flush só depois do render estar estável.
  const idle = (window as any).requestIdleCallback;
  const idleId = idle
    ? idle(() => flush(), { timeout: 2500 })
    : window.setTimeout(() => flush(), 2000);

  document.addEventListener("click", onClick, true);
  document.addEventListener("focusin", onFocusIn, true);
  document.addEventListener("submit", onSubmit, true);
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("pagehide", onPageHide);

  return () => {
    stopped = true;
    if (activeTrack === enqueue) activeTrack = null;
    window.clearInterval(timer);
    if (idle && typeof (window as any).cancelIdleCallback === "function") {
      (window as any).cancelIdleCallback(idleId);
    } else {
      window.clearTimeout(idleId);
    }
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("focusin", onFocusIn, true);
    document.removeEventListener("submit", onSubmit, true);
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("scroll", onScroll);
    window.removeEventListener("pagehide", onPageHide);
    flush();
  };
}
