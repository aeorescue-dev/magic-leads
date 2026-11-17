import { chromium } from "playwright";
import fs from "node:fs";

const BASE =
  process.env.AUDIT_BASE_URL ||
  "https://magic-leads-frontend-final-gv537n0ha-fabio-dev2.vercel.app";
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
    await page.waitForURL(/\/pt\/dashboard/, { timeout: 30000 });
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
  await page.waitForURL(/\/pt\/dashboard/, { timeout: 60000 });
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
await page.waitForURL(/\/pt\/dashboard/, { timeout: 30000 });
check("Staging token accepted", page.url().includes("/pt/dashboard"));

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
await page.waitForTimeout(1200);
await page.getByTestId("credits-panel").first().waitFor({ timeout: 30000 });
check(
  "Freemium keeps dashboard + masked signals",
  (await page.getByTestId("credits-panel").first().isVisible()) &&
    (await page.getByText(/\*\*\* Seed Street/).first().isVisible()),
);
await page.screenshot({ path: `${OUT}/03-map-masked-signals.png`, fullPage: true });

// ---------------------------------------------------------------------------
// 2. Sidebar "Créditos / Planos" opens the packs inside the dashboard
// ---------------------------------------------------------------------------
await page.locator('button:has-text("Créditos / Planos")').first().click();
await page.getByTestId("credits-panel").first().waitFor({ timeout: 30000 });
const panel = page.getByTestId("credits-panel").first();
const packs = await panel.locator('button:has-text("Starter")').count();
check("Sidebar opens credit packs in dashboard", packs > 0);
await page.screenshot({ path: `${OUT}/04-credits-packs.png`, fullPage: true });

// Header wallet starts empty for the seeded buyer.
const headerWallet = page.locator('button[title="Carteira de créditos"]');
check(
  "Header wallet visible",
  (await headerWallet.first().innerText()).trim().includes("$0.00"),
);

// ---------------------------------------------------------------------------
// 3. Mock purchase + webhook idempotency + wallet in the header
// ---------------------------------------------------------------------------
await panel.locator('button:has-text("Starter")').first().click();
await page.getByText(/Mock: Starter/).first().waitFor({ timeout: 10000 });
check("Mock checkout created", true);

await page.locator('button:has-text("Simular webhook duplicado")').first().click();
await page.waitForTimeout(1500);
const webhookMsg = await page
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

await page.locator('button:has-text("Simular pagamento")').first().click();
await page.waitForTimeout(1500);
check(
  "Credits appear in header wallet",
  (await headerWallet.first().innerText()).trim().includes("$7.00"),
  await headerWallet.first().innerText(),
);
await page.screenshot({ path: `${OUT}/06-wallet-700-dashboard.png`, fullPage: true });

// ---------------------------------------------------------------------------
// 4. Reveal a signal in the dashboard and debit the wallet
// ---------------------------------------------------------------------------
await panel.locator('button:has-text("Revelar sinal")').first().click();
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
await freePage.locator('button:has-text("Créditos / Planos")').first().click();
const freePanel = freePage.getByTestId("credits-panel").first();
await freePanel.waitFor({ timeout: 30000 });
await freePage.waitForTimeout(800);
await freePanel.locator('button:has-text("Revelar sinal")').first().click();
await freePage.waitForTimeout(1200);
const insufficient = await freePage
  .getByText(/Saldo insuficiente/)
  .first()
  .innerText()
  .catch(() => "");
check("Insufficient balance opens pack paywall", Boolean(insufficient), insufficient);
check(
  "Zero-balance wallet unchanged",
  (await freePage
    .locator('button[title="Carteira de créditos"]')
    .first()
    .innerText()).trim().includes("$0.00"),
);
await freePage.screenshot({ path: `${OUT}/09-insufficient-paywall.png`, fullPage: true });

fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(
  `RESULT ${failed.length ? "FAIL" : "ALL PASS"} (${results.length - failed.length}/${results.length})`,
);
if (failed.length) process.exitCode = 1;
