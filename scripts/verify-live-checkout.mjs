#!/usr/bin/env node
/**
 * Verificação de ponta a ponta do deploy do frontend + clique real no Stripe.
 *
 * Executa 3 níveis de validação:
 *   1. BUNDLE  – confirma que o build AO VIVO tem o novo fluxo (sem cache antigo);
 *   2. CLIQUE  – navegador headless (Edge/Chrome) logado: clica em "Assinar $79/semana"
 *                na tela de bloqueio e espera o redirect para checkout.stripe.com;
 *   3. API     – replica o contrato do botão via API.
 *
 * Uso:
 *   node scripts/verify-live-checkout.mjs
 *   node scripts/verify-live-checkout.mjs --api-only   (pula o navegador)
 *
 * Variáveis (opcionais):
 *   FRONT_URL=https://magicleads-oficial.vercel.app
 *   API_URL=https://magic-leads-production.up.railway.app
 *   PW_DIR=<pasta do pacote playwright-core>           (default: temp local)
 *
 * Saída: exit 0 = tudo verde; exit 2 = ainda não está no ar/verificação falhou; exit 1 = erro fatal.
 */
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const FRONT_URL = (process.env.FRONT_URL || "https://magicleads-oficial.vercel.app").replace(/\/$/, "");
const API_URL = (process.env.API_URL || "https://magic-leads-production.up.railway.app").replace(/\/$/, "");
const PW_DIR = (
  process.env.PW_DIR ||
  "C:/Users/Fabio/AppData/Local/Temp/opencode/pw/node_modules/playwright-core"
).replace(/\/$/, "");

const FIXED_MARKERS = ["Abrindo pagamento", "Falha ao iniciar o pagamento. Tente novamente."];
const REMOVED_MARKERS = ["Ambiente de demonstração sem cobrança real"];

const TIMEOUT = 60000;

function banner(msg) { console.log("\n======== " + msg + " ========"); }
function ok(msg) { console.log("  [PASS] " + msg); }
function fail(msg) { console.log("  [FAIL] " + msg); }

function loadPlaywright() {
  const attempt = (from) => {
    const req = createRequire(path.join(from, "fake.js"));
    const pw = req("playwright-core");
    if (pw?.chromium) return pw;
    return null;
  };
  return (
    attempt(path.dirname(PW_DIR)) ||
    attempt(fileURLToPath(new URL(".", import.meta.url)))
  );
}

async function httpStatus(url, timeout = TIMEOUT) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(timeout), redirect: "follow" });
    return res.status;
  } catch {
    return null;
  }
}

async function apiContract() {
  banner("NÍVEL 3 — Contrato da API de checkout");
  try {
    const email = `verify-live-${Date.now()}-${process.pid}@gmail.com`;
    const reg = await fetch(`${API_URL}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password: "Teste12345!", company_name: "Verify Live" }),
      signal: AbortSignal.timeout(TIMEOUT),
    });
    if (!reg.ok) throw new Error(`register HTTP ${reg.status}`);
    const { token, user } = await reg.json();
    if (!token || !user) throw new Error("register sem token/user");

    const co = await fetch(`${API_URL}/api/billing/checkout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(TIMEOUT),
    });
    const body = await co.json();
    if (co.status !== 200) throw new Error(`checkout HTTP ${co.status}: ${JSON.stringify(body)}`);
    if (body.mock) throw new Error("checkout retornou mock=True (Stripe não configurado)");
    if (!(body.checkout_url && body.checkout_url.startsWith("https://checkout.stripe.com/") && body.checkout_url.includes("cs_"))) {
      throw new Error(`checkout_url inválida: ${body.checkout_url}`);
    }
    const page = await httpStatus(body.checkout_url);
    if (page !== 200) throw new Error(`página do Stripe respondeu HTTP ${page}`);

    ok(`checkout real -> ${body.checkout_url.slice(0, 70)}... (página HTTP 200)`);
    ok(`$ ${body.plan?.amount_usd}/semana | mock=False | usuário ${user.email}`);
    return { token, user, checkout_url: body.checkout_url };
  } catch (e) {
    fail("contrato da API: " + e.message);
    return null;
  }
}

async function checkBundle() {
  banner("NÍVEL 1 — Build ao vivo");
  try {
    const html = await fetch(FRONT_URL + "/dashboard", { signal: AbortSignal.timeout(TIMEOUT) });
    if (!html.ok) throw new Error(`HTTP ${html.status}`);
    const scripts = [...(await html.text()).matchAll(/src="(\/_next\/static\/[^"]+\.js)"/g)].map((m) => m[1]);
    console.log(`  /dashboard -> 200, ${scripts.length} chunks`);

    let bundle = "";
    for (const s of scripts.slice(0, 30)) {
      const js = await (await fetch(FRONT_URL + s, { signal: AbortSignal.timeout(TIMEOUT) })).text();
      bundle += js;
      if (js.includes(FIXED_MARKERS[0])) break;
    }
    const missing = FIXED_MARKERS.filter((m) => !bundle.includes(m));
    const stale = REMOVED_MARKERS.filter((m) => bundle.includes(m));
    if (missing.length) { fail(`marcadores novos ausentes: ${missing.join(", ")}`); return false; }
    if (stale.length) { fail(`resquício antigo presente: ${stale.join(", ")}`); return false; }
    ok("build corrigido está AO VIVO (sem cache antigo)");
    return true;
  } catch (e) {
    fail("leitura do frontend: " + e.message);
    return false;
  }
}

