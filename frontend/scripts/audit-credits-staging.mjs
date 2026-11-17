import { chromium } from "playwright";
import fs from "node:fs";

const BASE =
  process.env.AUDIT_BASE_URL ||
  "https://magic-leads-staging-fabio-dev2.vercel.app";
const TOKEN = process.env.STAGING_ACCESS_TOKEN || "";
const BYPASS = process.env.VERCEL_AUTOMATION_BYPASS_SECRET || "";
const OUT = process.env.AUDIT_OUT || "../reports/marco-1a/staging";
fs.mkdirSync(OUT, { recursive: true });
if (!TOKEN) throw new Error("STAGING_ACCESS_TOKEN is required");

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok: Boolean(ok), detail });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " · " + detail : ""}`);
}

function num(text) {
  const match = String(text || "").match(/\d[\d.]*/);
  return Number((match ? match[0] : "0").replace(/\./g, ""));
}

const browser = await chromium.launch();
const bypassHeaders = BYPASS
  ? {
      "x-vercel-protection-bypass": BYPASS,
      "x-vercel-set-bypass-cookie": "true",
    }
  : {};

async function unlockGate(page) {
  await page.goto(`${BASE}/pt/dashboard`, {
    waitUntil: "networkidle",
    timeout: 60000,
  });
  if (page.url().includes("/staging-login")) {
    await page.getByText("Acesso protegido").first().waitFor({ timeout: 30000 });
    await page.fill('input[type="password"]', TOKEN);
    await page.locator("form button").first().click();
    // O gate volta para /pt/dashboard; sem sessão, o proxy manda para /pt/auth.
    await page.waitForFunction(
      () =>
        window.location.pathname.includes("/auth") ||
        window.location.pathname.includes("/dashboard"),
      null,
      { timeout: 60000 },
    );
  }
}

async function login(page, email) {
  await page.goto(`${BASE}/pt/auth`, {
    waitUntil: "networkidle",
    timeout: 60000,
  });
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', "dev-demo-only");
  await page.locator('form button[type="submit"]').first().click();
  await page.waitForFunction(
    () => window.location.pathname.includes("/dashboard"),
    null,
    { timeout: 60000 },
  );
  await page.getByText("Oportunidades").first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(800);
}

// ---------------------------------------------------------------------------
// 1. Gate + free login directly into the official dashboard
// ---------------------------------------------------------------------------
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  extraHTTPHeaders: bypassHeaders,
});
const page = await context.newPage();

await page.goto(`${BASE}/pt/dashboard`, {
  waitUntil: "networkidle",
  timeout: 60000,
});
await page.getByText("Acesso protegido").first().waitFor({ timeout: 30000 });
check("Staging gate redirects", page.url().includes("/staging-login"));
await page.screenshot({ path: `${OUT}/01-gate.png`, fullPage: true });

await page.fill('input[type="password"]', TOKEN);
await page.locator("form button").first().click();
await page.waitForFunction(
  () =>
    window.location.pathname.includes("/auth") ||
    window.location.pathname.includes("/dashboard"),
  null,
  { timeout: 60000 },
);
check(
  "Staging token accepted",
  page.url().includes("/pt/auth") || page.url().includes("/pt/dashboard"),
);

await login(page, "qa-buyer+staging@magicleads.app");
check(
  "Free login lands in official dashboard",
  await page.getByText("Visão Geral").first().isVisible(),
);
check(
  "Official sidebar keeps Opportunities",
  await page.getByText("Oportunidades").first().isVisible(),
);
await page.screenshot({ path: `${OUT}/02-dashboard-freemium.png`, fullPage: true });

// Map / freemium browse: Opportunities tab keeps the dashboard shell and the
// masked credits panel. No contact details are shown before a reveal.
await page.locator('button:has-text("Oportunidades")').first().click();
await page.waitForTimeout(2500);
await page.getByTestId("credits-panel").first().waitFor({ timeout: 30000 });
const panel = page.getByTestId("credits-panel").first();
check(
  "Freemium keeps dashboard + masked signals",
  (await page.getByTestId("credits-panel").first().isVisible()) &&
    (await page.getByText(/\*\*\* Seed Street/).first().isVisible()),
);
await page.screenshot({ path: `${OUT}/03-map-masked-signals.png`, fullPage: true });

check(
  "Map follows active readiness",
  await page.getByText(/Mapa: Carta \/ Visita/i).first().isVisible(),
);
const readyAll = page.getByTestId("readiness-all").first();
const readyLetter = page.getByTestId("readiness-letter").first();
const readyPhone = page.getByTestId("readiness-phone").first();
check(
  "Readiness tabs visible (Todos / Carta / Telefone)",
  (await readyAll.isVisible()) && (await readyLetter.isVisible()) && (await readyPhone.isVisible()),
);
await readyPhone.click();
await page.waitForTimeout(1200);
const phoneTabText = await readyPhone.innerText();
const phoneTabCount = num(phoneTabText);
check(
  "Phone tab shows eligible leads (not zero)",
  phoneTabCount > 0,
  phoneTabText,
);
const bodyAfterPhone = await page.locator("body").innerText();
check(
  "No internal phone jargon in UI",
  !/Marco 1B|Milestone 1B|Hito 1B|Sem Searchbug/i.test(bodyAfterPhone),
);
await readyLetter.click();
await page.waitForTimeout(1200);

const sidebarCount = num(await page.locator('button:has-text("Oportunidades")').first().innerText());
const todosCount = num(await readyAll.innerText());
check(
  "Sidebar count matches Todos tab",
  sidebarCount === todosCount,
  `${sidebarCount} vs ${todosCount}`,
);
const bodyText = await page.locator("body").innerText();
check("Card titles use UTF-8 (no Â·)", !bodyText.includes("Â·"));

// ---------------------------------------------------------------------------
// 2. Sidebar "Créditos / Planos" opens the wallet modal (packs + movements)
// ---------------------------------------------------------------------------
await page.locator('button:has-text("Créditos / Planos")').first().click();
const walletModal = page.getByTestId("wallet-modal");
await walletModal.waitFor({ timeout: 30000 });
await walletModal.locator('button:has-text("Starter")').first().waitFor({ timeout: 30000 });
check(
  "Sidebar opens wallet modal with packs",
  (await walletModal.locator('button:has-text("Starter")').count()) > 0,
);
check(
  "Wallet modal includes movements",
  await walletModal.getByText("MOVIMENTOS").first().isVisible(),
);
check(
  "Feed no longer shows packs/ledger",
  (await panel.getByText("MOVIMENTOS").count()) === 0 &&
    (await panel.locator('button:has-text("Starter")').count()) === 0,
);
await page.screenshot({ path: `${OUT}/04-wallet-modal.png`, fullPage: true });

// Header wallet starts empty for the seeded buyer.
const headerWallet = page.locator('button[title="Carteira de créditos"]');
check(
  "Header wallet visible",
  (await headerWallet.first().innerText()).trim().includes("$0.00"),
);

// ---------------------------------------------------------------------------
// 3. Mock purchase + webhook idempotency + wallet in the header
// ---------------------------------------------------------------------------
await walletModal.locator('button:has-text("Starter")').first().click();
await walletModal.getByText(/Mock: Starter/).first().waitFor({ timeout: 10000 });
check("Mock checkout created", true);

await walletModal.locator('button:has-text("Simular webhook duplicado")').first().click();
await page.waitForTimeout(1500);
const webhookMsg = await walletModal
  .locator("text=Webhook 1:")
  .first()
  .innerText()
  .catch(() => "");
check(
  "Webhook idempotency",
  webhookMsg.includes("aplicado") && webhookMsg.includes("duplicado"),
  webhookMsg,
);
await page.screenshot({ path: `${OUT}/05-webhook-idempotent.png`, fullPage: true });

await walletModal.locator('button:has-text("Simular pagamento")').first().click();
await page.waitForTimeout(1500);
check(
  "Credits appear in header wallet",
  (await headerWallet.first().innerText()).trim().includes("$7.00"),
  await headerWallet.first().innerText(),
);
check(
  "Wallet ledger shows pack purchase",
  await walletModal.getByText("pack_purchase").first().isVisible(),
);
await page.screenshot({ path: `${OUT}/06-wallet-700-dashboard.png`, fullPage: true });
await walletModal.locator('button:has-text("Fechar")').last().click();
await page.waitForTimeout(500);

// ---------------------------------------------------------------------------
// 4. Reveal a signal in the dashboard and debit the wallet
// ---------------------------------------------------------------------------
await panel.locator('button:has-text("Revelar sinal"):not([disabled])').first().click();
await page.getByText("Sinal desbloqueado").first().waitFor({ timeout: 15000 });
const modal = await page
  .locator("text=Sinal desbloqueado")
  .first()
  .locator("..")
  .locator("..")
  .innerText()
  .catch(() => "");
check(
  "Signal unlocks full address + owner + mailing",
  modal.includes("Seed Street") && modal.includes("Mail Avenue"),
  modal.slice(0, 160),
);
await page.screenshot({ path: `${OUT}/07-reveal-dashboard.png`, fullPage: true });
await page.locator('button:has-text("Fechar")').first().click();
await page.waitForTimeout(800);
check(
  "Wallet debited $1.50 after reveal",
  (await headerWallet.first().innerText()).trim().includes("$5.50"),
  await headerWallet.first().innerText(),
);
await page.screenshot({ path: `${OUT}/08-wallet-after-reveal.png`, fullPage: true });

// ---------------------------------------------------------------------------
// 5. Free account with zero balance: reveal opens the packs (paywall)
// ---------------------------------------------------------------------------
const freeContext = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  extraHTTPHeaders: bypassHeaders,
});
const freePage = await freeContext.newPage();
await unlockGate(freePage);
await login(freePage, "qa-free+staging@magicleads.app");
await freePage.locator('button:has-text("Oportunidades")').first().click();
const freePanel = freePage.getByTestId("credits-panel").first();
await freePanel.waitFor({ timeout: 30000 });
await freePage.waitForTimeout(1000);
await freePanel.locator('button:has-text("Revelar sinal"):not([disabled])').first().click();
const paywall = freePage.getByTestId("credit-paywall");
await paywall.first().waitFor({ timeout: 15000 });
const paywallText = await paywall.first().innerText().catch(() => "");
check("Insufficient balance opens elegant paywall modal", Boolean(paywallText), paywallText.slice(0, 120));
check(
  "Paywall shows $6–$180 packs over the dashboard",
  paywallText.includes("Starter") && paywallText.includes("Agency"),
);
check(
  "Zero-balance wallet unchanged",
  (await freePage
    .locator('button[title="Carteira de créditos"]')
    .first()
    .innerText()).trim().includes("$0.00"),
);
await freePage.screenshot({ path: `${OUT}/09-insufficient-paywall.png`, fullPage: true });

// Compra dentro da modal: os créditos entram e o lead desbloqueia sem sair
// do dashboard (mock staging).
await paywall.locator('button:has-text("Starter")').first().click();
await freePage.getByText(/Mock: Starter/).first().waitFor({ timeout: 10000 });
await paywall.locator('button:has-text("Simular pagamento")').first().click();
await freePage.getByText("Sinal desbloqueado").first().waitFor({ timeout: 20000 });
check("Payment in paywall unlocks lead without leaving dashboard", true);
check(
  "Header wallet after paywall purchase + reveal",
  (await freePage
    .locator('button[title="Carteira de créditos"]')
    .first()
    .innerText()).trim().includes("$5.50"),
  await freePage.locator('button[title="Carteira de créditos"]').first().innerText(),
);
await freePage.screenshot({ path: `${OUT}/10-paywall-purchase-unlock.png`, fullPage: true });

fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(
  `RESULT ${failed.length ? "FAIL" : "ALL PASS"} (${results.length - failed.length}/${results.length})`,
);
if (failed.length) process.exitCode = 1;
