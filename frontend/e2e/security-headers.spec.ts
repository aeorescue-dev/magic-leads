import { expect, test } from "@playwright/test";

import { installApiProxy } from "./api-proxy";

/**
 * Fase B — headers de segurança no frontend (next.config.js).
 * Precisa de sessão para o middleware não redirecionar /dashboard.
 */

test("o frontend envia headers de segurança", async ({ page }) => {
  await installApiProxy(page, { token: "e2e-token-ciclo" });

  const response = await page.goto("/pt/dashboard");
  expect(response).not.toBeNull();
  const headers = response!.headers();

  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(headers["permissions-policy"]).toContain("geolocation=(self)");
  expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
});
