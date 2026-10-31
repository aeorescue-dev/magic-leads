import { describe, expect, it } from "vitest";

import { toggleInterestKey } from "@/lib/interests";
import { needsOnboarding, TRADE_CATEGORIES, TRADE_CATEGORY_KEYS } from "@/lib/categories";

const ALL = ["Roof", "Plumbing", "Paint", "Electrical"];

describe("toggleInterestKey — invariante 'nunca vazio'", () => {
  it("marca uma categoria que estava desmarcada", () => {
    const next = toggleInterestKey(["Roof"], "Plumbing", ALL);
    expect(Array.from(next).sort()).toEqual(["Plumbing", "Roof"]);
  });

  it("desmarca uma categoria que estava marcada", () => {
    const next = toggleInterestKey(["Roof", "Plumbing"], "Roof", ALL);
    expect(Array.from(next)).toEqual(["Plumbing"]);
  });

  it("desmarcar a ÚLTIMA categoria volta a marcar todas (nunca fica vazio)", () => {
    // Bug corrigido: com o conjunto vazio, o PUT gravava vazio e o auto-PUT
    // do reload repunha as 16 — a escolha do utilizador desaparecia.
    const next = toggleInterestKey(["Roof"], "Roof", ALL);
    expect(next.size).toBe(ALL.length);
    expect(Array.from(next).sort()).toEqual(ALL.slice().sort());
  });

  it("nunca devolve um conjunto vazio", () => {
    const next = toggleInterestKey([], "Roof", ALL);
    expect(next.size).toBeGreaterThan(0);
  });

  it("não muta o conjunto de origem", () => {
    const current = new Set(["Roof"]);
    toggleInterestKey(current, "Plumbing", ALL);
    expect(Array.from(current)).toEqual(["Roof"]);
  });

  it("aceita um iterável (não só Set)", () => {
    const next = toggleInterestKey(["Roof"], "Paint", ALL);
    expect(next.has("Paint")).toBe(true);
    expect(next.has("Roof")).toBe(true);
  });
});

describe("needsOnboarding — gate do wizard", () => {
  it("exige onboarding quando o servidor devolve lista vazia", () => {
    expect(needsOnboarding([])).toBe(true);
  });

  it("exige onboarding quando não há resposta (null/undefined)", () => {
    expect(needsOnboarding(null)).toBe(true);
    expect(needsOnboarding(undefined)).toBe(true);
  });

  it("NÃO exige onboarding quando já há ≥1 ofício escolhido", () => {
    expect(needsOnboarding(["Roof"])).toBe(false);
  });

  it("TRADE_CATEGORIES tem 16 ofícios com chaves únicas", () => {
    expect(TRADE_CATEGORIES).toHaveLength(16);
    expect(new Set(TRADE_CATEGORY_KEYS).size).toBe(16);
  });
});
