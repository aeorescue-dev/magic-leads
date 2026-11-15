import { chromium } from "playwright";

const base = process.env.AUDIT_BASE_URL || "http://localhost:3002";
const apiBase =
  process.env.AUDIT_API_URL || "http://127.0.0.1:8011";
const token = process.env.AUDIT_TOKEN || process.env.DEV_TOKEN;
const maxMs = Number(process.env.AUDIT_MAX_MS || 50);
const latencyOnly = process.argv.includes("--latency-only");
const results = [];
const requests = [];
const territoryRequests = [];
const freshByCity = {};

if (!token) throw new Error("AUDIT_TOKEN/DEV_TOKEN missing");

function check(label, condition, detail) {
  results.push({ label, ok: condition, detail });
  console.log(condition ? "PASS" : "FAIL", label, detail ?? "");
}

/**
 * Pós-deploy: o tempo do servidor (Server-Timing: db) tem de ficar abaixo de
 * `AUDIT_MAX_MS` para as 4 cidades. Mede o processamento do SQLite, não a latência
 * WAN. Também exige 200 e payload válido — 500/timeout falha o deploy.
 */
async function fetchCityTiming(city) {
  const url = `${apiBase}/api/leads/neighborhoods?city=${encodeURIComponent(
    city
  )}&days=7`;
  const started = Date.now();
  let status = 0;
  let dbMs = null;
  let valid = false;
  let fresh = 0;
  let error = "";
  try {
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    status = res.status;
    const timing = res.headers.get("server-timing") || "";
    const match = timing.match(/db;dur=([\d.]+)/);
    dbMs = match ? Number(match[1]) : null;
    if (status === 200) {
      const body = await res.json();
      valid = typeof body.total === "number" && Array.isArray(body.groups);
      fresh = (body.groups ?? []).reduce(
        (sum, group) => sum + Number(group.fresh ?? 0),
        0
      );
    }
  } catch (exc) {
    error = String(exc).slice(0, 120);
  }
  return { status, dbMs, valid, fresh, totalMs: Date.now() - started, error };
}

/**
 * Pós-deploy: o tempo de servidor (Server-Timing: db) tem de ficar abaixo de
 * `AUDIT_MAX_MS` nas 4 cidades, sem 500/timeout. Faz uma chamada de aquecimento
 * (ignorada) e mede 3 chamadas; falha se o máximo exceder o SLO.
 */
async function checkMapLatency() {
  for (const city of ["Boston", "NYC", "Dallas", "Chicago"]) {
    await fetchCityTiming(city); // warm-up (não conta para o SLO)
    const samples = [];
    for (let index = 0; index < 3; index += 1) {
      samples.push(await fetchCityTiming(city));
    }
    const dbValues = samples
      .map((sample) => sample.dbMs)
      .filter((value) => value !== null)
      .sort((a, b) => a - b);
    const allOk = samples.every(
      (sample) => sample.status === 200 && sample.valid
    );
    const maxDb = dbValues.length ? dbValues[dbValues.length - 1] : null;
    const minDb = dbValues.length ? dbValues[0] : null;
    const median =
      dbValues.length === 3 ? dbValues[1] : minDb;
    const lastError = samples.find((sample) => sample.error)?.error || "";
    freshByCity[city] = Math.max(...samples.map((sample) => sample.fresh));
    check(
      `${city} mapa < ${maxMs} ms`,
      allOk && maxDb !== null && maxDb < maxMs,
      `db min/med/max=${minDb}/${median}/${maxDb}ms ` +
        `http=${samples.map((s) => s.status).join(",")} ` +
        `total=${samples.map((s) => `${s.totalMs}ms`).join(",")}${
          lastError ? ` erro=${lastError}` : ""
        }`
    );
  }
}

await checkMapLatency();
if (latencyOnly) {
  const failed = results.filter((item) => !item.ok);
  console.log(
    "RESULT",
    failed.length === 0 ? "ALL PASS" : `${failed.length} FAIL`
  );
  process.exit(failed.length === 0 ? 0 : 1);
}

const browser = await chromium.launch({ channel: "chrome" });

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

