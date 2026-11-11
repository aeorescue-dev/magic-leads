import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

/**
 * Painel de amostra da landing (`landing.sampleLeads`).
 *
 * Motivo: os 12 leads vêm do i18n e são cruzados com `SAMPLE_LEADS_BASE` por id.
 * Se um id faltar no bloco de um idioma, o cartão abre vazio (sem ofício nem
 * descrição) — e se o bloco EN ficar em português voltamos ao problema que a
 * Fase 17 corrigiu. Este teste guarda as duas coisas.
 */

const ROOT = process.cwd();
const readLocale = (lang: "pt" | "en" | "es") =>
  fs.readFileSync(path.join(ROOT, "lib", "i18n", `${lang}.ts`), "utf8");
const LANDING = fs.readFileSync(
  path.join(ROOT, "app", "[locale]", "(marketing)", "page.tsx"),
  "utf8"
);

function sampleLeads(block: string): string[] {
  const m = block.match(/"landing\.sampleLeads":\s*"([^"]*)"/);
  return m ? m[1].split("||") : [];
}

function baseIds(): string[] {
  const start = LANDING.indexOf("const SAMPLE_LEADS_BASE");
  const end = LANDING.indexOf("const SIGNAL_STYLE", start);
  const block = LANDING.slice(start, end);
  return Array.from(block.matchAll(/\bid:\s*"([a-z]{2,3}-\d)"/g)).map((m) => m[1]);
}

const blocks = {
  pt: readLocale("pt"),
  en: readLocale("en"),
  es: readLocale("es"),
};
const ids = baseIds();

describe("landing — painel de amostra traduzido", () => {
  it("a base tem os 12 leads (3 por cidade)", () => {
    expect(ids).toHaveLength(12);
    expect(new Set(ids).size).toBe(12);
  });

  it("cada idioma tem os 12 ids, com 4 campos e texto preenchido", () => {
    for (const lang of ["pt", "en", "es"] as const) {
      const rows = sampleLeads(blocks[lang]);
      expect(rows, `${lang}: linhas`).toHaveLength(12);
      const parsed = rows.map((row) => row.split("|"));
      for (const fields of parsed) {
        expect(fields, `${lang}: campos`).toHaveLength(4);
        const [id, category, badge, description] = fields;
        expect(ids, `${lang}: id ${id}`).toContain(id);
        expect(category.trim().length, `${lang}: ofício de ${id}`).toBeGreaterThan(2);
        expect(["urgent", "high", "medium"], `${lang}: badge de ${id}`).toContain(badge);
        expect(description.trim().length, `${lang}: descrição de ${id}`).toBeGreaterThan(20);
      }
      expect(new Set(parsed.map((f) => f[0])).size, `${lang}: ids duplicados`).toBe(12);
    }
  });

  it("a versão inglesa não contém texto português", () => {
    const ptWords = [
      "Infiltração",
      "Vazamento",
      "Trinca",
      "Descamação",
      "Afundamento",
      "Telhas",
      "Calha",
      "Fiação",
      "Caldeira",
      "Proprietário",
      "Necessita",
      "Deseja",
      "Encanamento",
      "Telhado",
      "Elétrica",
      "Aquecimento",
    ];
    const en = sampleLeads(blocks.en).join("|");
    const found = ptWords.filter((w) => en.includes(w));
    expect(found, `EN com PT: ${found.join(", ")}`).toEqual([]);
  });

  it("os selos de gravidade existem nos três idiomas", () => {
    for (const lang of ["pt", "en", "es"] as const) {
      for (const badge of ["urgent", "high", "medium"]) {
        const re = new RegExp(`"landing\\.badge\\.${badge}":\\s*"[^"]+"`);
        expect(re.test(blocks[lang]), `${lang} sem landing.badge.${badge}`).toBe(true);
      }
    }
  });
});
