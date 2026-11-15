import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const OUT = join(process.cwd(), "..", "reports", "opportunities-tab-preview");
mkdirSync(OUT, { recursive: true });
const base = "http://localhost:3002";

async function launch() {
  try {
    return await chromium.launch({ channel: "chrome" });
  } catch {
    return await chromium.launch();
  }
}

const browser = await launch();
const errors = [];

async function openOpportunities(options = {}) {
  const context = await browser.newContext({
    viewport: options.viewport ?? { width: 1500, height: 1100 },
    deviceScaleFactor: 1,
    permissions: options.geolocation ? ["geolocation"] : [],
    geolocation: options.geolocation,
  });
  const token = process.env.DEV_TOKEN;
  if (token) {
    await context.addCookies([
      { name: "garimpador_auth", value: "1", domain: "localhost", path: "/" },
      { name: "garimpador_token", value: token, domain: "localhost", path: "/" },
    ]);
    await context.addInitScript((value) => {
      localStorage.setItem("garimpador.token", value);
      localStorage.setItem("garimpador.push.ios_tutorial.dismissed", "1");
      localStorage.setItem("magic_leads_notice_seen_5", "true");
    }, token);
  } else {
    throw new Error("DEV_TOKEN missing");
  }

  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text().slice(0, 200));
  });
  page.on("pageerror", (err) => errors.push(err.message.slice(0, 200)));

  await page.goto(`${base}/en/dashboard`, { waitUntil: "networkidle" });
  await page
    .evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((item) =>
        item.textContent?.trim().startsWith("Opportunities")
      );
      button?.click();
    })
    .catch(() => {});

  await page.getByText("Where the work is", { exact: true }).waitFor({
    timeout: 30000,
  });
  return { context, page };
}

async function selectCity(page, name) {
  const clicked = await page.evaluate((city) => {
    const button = [...document.querySelectorAll("button")].find(
      (item) =>
        item.textContent?.trim() === city &&
        item.getAttribute("aria-haspopup") !== "dialog"
    );
    if (!button) return false;
    button.click();
    return true;
  }, name);
  if (!clicked) throw new Error(`city button not found: ${name}`);
}

async function clickZone(page, name) {
  const clicked = await page.evaluate((zoneName) => {
    const section = [...document.querySelectorAll("section")].find((item) =>
      item.textContent?.includes("Where the work is")
    );
    if (!section) return false;
    const row = [...section.querySelectorAll('div[role="button"]')].find(
      (item) => item.textContent?.includes(zoneName)
    );
    if (!row) return false;
    row.click();
    return true;
  }, name);
  if (!clicked) throw new Error(`zone not found: ${name}`);
}

async function shot(page, name) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(900);
  const path = join(OUT, `${name}.png`);
  await page.screenshot({ path, fullPage: true });
  console.log("SAVED", path);
}

// 01 — Opportunities com mapa (Boston)
{
  const { context, page } = await openOpportunities();
  await selectCity(page, "Boston");
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await shot(page, "01-opportunities-boston");
  await context.close();
}

// 02 — bairro filtra os cartões na mesma tela
{
  const { context, page } = await openOpportunities();
  await selectCity(page, "Boston");
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await clickZone(page, "Dorchester");
  await page.getByText("Neighborhood: Dorchester").waitFor({ timeout: 20000 });
  await shot(page, "02-filtered-dorchester");
  await context.close();
}

// 03 — Near me
{
  const { context, page } = await openOpportunities({
    geolocation: { latitude: 42.3555, longitude: -71.0605 },
  });
  await selectCity(page, "Boston");
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find(
      (item) => item.textContent?.trim() === "Near me"
    );
    button?.click();
  });
  await page.getByText(/mi$/).first().waitFor({ timeout: 20000 });
  await shot(page, "03-near-me");
  await context.close();
}

// 04 — Dallas (setores)
{
  const { context, page } = await openOpportunities();
  await selectCity(page, "Dallas");
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await shot(page, "04-dallas");
  await context.close();
}

// 05 — Chicago (ZIP, sem bairro)
{
  const { context, page } = await openOpportunities();
  await selectCity(page, "Chicago");
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await shot(page, "05-chicago");
  await context.close();
}

// 06 — mobile
{
  const { context, page } = await openOpportunities({
    viewport: { width: 390, height: 844 },
  });
  await selectCity(page, "Boston");
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await shot(page, "06-mobile");
  await context.close();
}

await browser.close();
console.log("ERRORS", JSON.stringify(errors.slice(0, 6)));
