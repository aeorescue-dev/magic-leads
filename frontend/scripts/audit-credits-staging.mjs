import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.AUDIT_BASE_URL || "https://magic-leads-frontend-final-gv537n0ha-fabio-dev2.vercel.app";
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
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  extraHTTPHeaders: BYPASS
    ? { "x-vercel-protection-bypass": BYPASS, "x-vercel-set-bypass-cookie": "true" }
    : {},
});
const page = await context.newPage();

await page.goto(`${BASE}/pt/credits`, { waitUntil: "networkidle", timeout: 60000 });
await page.getByText("Acesso protegido").first().waitFor({ timeout: 30000 });
check("Staging gate redirects", page.url().includes("/staging-login"));
await page.screenshot({ path: `${OUT}/01-gate.png`, fullPage: true });

await page.fill('input[type="password"]', TOKEN);
await page.locator("form button").first().click();
await page.waitForURL(/\/pt\/credits/, { timeout: 30000 });
await page.locator("h1").first().waitFor({ timeout: 30000 });
check("Staging token accepted", page.url().includes("/pt/credits"));
await page.screenshot({ path: `${OUT}/02-credits-login.png`, fullPage: true });

await page.fill('input[type="email"]', "qa-buyer+staging@magicleads.app");
await page.fill('input[type="password"]', "dev-demo-only");
await page.locator("form button").first().click();
await page.getByText("Carteira").first().waitFor({ timeout: 30000 });
await page.waitForTimeout(1000);
check("Free account login in staging", await page.getByText("qa-buyer+staging@magicleads.app").first().isVisible());
await page.screenshot({ path: `${OUT}/03-wallet-leads.png`, fullPage: true });

await page.locator('button:has-text("Starter")').first().click();
await page.getByText(/Mock: Starter/).first().waitFor({ timeout: 10000 });
await page.locator('button:has-text("Simular webhook duplicado")').first().click();
await page.waitForTimeout(1000);
const webhookMsg = await page.locator("text=Webhook 1:").first().innerText().catch(() => "");
check("Staging webhook idempotency", webhookMsg.includes("aplicado") && webhookMsg.includes("duplicado"), webhookMsg);
await page.screenshot({ path: `${OUT}/04-webhook.png`, fullPage: true });

await page.locator('button:has-text("Simular pagamento")').first().click();
await page.waitForTimeout(1000);
const wallet = await page.locator("section").first().innerText();
check("Staging wallet +700", wallet.includes("$7.00") || wallet.includes("700"), wallet.slice(0, 70));

await page.locator('button:has-text("Revelar sinal")').first().click();
await page.getByText("Sinal desbloqueado").first().waitFor({ timeout: 15000 });
const modal = await page.locator("text=Sinal desbloqueado").first().locator("..").locator("..").innerText().catch(() => "");
check("Staging signal reveal", modal.includes("Mail Avenue") && modal.includes("Owner"), modal.slice(0, 140));
await page.screenshot({ path: `${OUT}/05-reveal.png`, fullPage: true });

fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`RESULT ${failed.length ? "FAIL" : "ALL PASS"} (${results.length - failed.length}/${results.length})`);
if (failed.length) process.exitCode = 1;
