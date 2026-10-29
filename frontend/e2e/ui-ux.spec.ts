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
    const toggle = page.getByRole("switch", { name: /morada no alerta/i });
    await expect(toggle).toBeVisible({ timeout: 20000 });

    const before = (await toggle.getAttribute("aria-checked")) === "true";
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", String(!before));

    await page.reload();
    await expect(page.getByRole("switch", { name: /morada no alerta/i })).toHaveAttribute(
      "aria-checked",
      String(!before),
      { timeout: 20000 }
    );
  });

  test("resumo diário e avisos de reserva são interruptores persistentes", async ({
    page,
  }) => {
    await page.goto("/pt/dashboard/settings");
    const digest = page.getByRole("switch", { name: /resumo diário/i });
    await expect(digest).toBeVisible({ timeout: 20000 });
    // Default ligado (B2).
    await expect(digest).toHaveAttribute("aria-checked", "true");

    await digest.click();
    await expect(digest).toHaveAttribute("aria-checked", "false");
    await page.reload();
    await expect(page.getByRole("switch", { name: /resumo diário/i })).toHaveAttribute(
      "aria-checked",
      "false",
      { timeout: 20000 }
    );

    const life = page.getByRole("switch", { name: /avisos de reserva/i });
    await expect(life).toHaveAttribute("aria-checked", "false");
    await life.click();
    await expect(life).toHaveAttribute("aria-checked", "true");
  });

  test("o chime de alerta está disponível e o toggle persiste", async ({ page }) => {
    const asset = await page.request.get("/sounds/alert-chime.mp3");
    expect(asset.status()).toBe(200);
    expect(asset.headers()["content-type"]).toContain("audio");

    await page.goto("/pt/dashboard/settings");
    const chime = page.getByRole("switch", { name: /som de alerta/i });
    await expect(chime).toBeVisible({ timeout: 20000 });
    await expect(chime).toHaveAttribute("aria-checked", "true"); // default ligado

    await chime.click();
    await expect(chime).toHaveAttribute("aria-checked", "false");
    await page.reload();
    await expect(page.getByRole("switch", { name: /som de alerta/i })).toHaveAttribute(
      "aria-checked",
      "false",
      { timeout: 20000 }
    );
  });

  test("o sino de push por ofício desliga sem esconder o in-app", async ({ page }) => {    await page.goto("/pt/dashboard/settings");
    const trades = page.getByRole("switch", { name: /^Roof$/ });
    await expect(trades.first()).toBeVisible({ timeout: 20000 });

    const first = trades.first();
    const before = (await first.getAttribute("aria-checked")) === "true";
    await first.click();
    await expect(first).toHaveAttribute("aria-checked", String(!before));

    // O cartão continua a explicar que o in-app fica intacto.
    await expect(page.getByText(/só no in-app/i)).toBeVisible();
  });
});
