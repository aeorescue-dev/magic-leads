import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const OUT = join(process.cwd(), "..", "reports", "dashboard-map-preview");
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

async function openDashboard(options = {}) {
  const context = await browser.newContext({
    viewport: options.viewport ?? { width: 1500, height: 1100 },
    deviceScaleFactor: 1,
    permissions: options.geolocation ? ["geolocation"] : [],
    geolocation: options.geolocation,
  });

  const devToken = process.env.DEV_TOKEN;
  if (devToken) {
    await context.addCookies([
      { name: "garimpador_auth", value: "1", domain: "localhost", path: "/" },
      {
        name: "garimpador_token",
        value: devToken,
        domain: "localhost",
        path: "/",
      },
    ]);
    await context.addInitScript((token) => {
      localStorage.setItem("garimpador.token", token);
      localStorage.setItem("garimpador.push.ios_tutorial.dismissed", "1");
      localStorage.setItem("magic_leads_notice_seen_5", "true");
    }, devToken);
  }

  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text().slice(0, 200));
  });
  page.on("pageerror", (err) => errors.push(err.message.slice(0, 200)));

  let login = { email: "reused-session" };
  if (!devToken) {
    await page.goto(`${base}/en`, { waitUntil: "domcontentloaded" });
    login = await page.evaluate(async () => {
      const res = await fetch("/api/auth/demo", {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok)
        return { error: res.status, body: (await res.text()).slice(0, 300) };
      const data = await res.json();
      localStorage.setItem("garimpador.token", data.token);
      localStorage.setItem("garimpador.push.ios_tutorial.dismissed", "1");
      localStorage.setItem("magic_leads_notice_seen_5", "true");
      document.cookie = "garimpador_auth=1; path=/; samesite=lax";
      return { email: data.user?.email ?? null };
    });
  }
  if (login.error) throw new Error(`demo login failed: ${JSON.stringify(login)}`);

  await page.goto(`${base}/en/dashboard`, { waitUntil: "networkidle" });

  await page
    .evaluate(() => {
      const button = [...document.querySelectorAll("button")].find(
        (item) => item.textContent?.trim() === "Not now"
      );
      button?.click();
    })
    .catch(() => {});

  await page
    .waitForFunction(
      () =>
        [...document.querySelectorAll("button")].some((item) =>
          item.textContent?.trim().startsWith("Preventive")
        ),
      { timeout: 30000 }
    )
    .catch(() => {});
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((item) =>
      item.textContent?.trim().startsWith("Preventive")
    );
    button?.click();
  });
  await page.getByText("Where the work is", { exact: true }).waitFor();
  return { context, page };
}

function panel(page) {
  return page.locator("section", { hasText: "Where the work is" }).first();
}

async function clickPanelButton(page, label) {
  const clicked = await page.evaluate((text) => {
    const section = [...document.querySelectorAll("section")].find((item) =>
      item.textContent?.includes("Where the work is")
    );
    if (!section) return false;
    const button = [...section.querySelectorAll("button")].find(
      (item) => item.textContent?.trim() === text
    );
    if (!button) return false;
    button.click();
    return true;
  }, label);
  if (!clicked) throw new Error(`panel button not found: ${label}`);
}

async function clickNeighborhood(page, name) {
  const clicked = await page.evaluate((text) => {
    const section = [...document.querySelectorAll("section")].find((item) =>
      item.textContent?.includes("Where the work is")
    );
    if (!section) return false;
    const row = [...section.querySelectorAll('div[role="button"]')].find(
      (item) => item.textContent?.includes(text)
    );
    if (!row) return false;
    row.click();
    return true;
  }, name);
  if (!clicked) throw new Error(`neighborhood not found: ${name}`);
}

async function shot(page, name) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(900);
  const path = join(OUT, `${name}.png`);
  await page.screenshot({ path, fullPage: true });
  console.log("SAVED", path);
}

// 01 — dashboard real, Preventive, Boston
{
  const { context, page } = await openDashboard();
  await clickPanelButton(page, "Boston");
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await shot(page, "01-dashboard-boston");
  await context.close();
}

// 02 — bairro filtra o feed na mesma tela
{
  const { context, page } = await openDashboard();
  await clickPanelButton(page, "Boston");
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await clickNeighborhood(page, "Dorchester");
  await page.getByText("Neighborhood: Dorchester").waitFor({ timeout: 20000 });
  await shot(page, "02-filtered-dorchester");
  await context.close();
}

// 03 — Near me
{
  const { context, page } = await openDashboard({
    geolocation: { latitude: 42.3555, longitude: -71.0605 },
  });
  await clickPanelButton(page, "Boston");
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await clickPanelButton(page, "Near me");
  await page.getByText(/mi$/).first().waitFor({ timeout: 20000 });
  await shot(page, "03-near-me");
  await context.close();
}

// 04 — Dallas
{
  const { context, page } = await openDashboard();
  await clickPanelButton(page, "Dallas");
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await shot(page, "04-dallas");
  await context.close();
}

// 05 — Chicago: seletor funciona, mapa indisponível, leads abaixo
{
  const { context, page } = await openDashboard();
  await clickPanelButton(page, "Chicago");
  await page
    .getByText("Map unavailable for this city")
    .waitFor({ timeout: 20000 });
  await shot(page, "05-chicago");
  await context.close();
}

// 06 — mobile
{
  const { context, page } = await openDashboard({
    viewport: { width: 390, height: 844 },
  });
  await clickPanelButton(page, "Boston");
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await shot(page, "06-mobile");
  await context.close();
}

await browser.close();
console.log("ERRORS", JSON.stringify(errors.slice(0, 8)));
