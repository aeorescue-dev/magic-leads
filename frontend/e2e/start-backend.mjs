// Arranca o backend E2E sobre uma BD ISOLADA e ACABADA DE SEMEAR.
//
// O `playwright.config.ts` (webServer) usa este script em vez de chamar o
// uvicorn diretamente para que cada corrida comece com `e2e.db` regenerado:
// os testes de ciclo vivo partilham a BD e transicoes nacionais (convert/expire)
// persistiriam entre corridas e tornariam os cenarios irreprodutiveis.
//
// Uso:  node e2e/start-backend.mjs <caminho_db> <porta>
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const PYTHON = path.join(REPO_ROOT, "backend", "venv", "Scripts", "python.exe");
const SEED = path.join(__dirname, "seed.py");

const db = process.argv[2];
const port = process.argv[3];
if (!db || !port) {
  console.error("uso: node e2e/start-backend.mjs <db> <port>");
  process.exit(2);
}

if (fs.existsSync(db)) fs.unlinkSync(db);
console.log(`[e2e] BD regenerada: ${db}`);

const seed = spawnSync(PYTHON, [SEED, db], { cwd: REPO_ROOT, encoding: "utf8" });
if (seed.status !== 0) {
  console.error("[e2e] seed falhou:\n" + (seed.stderr || seed.stdout));
  process.exit(seed.status ?? 1);
}

const server = spawn(
  PYTHON,
  ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", port],
  { cwd: REPO_ROOT, stdio: "inherit" }
);

server.on("exit", (code) => process.exit(code ?? 0));
process.on("SIGTERM", () => server.kill());
process.on("SIGINT", () => server.kill());