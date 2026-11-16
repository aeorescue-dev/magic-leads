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

await page.goto(`${BASE}/pt/credits`, { waitUntil: "networkidle", timeout: 60000 });
await page.locator("h1").first().waitFor({ timeout: 30000 });
check("Staging page loads", await page.locator("h1").first().isVisible());
await page.screenshot({ path: `${OUT}/01-login.png`, fullPage: true });

await page.fill('input[type="email"]', "qa-buyer+staging@magicleads.app");
await page.fill('input[type="password"]', "dev-demo-only");
await page.locator("form button").first().click();
await page.getByText("Carteira").first().waitFor({ timeout: 30000 });
await page.waitForTimeout(1200);
check("Free account login", await page.getByText("qa-buyer+staging@magicleads.app").first().isVisible());
await page.screenshot({ path: `${OUT}/02-wallet-leads.png`, fullPage: true });

await page.locator('button:has-text("Starter")').first().click();
await page.getByText(/Mock: Starter/).first().waitFor({ timeout: 10000 });
await page.screenshot({ path: `${OUT}/03-mock-checkout.png`, fullPage: true });
check("Mock checkout created", true);

await page.locator('button:has-text("Simular webhook duplicado")').first().click();
await page.waitForTimeout(1200);
const webhookMsg = await page.locator("text=Webhook 1:").first().innerText().catch(() => "");
check("Webhook idempotency visible", webhookMsg.includes("aplicado") && webhookMsg.includes("duplicado"), webhookMsg);
await page.screenshot({ path: `${OUT}/04-webhook-idempotent.png`, fullPage: true });

await page.locator('button:has-text("Simular pagamento")').first().click();
await page.waitForTimeout(1200);
const walletAfter = await page.locator("section").first().innerText();
check("Wallet credited 700", walletAfter.includes("$7.00") || walletAfter.includes("700"), walletAfter.slice(0, 80));
await page.screenshot({ path: `${OUT}/05-wallet-700.png`, fullPage: true });

await page.locator('button:has-text("Revelar sinal")').first().click();
await page.getByText("Sinal desbloqueado").first().waitFor({ timeout: 15000 });
const modalText = await page.locator("text=Sinal desbloqueado").first().locator("..").locator("..").innerText().catch(() => "");
check("Signal reveal returns full owner/mailing", modalText.includes("Mail Avenue") && modalText.includes("Owner"), modalText.slice(0, 160));
await page.screenshot({ path: `${OUT}/06-signal-reveal.png`, fullPage: true });
await page.locator('button:has-text("Fechar")').first().click();
await page.waitForTimeout(600);

await page.locator("select").selectOption("Electrical");
await page.locator('button:has-text("Revelar sinal")').first().click();
await page.waitForTimeout(900);
const crossTrade = await page.locator("text=Sinal desbloqueado").first().isVisible().catch(() => false);
check("Same lead can be revealed by another trade", crossTrade);
await page.screenshot({ path: `${OUT}/07-cross-trade.png`, fullPage: true });
if (crossTrade) await page.locator('button:has-text("Fechar")').first().click();
await page.waitForTimeout(500);

await page.locator("select").selectOption("Plumbing");
await page.locator('button:has-text("Revelar sinal")').first().click();
await page.waitForTimeout(900);
const dupMsg = await page.getByText(/duplicado|Duplicate/i).first().innerText().catch(() => "");
check("Same user/trade duplicate does not charge", Boolean(dupMsg), dupMsg);
await page.screenshot({ path: `${OUT}/08-duplicate.png`, fullPage: true });

const context2 = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
const page2 = await context2.newPage();
await page2.goto(`${BASE}/pt/credits`, { waitUntil: "networkidle", timeout: 60000 });
await page2.fill('input[type="email"]', "qa-free+staging@magicleads.app");
await page2.fill('input[type="password"]', "dev-demo-only");
await page2.locator("form button").first().click();
await page2.getByText("Carteira").first().waitFor({ timeout: 30000 });
await page2.waitForTimeout(800);
await page2.locator('button:has-text("Revelar sinal")').nth(1).click();
await page2.waitForTimeout(900);
const insufficient = await page2.getByText(/Saldo insuficiente/).first().innerText().catch(() => "");
check("Insufficient credits blocked", Boolean(insufficient), insufficient);
await page2.screenshot({ path: `${OUT}/09-insufficient.png`, fullPage: true });

fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`RESULT ${failed.length ? "FAIL" : "ALL PASS"} (${results.length - failed.length}/${results.length})`);
if (failed.length) process.exitCode = 1;
