import { expect, test } from "@playwright/test";

/**
 * Deep link de push com sessão expirada: o proxy tem de preservar `next`
 * para o utilizador voltar ao lead depois do login/passkey.
 */
test("dashboard sem sessão redireciona para auth com next do deep link", async ({ page }) => {
  await page.goto("/pt/dashboard?lead=42");
  await expect(page).toHaveURL(/\/pt\/auth\?next=/);
  const url = new URL(page.url());
  expect(url.searchParams.get("next")).toBe("/pt/dashboard?lead=42");
  await expect(page.getByRole("button", { name: /Entrar/ }).first()).toBeVisible({
    timeout: 20000,
  });
});
