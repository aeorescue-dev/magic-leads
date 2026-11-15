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
const newYork = payload?.cities?.find((city) => city.label === "New York");
const areasTotal = (payload?.cities ?? []).reduce(
  (sum, city) => sum + city.totals.zones,
  0
);
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
check(
  "Rótulos legíveis nas 4 cidades (sem ZIP numérico)",
  (payload?.cities ?? []).every((city) => city.zones.length > 0) &&
    zones.every(
      (zone) =>
        Boolean(zone.label) &&
        !/^\s*area\s*\d{3,5}\s*$/i.test(zone.label) &&
        !/^\d{5}$/.test(zone.label)
    ),
  payload?.cities
    ?.map((city) => `${city.label}:${city.zones[0]?.label ?? "—"}`)
    .join(" · ")
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
const out =
  process.env.AUDIT_OUT || "../reports/landing-live-map-preview";
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
    "Mapa renderiza as 3 zonas principais",
    bubbles > 0 && bubbles <= 3 && chips === 3,
    `bubbles=${bubbles} chips=${chips}`
  );
  check(
    "Legenda âmbar visível",
    await page.getByText("New in the last 24h", { exact: true }).isVisible(),
    "legend"
  );
  const cardCities = await page.locator('[data-track^="card_city_"]').count();
  const hintVisible = await page
    .getByText("Select your city or click a neighborhood to explore.", {
      exact: true,
    })
    .isVisible();
  check(
    "Instrução e seletor de cidade no cartão",
    cardCities === 4 && hintVisible,
    `cities=${cardCities} hint=${hintVisible}`
  );
  await page
    .waitForFunction(
      () => /\d[\d.,]*\s+opportunities tracked/i.test(document.body.innerText),
      { timeout: 15000 }
    )
    .catch(() => {});
  await page.mouse.move(10, 10);
  await page.locator("#topo").screenshot({ path: `${out}/01-hero-map.png` });

  const moreAreas = page.locator("[data-map-more]");
  const hasMore = (await moreAreas.count()) > 0;
  check(
    "Chips mostram +áreas escondidas",
    hasMore && (await moreAreas.first().innerText()).includes("+2"),
    hasMore ? (await moreAreas.first().innerText()).trim() : "missing"
  );
  if (hasMore) {
    await moreAreas.first().click();
    await page.waitForTimeout(300);
  }
  const expandedChips = await page.locator("[data-map-zone]").count();
  check(
    "+áreas expande os chips",
    expandedChips > chips,
    `${chips} -> ${expandedChips}`
  );
  await page.mouse.move(10, 10);
  await page.locator("#topo").screenshot({ path: `${out}/01b-hero-areas.png` });

  // A navbar tem de ficar sempre acima das camadas do Leaflet ao rolar.
  await page.evaluate(() => window.scrollTo(0, 340));
  await page.waitForTimeout(600);
  const scrollHit = await page.evaluate(() => {
    const probe = (x, y) => {
      const el = document.elementFromPoint(x, y);
      return {
        inHeader: Boolean(el?.closest("header")),
        tag: el?.tagName ?? "",
        cls: String(el?.className ?? "").slice(0, 50),
      };
    };
    const flag = document.querySelector('[data-track="language_en"]');
    const cta = document.querySelector('[data-track="header_cta"]');
    const flagRect = flag?.getBoundingClientRect();
    const ctaRect = cta?.getBoundingClientRect();
    return {
      scrollY: window.scrollY,
      map: Boolean(document.querySelector(".pub-map")),
      header: probe(Math.min(window.innerWidth - 120, 1100), 30),
      flag: flagRect
        ? probe(flagRect.x + flagRect.width / 2, flagRect.y + flagRect.height / 2)
        : null,
      cta: ctaRect
        ? probe(ctaRect.x + ctaRect.width / 2, ctaRect.y + ctaRect.height / 2)
        : null,
    };
  });
  check(
    "Navbar acima do mapa durante o scroll",
    scrollHit.header.inHeader &&
      scrollHit.flag?.inHeader === true &&
      (!scrollHit.cta || scrollHit.cta.inHeader),
    `scrollY=${scrollHit.scrollY} header=${scrollHit.header.inHeader} flag=${
      scrollHit.flag?.inHeader
    } cta=${scrollHit.cta?.inHeader}`
  );
  await page.screenshot({ path: `${out}/06-scroll-navbar.png` });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(400);

  await page.locator('[data-track="card_city_boston"]').click();
  await page.waitForTimeout(900);
  const cardTotal = Number(
    await page.locator("[data-map-total]").first().getAttribute("data-map-total")
  );
  check(
    "Seletor do cartão sincroniza o mapa (Boston)",
    Number.isFinite(cardTotal) && cardTotal === boston?.totals.count,
    `${cardTotal} vs ${boston?.totals.count}`
  );

  await page.locator('[data-track="card_city_new_york"]').click();
  await page.waitForTimeout(900);
  const cardNyTotal = Number(
    await page.locator("[data-map-total]").first().getAttribute("data-map-total")
  );
  check(
    "Seletor do cartão volta a New York",
    Number.isFinite(cardNyTotal) && cardNyTotal === newYork?.totals.count,
    `${cardNyTotal} vs ${newYork?.totals.count}`
  );

  await page.locator('[data-track="card_city_boston"]').click();
  await page.waitForTimeout(900);
  const uiTotal = Number(
    await page.locator("[data-map-total]").first().getAttribute("data-map-total")
  );
  check(
    "Seletor de cidade atualiza o mapa (Boston)",
    Number.isFinite(uiTotal) && uiTotal === boston?.totals.count,
    `${uiTotal} vs ${boston?.totals.count}`
  );

  await page.locator('[data-track="card_city_chicago"]').click();
  await page.waitForTimeout(1200);
  const chicagoChip = (
    await page.locator("[data-map-zone]").first().innerText()
  ).trim();
  check(
    "Chicago mostra setor legível (sem ZIP)",
    !/area\s*\d{4,5}/i.test(chicagoChip) && !/^\d{5}$/.test(chicagoChip),
    chicagoChip.slice(0, 40)
  );
  await page.mouse.move(10, 10);
  await page.locator("#topo").screenshot({ path: `${out}/10-chicago.png` });
  await page.locator('[data-track="card_city_boston"]').click();
  await page.waitForTimeout(900);

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

