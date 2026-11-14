import { TRADE_CATEGORIES } from "@/lib/categories";

const SEVERITY_KEYS: Record<string, string> = {
  critical: "dashboard.severity.critical",
  high: "dashboard.severity.high",
  medium: "dashboard.severity.medium",
  routine: "dashboard.severity.routine",
  emergency: "dashboard.severity.emergency",
  immediate: "dashboard.severity.immediate",
  class_1: "dashboard.severity.class_1",
  class_2: "dashboard.severity.class_2",
  class_3: "dashboard.severity.class_3",
  class_a: "dashboard.severity.class_a",
  class_b: "dashboard.severity.class_b",
  class_c: "dashboard.severity.class_c",
};

export function severityKey(value?: string | null): string {
  return SEVERITY_KEYS[String(value || "").toLowerCase()] || "dashboard.severity.medium";
}

export function severityColor(value?: string | null): string {
  const key = String(value || "").toLowerCase();
  if (key === "critical" || key === "immediate" || key === "emergency" || key === "class_1" || key === "class_c") {
    return "#ef4444";
  }
  if (key === "high" || key === "class_2" || key === "class_b") {
    return "#f59e0b";
  }
  if (key === "medium" || key === "class_a") return "#2563eb";
  return "#64748b";
}

export function categoryLabelKey(value?: string | null): string | null {
  if (!value) return null;
  if (value === "Unclassified" || value === "General") {
    return "dashboard.cat.general";
  }
  return TRADE_CATEGORIES.find((c) => c.key === value)?.labelKey || null;
}

const POSSIBLE_VALUES = new Set(["possible", "possível", "posible"]);

export function severityBucket(value?: string | null): "critical" | "high" | "medium" | "routine" {
  const key = String(value || "").toLowerCase();
  if (["critical", "immediate", "emergency", "class_1", "class_c"].includes(key)) return "critical";
  if (["high", "class_2", "class_b"].includes(key)) return "high";
  if (["medium", "class_a"].includes(key)) return "medium";
  return "routine";
}

/**
 * Dias de calendário até à data do prazo, imune ao fuso do browser.
 *
 * A data é lida como `YYYY-MM-DD` e comparada ao dia local do utilizador. Usar
 * `Date.parse("2026-11-14Z")` dava meia-noite UTC e, em fusos negativos, o
 * contador podia recuar um dia. Aqui ambos os lados são meia-noite local.
 */
export function deadlineDaysLeft(deadline?: string | null, now: number = Date.now()): number | null {
  if (!deadline) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(deadline).trim());
  if (!match) return null;
  const target = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])).getTime();
  if (!Number.isFinite(target)) return null;
  const current = new Date(now);
  const today = new Date(current.getFullYear(), current.getMonth(), current.getDate()).getTime();
  return Math.max(0, Math.round((target - today) / 86400000));
}

/** Converte um timestamp da BD (UTC, `YYYY-MM-DD HH:MM:SS`) em Date local. */
export function parseServerDate(value?: string | null): Date | null {
  if (!value) return null;
  const text = String(value).trim().replace(" ", "T");
  const withZone = /[Zz]|[+-]\d{2}:?\d{2}$/.test(text) ? text : `${text}Z`;
  const parsed = new Date(withZone);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * Dias de calendário desde a última visualização. `0` = hoje, `1` = ontem.
 * Datas futuras/ inválidas devolvem `null` ou `0` para não mostrar rótulos falsos.
 */
export function viewedDaysAgo(value?: string | null, now: number = Date.now()): number | null {
  const viewed = parseServerDate(value);
  if (!viewed) return null;
  const current = new Date(now);
  const viewedDay = new Date(viewed.getFullYear(), viewed.getMonth(), viewed.getDate()).getTime();
  const today = new Date(current.getFullYear(), current.getMonth(), current.getDate()).getTime();
  return Math.max(0, Math.round((today - viewedDay) / 86400000));
}

/** `stale` é true a partir de 3 dias, quando o cartão fica mais apagado. */
export function viewedState(
  value?: string | null,
  now: number = Date.now(),
): { days: number; stale: boolean } | null {
  const days = viewedDaysAgo(value, now);
  if (days == null) return null;
  return { days, stale: days > 2 };
}

const TAG_KEYS: Record<string, string> = {
  inspection_possible: "dashboard.preinspection.possible",
  no_fine: "dashboard.preinspection.no_fine",
  owner_identified: "dashboard.preinspection.owner_identified",
  deadline_soon: "dashboard.preinspection.deadline_soon",
  fine_active: "dashboard.preinspection.fine_active",
};

const OWNER_TYPE_KEYS: Record<string, string> = {
  company: "dashboard.preinspection.owner_company",
  individual: "dashboard.preinspection.owner_individual",
  institutional: "dashboard.preinspection.owner_institutional",
  unknown: "dashboard.preinspection.owner_unknown",
};

export function ownerTypeLabel(
  t: (key: string, values?: Record<string, string | number>) => string,
  value?: string | null,
): string {
  if (!value) return "—";
  const key = OWNER_TYPE_KEYS[String(value).trim().toLowerCase()];
  return key ? t(key) : value;
}

export function tagLabel(
  t: (key: string, values?: Record<string, string | number>) => string,
  tag: string,
): string {
  const key = TAG_KEYS[tag];
  return key ? t(key) : tag;
}

export function inspectionStatusLabel(
  t: (key: string, values?: Record<string, string | number>) => string,
  value?: string | null,
): string {
  if (!value) return t("dashboard.preinspection.possible");
  if (POSSIBLE_VALUES.has(value.trim().toLowerCase())) {
    return t("dashboard.preinspection.possible");
  }
  return value;
}

export function sourceLabel(
  t: (key: string, values?: Record<string, string | number>) => string,
  value?: string | null,
): string {
  const key = String(value || "").toLowerCase();
  if (key === "pre_inspection" || key === "preventive") return t("dashboard.preinspection.badge");
  if (key === "reactive") return t("dashboard.signal.reactive");
  if (key === "permit") return t("dashboard.signal.permit");
  return value || "—";
}

export function deadlineLabel(
  t: (key: string, values?: Record<string, string | number>) => string,
  deadline?: string | null,
  now?: number,
): string {
  if (!deadline) return t("dashboard.deadline.none");
  const days = deadlineDaysLeft(deadline, now);
  if (days == null) return t("dashboard.deadline.not_published");
  if (days === 0) return t("dashboard.deadline.today");
  if (days === 1) return t("dashboard.deadline.in_days_one");
  return t("dashboard.deadline.in_days").replace("{days}", String(days));
}
