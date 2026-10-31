import { expect, test, type APIRequestContext } from "@playwright/test";

import { BACKEND_ORIGIN, E2E_CYCLE_TOKEN, installApiProxy } from "./api-proxy";

/**
 * A5 — 402 abre o CheckoutModal imediatamente.
 *
 * O backend devolve 402 com `action=REDIRECT_TO_CHECKOUT` quando a assinatura
 * expira. Antes, a UI só reagia no refresh periódico (até 10 min). Este teste
 * intercepta o reserve com 402 e exige o modal no mesmo gesto.
 */

const DASHBOARD = "/pt/dashboard";
const PAYMENT_ADDRESS = "11 PAYMENT ST";

function auth(token: string) {
  return { Authorization: `Bearer ${token}` };
}

async function findLeadId(request: APIRequestContext, address: string): Promise<number> {
  const res = await request.get(`${BACKEND_ORIGIN}/api/leads/today?limit=100`, {
    headers: auth(E2E_CYCLE_TOKEN),
  });
  expect(res.ok()).toBeTruthy();
  const { leads } = await res.json();
  const lead = (leads || []).find((l: any) => (l.address || "").includes(address));
  expect(lead, `lead "${address}" nao esta no feed`).toBeTruthy();
  return Number(lead.id);
}

async function ensureAvailable(request: APIRequestContext, leadId: number): Promise<void> {
  await request
    .post(`${BACKEND_ORIGIN}/api/leads/${leadId}/release`, {
      headers: { ...auth(E2E_CYCLE_TOKEN), "Content-Type": "application/json" },
      data: { reason: "other", note: "reset de cenario" },
    })
    .catch(() => undefined);
}

test.beforeEach(async ({ page }) => {
  await installApiProxy(page, { token: E2E_CYCLE_TOKEN });
});

test("402 no reserve abre o checkout sem esperar o refresh de 10 min", async ({
  page,
  request,
}) => {
  const leadId = await findLeadId(request, PAYMENT_ADDRESS);
  await ensureAvailable(request, leadId);

  // Intercepta APENAS o reserve (registado depois do proxy global -> ganha).
  let reserveHits = 0;
  await page.route("**/api/leads/*/reserve", async (route) => {
    reserveHits += 1;
    await route.fulfill({
      status: 402,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          error: "subscription_required",
          status: "expired",
          message: "Assinatura necessária para continuar.",
          action: "REDIRECT_TO_CHECKOUT",
        },
      }),
    });
  });

  await page.goto(DASHBOARD);
  const card = page.locator('[data-testid="lead-card"]').filter({ hasText: PAYMENT_ADDRESS });
  await expect(card.first()).toBeVisible({ timeout: 20000 });

  await card.locator("button", { hasText: /Reservar 1 Hora/ }).first().click();
  await page.getByRole("button", { name: /Reservar 1 Hora\W+Revelar/ }).click();

  // O modal de checkout tem de aparecer imediatamente.
  await expect(
    page.getByText(/Reativar a tua subscrição|Assinar agora/).first()
  ).toBeVisible({ timeout: 10000 });
  expect(reserveHits).toBeGreaterThan(0);
});

test("em /en o checkout de conversão aparece em inglês natural", async ({
  page,
  request,
}) => {
  const leadId = await findLeadId(request, PAYMENT_ADDRESS);
  await ensureAvailable(request, leadId);

  await page.route("**/api/leads/*/reserve", async (route) => {
    await route.fulfill({
      status: 402,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          error: "subscription_required",
          status: "expired",
          message: "Subscription required.",
          action: "REDIRECT_TO_CHECKOUT",
        },
      }),
    });
  });

  await page.goto("/en/dashboard");
  const card = page.locator('[data-testid="lead-card"]').filter({ hasText: PAYMENT_ADDRESS });
  await expect(card.first()).toBeVisible({ timeout: 20000 });

  await card.locator("button", { hasText: /Reserve 1 Hour/ }).first().click();
  await page.getByRole("button", { name: /Reserve 1 Hour\W+Reveal/ }).click();

  // Copy EN (não deve cair para PT nem mostrar keys cruas).
  await expect(
    page.getByText(/Reactivate your access|Start your 7-day access/).first()
  ).toBeVisible({ timeout: 10000 });
  const body = (await page.locator("body").innerText()).toLowerCase();
  expect(body).not.toContain("reativar a tua");
  expect(body).not.toContain("checkout.title_");
});
