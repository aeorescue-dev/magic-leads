import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const OUT = join(process.cwd(), "..", "reports", "territory-preview");
mkdirSync(OUT, { recursive: true });

const base = "http://localhost:3002/en/territory-preview";

async function launch() {
  try {
    return await chromium.launch({ channel: "chrome" });
  } catch {
    return await chromium.launch();
  }
}

const browser = await launch();
const errors = [];

async function capture(name, viewport, steps) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`${name}: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`${name}: ${err.message}`));
  await page.goto(base, { waitUntil: "networkidle" });
  await page.getByText("Where the opportunities are").waitFor({ timeout: 30000 });
  if (steps) await steps(page);
  await page.waitForTimeout(400);
  const path = join(OUT, `${name}.png`);
  await page.screenshot({ path, fullPage: true });
  console.log("SAVED", path);
  await context.close();
}

await capture("01-zones-desktop", { width: 1440, height: 1000 });

await capture("02-matrix-desktop", { width: 1440, height: 1000 }, async (page) => {
  await page.getByRole("button", { name: "Matrix" }).click();
  await page.waitForTimeout(300);
});

await capture("03-map-dallas", { width: 1440, height: 1000 }, async (page) => {
  await page.getByRole("button", { name: /^Dallas/ }).click();
  await page.getByRole("button", { name: "Map", exact: true }).click();
  await page.waitForTimeout(400);
});

await capture("04-zone-detail", { width: 1440, height: 1000 }, async (page) => {
  await page.getByText("Dorchester", { exact: true }).first().click();
  await page.waitForTimeout(300);
});

await capture("05-mobile-zones", { width: 390, height: 844 });

await browser.close();
console.log("ERRORS", JSON.stringify(errors));
