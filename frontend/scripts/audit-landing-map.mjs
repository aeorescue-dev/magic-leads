import { chromium } from "playwright";
import fs from "node:fs";

const base = process.env.AUDIT_BASE_URL || "http://localhost:3002";
const apiBase = process.env.AUDIT_API_URL || "http://127.0.0.1:8011";
const maxMs = Number(process.env.AUDIT_MAX_MS || 50);
const results = [];

function check(label, condition, detail) {
  results.push({ label, ok: condition, detail });
  console.log(condition ? "PASS" : "FAIL", label, detail ?? "");
}

async function probe() {
  const started = Date.now();
  let status = 0;
  let dbMs = null;
  let body = null;
  let error = "";
  try {
    const res = await fetch(`${apiBase}/api/public/live-map`);
    status = res.status;
    const timing = res.headers.get("server-timing") || "";
    const match = timing.match(/db;dur=([\d.]+)/);
    dbMs = match ? Number(match[1]) : null;
    if (status === 200) body = await res.json();
  } catch (exc) {
    error = String(exc).slice(0, 120);
  }
  return { status, dbMs, body, totalMs: Date.now() - started, error };
}

function collectKeys(value, keys = []) {
  if (Array.isArray(value)) {
    for (const item of value) collectKeys(item, keys);
  } else if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      keys.push(key);
      collectKeys(item, keys);
    }
  }
  return keys;
}

await probe(); // warm-up
const samples = [];
for (let index = 0; index < 3; index += 1) samples.push(await probe());
const ok = samples.every(
  (sample) => sample.status === 200 && sample.body?.cities?.length === 4
);
const dbValues = samples
  .map((sample) => sample.dbMs)
  .filter((value) => value !== null)
  .sort((a, b) => a - b);
const maxDb = dbValues.length ? dbValues[dbValues.length - 1] : null;
check(
  `Endpoint /api/public/live-map < ${maxMs} ms`,
  ok && maxDb !== null && maxDb < maxMs,
  `db min/med/max=${dbValues[0]}/${dbValues[1]}/${maxDb}ms http=${samples
    .map((sample) => sample.status)
    .join(",")}`
);

const payload = samples[0].body;
check(
  "Payload com 4 cidades e totais",
  Boolean(
    payload?.cities?.length === 4 &&
      payload.cities.every(
        (city) =>
          typeof city.totals?.count === "number" &&
          Array.isArray(city.zones)
      )
  ),
  payload?.cities?.map((city) => `${city.label}:${city.totals.count}`).join(" · ")
);

const boston = payload?.cities?.find((city) => city.label === "Boston");
let gridBoston = null;
try {
  const res = await fetch(`${apiBase}/api/public/trade-grid?city=Boston`);
  if (res.status === 200) gridBoston = await res.json();
} catch {
  gridBoston = null;
}
check(
  "Mapa e grelha usam a mesma população (Boston)",
  Boolean(gridBoston) && gridBoston.total === boston?.totals.count,
  `${gridBoston?.total} vs ${boston?.totals.count}`
);

const forbidden = new Set([
  "address",
  "owner",
  "owner_name",
  "owner_phone",
  "phone",
  "description",
  "external_id",
  "lead_id",
  "id",
  "zip",
]);
const keys = new Set(collectKeys(payload));
const leaked = [...keys].filter((key) => forbidden.has(key.toLowerCase()));
check("Sem campos privados no payload", leaked.length === 0, leaked.join(","));

const zones = (payload?.cities ?? []).flatMap((city) => city.zones ?? []);
check(
  "Piso de privacidade (zonas >= 5)",
  zones.every((zone) => zone.count >= 5),
  `${zones.length} zonas`
);
check(
  "Frescos expostos só a partir de 3",
  zones.every((zone) => zone.fresh === 0 || zone.fresh >= 3),
  `fresh>0: ${zones.filter((zone) => zone.fresh > 0).length}`
);
check(
  "Coordenadas arredondadas a 3 casas",
  zones.every(
    (zone) =>
      (zone.lat === null ||
        Math.abs(zone.lat * 1000 - Math.round(zone.lat * 1000)) < 1e-6) &&
      (zone.lng === null ||
        Math.abs(zone.lng * 1000 - Math.round(zone.lng * 1000)) < 1e-6)
  ),
  "ok"
);

try {
  const first = await fetch(`${apiBase}/api/public/live-map`);
  const etag = first.headers.get("etag");
  const conditional = etag
    ? await fetch(`${apiBase}/api/public/live-map`, {
        headers: { "If-None-Match": etag },
      })
    : null;
  check(
    "ETag devolve 304 (cache condicional)",
    Boolean(etag) && conditional?.status === 304,
    `etag=${etag ? "yes" : "no"} status=${conditional?.status ?? "n/a"}`
  );
} catch (exc) {
  check("ETag devolve 304 (cache condicional)", false, String(exc).slice(0, 80));
}

