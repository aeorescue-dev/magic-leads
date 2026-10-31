import { describe, expect, it } from "vitest";

import { pickLang } from "@/lib/i18n";

/**
 * Mercado principal = EUA. Sem escolha explícita (storage/cookie/browser),
 * o idioma tem de ser EN; nunca PT por omissão.
 */
describe("pickLang — default EN no checkout/conversão", () => {
  it("respeita a escolha explícita guardada", () => {
    expect(pickLang("pt", "en", "en-US")).toBe("pt");
    expect(pickLang("es", null, "en-US")).toBe("es");
  });

  it("usa o cookie quando não há storage", () => {
    expect(pickLang(null, "es", "en-US")).toBe("es");
  });

  it("usa o idioma do browser quando é suportado", () => {
    expect(pickLang(null, null, "en-US")).toBe("en");
    expect(pickLang(null, null, "pt-BR")).toBe("pt");
    expect(pickLang(null, null, "es-MX")).toBe("es");
  });

  it("cai em EN para browser não suportado ou desconhecido", () => {
    expect(pickLang(null, null, "fr-FR")).toBe("en");
    expect(pickLang(null, null, null)).toBe("en");
    expect(pickLang("de", "it", "fr")).toBe("en");
  });
});