// Busca por cidade, bairro e ZIP no campo do herói.
{
  const searchContext = await browser.newContext({
    viewport: { width: 1500, height: 1200 },
  });
  const searchPage = await searchContext.newPage();
  try {
    await searchPage.goto(`${base}/en`, {
      waitUntil: "networkidle",
      timeout: 60000,
    });
    const searchInput = searchPage.locator(
      'input[placeholder="Search by city, neighborhood or ZIP"]'
    );
    await searchInput.waitFor({ timeout: 30000 });
    check(
      "Placeholder da busca por cidade/bairro/ZIP",
      await searchInput.isVisible(),
      "placeholder"
    );
    await searchPage.locator("[data-map-zone]").first().waitFor({
      timeout: 30000,
    });

    await searchInput.fill("Boston");
    await searchInput.press("Enter");
    await searchPage.waitForTimeout(1200);
    const cityTotal = Number(
      await searchPage
        .locator("[data-map-total]")
        .first()
        .getAttribute("data-map-total")
    );
    check(
      "Busca por cidade (Boston)",
      Number.isFinite(cityTotal) && cityTotal === boston?.totals.count,
      `${cityTotal} vs ${boston?.totals.count}`
    );
    await searchPage.mouse.move(10, 10);
    await searchPage
      .locator("#topo")
      .screenshot({ path: `${out}/08-search-boston.png` });

    await searchInput.fill("Dorchester");
    await searchInput.press("Enter");
    await searchPage
      .getByText("This is happening near you", { exact: true })
      .waitFor({ timeout: 10000 });
    const searchModal = searchPage
      .locator("div.fixed.inset-0")
      .filter({ hasText: "This is happening" })
      .first();
    check(
      "Busca por bairro abre o teaser",
      (await searchModal.innerText()).includes("Dorchester"),
      "Dorchester"
    );
    await searchModal.click({ position: { x: 5, y: 5 } });
    await searchPage.waitForTimeout(300);

    await searchInput.fill("02124");
    await searchInput.press("Enter");
    await searchPage.waitForTimeout(1200);
    check(
      "Busca por ZIP mantém o fluxo",
      (await searchPage.getByText("ZIP 02124", { exact: false }).count()) > 0,
      "ZIP 02124"
    );
    const strip = searchPage
      .locator("section")
      .filter({ hasText: "Neighborhoods and sectors with active work" })
      .first();
    await strip.screenshot({ path: `${out}/09-areas-strip.png` });
  } catch (exc) {
    check("Busca cidade/bairro/ZIP", false, String(exc).slice(0, 160));
  }
  await searchContext.close();
}

