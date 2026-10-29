import { expect, test } from "@playwright/test";

import { installApiProxy } from "./api-proxy";

/**
 * Regressoes de UI/UX do sprint: tema claro persistente, cartao acessivel por
 * teclado e gaveta de filtros mobile (Escape + devolucao de foco).
 *
 * Corre contra o backend LOCAL semeado; nunca toca na producao.
 */

test.describe("UI/UX — tema, teclado e gaveta", () => {
  test.beforeEach(async ({ page }) => {
    await installApiProxy(page, { token: "e2e-token-ciclo" });
  });

  test("o cartao e focavel e Enter abre o detalhe", async ({ page }) => {
    await page.goto("/pt/dashboard");
    const card = page.locator('[data-testid="lead-card"]').first();
    await expect(card).toBeVisible({ timeout: 20000 });

    await card.focus();
    await expect(card).toBeFocused();
    await page.keyboard.press("Enter");

    await expect(page.getByRole("dialog").first()).toBeVisible({ timeout: 20000 });
  });

  test("a gaveta de filtros abre, fecha com Escape e devolve o foco", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/pt/dashboard");

    const trigger = page.getByRole("button", { name: /Filtros/ }).first();
    await expect(trigger).toBeVisible({ timeout: 20000 });
    await trigger.click();

    const sheet = page.getByRole("dialog", { name: /Filtros/ });
    await expect(sheet).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("o tema claro persiste depois de reload", async ({ page }) => {
    await page.goto("/pt/dashboard");
    const root = page.locator("[data-theme]").first();
    await expect(root).toHaveAttribute("data-theme", "dark", { timeout: 20000 });

    await page.getByTestId("theme-toggle").click();
    await expect(root).toHaveAttribute("data-theme", "light");

    await page.reload();
    await expect(page.locator("[data-theme]").first()).toHaveAttribute(
      "data-theme",
      "light",
      { timeout: 20000 }
    );
  });

  test("a privacidade da morada no push persiste", async ({ page }) => {
    await page.goto("/pt/dashboard/settings");
    const toggle = page.getByRole("button", { name: /morada no alerta/i });
    await expect(toggle).toBeVisible({ timeout: 20000 });

    const before = (await toggle.getAttribute("aria-pressed")) === "true";
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", String(!before));

    await page.reload();
    await expect(page.getByRole("button", { name: /morada no alerta/i })).toHaveAttribute(
      "aria-pressed",
      String(!before),
      { timeout: 20000 }
    );
  });
});
