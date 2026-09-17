#!/usr/bin/env node
/**
 * Auto-deploy do frontend na Vercel (quota guard p/ plano free).
 *
 * O projeto magic-leads-frontend-final tem Root Directory = "frontend" (Project
 * Setting). Portanto `vercel deploy --prod` roda da RAIZ do repo (o Vercel usa o
 * Root Directory para isolar frontend/ no build). Deploys via Git seguem o
 * mesmo Root Directory — a chave `rootDirectory` NÃO é aceita no schema do
 * vercel.json. O .vercelignore evita enviar backend/data/scripts.
 *
 * Enquanto a cota diária (api-deployments-free-per-day) está fechada, o Vercel
 * responde "Resource is limited - try again in 24 hours" e o script apenas
 * registra no log e sai com exit 0 (barato, sem build).
 * Quando a janela abre, o deploy é criado; ao confirmar sucesso o script:
 *   - remove a própria Scheduled Task (default MagicLeads-AutoDeployFront);
 *   - dispara ntfy (opcional) e loga a URL de produção.
 *
 * Env:
 *   REPO        (default: diretório-pai deste script)
 *   FRONT_URL   (default: https://magicleads-oficial.vercel.app)
 *   NTFY_TOPIC  (opcional)
 *   AUTO_TASK   (opcional; default: "MagicLeads-AutoDeployFront")
 *   VERCEL_CLI  (opcional; default: junto ao node atual)
 */
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, appendFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO = process.env.REPO || ROOT;
const FRONT_DIR = path.join(REPO, "frontend");
const LOG = path.join(REPO, "scripts", "auto-deploy.log");
const TIMEOUT_MS = 30 * 60 * 1000;

const PORTABLE_NODE = process.execPath;
const VERCEL_CLI =
  process.env.VERCEL_CLI ||
  path.join(path.dirname(PORTABLE_NODE), "node_modules", "vercel", "dist", "index.js");

const AUTO_TASK = process.env.AUTO_TASK || "MagicLeads-AutoDeployFront";

const RATE_LIMIT_PATTERNS = [
  "api-deployments-free-per-day",
  "Resource is limited",
  "rate limited",
  "try again in 24 hours",
];

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`;
  console.log(line);
  try { mkdirSync(path.dirname(LOG), { recursive: true }); appendFileSync(LOG, line + "\n"); } catch {}
}

function run(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, {
      ...opts,
      env: { ...process.env, ...(opts.env || {}) },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    child.on("close", (code) => resolve({ code, out }));
    child.on("error", (e) => resolve({ code: -1, out: e.message }));
  });
}

function removeScheduledTask() {
  return run("schtasks", ["/Delete", "/TN", AUTO_TASK, "/F"], { shell: true });
}

async function notify(title, body) {
  const topic = process.env.NTFY_TOPIC;
  if (!topic) return;
  try {
    await fetch(`https://ntfy.sh/${topic}`, {
      method: "POST",
      body: `${title}\n${body}`,
      headers: { "Title": title, "Priority": "high" },
      signal: AbortSignal.timeout(30000),
    });
  } catch (e) {
    log("ntfy falhou: " + e.message);
  }
}

async function main() {
  const started = Date.now();
  log("auto-deploy iniciado (quota guard)");
  if (!existsSync(VERCEL_CLI) || !existsSync(path.join(FRONT_DIR, "package.json"))) {
    log("ABORT: VERCEL_CLI ou frontend/package.json ausente (CLI=" + VERCEL_CLI + ", FRONT=" + FRONT_DIR + ")");
    process.exit(0);
  }

  const { code, out } = await run(PORTABLE_NODE, [VERCEL_CLI, "deploy", "--prod", "--yes"], {
    cwd: REPO,
    timeout: TIMEOUT_MS,
  });

  log("vercel exit=" + code);
  const isRate = code !== 0 && RATE_LIMIT_PATTERNS.some((p) => out.includes(p));
  if (isRate) {
    log("quota ainda fechada (rate limit). Sair sem custo. Próxima tentativa no próximo ciclo.");
    process.exit(0);
  }

  const prodUrl = (out.match(/Production\s+https:\/\/([\w-]+\.vercel\.app)/) || [])[1];
  if (code === 0 && prodUrl) {
    log("DEPLOY CRIADO -> " + prodUrl + " em " + ((Date.now() - started) / 1000).toFixed(0) + "s (build é assíncrono)");
    await notify("MagicLeads: deploy do front criado", "URL: " + prodUrl + "\nO watcher valida quando READY.");
    await removeScheduledTask();
    log("task " + AUTO_TASK + " removida (sucesso).");
  } else {
    log("DEPLOY FALHOU (não foi rate-limit). Exit=" + code + ". Resposta: " + out.slice(-1200).replace(/\n/g, " "));
    process.exit(0);
  }
}

main();