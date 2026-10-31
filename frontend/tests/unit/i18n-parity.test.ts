import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

/**
 * Paridade i18n: toda a chave usada via `t("...")` tem de existir em PT/EN/ES.
 *
 * Motivo: `t()` devolve a própria key quando falta a tradução. Sem este teste,
 * um `checkout.error_payment_fail` em falta aparece literalmente ao utilizador.
 */

const ROOT = process.cwd();
const I18N = fs.readFileSync(path.join(ROOT, "lib", "i18n.tsx"), "utf8");

function localeBlocks(text: string): Record<"pt" | "en" | "es", string> {
  const pt = text.indexOf("const PT: Dict = {");
  const en = text.indexOf("const EN: Dict = {");
  const es = text.indexOf("const ES: Dict = {");
  const end = text.indexOf("export const DICTS");
  return {
    pt: text.slice(pt, en),
    en: text.slice(en, es),
    es: text.slice(es, end),
  };
}

function collectUsedKeys(): string[] {
  const used = new Set<string>();
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (["node_modules", ".next", "tests"].includes(entry.name)) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (/\.(ts|tsx)$/.test(entry.name) && entry.name !== "i18n.tsx") {
        const text = fs.readFileSync(full, "utf8");
        for (const m of Array.from(
          text.matchAll(/\bt\(\s*["'`]([a-zA-Z0-9_.\-]+)["'`]/g)
        )) {
          used.add(m[1]);
        }
      }
    }
  };
  walk(ROOT);
  return Array.from(used);
}

const blocks = localeBlocks(I18N);
const keys = {
  pt: new Set(
    Array.from(blocks.pt.matchAll(/"([a-zA-Z0-9_.\-]+)"\s*:/g)).map((m) => m[1])
  ),
  en: new Set(
    Array.from(blocks.en.matchAll(/"([a-zA-Z0-9_.\-]+)"\s*:/g)).map((m) => m[1])
  ),
  es: new Set(
    Array.from(blocks.es.matchAll(/"([a-zA-Z0-9_.\-]+)"\s*:/g)).map((m) => m[1])
  ),
};

describe("i18n — paridade PT/EN/ES", () => {
  it("todas as chaves usadas existem nos três idiomas", () => {
    const used = collectUsedKeys();
    expect(used.length).toBeGreaterThan(100);

    const missing = {
      pt: used.filter((k) => !keys.pt.has(k)),
      en: used.filter((k) => !keys.en.has(k)),
      es: used.filter((k) => !keys.es.has(k)),
    };
    expect(missing.pt, `PT sem: ${missing.pt.join(", ")}`).toEqual([]);
    expect(missing.en, `EN sem: ${missing.en.join(", ")}`).toEqual([]);
    expect(missing.es, `ES sem: ${missing.es.join(", ")}`).toEqual([]);
  });

  it("chaves críticas de checkout e telefone existem em todos os idiomas", () => {
    const critical = [
      "checkout.btn_processing",
      "checkout.error_company_req",
      "checkout.error_generic_fail",
      "checkout.error_payment_fail",
      "dashboard.action.reveal_phone",
      "dashboard.detail.copy_phone",
      "dashboard.toast.phone_revealed",
      "dashboard.toast.phone_reveal_failed",
      "dashboard.toast.phone_reveal_error",
    ];
    for (const lang of ["pt", "en", "es"] as const) {
      for (const key of critical) {
        expect(keys[lang].has(key), `${lang} sem ${key}`).toBe(true);
      }
    }
  });
});
