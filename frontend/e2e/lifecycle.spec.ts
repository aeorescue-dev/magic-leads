import { expect, test, type APIRequestContext } from "@playwright/test";

import { BACKEND_ORIGIN, E2E_CYCLE_TOKEN, installApiProxy } from "./api-proxy";

/**
 * E2E do ciclo de vida por fases (Reserva 1h -> Contactar 48h -> Negociar 48h
 * -> Converter terminal), num browser real, contra o backend LOCAL semeado.
 *
 * Cobre:
 *   - o ReserveGuideModal automatico apos reservar (4 etapas, status, countdown)
 *   - o painel do ciclo no modal analitico e as transicoes de fase na UI
 *   - o badge de fase com contagem dinamica (<1h mostra segundos e decrementa)
 *   - a conversao que tira o lead do feed publico
 *
 * NAO TOCA A PRODUCAO: `installApiProxy` encaminha `/api/**` para o uvicorn
 * local (base isolada `e2e.db`, semeada pelo `seed.py`).
 */

const DASHBOARD = "/pt/dashboard";
const CYCLE_ADDRESS = "9 CYCLE AVE";
const TIMER_ADDRESS = "10 TIMER ST";

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

/** Devolve o lead ao pool antes de cada teste (os testes partilham a mesma BD). */
async function ensureAvailable(request: APIRequestContext, leadId: number): Promise<void> {
  await request
    .post(`${BACKEND_ORIGIN}/api/leads/${leadId}/release`, {
      headers: { ...auth(E2E_CYCLE_TOKEN), "Content-Type": "application/json" },
      data: { reason: "other", note: "reset de cenario" },
    })
    .catch(() => undefined);
}

/** Fluxo UI completo: abrir o card -> consentimento -> guia do ciclo. */
async function reserveViaUiAndGetGuide(page: import("@playwright/test").Page, address: string) {
  await page.goto(DASHBOARD);
  const card = page.locator('[data-testid="lead-card"]').filter({ hasText: address });
  await expect(card.first()).toBeVisible({ timeout: 20000 });

  await card.locator("button", { hasText: /Reservar 1 Hora/ }).first().click();
  await page.getByRole("button", { name: /Reservar 1 Hora\W+Revelar/ }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 20000 });
  return dialog;
}

test.beforeEach(async ({ page }) => {
  await installApiProxy(page, { token: E2E_CYCLE_TOKEN });
});

test("reservar abre o guia do ciclo: 4 etapas, status ATIVO/PRÓXIMO/BLOQUEADO e countdown 1h", async ({ page, request }) => {
  const cycle = await findLeadId(request, CYCLE_ADDRESS);
  await ensureAvailable(request, cycle);

  const dialog = await reserveViaUiAndGetGuide(page, CYCLE_ADDRESS);
  await expect(dialog.getByText("9 CYCLE AVE")).toBeVisible();

  // As 4 fases do pipeline (1h/48h/48h/terminal)
  for (const step of ["Reservar", "Contactar", "Negociar", "Converter"]) {
    await expect(dialog.getByText(step).first()).toBeVisible();
  }
  await expect(dialog.getByText("ATIVO")).toBeVisible();
  await expect(dialog.getByText("PRÓXIMO")).toBeVisible();
  await expect(dialog.getByText("BLOQUEADO").first()).toBeVisible();

  // Reserva = janela de 1h -> a reserva cai sempre um pouco abaixo de 3600s,
  // logo o guia renderiza o countdown em segundos (59:xx), não "1h 00m".
  const timer = dialog.getByTestId("stage-countdown");
  await expect(timer).toBeVisible();
  await expect(timer).toHaveText(/^59:\d{2}$/);

  // Fechar guia abre o pipeline completo (painel sticky no modal analítico)
  await dialog.getByRole("button", { name: "Ver pipeline completo" }).click();
  await expect(page.getByText("Guia rápido — como aproveitar este lead")).toBeVisible();
});