async function browserClickTest() {
  banner("NÍVEL 2 — Clique real na tela de bloqueio");
  const pw = loadPlaywright();
  if (!pw) {
    console.log("  (playwright-core indisponível — use o modo --api-only)");
    return null;
  }

  const session = await apiContract();
  if (!session) {
    console.log("  (pulado — sem sessão válida para injetar)");
    return null;
  }
  const { token, user } = session;

  let browser;
  try {
    browser = await openBrowser(pw);
  } catch (e) {
    console.log("  erro ao abrir navegador: " + e.message + " — clique não testado");
    return null;
  }

  try {
    const context = await browser.newContext({ locale: "pt-BR" });
    await context.addCookies([{
      name: "garimpador_auth",
      value: token,
      path: "/",
      domain: new URL(FRONT_URL).hostname,
      secure: new URL(FRONT_URL).protocol === "https:",
      sameSite: "Lax",
    }]);
    await context.addInitScript(([t, u]) => {
      window.localStorage.setItem("garimpador.token", t);
      window.localStorage.setItem("garimpador.user", JSON.stringify(u));
    }, [token, user]);

    const page = await context.newPage();
    const consoleErrors = [];
    page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

    await page.goto(`${FRONT_URL}/dashboard`, { waitUntil: "domcontentloaded", timeout: TIMEOUT });

    banner("NÍVEL 2a — tela de bloqueio");
    const btn = page.getByRole("button", { name: "Assinar $79/semana" });
    try {
      await btn.waitFor({ state: "visible", timeout: 45000 });
    } catch {
      fail("CTA 'Assinar $79/semana' não apareceu. URL atual: " + page.url());
      await maybeShot(page, "scripts/.shots/1-blocked");
      return null;
    }
    ok("tela de bloqueio renderizada com o CTA");

    banner("NÍVEL 2b — clique -> redirect para Stripe");
    let finalUrl = "";
    try {
      await Promise.all([
        page.waitForURL((u) => u.href.startsWith("https://checkout.stripe.com/"), { timeout: TIMEOUT }),
        btn.click(),
      ]);
      finalUrl = page.url();
    } catch {
      fail("o clique NÃO levou ao Stripe. URL atual: " + page.url());
      await maybeShot(page, "scripts/.shots/2-fail-after-click");
      if (consoleErrors.length) console.log("  erros de console:", consoleErrors.slice(0, 5));
      return false;
    }

    if (!finalUrl.includes("/c/pay/") || !finalUrl.includes("cs_")) {
      fail("redirecionou para fora do Stripe Checkout: " + finalUrl);
      return false;
    }
    ok("DIRECIONADO PARA O STRIPE: " + finalUrl.slice(0, 90) + "...");
    return true;
  } finally {
    if (browser) await browser.close();
  }
}

async function maybeShot(page, base) {
  try {
    const { mkdirSync } = await import("node:fs");
    mkdirSync(path.dirname(base), { recursive: true });
    await page.screenshot({ path: base + ".png" });
    console.log("  screenshot salva em " + base + ".png");
  } catch { /* sem screenshot não bloqueia */ }
}

async function openBrowser(pw) {
  for (const ch of ["msedge", "chrome"]) {
    try { return await pw.chromium.launch({ channel: ch, headless: true }); } catch { /* próximo */ }
  }
  throw new Error("nenhum Edge/Chrome disponível");
}

async function main() {
  const apiOnly = process.argv.includes("--api-only");
  banner("FRONT " + FRONT_URL + " | API " + API_URL + (apiOnly ? " | modo API-only" : ""));

  const bundleLive = apiOnly ? true : await checkBundle();
  const browserOk = apiOnly ? null : await browserClickTest();
  const contractOk = browserOk ? true : !!(await apiContract());

  console.log("\n===== RESUMO =====");
  console.log("  build novo ao vivo:  " + (bundleLive ? "PASS" : "NÃO (build antigo / limite)"));
  console.log("  clique -> Stripe:     " + (browserOk === null ? "NÃO TESTADO (sem browser)" : browserOk ? "PASS" : "FALHOU"));
  console.log("  contrato da API:      " + (contractOk ? "PASS" : "FALHOU"));

  if (bundleLive && browserOk === true && contractOk) {
    console.log("\n  => TUDO VERDE — deploy corrigido no ar e clique vai para o Stripe.");
    process.exitCode = 0;
  } else {
    console.log("\n  => AINDA NÃO AO VIVO (aguarde o reset da janela da Vercel) ou erro técnico acima.");
    process.exitCode = 2;
  }
}

process.on("unhandledRejection", (e) => { console.error("erro fatal: " + e.message); process.exitCode = 1; });
main();