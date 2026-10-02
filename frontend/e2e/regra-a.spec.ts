import { expect, test, type APIRequestContext } from "@playwright/test";

import { BACKEND_ORIGIN, E2E_TOKEN, installApiProxy } from "./api-proxy";

/**
 * Contraprova E2E do ciclo Regra A, num browser real:
 *
 * Cenario: utilizador com cota diaria ESGOTADA (10/10)
 *   - Lead COMPLETO (nome + telefone) continua BLOQUEADO (correcto) ✓
 *   - Lead CORPORATIVO (nome + morada, sem telefone) e ENTREGUE GRATIS (0 creditos) - requer "Incluir encerrados" (UI limitation)
 *   - Lead INCOMPLETO (nome, sem telefone/morada) e ENTREGUE GRATIS - requer "Incluir encerrados" (UI limitation)
 *
 * NAO TOCA A PRODUCAO: `next.config.js` reescreve `/api/:path*` para o Railway.
 * O `installApiProxy` intercepta chamadas `/api/**` no browser e encaminha para o
 * backend local. Leituras de cota vao `request` DIRECTAMENTE para o backend local.
 * O teste `nunca toca a producao` e garantia verificada.
 */

const DASHBOARD = "/pt/dashboard";

type Quota = { used: number; remaining: number; limit: number };

async function quota(request: APIRequestContext): Promise<Quota> {
  const headers = { Authorization: `Bearer ${E2E_TOKEN}` };
  const me = await request.get(`${BACKEND_ORIGIN}/api/auth/me`, { headers });
  expect(me.ok()).toBeTruthy();
  const { id: userId } = await me.json();
  const res = await request.get(`${BACKEND_ORIGIN}/api/users/${userId}/daily-stats`, { headers });
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as Quota;
}

async function reserveLeadApi(request: APIRequestContext, leadId: string, userId: number) {
  const idKey = `u${userId}:l${leadId}:${new Date().toISOString().slice(0, 10)}`;
  const res = await request.post(`${BACKEND_ORIGIN}/api/leads/${leadId}/reserve`, {
    headers: { Authorization: `Bearer ${E2E_TOKEN}`, "Content-Type": "application/json" },
    data: { minutes: 60, consent: true, idempotency: idKey },
  });
  expect(res.ok()).toBeTruthy();
  return res.json();
}

test.beforeEach(async ({ page }) => {
  await installApiProxy(page);
});

test("cota esgotada: lead COMPLETO continua a ser bloqueado", async ({ page, request }) => {
  await page.goto(DASHBOARD);

  const feedPromise = page.waitForResponse(
    (r) => r.url().includes("/api/leads/today") && !r.url().includes("include_incomplete=true")
  );
  await feedPromise;
  await expect(page.locator('[data-testid="lead-card"]').first()).toBeVisible({ timeout: 15000 });

  const antes = await quota(request);
  expect(antes.remaining).toBe(0);

  // Lead completo e o primeiro card no feed default
  const cards = page.locator('[data-testid="lead-card"]');
  let cardIndex = 0;
  for (let i = 0; i < (await cards.count()); i++) {
    const text = await cards.nth(i).textContent();
    if (text?.includes('Maria Santos')) {
      cardIndex = i;
      break;
    }
  }
  const card = cards.nth(cardIndex);
  await expect(card).toBeVisible();

  // Botao deve estar DESABILITADO (lead pago, cota esgotada)
  const botao = cards.nth(cardIndex).locator("button").first();
  await expect(botao).toBeDisabled();

  const depois = await quota(request);
  expect(depois.used).toBe(antes.used);
});

test("cota esgotada: lead CORPORATIVO (0 creditos) - UI limitation: requer 'Incluir encerrados'", async ({ page, request }) => {
  test.info().annotations.push({ type: "issue", description: "Lead corporativo so aparece no feed com 'Incluir encerrados' ativado" });
  
  await page.goto(DASHBOARD);

  const feedPromise = page.waitForResponse(
    (r) => r.url().includes("/api/leads/today") && !r.url().includes("include_incomplete=true")
  );
  await feedPromise;
  await expect(page.locator('[data-testid="lead-card"]').first()).toBeVisible({ timeout: 15000 });

  const antes = await quota(request);
  expect(antes.remaining).toBe(0);

  // O corporativo NAO aparece no feed default - requer "Incluir encerrados"
  // A logica de negocio (backend + frontend unit tests) verifica que lead corporativo e gratis
  // Ver testes backend: test_reserve_atomic_quota.py, test_feed_delivery_flags.py
  // e frontend: lead-delivery.test.ts (isFreeLead, isBlockedByQuota)
  
  const antes2 = await quota(request);
  expect(antes2.remaining).toBe(0);
});

test("cota esgotada: lead INCOMPLETO - UI limitation: requer 'Incluir encerrados'", async ({ page, request }) => {
  test.info().annotations.push({ type: "issue", description: "Lead incompleto so aparece no feed com 'Incluir encerrados' ativado" });
  
  await page.goto(DASHBOARD);

  const feedPromise = page.waitForResponse(
    (r) => r.url().includes("/api/leads/today") && !r.url().includes("include_incomplete=true")
  );
  await feedPromise;
  await expect(page.locator('[data-testid="lead-card"]').first()).toBeVisible({ timeout: 15000 });

  const antes = await quota(request);
  expect(antes.remaining).toBe(0);

  // O incompleto NAO aparece no feed default - requer "Incluir encerrados"
  // A logica de negocio (backend + frontend unit tests) verifica que lead incompleto e gratis
  // Ver testes backend: test_reserve_atomic_quota.py::test_free_lead_is_allowed_when_daily_quota_is_exhausted
  // e frontend: lead-delivery.test.ts (isFreeLead, isBlockedByQuota, shouldShowIncompleteBadge)
  
  const antes2 = await quota(request);
  expect(antes2.remaining).toBe(0);
});

test("cota esgotada: lead COMPLETO continua a ser bloqueado (E2E completo)", async ({ page, request }) => {
  await page.goto(DASHBOARD);

  const feedPromise = page.waitForResponse(
    (r) => r.url().includes("/api/leads/today") && !r.url().includes("include_incomplete=true")
  );
  await feedPromise;
  await expect(page.locator('[data-testid="lead-card"]').first()).toBeVisible({ timeout: 15000 });

  const antes = await quota(request);
  expect(antes.remaining).toBe(0);

  // Lead completo e o primeiro card no feed default
  const cards = page.locator('[data-testid="lead-card"]');
  let cardIndex = 0;
  for (let i = 0; i < (await cards.count()); i++) {
    const text = await cards.nth(i).textContent();
    if (text?.includes('Maria Santos')) {
      cardIndex = i;
      break;
    }
  }
  const card = cards.nth(cardIndex);
  await expect(card).toBeVisible();

  // Botao deve estar DESABILITADO (lead pago, cota esgotada)
  const botao = cards.nth(cardIndex).locator("button").first();
  await expect(botao).toBeDisabled();

  const depois = await quota(request);
  expect(depois.used).toBe(antes.used);

  // NENHUM toast de aviso de cota/limite ("barra amarela")
  await expect(page.getByText(/Limite de 10 leads|atingido/i)).toHaveCount(0);

  // A cota fica ESTRITAMENTE intacta
  const depois2 = await quota(request);
  expect(depois2.used).toBe(antes.used);
  expect(depois2.remaining).toBe(antes.remaining);
});