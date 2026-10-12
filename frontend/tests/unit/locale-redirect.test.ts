import { describe, expect, it } from "vitest";

import { buildLocaleRedirectPath } from "@/lib/locale-redirect";

/**
 * Regressão: o middleware redirecionava `/dashboard?lead=42` para
 * `/{locale}/dashboard` e perdia a query string — o deep link das push
 * notifications morria logo no primeiro redirect.
 */
describe("buildLocaleRedirectPath", () => {
  it("preserva o ?lead do deep link das push notifications", () => {
    expect(buildLocaleRedirectPath("/dashboard", "en", "?lead=42")).toBe(
      "/en/dashboard?lead=42",
    );
  });

  it("funciona sem query string", () => {
    expect(buildLocaleRedirectPath("/dashboard", "pt")).toBe("/pt/dashboard");
    expect(buildLocaleRedirectPath("/dashboard", "es", "")).toBe("/es/dashboard");
  });

  it("preserva múltiplos parâmetros", () => {
    expect(buildLocaleRedirectPath("/dashboard", "es", "?lead=7&fav=1")).toBe(
      "/es/dashboard?lead=7&fav=1",
    );
  });
});