// Mobile: o seletor visível é o do herói; o do cartão não duplica.
{
  const mobileContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  const mobilePage = await mobileContext.newPage();
  try {
    await mobilePage.goto(`${base}/en`, {
      waitUntil: "networkidle",
      timeout: 60000,
    });
    await mobilePage.locator('[data-track="hero_city_boston"]').waitFor({
      timeout: 30000,
    });
    const heroVisible = await mobilePage
      .locator('[data-track="hero_city_boston"]')
      .isVisible();
    const cardVisible = await mobilePage
      .locator('[data-track="card_city_boston"]')
      .isVisible();
    check(
      "Mobile: seletor do herói, sem duplicar no cartão",
      heroVisible && !cardVisible,
      `hero=${heroVisible} card=${cardVisible}`
    );
    await mobilePage.locator('[data-track="hero_city_boston"]').click();
    await mobilePage.locator("[data-map-total]").first().waitFor({
      timeout: 30000,
    });
    const bostonBubbleTexts = (boston?.zones ?? [])
      .slice(0, 3)
      .map((zone) => new Intl.NumberFormat("en-US").format(zone.count));
    await mobilePage
      .waitForFunction(
        (counts) => {
          const texts = [
            ...document.querySelectorAll(".pub-bubble"),
          ].map((el) => (el.textContent || "").trim());
          return counts.some((count) => texts.includes(count));
        },
        bostonBubbleTexts,
        { timeout: 30000 }
      )
      .catch(() => {});
    await mobilePage.waitForTimeout(800);
    const mobileBubbles = await mobilePage.locator(".pub-bubble").count();
    check(
      "Mobile: mapa mostra as bolhas da cidade",
      mobileBubbles > 0,
      `bubbles=${mobileBubbles}`
    );
    const mobileTotal = Number(
      await mobilePage
        .locator("[data-map-total]")
        .first()
        .getAttribute("data-map-total")
    );
    check(
      "Mobile: chips do herói atualizam o mapa",
      Number.isFinite(mobileTotal) && mobileTotal === boston?.totals.count,
      `${mobileTotal} vs ${boston?.totals.count}`
    );
    await mobilePage.locator(".pub-map").scrollIntoViewIfNeeded();
    await mobilePage.waitForTimeout(500);
    await mobilePage.screenshot({ path: `${out}/07-mobile-map.png` });
  } catch (exc) {
    check("Mobile: seletores e mapa", false, String(exc).slice(0, 140));
  }
  await mobileContext.close();
}