// ---------------------------------------------------------------- UI
const out = "../reports/landing-live-map-preview";
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ channel: "chrome" });
const context = await browser.newContext({ viewport: { width: 1500, height: 1200 } });
const page = await context.newPage();
let uiError = "";
try {
  await page.goto(`${base}/en`, { waitUntil: "networkidle", timeout: 60000 });
  await page.locator('[data-track="hero_tab_map"]').first().waitFor({ timeout: 30000 });
  check(
    "Mapa é o separador por defeito",
    (await page
      .locator('[data-track="hero_tab_map"]')
      .first()
      .getAttribute("aria-pressed")) === "true",
    "map pressed"
  );
  await page.locator("[data-map-zone]").first().waitFor({ timeout: 30000 });
  await page.locator(".pub-bubble").first().waitFor({ timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1800);
  const bubbles = await page.locator(".pub-bubble").count();
  const chips = await page.locator("[data-map-zone]").count();
  check(
    "Mapa renderiza bolhas e top zonas",
    bubbles > 0 && chips > 0,
    `bubbles=${bubbles} chips=${chips}`
  );
  await page.locator("#topo").screenshot({ path: `${out}/01-hero-map.png` });

  await page.locator('[data-track="hero_city_boston"]').click();
  await page.waitForTimeout(900);
  const uiTotal = Number(
    await page.locator("[data-map-total]").first().getAttribute("data-map-total")
  );
  check(
    "Seletor de cidade atualiza o mapa (Boston)",
    Number.isFinite(uiTotal) && uiTotal === boston?.totals.count,
    `${uiTotal} vs ${boston?.totals.count}`
  );

  await page.locator('[data-track="hero_tab_trades"]').click();
  await page.locator('[data-track^="p1_trade_"]').first().waitFor({ timeout: 20000 });
  check(
    "Separador By trade mantém a grelha",
    (await page.locator('[data-track^="p1_trade_"]').count()) > 0,
    "cards visíveis"
  );
  await page.locator("#topo").screenshot({ path: `${out}/02-hero-trades.png` });

  await page.locator('[data-track="hero_tab_map"]').click();
  const firstZone = page.locator("[data-map-zone]").first();
  const zoneLabel = (await firstZone.innerText()).trim();
  await firstZone.click();
  await page.getByText("This is happening near you", { exact: true }).waitFor({
    timeout: 10000,
  });
  check(
    "Clique na zona abre o teaser no modal",
    await page.getByText("This is happening near you", { exact: true }).isVisible(),
    zoneLabel
  );
  check(
    "Teaser inclui formulário de registo",
    (await page.locator('input[type="email"]').count()) > 0,
    "email input"
  );
  check(
    "Teaser abre em modo de registo",
    (await page.locator('[data-auth-register="true"]').count()) > 0,
    "register mode"
  );
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${out}/03-teaser-modal.png` });
} catch (exc) {
  uiError = String(exc).slice(0, 200);
  check("UI da landing", false, uiError);
}

await context.close();

// Kill switch: se o endpoint devolver 503, a aba Map desaparece e a grelha fica.
{
  const fallbackContext = await browser.newContext({
    viewport: { width: 1500, height: 1200 },
  });
  const fallbackPage = await fallbackContext.newPage();
  await fallbackPage.route("**/api/public/live-map*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "live_map_disabled" }),
    })
  );
  try {
    await fallbackPage.goto(`${base}/en`, {
      waitUntil: "networkidle",
      timeout: 60000,
    });
    await fallbackPage.waitForTimeout(1800);
    const mapTab = await fallbackPage
      .locator('[data-track="hero_tab_map"]')
      .count();
    const tradeCards = await fallbackPage
      .locator('[data-track^="p1_trade_"]')
      .count();
    check(
      "Kill switch: esconde o mapa e mantém By trade",
      mapTab === 0 && tradeCards > 0,
      `mapTab=${mapTab} trades=${tradeCards}`
    );
  } catch (exc) {
    check(
      "Kill switch: esconde o mapa e mantém By trade",
      false,
      String(exc).slice(0, 120)
    );
  }
  await fallbackContext.close();
}

await browser.close();

const failed = results.filter((item) => !item.ok);
console.log("RESULT", failed.length === 0 ? "ALL PASS" : `${failed.length} FAIL`);
process.exit(failed.length === 0 ? 0 : 1);