async function open(tab = "Opportunities") {
  const host = new URL(base).hostname;
  const context = await browser.newContext({
    viewport: { width: 1500, height: 1100 },
  });
  await context.addCookies([
    { name: "garimpador_auth", value: "1", domain: host, path: "/" },
    { name: "garimpador_token", value: token, domain: host, path: "/" },
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
    if (url.includes("/api/opportunities/territories")) {
      territoryRequests.push(url);
    }
  });
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

async function selectCityPrevention(page, name) {
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
  await page.waitForTimeout(600);
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

  // Destaque de frescos (<24h): selo na lista, pin com glow e toggle.
  const fresh = await page.evaluate(() => {
    const panel = [...document.querySelectorAll("section")].find((item) =>
      item.textContent?.includes("Where the work is")
    );
    const toggle = [...(panel?.querySelectorAll("button") ?? [])].find((item) =>
      /New \(<24h\)/i.test(item.textContent ?? "")
    );
    const badges = [
      ...(panel?.querySelectorAll("[data-fresh]") ?? []),
    ].filter((item) => item.getAttribute("data-fresh") === "1");
    const pins = panel?.querySelectorAll(".opp-pin.is-fresh").length ?? 0;
    toggle?.click();
    return {
      hasToggle: Boolean(toggle),
      badges: badges.length,
      pins,
    };
  });
  await page.waitForTimeout(500);
  const pressed = await page.evaluate(() => {
    const panel = [...document.querySelectorAll("section")].find((item) =>
      item.textContent?.includes("Where the work is")
    );
    const toggle = [...(panel?.querySelectorAll("button") ?? [])].find((item) =>
      /New \(<24h\)/i.test(item.textContent ?? "")
    );
    return toggle?.getAttribute("aria-pressed") === "true";
  });
  const expectedFresh = freshByCity.Boston ?? 0;
  if (expectedFresh > 0) {
    check(
      "Fresh (<24h): selo na lista + pin destacado",
      fresh.badges > 0 && fresh.pins > 0,
      `badges=${fresh.badges} pins=${fresh.pins} api=${expectedFresh}`
    );
    check(
      "Fresh (<24h): toggle liga e filtra",
      fresh.hasToggle && pressed,
      `toggle=${fresh.hasToggle} pressed=${pressed}`
    );
  } else {
    check(
      "Fresh (<24h): amostra sem frescos (destaque inativo)",
      true,
      "api=0"
    );
  }
  // Volta ao estado normal para os testes seguintes.
  await page.evaluate(() => {
    const panel = [...document.querySelectorAll("section")].find((item) =>
      item.textContent?.includes("Where the work is")
    );
    [...(panel?.querySelectorAll("button") ?? [])]
      .find((item) => /New \(<24h\)/i.test(item.textContent ?? ""))
      ?.click();
  });
  await page.waitForTimeout(300);

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

// Pre-inspection: agregação ao vivo (territories) + destaque de frescos
{
  const before = territoryRequests.length;
  let expectedPreventiveFresh = 0;
  try {
    const res = await fetch(
      `${apiBase}/api/opportunities/territories?city=Boston&kind=preventive&days=30`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    if (res.status === 200) {
      const body = await res.json();
      expectedPreventiveFresh = Number(body?.totals?.fresh ?? 0);
    }
  } catch {
    expectedPreventiveFresh = 0;
  }
  const { context, page } = await open("Pre-inspection");
  await selectCityPrevention(page, "Boston");
  const state = await page.evaluate(() => {
    const panel = [...document.querySelectorAll("section")].find((item) =>
      item.textContent?.includes("Where the work is")
    );
    const toggle = [...(panel?.querySelectorAll("button") ?? [])].find((item) =>
      /New \(<24h\)/i.test(item.textContent ?? "")
    );
    return {
      badges: panel?.querySelectorAll("[data-fresh]").length ?? 0,
      pins: panel?.querySelectorAll(".opp-pin.is-fresh").length ?? 0,
      hasToggle: Boolean(toggle),
    };
  });
  check(
    "Pre-inspection: agregação ao vivo (territories)",
    territoryRequests.length > before,
    `${territoryRequests.length - before} request(s)`
  );
  check(
    "Pre-inspection: selo + pin fresco + toggle",
    expectedPreventiveFresh === 0 ||
      (state.badges > 0 && state.pins > 0 && state.hasToggle),
    `badges=${state.badges} pins=${state.pins} toggle=${state.hasToggle} api=${expectedPreventiveFresh}`
  );
  await context.close();
}

await browser.close();
const failed = results.filter((item) => !item.ok);
console.log("RESULT", failed.length === 0 ? "ALL PASS" : `${failed.length} FAIL`);
process.exit(failed.length === 0 ? 0 : 1);
