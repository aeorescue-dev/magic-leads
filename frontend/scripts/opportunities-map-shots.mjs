import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const OUT = join(process.cwd(), "..", "reports", "opportunities-map-preview");
mkdirSync(OUT, { recursive: true });

const base = "http://localhost:3002/en/opportunities-preview";

async function launch() {
  try {
    return await chromium.launch({ channel: "chrome" });
  } catch {
    return await chromium.launch();
  }
}

const browser = await launch();
const errors = [];

async function capture(name, options = {}) {
  const context = await browser.newContext({
    viewport: options.viewport ?? { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
    permissions: options.geolocation ? ["geolocation"] : [],
    geolocation: options.geolocation,
  });
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`${name}: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`${name}: ${err.message}`));

  await page.goto(base, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Opportunities" }).waitFor({ timeout: 30000 });
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });

  if (options.steps) await options.steps(page);

  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1200);

  const path = join(OUT, `${name}.png`);
  await page.screenshot({ path, fullPage: true });
  console.log("SAVED", path);
  await context.close();
}

await capture("01-overview-boston");

await capture("02-roof-boston", {
  steps: async (page) => {
    await page.getByRole("button", { name: "Roofing & Structure" }).click();
    await page.locator(".opp-pin").first().waitFor();
  },
});

await capture("03-dallas", {
  steps: async (page) => {
    await page.getByRole("button", { name: "Dallas" }).click();
    await page.locator(".opp-pin").first().waitFor();
  },
});

await capture("04-near-me", {
  geolocation: { latitude: 42.3555, longitude: -71.0605 },
  steps: async (page) => {
    await page.getByRole("button", { name: "Near me" }).click();
    await page.getByText(/mi$/).first().waitFor({ timeout: 20000 });
  },
});

await capture("06-selected", {
  steps: async (page) => {
    await page
      .locator('div[role="button"]', { hasText: "Dorchester" })
      .first()
      .click();
    await page.getByText("204 opportunities").last().waitFor();
  },
});

await capture("07-view-leads", {
  steps: async (page) => {
    const row = page
      .locator('div[role="button"]', { hasText: "Dorchester" })
      .first();
    await row.click();
    await row.getByRole("button", { name: "View leads" }).click();
    await page.getByText(/Opening 204 leads in Dorchester/).waitFor();
  },
});

await capture("05-mobile", {
  viewport: { width: 390, height: 844 },
});

await capture("08-mobile-list", {
  viewport: { width: 390, height: 844 },
  steps: async (page) => {
    await page.getByRole("button", { name: "List" }).click();
    await page.getByText("Dorchester").first().waitFor();
  },
});

await browser.close();
console.log("ERRORS", JSON.stringify(errors));
