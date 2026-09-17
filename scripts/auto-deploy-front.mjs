#!/usr/bin/env node
/**
 * Auto-deploy do frontend na Vercel contornando a cota free (api-deployments-free-per-day).
 *
 * O projeto magic-leads-frontend-final tem rootDirectory="frontend" no painel.
 * Por isso o CLI precisa receber o conteúdo com a pasta "frontend/" no topo (layout
 * igual ao clone do Git). Este script remonta esse layout num diretório de staging e
 * roda `vercel deploy --prod` de lá.
 *
 * Enquanto a cota diária estiver fechada o Vercel responde
 *   Resource is limited - try again in 24 hours (code api-deployments-free-per-day)
 * e o script apenas registra no log e sai com exit 0 (não gera build, é barato).
 * Quando a janela abre, o deploy é criado; ao confirmar sucesso o script:
 *   - remove a própria Scheduled Task (MagicLeads-AutoDeployFront) se AUTO_TASK estiver set;
 *   - dispara ntfy (opcional) e loga a URL de produção.
 * A task de verificação (MagicLeads-VerifyDeploy, a cada 2 min, com fingerprint)
 * detecta a mudança de build e valida de ponta a ponta.
 *
 * Env:
 *   REPO        (default: diretório-pai deste script)
 *   FRONT_URL   (default: https://magicleads-oficial.vercel.app)
 *   NTFY_TOPIC  (opcional)
 *   AUTO_TASK   (opcional: nome da Scheduled Task a auto-deletar ao conseguir deploy)
 *   VERCEL_CLI  (opcional: caminho do binário do CLI; default: junto ao node atual)
 */
import { spawn, spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, rmSync, writeFileSync, appendFileSync, readFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO = process.env.REPO || ROOT;
const FRONT_DIR = path.join(REPO, "frontend");
const STAGE = path.join(os.tmpdir(), "opencode", "deploystage");
const LOG = path.join(REPO, "scripts", "auto-deploy.log");
const TIMEOUT_MS = 30 * 60 * 1000;

const PORTABLE_NODE = process.execPath;
const VERCEL_CLI =
  process.env.VERCEL_CLI ||
  path.join(path.dirname(PORTABLE_NODE), "node_modules", "vercel", "dist", "index.js");

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

function removeScheduledTask(name) {
  if (!name) return Promise.resolve();
  return run("schtasks", ["/Delete", "/TN", name, "/F"], { shell: true });
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

function buildStage() {
  rmSync(STAGE, { recursive: true, force: true });
  mkdirSync(path.join(STAGE, "frontend"), { recursive: true });

  const linkSrc = path.join(FRONT_DIR, ".vercel");
  if (!existsSync(linkSrc)) throw new Error(".vercel link ausente em " + linkSrc);
  cpSync(linkSrc, path.join(STAGE, ".vercel"), { recursive: true });

  cpSync(FRONT_DIR, path.join(STAGE, "frontend"), {
    recursive: true,
    filter: (src) => {
      const rel = path.relative(FRONT_DIR, src);
      if (!rel) return true;
      const first = rel.split(path.sep)[0];
      if (first === "node_modules" || first === ".next" || first === ".git" || first === ".vercel") return false;
      return true;
    },
  });
  log("staging pronto: " + STAGE + " (frontend/)");
}

async function main() {
  const started = Date.now();
  log("auto-deploy iniciado (quota guard)");
  if (!existsSync(VERCEL_CLI) || !existsSync(FRONT_DIR)) {
    log("ABORT: VERCEL_CLI ou frontend ausente (CLI=" + VERCEL_CLI + ", FRONT=" + FRONT_DIR + ")");
    process.exit(0);
  }

  try {
    buildStage();
  } catch (e) {
    log("ABORT staging: " + e.message);
    process.exit(0);
  }

  const { code, out } = await run(PORTABLE_NODE, [VERCEL_CLI, "deploy", "--prod", "--yes"], {
    cwd: STAGE,
    timeout: TIMEOUT_MS,
  });

  log("vercel exit=" + code);
  const isRate = code !== 0 && RATE_LIMIT_PATTERNS.some((p) => out.includes(p));
  if (isRate) {
    log("quota ainda fechada (rate limit). Sair sem custo. Próxima tentativa no próximo ciclo.");
    process.exit(0);
  }

  const prodUrl = (out.match(/Production\s+https:\/\/(magic-leads-frontend-final-[\w-]+\.vercel\.app)/) || [])[1];
  if (code === 0 && prodUrl) {
    log("DEPLOY OK -> " + prodUrl + " em " + ((Date.now() - started) / 1000).toFixed(0) + "s");
    log("FINGERPRINT do deploy: " + prodUrl);
    await notify("MagicLeads: deploy do front publicado", "Build novo no ar: " + prodUrl + "\nO watcher vai validar o clique no Stripe.");
    await removeScheduledTask(process.env.AUTO_TASK);
    log("task " + (process.env.AUTO_TASK || "") + " removida (sucesso).");
  } else {
    log("DEPLOY FALHOU (não foi rate-limit). Exit=" + code + ". Resposta: " + out.slice(-1200).replace(/\n/g, " "));
    process.exit(0);
  }
}

main();