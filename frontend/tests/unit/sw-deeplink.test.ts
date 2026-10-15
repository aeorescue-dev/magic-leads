import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import * as vm from "node:vm";
import { describe, expect, it, vi } from "vitest";

/**
 * Regressão do deep link das push notifications.
 *
 * Bug em produção: clicar na notificação abria sempre /dashboard e nunca o
 * lead. O `notificationclick` do sw.js só fazia `postMessage` (que ninguém
 * ouvia) e `focus()`, sem nunca navegar a janela existente para o URL do
 * payload. Estes testes fixam o contrato observável do SW.
 */

const swCode = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), "../../public/sw.js"),
  "utf8",
);

type Listener = (event: unknown) => void;

function loadSW() {
  const listeners: Record<string, Listener> = {};
  const showNotification = vi.fn().mockResolvedValue(undefined);
  const openWindow = vi.fn().mockResolvedValue(undefined);
  const matchAll = vi.fn().mockResolvedValue([]);
  const claim = vi.fn().mockResolvedValue(undefined);
  const skipWaiting = vi.fn().mockResolvedValue(undefined);

  const sandbox: Record<string, unknown> = {
    self: {
      location: { origin: "https://app.example" },
      addEventListener: (type: string, cb: Listener) => {
        listeners[type] = cb;
      },
      registration: { showNotification },
      skipWaiting,
    },
    clients: { matchAll, openWindow, claim },
    console: { log: () => {}, error: () => {}, warn: () => {} },
    URL,
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(swCode, sandbox);

  return { listeners, showNotification, matchAll, openWindow, claim, skipWaiting };
}

function click(
  listener: Listener,
  data: Record<string, unknown> | undefined,
  action?: string,
) {
  const pending: Promise<unknown>[] = [];
  const close = vi.fn();
  listener({
    action,
    notification: { data, close },
    waitUntil: (p: Promise<unknown>) => pending.push(p),
  });
  return { pending: Promise.all(pending), close };
}

describe("sw.js ciclo de vida — ativação imediata", () => {
  it("install chama skipWaiting para não ficar em 'waiting'", () => {
    const { listeners, skipWaiting } = loadSW();
    listeners.install({});
    expect(skipWaiting).toHaveBeenCalledTimes(1);
  });

  it("activate chama clients.claim para assumir a página", async () => {
    const { listeners, claim } = loadSW();
    const pending: Promise<unknown>[] = [];
    listeners.activate({
      waitUntil: (p: Promise<unknown>) => pending.push(p),
    });
    await Promise.all(pending);
    expect(claim).toHaveBeenCalledTimes(1);
  });
});

describe("sw.js push — payload preserva a rota", () => {
  it("copia url e leadId do payload para options.data", async () => {
    const { listeners, showNotification } = loadSW();
    const pending: Promise<unknown>[] = [];
    listeners.push({
      data: {
        json: () => ({
          title: "Novo lead",
          body: "Rua X",
          url: "/dashboard?lead=42",
          leadId: 42,
        }),
      },
      waitUntil: (p: Promise<unknown>) => pending.push(p),
    });
    await Promise.all(pending);

    expect(showNotification).toHaveBeenCalledTimes(1);
    const [, options] = showNotification.mock.calls[0] as [string, { data: unknown }];
    expect(options.data).toEqual({ url: "/dashboard?lead=42", leadId: 42 });
  });
});

describe("sw.js notificationclick — deep link", () => {
  it("navega a janela existente no dashboard para o lead (e não openWindow)", async () => {
    const { listeners, matchAll, openWindow } = loadSW();
    const focus = vi.fn().mockResolvedValue(undefined);
    const navigate = vi.fn().mockResolvedValue({ focus });
    matchAll.mockResolvedValue([
      { url: "https://app.example/en/dashboard", focus, navigate, postMessage: vi.fn() },
    ]);

    const { pending } = click(listeners.notificationclick, {
      url: "/dashboard?lead=42",
      leadId: 42,
    });
    await pending;

    expect(navigate).toHaveBeenCalledWith("https://app.example/dashboard?lead=42");
    expect(openWindow).not.toHaveBeenCalled();
  });

  it("abre uma nova janela quando não há janela existente", async () => {
    const { listeners, openWindow } = loadSW();
    const { pending } = click(listeners.notificationclick, {
      url: "/dashboard?lead=42",
      leadId: 42,
    });
    await pending;

    expect(openWindow).toHaveBeenCalledWith("https://app.example/dashboard?lead=42");
  });

  it("faz fallback para openWindow quando navigate falha", async () => {
    const { listeners, matchAll, openWindow } = loadSW();
    const navigate = vi.fn().mockRejectedValue(new Error("navigate indisponível"));
    matchAll.mockResolvedValue([
      {
        url: "https://app.example/en/dashboard",
        focus: vi.fn(),
        navigate,
        postMessage: vi.fn(),
      },
    ]);

    const { pending } = click(listeners.notificationclick, { url: "/dashboard?lead=9" });
    await pending;

    expect(navigate).toHaveBeenCalled();
    expect(openWindow).toHaveBeenCalledWith("https://app.example/dashboard?lead=9");
  });

  it("sem navigate usa postMessage no cliente existente", async () => {
    const { listeners, matchAll, openWindow } = loadSW();
    const focus = vi.fn().mockResolvedValue(undefined);
    const postMessage = vi.fn();
    matchAll.mockResolvedValue([
      { url: "https://app.example/en/dashboard", focus, postMessage },
    ]);

    const { pending } = click(listeners.notificationclick, {
      url: "/dashboard?lead=42",
      leadId: 42,
    });
    await pending;

    expect(postMessage).toHaveBeenCalledWith({
      type: "NOTIFICATION_CLICK",
      leadId: 42,
      url: "/dashboard?lead=42",
    });
    expect(openWindow).not.toHaveBeenCalled();
  });

  it("sem url no payload cai no /dashboard", async () => {
    const { listeners, openWindow } = loadSW();
    const { pending } = click(listeners.notificationclick, { leadId: 7 });
    await pending;

    expect(openWindow).toHaveBeenCalledWith("https://app.example/dashboard");
  });

  it("ação 'dismiss' não navega", async () => {
    const { listeners, openWindow, matchAll } = loadSW();
    const { pending } = click(listeners.notificationclick, { url: "/dashboard?lead=1" }, "dismiss");
    await pending;

    expect(matchAll).not.toHaveBeenCalled();
    expect(openWindow).not.toHaveBeenCalled();
  });
});
