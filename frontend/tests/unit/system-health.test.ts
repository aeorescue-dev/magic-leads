import { describe, expect, it } from "vitest";

import {
  fmtAge,
  fmtValue,
  fmtWhen,
  scoreClasses,
  scoreTone,
  sparkPoints,
} from "@/lib/system-health";

describe("System Health — score e formatação", () => {
  it("classifica 0–100 nos três estados", () => {
    expect(scoreTone(100)).toBe("ok");
    expect(scoreTone(90)).toBe("ok");
    expect(scoreTone(89)).toBe("warn");
    expect(scoreTone(60)).toBe("warn");
    expect(scoreTone(59)).toBe("fail");
    expect(scoreTone(0)).toBe("fail");
  });

  it("devolve classes distintas por estado", () => {
    expect(scoreClasses(95).bar).toContain("emerald");
    expect(scoreClasses(75).bar).toContain("amber");
    expect(scoreClasses(40).bar).toContain("rose");
  });

  it("formata idade em minutos, horas e dias", () => {
    expect(fmtAge(0.5)).toBe("30 min");
    expect(fmtAge(6)).toBe("6.0 h");
    expect(fmtAge(48)).toBe("2.0 d");
    expect(fmtAge(null)).toBe("—");
  });

  it("formata valores com unidade", () => {
    expect(fmtValue(12)).toBe("12");
    expect(fmtValue(12.34, "%")).toBe("12.3%");
    expect(fmtValue(9, "min")).toBe("9 min");
    expect(fmtValue(2.5, "$")).toBe("$2.5");
    expect(fmtValue(null)).toBe("—");
  });

  it("formata datas em UTC", () => {
    expect(fmtWhen("2026-11-02T16:00:00+00:00")).toContain("UTC");
    expect(fmtWhen(null)).toBe("—");
  });

  it("gera polyline válida", () => {
    const points = sparkPoints([100, 50, 0]);
    const coords = points.split(" ");
    expect(coords).toHaveLength(3);
    expect(coords[0]).toBe("0.0,0.0");
    expect(coords[2]).toBe("120.0,32.0");
    expect(sparkPoints([])).toBe("");
  });
});
