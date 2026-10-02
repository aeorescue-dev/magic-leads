import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

/**
 * E2E do ciclo de entrega da Regra A, num browser real.
 *
 * Decisao importante: `frontend/next.config.js` tem o destino do rewrite
 * `/api/:path*` FIXO na producao (Railway) e ignora `NEXT_PUBLIC_API_URL`.
 * Nao se mexe nessa config -- mexer na config de producao para correr testes
 * seria exactamente o tipo de risco que este lote existe para evitar.
 *
 * Em vez disso, o `api-proxy.ts` interceta `/api/**` no browser e encaminha
 * para um backend LOCAL (uvicorn) com uma base de dados isolada. Resultado:
 *   - o bundle real do frontend (o que o utilizador executa)
 *   - o backend real (SQLite, cota, reveal, regra A)
 *   - zero contacto com a producao
 */
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT || 8799);
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT || 3899);
const REPO_ROOT = path.resolve(__dirname, "..");
// Caminho absoluto: o `cwd` do webServer ja e a raiz do repo, logo um caminho
// relativo a partir dai apontaria para fora da arvore.
const PYTHON = path.join(REPO_ROOT, "backend", "venv", "Scripts", "python.exe");

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Backend local com a BD semeada.
      command: `"${PYTHON}" -m uvicorn backend.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: REPO_ROOT,
      env: {
        LEADS_DB_PATH: path.resolve(__dirname, "e2e", "e2e.db"),
        LEADS_SEED_FILE: "",
      },
      url: `http://127.0.0.1:${BACKEND_PORT}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: `npx next start -p ${FRONTEND_PORT}`,
      cwd: path.resolve(__dirname),
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
});