test("transições de fase na UI: Contactar e Negociar reabrem 48h; Converter sai do feed", async ({ page, request }) => {
  const cycle = await findLeadId(request, CYCLE_ADDRESS);
  await ensureAvailable(request, cycle);

  const dialog = await reserveViaUiAndGetGuide(page, CYCLE_ADDRESS);
  await dialog.getByRole("button", { name: "Ver pipeline completo" }).click();

  // Painel do ciclo visível no modal analítico com countdown ~1h.
  const panelTimer = page.getByTestId("stage-countdown");
  await expect(panelTimer).toBeVisible();
  await expect(panelTimer).toHaveText(/^59:\d{2}$/);

  // --- CONTACTAR: abre 48h e o passo 2 passa a estar ativo ---
  await page.getByRole("button", { name: "Contactar", exact: true }).click();
  await expect(page.getByText(/SMS, chamada ou e-mail/)).toBeVisible({ timeout: 20000 });
  await expect(panelTimer).toHaveText(/^4[78]h \d{2}m$/);

  // Re-clique em Contactar NÃO estica o prazo (anti-reclick): o backend devolve
  // exatamente o MESMO stage_expires_at (a UI não reabre a fase).
  const status = async () =>
    (await (
      await request.get(`${BACKEND_ORIGIN}/api/leads/${cycle}/status`, {
        headers: auth(E2E_CYCLE_TOKEN),
      })
    ).json()) as { stage_expires_at?: string; lead_status?: string };
  const expiresAposContacto = (await status()).stage_expires_at;
  await page.getByRole("button", { name: "Contactar", exact: true }).click();
  await expect(page.getByText(/SMS, chamada ou e-mail/)).toBeVisible();
  expect((await status()).stage_expires_at).toBe(expiresAposContacto);

  // --- NEGOCIAR: reabre 48h e o passo 3 passa a estar ativo ---
  await page.getByRole("button", { name: "Negociar", exact: true }).click();
  await expect(page.getByText(/Cliente respondendo/)).toBeVisible({ timeout: 20000 });
  await expect(panelTimer).toHaveText(/^4[78]h \d{2}m$/);

  // --- CONVERTER: terminal, sem countdown, tudo CONCLUÍDO ---
  await page.getByRole("button", { name: "Converter", exact: true }).click();
  await expect(page.getByText("CONCLUÍDO").first()).toBeVisible({ timeout: 20000 });

  // O lead saiu do feed público de descoberta (para todos, incluindo o dono).
  const feed = await request.get(`${BACKEND_ORIGIN}/api/leads/today?limit=100`, {
    headers: auth(E2E_CYCLE_TOKEN),
  });
  expect(feed.ok()).toBeTruthy();
  const { leads } = await feed.json();
  const noFeed = (leads || []).filter((l: any) => (l.address || "").includes(CYCLE_ADDRESS));
  expect(noFeed).toHaveLength(0);

  // E ficou guardado em "Meus Leads" como convertido, sem prazo de fase.
  const history = await request.get(`${BACKEND_ORIGIN}/api/me/history?limit=100`, {
    headers: auth(E2E_CYCLE_TOKEN),
  });
  expect(history.ok()).toBeTruthy();
  const entry = history
    .json()
    .then((data: any) =>
      (data.leads || []).find((l: any) => (l.address || "").includes(CYCLE_ADDRESS))
    );
  const row = await entry;
  expect(row).toBeTruthy();
  expect(row.stage).toBe("converted");
  expect(row.stage_expires_at).toBeNull();
  expect(row.server_now).toBeTruthy();
});

test("badge de fase com contagem dinâmica (<1h em segundos) na aba Meus Leads", async ({ page, request }) => {
  const timer = await findLeadId(request, TIMER_ADDRESS);
  await ensureAvailable(request, timer);

  // Reserva curta (1 minuto) via API: countdown <1h mostra MM:SS e decrementa.
  const res = await request.post(`${BACKEND_ORIGIN}/api/leads/${timer}/reserve`, {
    headers: { ...auth(E2E_CYCLE_TOKEN), "Content-Type": "application/json" },
    data: {
      minutes: 1,
      consent: true,
      idempotency: `e2e-timer:${timer}:${Date.now()}`,
    },
  });
  expect(res.ok()).toBeTruthy();

  await page.goto(DASHBOARD);

  // Leads em andamento NÃO aparecem no feed de Oportunidades (ficam só nos
  // "Meus Leads"). Esperar o feed assentar num card genérico (o CYCLE do teste
  // 2 já foi convertido e saiu do feed) e confirmar que o TIMER está fora.
  await expect(page.locator('[data-testid="lead-card"]').first()).toBeVisible({ timeout: 20000 });
  const timerCardInFeed = page
    .locator('[data-testid="lead-card"]')
    .filter({ hasText: TIMER_ADDRESS });
  await expect(timerCardInFeed).toHaveCount(0);

  // Na aba "Meus Leads" o histórico mostra o badge vivo com contagem regressiva.
  await page.getByRole("button", { name: "Meus Leads" }).click();
  const historyRow = page.locator('[data-testid="history-row"]').filter({ hasText: TIMER_ADDRESS });
  await expect(historyRow.first()).toBeVisible({ timeout: 20000 });

  const historyBadge = historyRow.first().locator('[role="timer"]');
  await expect(historyBadge).toBeVisible();
  await expect(historyBadge).toHaveText(/^Reservado · \d{2}:\d{2}$/);
  const before = (await historyBadge.textContent())?.trim();
  await expect.poll(async () => (await historyBadge.textContent())?.trim()).not.toBe(before);
});