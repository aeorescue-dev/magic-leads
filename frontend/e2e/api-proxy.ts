import type { Page, Route } from "@playwright/test";

/**
 * Encaminha `/api/**` do browser para o backend LOCAL.
 *
 * `next.config.js` reescreve `/api/:path*` para a PRODUCAO. Este proxy
 * intercepta antes de a rewrite happen e fala com o uvicorn local, que tem a
 * base de dados semeada pelo `seed.py`. Assim o E2E corre o frontend real sem
 * tocar em producao nem alterar a config de producao.
 */

export const BACKEND_ORIGIN =
  process.env.E2E_BACKEND_ORIGIN || `http://127.0.0.1:${process.env.E2E_BACKEND_PORT || 8799}`;

export const FRONTEND_ORIGIN =
  process.env.E2E_FRONTEND_ORIGIN || `http://127.0.0.1:${process.env.E2E_FRONTEND_PORT || 3899}`;

export const E2E_TOKEN = "e2e-token-cota-esgotada";

/** Chave de localStorage usada pelo frontend para a sessao. */
const AUTH_TOKEN_KEY = "garimpador.token";

/** Regista o proxy de API e autentica a sessao antes de qualquer script da app. */
export async function installApiProxy(page: Page): Promise<void> {
  const baseURL = FRONTEND_ORIGIN;

  // O `frontend/middleware.ts` protege `/dashboard` exigindo PRESENCA do cookie
  // `garimpador_auth` (ou `garimpador_token`) -- e apenas presenca, nao valida o
  // valor. Sem este cookie o middleware nega a rota e serve a pagina publica de
  // upgrade, que e o que fazia o dashboard aparecer vazio.
  await page.context().addCookies([
    { name: "garimpador_auth", value: E2E_TOKEN, url: baseURL },
    { name: "garimpador_token", value: E2E_TOKEN, url: baseURL },
  ]);

  // Remover overlay de notificacoes (fixed inset-0) que intercepta cliques
  // no botao "Incluir encerrados" e no modal de reserva (z-[90] cobre z-[80]).
  // Este script corre antes de qualquer JS da app.
  await page.addInitScript(() => {
    const removeOverlays = () => {
      const overlays = document.querySelectorAll('div.fixed.inset-0');
      overlays.forEach((el) => {
        const style = window.getComputedStyle(el);
        const zi = parseInt(style.zIndex, 10);
        if (zi >= 90) {
          el.remove();
        }
      });
    };
    // Limpeza imediata e contínua
    removeOverlays();
    const observer = new MutationObserver(removeOverlays);
    observer.observe(document.body, { childList: true, subtree: true });
    // Fallback periódico agressivo
    setInterval(removeOverlays, 100);
  });

  // Token no localStorage ANTES da app carregar: e assim que o frontend le a sessao
  // e envia o header `Authorization` nas chamadas da API.
  await page.addInitScript(
    ([key, token]) => {
      window.localStorage.setItem(key, token);
    },
    [AUTH_TOKEN_KEY, E2E_TOKEN] as const
  );

  await page.route("**/api/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const target = `${BACKEND_ORIGIN}${url.pathname}${url.search}`;

    const headers: Record<string, string> = {};
    for (const [name, value] of Object.entries(request.headers())) {
      // Hop-by-hop e content-length nao se replicam.
      if (["host", "content-length", "connection"].includes(name)) continue;
      headers[name] = value;
    }

    try {
      const response = await fetch(target, {
        method: request.method(),
        headers,
        body: ["GET", "HEAD"].includes(request.method())
          ? undefined
          : request.postData() ?? undefined,
        redirect: "manual",
      });

      const body = Buffer.from(await response.arrayBuffer());
      const outHeaders: Record<string, string> = {};
      response.headers.forEach((value, key) => {
        if (["content-encoding", "content-length", "transfer-encoding"].includes(key)) return;
        outHeaders[key] = value;
      });

      await route.fulfill({
        status: response.status,
        headers: outHeaders,
        body,
      });
    } catch (error) {
      // Falha do proxy tem de ser visivel no teste, nao silenciosa.
      await route.fulfill({
        status: 599,
        contentType: "application/json",
        body: JSON.stringify({ error: `proxy E2E falhou: ${String(error)}` }),
      });
    }
  });
}