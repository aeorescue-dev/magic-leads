#!/usr/bin/env node
/**
 * Watcher de deploy da Vercel.
 *
 * Enquanto o build corrigido NÃO estiver no ar (limite de deploys da Vercel),
 * faz uma checagem leve e barata (HTML + chunks JS, procurando o marcador novo).
 * No instante em que o build novo aparece, roda a verificação completa
 * (scripts/verify-live-checkout.mjs), grava o resultado em scripts/.shots/
 * e (opcional) dispara um aviso ntfy.sh.
 *
 * Modos:
 *   node scripts/watch-deploy.mjs --once   -> roda UMA checagem e sai (para Task Scheduler)
 *   node scripts/watch-deploy.mjs          -> loop contínuo (intervalo via --every 120 segundos)
 *
 * Env: FRONT_URL, API_URL, PW_DIR, NTFY_TOPIC (opcional, ex: seu-token-pessoal)
 */
import { spawn } from "node:child_process";
import { writeFileSync, appendFileSync, mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SHOTS = path.join(ROOT, "scripts", ".shots");
const LOG = path.join(ROOT, "scripts", "watch-deploy.log");
const MARKER_FILE = path.join(SHOTS, "VERIFIED-DEPLOY.txt");
const FP_FILE = path.join(SHOTS, "live-fingerprint.json");

const FRONT_URL = (process.env.FRONT_URL || "https://magicleads-oficial.vercel.app").replace(/\/$/, "");
const NEW_MARKER = "Assinar $79/semana";
const OLD_MARKER = "Abrindo pagamento";
const TIMEOUT = 60000;

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`;
  console.log(line);
  try { mkdirSync(path.dirname(LOG), { recursive: true }); appendFileSync(LOG, line + "\n"); } catch {}
}

function args() {
  const once = process.argv.includes("--once");
  const everyIx = process.argv.indexOf("--every");
  const every = everyIx >= 0 ? Math.max(10, Number(process.argv[everyIx + 1]) || 120) : 120;
  return { once, every };
}

async function fetchScriptList() {
  try {
    const res = await fetch(FRONT_URL + "/dashboard", { signal: AbortSignal.timeout(TIMEOUT) });
    if (!res.ok) return null;
    return [...(await res.text()).matchAll(/src="(\/_next\/static\/[^"]+\.js)"/g)].map((m) => m[1]);
  } catch {
    return null;
  }
}

async function bundleHasNewBuild() {
  try {
    const scripts = await fetchScriptList();
    if (!scripts) return false;
    let bundle = "";
    for (const s of scripts.slice(0, 30)) {
      const js = await (await fetch(FRONT_URL + s, { signal: AbortSignal.timeout(TIMEOUT) })).text();
      bundle += js;
      if (js.includes(NEW_MARKER)) break;
    }
    // Build novo: CTA novo presente E resquício do CTA antigo ausente.
    return bundle.includes(NEW_MARKER) && !bundle.includes(OLD_MARKER);
  } catch {
    return false;
  }
}

function readStoredFingerprint() {
  try {
    return JSON.parse(readFileSync(FP_FILE, "utf8")).fp;
  } catch {
    return null;
  }
}

const TASK_NAME = "MagicLeads-VerifyDeploy";
const AUTO_TASK_NAME = "MagicLeads-AutoDeployFront";

function removeScheduledTask(name) {
  return new Promise((resolve) => {
    const child = spawn("schtasks", ["/Delete", "/TN", name, "/F"], { shell: true });
    child.on("close", () => resolve());
  });
}

function runVerifier() {
  return new Promise((resolve) => {
    const script = path.join(ROOT, "scripts", "verify-live-checkout.mjs");
    log("Build novo detectado. Rodando verificação completa...");
    const child = spawn(process.execPath, [script], { cwd: ROOT, env: process.env, stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    child.on("close", (code) => resolve({ code, out }));
  });
}

async function notify(title, body) {
  const topic = process.env.NTFY_TOPIC;
  if (!topic) { log("NTFY_TOPIC não definido — sem aviso push (o log é o registro)."); return; }
  try {
    await fetch(`https://ntfy.sh/${topic}`, {
      method: "POST",
      body: `${title}\n${body}`,
      headers: { "Title": title, "Priority": "high" },
      signal: AbortSignal.timeout(TIMEOUT),
    });
    log("ntfy enviado.");
  } catch (e) {
    log("ntfy falhou: " + e.message);
  }
}

async function checkOnce() {
  const scripts = await fetchScriptList();
  if (!scripts) {
    log("Front sem resposta de /dashboard — re-checando no próximo ciclo.");
    return false;
  }
  const fp = scripts.join("|");
  if (readStoredFingerprint() === fp) {
    log("Bundle inalterado desde a última checagem — sem re-verificação.");
    return false;
  }
  writeFileSync(FP_FILE, JSON.stringify({ fp, at: new Date().toISOString() }), "utf8");
  log("Bundle mudou (" + scripts.length + " chunks) — nova fingerprint gravada. Conferindo marcadores...");
  if (!(await bundleHasNewBuild())) {
    log("Bundle mudou mas NÃO é o build novo (marcadores não batem — provável deploy do dono).");
    return false;
  }
  const { code, out } = await runVerifier();
  const result = {
    at: new Date().toISOString(),
    exitCode: code,
    output: out,
  };
  log("Verificação final: exit=" + code);
  if (code === 0) {
    mkdirSync(SHOTS, { recursive: true });
    writeFileSync(MARKER_FILE, JSON.stringify(result, null, 2));
    log("TUDO VERDE -> marker salvo em " + MARKER_FILE);
    await removeScheduledTask(TASK_NAME);
    await removeScheduledTask(AUTO_TASK_NAME);
    await notify("MagicLeads: deploy VERDE ✅", "O build corrigido está no ar e o clique vai para o Stripe. Pode fazer o teste final na aba anônima.");
    return true;
  }
  log("Verificação rodou mas falhou (exit " + code + "). Próximo ciclo só re-verifica se o bundle mudar de novo.");
  return false;
}

async function main() {
  const { once, every } = args();
  log("Watcher iniciado (mode=" + (once ? "once" : "loop") + ", every=" + every + "s)");
  let guard = 0;
  do {
    if (await checkOnce()) {
      log("Concluído. Encerrando.");
      return;
    }
    guard++;
    if (once) return;
    if (guard >= 720) { log("Tempo limite de espera atingido (24h). Encerrando."); return; }
    await new Promise((r) => setTimeout(r, every * 1000));
  } while (true);
}

main();