// A rota manda no idioma: /en com cookie PT abre EN; trocar a bandeira navega.
{
  const localeContext = await browser.newContext({
    viewport: { width: 1400, height: 1000 },
  });
  await localeContext.addCookies([
    {
      name: "NEXT_LOCALE",
      value: "pt",
      domain: new URL(base).hostname,
      path: "/",
    },
  ]);
  await localeContext.addInitScript(() => {
    localStorage.setItem("NEXT_LOCALE", "pt");
  });
  const localePage = await localeContext.newPage();
  try {
    await localePage.goto(`${base}/en`, {
      waitUntil: "networkidle",
      timeout: 60000,
    });
    await localePage.locator("[data-map-total]").first().waitFor({
      timeout: 30000,
    });
    await localePage.waitForTimeout(500);
    const enTotal = Number(
      await localePage
        .locator("[data-map-total]")
        .first()
        .getAttribute("data-map-total")
    );
    const enFormatted = new Intl.NumberFormat("en-US").format(enTotal);
    const enState = await localePage.evaluate(() => ({
      lang: document.documentElement.lang,
      en: document
        .querySelector('[data-track="language_en"]')
        ?.getAttribute("aria-pressed"),
      pt: document
        .querySelector('[data-track="language_pt"]')
        ?.getAttribute("aria-pressed"),
      body: document.body.innerText,
    }));
    check(
      "/en manda no idioma (cookie PT ignorado)",
      enState.lang === "en-US" &&
        enState.en === "true" &&
        enState.pt === "false" &&
        enTotal > 0 &&
        enState.body.includes(enFormatted) &&
        enState.body.includes(
          `${new Intl.NumberFormat("en-US").format(areasTotal)} areas`
        ) &&
        enState.body.includes("Neighborhoods and sectors with active work") &&
        !enState.body.includes("ZIPs covered") &&
        enState.body.includes("The owner just asked") &&
        enState.body.includes("From a small repair to a full build") &&
        enState.body.toLowerCase().includes("all cities") &&
        enState.body.includes("opportunities tracked") &&
        !enState.body.includes("new entries in 24h") &&
        !enState.body.includes("signals in the base") &&
        enState.body.includes(
          "Select your city or click a neighborhood to explore."
        ),
      `lang=${enState.lang} en=${enState.en} pt=${enState.pt} n=${enFormatted}`
    );

    await localePage.locator('[data-track="language_pt"]').click();
    await localePage.waitForURL("**/pt**", { timeout: 30000 });
    await localePage.locator("[data-map-total]").first().waitFor({
      timeout: 30000,
    });
    await localePage.waitForTimeout(700);
    const ptTotal = Number(
      await localePage
        .locator("[data-map-total]")
        .first()
        .getAttribute("data-map-total")
    );
    const ptFormatted = new Intl.NumberFormat("pt-BR").format(ptTotal);
    const ptPlaceholder = await localePage
      .locator('input[placeholder="Digite sua cidade, bairro ou ZIP"]')
      .isVisible();
    const ptState = await localePage.evaluate(() => ({
      lang: document.documentElement.lang,
      href: location.pathname,
      body: document.body.innerText,
    }));
    check(
      "Bandeira PT navega para /pt e renderiza PT-BR",
      ptState.href.startsWith("/pt") &&
        ptState.lang === "pt-BR" &&
        ptTotal > 0 &&
        ptPlaceholder &&
        ptState.body.includes(ptFormatted) &&
        ptState.body.includes(
          `${new Intl.NumberFormat("pt-BR").format(areasTotal)} áreas`
        ) &&
        ptState.body.includes("Bairros e setores com trabalho ativo") &&
        !ptState.body.includes("ZIPs cobertos") &&
        ptState.body.includes("Do serviço pequeno à obra completa") &&
        ptState.body.toLowerCase().includes("todas as cidades") &&
        ptState.body.includes("oportunidades registradas") &&
        !ptState.body.includes("novas entradas") &&
        !ptState.body.includes("sinais na base") &&
        ptState.body.includes(
          "Escolha sua cidade ou clique em um bairro para explorar."
        ),
      `href=${ptState.href} lang=${ptState.lang} n=${ptFormatted}`
    );

    await localePage.locator("[data-map-zone]").first().waitFor({
      timeout: 30000,
    });
    await localePage.locator("[data-map-zone]").first().click();
    await localePage
      .getByText("Isso está acontecendo perto de você", { exact: true })
      .waitFor({ timeout: 10000 });
    const modalText = await localePage.evaluate(() => {
      const modal = [...document.querySelectorAll("div.fixed.inset-0")].find(
        (node) => node.textContent?.includes("Isso está acontecendo")
      );
      return modal?.innerText || "";
    });
    check(
      "Copy PT-BR consistente no teaser",
      modalText.includes("Isso está acontecendo perto de você") &&
        !modalText.includes("perto de si") &&
        !modalText.includes("moradas") &&
        !modalText.includes("contactos"),
      `len=${modalText.length}`
    );
    await localePage.screenshot({ path: `${out}/05-locale-pt-teaser.png` });

    await localePage.goto(`${base}/en`, {
      waitUntil: "networkidle",
      timeout: 60000,
    });
    await localePage.waitForTimeout(700);
    const backEn = await localePage.evaluate(() => ({
      lang: document.documentElement.lang,
      en: document
        .querySelector('[data-track="language_en"]')
        ?.getAttribute("aria-pressed"),
    }));
    check(
      "/en volta a EN depois da troca",
      backEn.lang === "en-US" && backEn.en === "true",
      `lang=${backEn.lang} en=${backEn.en}`
    );
    await localePage.screenshot({ path: `${out}/04-locale-en.png` });
  } catch (exc) {
    check("Idioma por rota (en/pt)", false, String(exc).slice(0, 160));
  }
  await localeContext.close();
}

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
    await fallbackPage.waitForTimeout(1200);
    await fallbackPage
      .locator('[data-track^="p1_trade_"]')
      .first()
      .waitFor({ timeout: 25000 })
      .catch(() => {});
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
