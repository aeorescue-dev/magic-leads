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
export const E2E_CYCLE_TOKEN = "e2e-token-ciclo";

/** Chave de localStorage usada pelo frontend para a sessao. */
const AUTH_TOKEN_KEY = "garimpador.token";

export interface E2EProxyOptions {
  token?: string;
}

/** Regista o proxy de API e autentica a sessao antes de qualquer script da app. */
export async function installApiProxy(page: Page, opts: E2EProxyOptions = {}): Promise<void> {
  const token = opts.token ?? E2E_TOKEN;
  const baseURL = FRONTEND_ORIGIN;

  // O `frontend/middleware.ts` protege `/dashboard` exigindo PRESENCA do cookie
  // `garimpador_auth` (ou `garimpador_token`) -- e apenas presenca, nao valida o
  // valor. Sem este cookie o middleware nega a rota e serve a pagina publica de
  // upgrade, que e o que fazia o dashboard aparecer vazio.
  await page.context().addCookies([
    { name: "garimpador_auth", value: token, url: baseURL },
    { name: "garimpador_token", value: token, url: baseURL },
  ]);

  // O dashboard só mostra o WelcomePopup para quem NÃO tem a chave de
  // localStorage `magic_leads_notice_seen_<userId>` == "true". O backend NUNCA
  // devolve `welcome_popup_shown` no /api/auth/me (o campo existe no schema mas
  // o endpoint não o preenche), por isso o popup (overlay z-[90]) REABRE em cada
  // carregamento — e o removeOverlays abaixo passa o teste inteiro a travar um
  // "combate de re-render": remove-lo faz o React re-monta-lo constantemente.
  // Como a BD E2E é regenerada de raiz, os ids são baixos e previsíveis; pré-semear
  // as chaves desliga o popup para sempre sem tocar na app nem no backend.
  await page.addInitScript(() => {
    try {
      for (let i = 1; i <= 50; i++) {
        window.localStorage.setItem(`magic_leads_notice_seen_${i}`, "true");
      }
      window.localStorage.setItem("magic_leads_notice_seen", "true");
    } catch (e) {
      /* localStorage indisponível: não bloquear */
    }
  });

  // Remover overlay de notificacoes (fixed inset-0) que intercepta cliques
  // no botao "Incluir encerrados" e no modal de reserva (z-[90] cobre z-[80]).
  // Este script corre antes de qualquer JS da app.
  // NAO remove dialogs (role="dialog"): o ReserveGuideModal do ciclo de vida
  // e um overlay z-[110] e tem de sobreviver para os testes de fase.
  await page.addInitScript(() => {
    const removeOverlays = () => {
      const overlays = document.querySelectorAll('div.fixed.inset-0');
      overlays.forEach((el) => {
        if (el.getAttribute("role") === "dialog") return;
        if (el.querySelector('[role="dialog"]')) return;
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
    ([key, tok]) => {
      window.localStorage.setItem(key, tok);
    },
    [AUTH_TOKEN_KEY, token] as const
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