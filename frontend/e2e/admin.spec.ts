import { expect, test } from "@playwright/test";

import { installApiProxy } from "./api-proxy";

/**
 * Admin E2E — conta admin isolada (`e2e-token-admin`) na BD do Playwright.
 * Valida o fluxo gráfico de concessão/revogação e os painéis de saúde/funil.
 */

test.beforeEach(async ({ page }) => {
  await installApiProxy(page, { token: "e2e-token-admin" });
  page.on("dialog", (dialog) => dialog.accept());
});

test("admin carrega, mostra funil/saúde e concede+reverte acesso", async ({ page }) => {
  await page.goto("/admin");

  await expect(page.getByText("Torre de Controlo")).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("admin-access-grant")).toBeVisible();
  await expect(page.getByTestId("billing-funnel")).toBeVisible({ timeout: 20000 });

  // Saúde do motor (Control Tower) acessível a partir do painel Outbound.
  await page.getByRole("button", { name: /Saúde do motor/ }).click();
  await expect(page.getByTestId("outbound-health")).toBeVisible({ timeout: 20000 });

  // Concessão de 3 dias a um utilizador semeado.
  await page.getByTestId("admin-access-email").fill("e2e-ciclo@magicleads.app");
  await page.getByRole("button", { name: "Procurar" }).click();
  await expect(page.getByText("e2e-ciclo@magicleads.app").first()).toBeVisible({
    timeout: 20000,
  });
  await page.getByTestId("admin-access-days-3").click();
  await page.getByTestId("admin-access-confirm").click();

  await expect(page.getByText(/Acesso concedido até/)).toBeVisible({ timeout: 20000 });
  await expect(page.getByText(/\+3d/).first()).toBeVisible();

  // Reverter (undo seguro).
  const revert = page.getByRole("button", { name: /Reverter/ }).first();
  await expect(revert).toBeVisible({ timeout: 20000 });
  await revert.click();
  await expect(page.getByText(/Concessão #\d+ revertida/)).toBeVisible({ timeout: 20000 });
});

test("falha ao actualizar a fila mostra erro e repõe o botão", async ({ page }) => {
  await page.route("**/api/admin/outbound/batches*", (route) =>
    route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "fila indisponível" }),
    })
  );

  await page.goto("/admin");
  const button = page.getByTestId("reload-batches");
  await expect(button).toBeVisible({ timeout: 20000 });
  await expect(button).toBeEnabled();

  await button.click();

  await expect(page.getByTestId("batches-error")).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId("batches-error")).toContainText("Falha ao actualizar");
  // O botão não fica preso em loading.
  await expect(button).toBeEnabled();
  await expect(button).toContainText("Actualizar");
});
