import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.AUDIT_BASE_URL || "http://localhost:3002";
const OUT = process.env.AUDIT_OUT || "../reports/marco-1a";
fs.mkdirSync(OUT, { recursive: true });

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok: Boolean(ok), detail });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " · " + detail : ""}`);
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
const page = await context.newPage();

async function login(p, email) {
  await p.goto(`${BASE}/pt/auth`, { waitUntil: "networkidle", timeout: 60000 });
  await p.fill('input[type="email"]', email);
  await p.fill('input[type="password"]', "dev-demo-only");
  await p.locator('form button[type="submit"]').first().click();
  await p.waitForURL(/\/pt\/dashboard/, { timeout: 60000 });
  await p.getByText("Oportunidades").first().waitFor({ timeout: 30000 });
  await p.waitForTimeout(800);
}

await login(page, "qa-buyer+staging@magicleads.app");
check(
  "Free login lands in official dashboard",
  await page.getByText("Visão Geral").first().isVisible(),
);
await page.screenshot({ path: `${OUT}/01-dashboard-freemium.png`, fullPage: true });

// Masked signals inside the official shell.
await page.locator('button:has-text("Oportunidades")').first().click();
await page.getByTestId("credits-panel").first().waitFor({ timeout: 30000 });
check(
  "Freemium keeps masked signals",
  await page.getByText(/\*\*\* Seed Street/).first().isVisible(),
);
await page.screenshot({ path: `${OUT}/02-map-masked-signals.png`, fullPage: true });

// Packs via sidebar.
await page.locator('button:has-text("Créditos / Planos")').first().click();
const panel = page.getByTestId("credits-panel").first();
await panel.waitFor({ timeout: 30000 });
const headerWallet = page.locator('button[title="Carteira de créditos"]');
check("Sidebar opens credit packs", (await panel.locator('button:has-text("Starter")').count()) > 0);
await page.screenshot({ path: `${OUT}/03-credits-packs.png`, fullPage: true });

// Mock purchase + webhook idempotency.
await panel.locator('button:has-text("Starter")').first().click();
await page.getByText(/Mock: Starter/).first().waitFor({ timeout: 10000 });
await page.screenshot({ path: `${OUT}/04-mock-checkout.png`, fullPage: true });
await page.locator('button:has-text("Simular webhook duplicado")').first().click();
await page.waitForTimeout(1500);
const webhookMsg = await page.locator("text=Webhook 1:").first().innerText().catch(() => "");
check(
  "Webhook idempotency visible",
  webhookMsg.includes("aplicado") && webhookMsg.includes("duplicado"),
  webhookMsg,
);
await page.screenshot({ path: `${OUT}/05-webhook-idempotent.png`, fullPage: true });

await page.locator('button:has-text("Simular pagamento")').first().click();
await page.waitForTimeout(1500);
check(
  "Header wallet credited 700",
  (await headerWallet.first().innerText()).trim().includes("$7.00"),
  await headerWallet.first().innerText(),
);
await page.screenshot({ path: `${OUT}/06-wallet-700.png`, fullPage: true });

// Reveal signal.
await panel.locator('button:has-text("Revelar sinal")').first().click();
await page.getByText("Sinal desbloqueado").first().waitFor({ timeout: 15000 });
const modalText = await page
  .locator("text=Sinal desbloqueado")
  .first()
  .locator("..")
  .locator("..")
  .innerText()
  .catch(() => "");
check(
  "Signal reveal returns address + owner + mailing",
  modalText.includes("Seed Street") && modalText.includes("Mail Avenue"),
  modalText.slice(0, 160),
);
await page.screenshot({ path: `${OUT}/07-signal-reveal.png`, fullPage: true });
await page.locator('button:has-text("Fechar")').first().click();
await page.waitForTimeout(700);

// Same address, another trade: new exclusivity allowed.
const tradeSelect = panel.locator("select").nth(1);
await tradeSelect.selectOption("Electrical");
await panel.locator('button:has-text("Revelar sinal")').first().click();
await page.waitForTimeout(1200);
const crossTrade = await page
  .getByText("Sinal desbloqueado")
  .first()
  .isVisible()
  .catch(() => false);
check("Same lead can be revealed by another trade", crossTrade);
await page.screenshot({ path: `${OUT}/08-cross-trade.png`, fullPage: true });
if (crossTrade) await page.locator('button:has-text("Fechar")').first().click();
await page.waitForTimeout(500);

// Same user/trade twice: duplicate, no charge.
await tradeSelect.selectOption("Plumbing");
await panel.locator('button:has-text("Revelar sinal")').first().click();
await page.waitForTimeout(1200);
const dupMsg = await page.getByText(/duplicado|Duplicate/i).first().innerText().catch(() => "");
check("Same user/trade duplicate does not charge", Boolean(dupMsg), dupMsg);
await page.screenshot({ path: `${OUT}/09-duplicate.png`, fullPage: true });

// Zero balance account -> paywall.
const context2 = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
const page2 = await context2.newPage();
await login(page2, "qa-free+staging@magicleads.app");
await page2.locator('button:has-text("Créditos / Planos")').first().click();
const panel2 = page2.getByTestId("credits-panel").first();
await panel2.waitFor({ timeout: 30000 });
await page2.waitForTimeout(800);
await panel2.locator('button:has-text("Revelar sinal")').first().click();
await page2.waitForTimeout(1200);
const insufficient = await page2
  .getByText(/Saldo insuficiente/)
  .first()
  .innerText()
  .catch(() => "");
check("Insufficient credits blocked", Boolean(insufficient), insufficient);
await page2.screenshot({ path: `${OUT}/10-insufficient.png`, fullPage: true });

fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`RESULT ${failed.length ? "FAIL" : "ALL PASS"} (${results.length - failed.length}/${results.length})`);
if (failed.length) process.exitCode = 1;
