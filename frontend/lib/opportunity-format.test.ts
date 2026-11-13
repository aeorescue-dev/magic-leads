import { describe, expect, it } from "vitest";
import {
  deadlineDaysLeft,
  deadlineLabel,
  severityBucket,
  tagLabel,
} from "./opportunity-format";

const t = (key: string, values?: Record<string, string | number>) => {
  const dict: Record<string, string> = {
    "dashboard.deadline.in_days": "Prazo em {days} dias",
    "dashboard.deadline.in_days_one": "Prazo em 1 dia",
    "dashboard.deadline.today": "Prazo hoje",
    "dashboard.deadline.none": "Sem prazo",
    "dashboard.deadline.not_published": "Prazo nao publicado",
  };
  let out = dict[key] || key;
  for (const [name, value] of Object.entries(values || {})) {
    out = out.replace(`{${name}}`, String(value));
  }
  return out;
};

describe("opportunity-format", () => {
  it("agrupa severidades do backend nos quatro buckets do painel", () => {
    expect(severityBucket("immediate")).toBe("critical");
    expect(severityBucket("critical")).toBe("critical");
    expect(severityBucket("emergency")).toBe("critical");
    expect(severityBucket("class_c")).toBe("critical");
    expect(severityBucket("high")).toBe("high");
    expect(severityBucket("class_2")).toBe("high");
    expect(severityBucket("medium")).toBe("medium");
    expect(severityBucket("class_a")).toBe("medium");
    expect(severityBucket("low")).toBe("routine");
    expect(severityBucket(null)).toBe("routine");
  });

  it("conta dias de calendario sem desvio de fuso", () => {
    const now = new Date(2026, 10, 13, 23, 30).getTime();
    expect(deadlineDaysLeft("2026-11-13", now)).toBe(0);
    expect(deadlineDaysLeft("2026-11-14", now)).toBe(1);
    expect(deadlineDaysLeft("2026-11-20", now)).toBe(7);
    expect(deadlineDaysLeft("2026-11-12", now)).toBe(0);
  });

  it("aceita data-hora com e sem fuso e ignora a hora", () => {
    const now = new Date(2026, 10, 13, 8, 0).getTime();
    expect(deadlineDaysLeft("2026-11-14T23:59:59", now)).toBe(1);
    expect(deadlineDaysLeft("2026-11-14T23:59:59Z", now)).toBe(1);
    expect(deadlineDaysLeft("2026-11-14 10:00:00", now)).toBe(1);
  });

  it("devolve null para datas invalidas ou ausentes", () => {
    expect(deadlineDaysLeft(null)).toBeNull();
    expect(deadlineDaysLeft("")).toBeNull();
    expect(deadlineDaysLeft("sem-data")).toBeNull();
  });

  it("formata o prazo com os dias calculados", () => {
    const now = new Date(2026, 10, 13, 12, 0).getTime();
    expect(deadlineLabel(t, "2026-11-16", now)).toBe("Prazo em 3 dias");
    expect(deadlineLabel(t, "2026-11-13", now)).toBe("Prazo hoje");
    expect(deadlineLabel(t, "2026-11-14", now)).toBe("Prazo em 1 dia");
    expect(deadlineLabel(t, null, now)).toBe("Sem prazo");
    expect(deadlineLabel(t, "invalida", now)).toBe("Prazo nao publicado");
  });

  it("traduz tags conhecidas e preserva tokens desconhecidos", () => {
    expect(tagLabel((key) => key, "no_fine")).toBe("dashboard.preinspection.no_fine");
    expect(tagLabel((key) => key, "custom_token")).toBe("custom_token");
  });
});
