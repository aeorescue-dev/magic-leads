import { expect, test } from "@playwright/test";

import { installApiProxy } from "./api-proxy";

/**
 * Onboarding Wizard — gate e fluxo de 2 passos.
 *
 * `e2e-token-novo` é um utilizador semeado SEM interesses (wizard obrigatório);
 * `e2e-token-ciclo` já tem ofícios e por isso nunca deve ver o wizard.
 */

test.describe("Onboarding — gate e wizard", () => {
  test("utilizador sem ofícios é levado ao wizard antes do feed", async ({ page }) => {
    await installApiProxy(page, { token: "e2e-token-novo" });

    await page.goto("/pt/dashboard");
    await expect(page).toHaveURL(/\/pt\/onboarding/, { timeout: 20000 });

    // Passo 1: ofícios + cidades.
    await expect(page.getByText(/Onde e em que ofícios trabalha\?/i)).toBeVisible({
      timeout: 20000,
    });
    await expect(page.getByTestId("onboarding-cat-Roof")).toBeVisible();
    await expect(page.getByTestId("onboarding-city-NYC")).toBeVisible();
  });

  test("escolher ofício/cidade, saltar push e concluir abre o dashboard", async ({ page }) => {
    await installApiProxy(page, { token: "e2e-token-novo" });

    await page.goto("/pt/onboarding");
    const roof = page.getByTestId("onboarding-cat-Roof");
    await expect(roof).toBeVisible({ timeout: 20000 });
    await roof.click();
    await page.getByTestId("onboarding-city-NYC").click();

    await page.getByTestId("onboarding-next").click();

    // Passo 2: explicação do valor do push antes da permissão nativa.
    await expect(page.getByTestId("onboarding-push-step")).toBeVisible();
    await expect(page.getByText(/Receba alertas em tempo real/i)).toBeVisible();
    await expect(page.getByTestId("onboarding-enable-push")).toBeVisible();

    // "Agora não" = concluir sem push (a permissão é opcional).
    await page.getByTestId("onboarding-finish").click();

    await expect(page).toHaveURL(/\/pt\/dashboard/, { timeout: 20000 });
    await expect(page.locator('[data-testid="lead-card"]').first()).toBeVisible({
      timeout: 20000,
    });
  });

  test("quem já tem ofícios não volta ao wizard", async ({ page }) => {
    await installApiProxy(page, { token: "e2e-token-ciclo" });

    await page.goto("/pt/onboarding");
    await expect(page).toHaveURL(/\/pt\/dashboard/, { timeout: 20000 });
  });
});
