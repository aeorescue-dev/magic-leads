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
  if (key === "critical" || key === "immediate" || key === "class_1" || key === "class_c") {
    return "#ef4444";
  }
  if (key === "high" || key === "emergency" || key === "class_2" || key === "class_b") {
    return "#f59e0b";
  }
  if (key === "medium" || key === "class_a") return "#2563eb";
  return "#64748b";
}

export function categoryLabelKey(value?: string | null): string | null {
  if (!value) return null;
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
): string {
  if (!deadline) return t("dashboard.deadline.none");
  const target = Date.parse(deadline.replace(" ", "T") + (deadline.includes("T") ? "" : "Z"));
  if (!Number.isFinite(target)) return t("dashboard.deadline.not_published");
  const days = Math.max(0, Math.ceil((target - Date.now()) / 86400000));
  return t("dashboard.deadline.in_days").replace("{days}", String(days));
}
