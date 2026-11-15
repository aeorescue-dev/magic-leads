import { chromium } from "playwright";

const base = "http://localhost:3002";
const browser = await chromium.launch({ channel: "chrome" });
const results = [];
const requests = [];

async function waitPanel(page) {
  await page.waitForFunction(
    () => {
      const panel = [...document.querySelectorAll("section")].find((item) =>
        item.textContent?.includes("Where the work is")
      );
      const text = panel?.innerText ?? "";
      return (
        text.includes("opportunities in") && !text.includes("Loading opportunities")
      );
    },
    { timeout: 30000 }
  );
}

async function waitFeed(page) {
  await page.waitForFunction(
    () => {
      const feed = [...document.querySelectorAll("section")].find((item) =>
        item.textContent?.includes("Opportunities for you")
      );
      const header = feed?.querySelector("h2")?.innerText ?? "";
      const match = header.match(/([\d.,]+)\s+(?:of|de)\s+([\d.,]+)/i);
      return match ? Number(match[2].replace(/[^\d]/g, "")) > 0 : false;
    },
    { timeout: 30000 }
  );
}

async function open() {
  const token = process.env.DEV_TOKEN;
  if (!token) throw new Error("DEV_TOKEN missing");
  const context = await browser.newContext({
    viewport: { width: 1500, height: 1100 },
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
  await page.bringToFront();
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/leads/neighborhoods")) requests.push(url);
  });
  await page.goto(`${base}/en/dashboard`, { waitUntil: "networkidle" });
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((item) =>
      item.textContent?.trim().startsWith("Opportunities")
    );
    button?.click();
  });
  await page.getByText("Where the work is", { exact: true }).waitFor();
  return { context, page };
}

async function selectCity(page, name) {
  const ok = await page.evaluate((city) => {
    const button = [...document.querySelectorAll("button")].find(
      (item) =>
        item.textContent?.trim() === city &&
        item.getAttribute("aria-haspopup") !== "dialog"
    );
    if (!button) return false;
    button.click();
    return true;
  }, name);
  if (!ok) throw new Error(`city ${name} not found`);
  await page.locator(".opp-pin").first().waitFor({ timeout: 30000 });
  await waitPanel(page);
  await waitFeed(page);
  await page.waitForTimeout(400);
}

async function readState(page) {
  return page.evaluate(() => {
    const panel = [...document.querySelectorAll("section")].find((item) =>
      item.textContent?.includes("Where the work is")
    );
    const text = panel?.innerText ?? "";
    const totalMatch = text.match(
      /([\d.,]+)\s+opportunities in\s+([\d.,]+)\s+neighborhoods/i
    );
    const rows = [
      ...panel.querySelectorAll('ul li div[role="button"]'),
    ];
    const counts = rows
      .map((row) => row.innerText.match(/([\d.,]+)\s+opportunit/i))
      .map((match) => (match ? Number(match[1].replace(/[^\d]/g, "")) : 0));
    const feedSection = [...document.querySelectorAll("section")].find((item) =>
      item.textContent?.includes("Opportunities for you")
    );
    const header = feedSection?.querySelector("h2")?.innerText ?? "";
    const feedMatch = header.match(/([\d.,]+)\s+(?:of|de)\s+([\d.,]+)/i);
    return {
      total: totalMatch ? Number(totalMatch[1].replace(/[^\d]/g, "")) : null,
      neighborhoods: totalMatch
        ? Number(totalMatch[2].replace(/[^\d]/g, ""))
        : null,
      rowSum: counts.reduce((sum, value) => sum + value, 0),
      feedShown: feedMatch ? Number(feedMatch[1].replace(/[^\d]/g, "")) : null,
      feedTotal: feedMatch ? Number(feedMatch[2].replace(/[^\d]/g, "")) : null,
      header,
    };
  });
}

function check(label, condition, detail) {
  results.push({ label, ok: condition, detail });
  console.log(condition ? "PASS" : "FAIL", label, detail ?? "");
}

// Boston: lista/painel/feed + deadline
{
  const { context, page } = await open();
  await selectCity(page, "Boston");
  const state = await readState(page);
  check(
    "Boston lista = total do painel",
    state.total !== null && state.total === state.rowSum,
    `${state.rowSum} vs ${state.total}`
  );
  check(
    "Boston total do painel = total do feed",
    state.total !== null && state.total === state.feedTotal,
    `${state.total} vs ${state.feedTotal}`
  );

  const before = requests.length;
  await page.evaluate(() => {
    const label = [...document.querySelectorAll("button,label,span")].find(
      (item) => item.textContent?.trim() === "Deadline only"
    );
    (label?.closest("button") ?? label)?.click();
  });
  await page.waitForTimeout(1500);
  await waitPanel(page);
  await waitFeed(page);
  const deadline = await readState(page);
  const newRequests = requests.slice(before);
  check(
    "Deadline only enviado ao servidor",
    newRequests.some((url) => url.includes("deadline_only=true")),
    newRequests.join(" | ").slice(-100)
  );
  check(
    "Deadline only: painel = feed",
    deadline.total !== null && deadline.total === deadline.feedTotal,
    `${deadline.total} vs ${deadline.feedTotal}`
  );
  await context.close();
}

// Boston: clique num bairro filtra o feed
{
  const { context, page } = await open();
  await selectCity(page, "Boston");
  const zone = await page.evaluate(() => {
    const panel = [...document.querySelectorAll("section")].find((item) =>
      item.textContent?.includes("Where the work is")
    );
    const row = panel?.querySelector('ul li div[role="button"]');
    if (!row) return null;
    const text = row.innerText.replace(/\s+/g, " ");
    const match = text.match(/([\d.,]+)\s+opportunit/i);
    const name = text.split(" ").slice(0, -2).join(" ") || null;
    const count = match ? Number(match[1].replace(/[^\d]/g, "")) : null;
    row.click();
    return { name, count };
  });
  await page.getByText(/Neighborhood:/).waitFor({ timeout: 15000 });
  await page.waitForFunction(
    (expected) => {
      const feed = [...document.querySelectorAll("section")].find((item) =>
        item.textContent?.includes("Opportunities for you")
      );
      const header = feed?.querySelector("h2")?.innerText ?? "";
      const match = header.match(/([\d.,]+)\s+(?:of|de)\s+([\d.,]+)/i);
      return match ? Number(match[2].replace(/[^\d]/g, "")) === expected : false;
    },
    zone?.count ?? -1,
    { timeout: 20000 }
  ).catch(() => {});
  await page.waitForTimeout(500);
  const filtered = await readState(page);
  check(
    `Boston bairro ${zone?.name}: feed = linha`,
    zone !== null && zone.count !== null && filtered.feedTotal === zone.count,
    `${filtered.feedTotal} vs ${zone?.count}`
  );
  await context.close();
}

// NYC
{
  const { context, page } = await open();
  await selectCity(page, "NYC");
  const state = await readState(page);
  check(
    "NYC lista = total do painel",
    state.total !== null && state.total === state.rowSum,
    `${state.rowSum} vs ${state.total}`
  );
  check(
    "NYC total do painel = total do feed",
    state.total !== null && state.total === state.feedTotal,
    `${state.total} vs ${state.feedTotal}`
  );
  await context.close();
}

await browser.close();
const failed = results.filter((item) => !item.ok);
console.log("RESULT", failed.length === 0 ? "ALL PASS" : `${failed.length} FAIL`);
process.exit(failed.length === 0 ? 0 : 1);
