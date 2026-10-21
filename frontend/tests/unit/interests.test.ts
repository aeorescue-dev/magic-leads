import { describe, expect, it } from "vitest";

import {
  shouldSeedDefaultInterests,
  toggleInterestKey,
} from "@/lib/interests";

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

describe("shouldSeedDefaultInterests — auto-PUT do default", () => {
  it("faz o seed quando o servidor está vazio e o utilizador nunca tocou", () => {
    expect(shouldSeedDefaultInterests([], false)).toBe(true);
    expect(shouldSeedDefaultInterests(null, false)).toBe(true);
    expect(shouldSeedDefaultInterests(undefined, false)).toBe(true);
  });

  it("NÃO faz o seed quando o servidor já tem categorias", () => {
    expect(shouldSeedDefaultInterests(["Roof"], false)).toBe(false);
  });

  it("NÃO faz o seed quando o utilizador já tocou (mesmo com lista vazia)", () => {
    // O utilizador que desmarcou tudo tem uma escolha explicita — nunca
    // voltamos a impor as 16 categorias.
    expect(shouldSeedDefaultInterests([], true)).toBe(false);
  });
});
