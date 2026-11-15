import { chromium } from "playwright";
import fs from "node:fs";

const base = "http://localhost:3002";
const token = fs
  .readFileSync("C:/Users/Fabio/AppData/Local/Temp/opencode/dev_token.txt", "utf8")
  .trim();
const out = "../reports/opportunities-tab-preview";
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: "chrome" });

async function open(tab) {
  const context = await browser.newContext({
    viewport: { width: 1500, height: 1100 },
    deviceScaleFactor: 2,
  });
  await context.addCookies([
    { name: "garimpador_auth", value: "1", domain: "localhost", path: "/" },
    { name: "garimpador_token", value: token, domain: "localhost", path: "/" },
  ]);
  await context.addInitScript((value) => {
    localStorage.setItem("garimpador.token", value);
    localStorage.setItem("garimpador.push.ios_tutorial.dismissed", "1");
    localStorage.setItem("magic_leads_notice_seen_5", "true");
  }, token);
  const page = await context.newPage();
  await page.goto(`${base}/en/dashboard`, { waitUntil: "networkidle" });
  await page.evaluate((label) => {
    const button = [...document.querySelectorAll("button")].find(
      (item) =>
        item.textContent?.trim().startsWith(label) &&
        item.getAttribute("aria-haspopup") !== "dialog"
    );
    button?.click();
  }, tab);
  await page.getByText("Where the work is", { exact: true }).waitFor();
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find(
      (item) =>
        item.textContent?.trim() === "Boston" &&
        item.getAttribute("aria-haspopup") !== "dialog"
    );
    button?.click();
  });
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(1200);
  return { context, page };
}

for (const [tab, name] of [
  ["Opportunities", "fresh-opportunities-boston"],
  ["Pre-inspection", "fresh-prevention-boston"],
]) {
  const { context, page } = await open(tab);
  const panel = page
    .locator('section:has-text("Where the work is")')
    .first();
  await panel.screenshot({ path: `${out}/${name}.png` });
  await context.close();
  console.log("saved", `${out}/${name}.png`);
}

await browser.close();
