import { expect, test } from "@playwright/test";
import { E2E_CYCLE_TOKEN, FRONTEND_ORIGIN, installApiProxy } from "./api-proxy";

/**
 * Passkeys (WebAuthn) com o virtual authenticator do Chromium.
 *
 * Cobre o caminho completo: registo em Definições -> sessão local limpa ->
 * login no ecrã de auth sem palavra-passe. A criptografia é real: o backend
 * valida a atestação/asserção com o RP ID e a origem.
 *
 * Nota: o RP ID (WebAuthn) tem de ser um domínio, não um IP — por isso este
 * teste navega em `localhost` em vez do `127.0.0.1` do baseURL. O proxy E2E
 * de /api funciona igual nas duas origens.
 */
const LOCAL_ORIGIN = FRONTEND_ORIGIN.replace("127.0.0.1", "localhost");

test.describe("passkeys", () => {
  test("Android mostra impressão digital, nunca Face ID", async ({ page }) => {
    await installApiProxy(page, { token: E2E_CYCLE_TOKEN });
    await page.addInitScript(() => {
      // Android real: biometria primária é a impressão digital / bloqueio.
      Object.defineProperty(navigator, "userAgent", {
        get: () =>
          "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 " +
          "Chrome/140.0.0.0 Mobile Safari/537.36",
      });
      window.localStorage.setItem("garimpador.passkey.enabled", "1");
    });

    await page.goto("/pt/auth");
    const button = page.getByTestId("passkey-login");
    await expect(button).toBeVisible({ timeout: 20000 });
    await expect(button).toContainText(/impressão digital/i);
    await expect(button).not.toContainText(/Face ID/i);
  });

  test("regista chave de acesso e entra sem palavra-passe", async ({ page }) => {
    await installApiProxy(page, { token: E2E_CYCLE_TOKEN });
    // O proxy semeia cookies para 127.0.0.1; esta origem é localhost.
    await page.context().addCookies([
      { name: "garimpador_auth", value: E2E_CYCLE_TOKEN, url: LOCAL_ORIGIN },
      { name: "garimpador_token", value: E2E_CYCLE_TOKEN, url: LOCAL_ORIGIN },
    ]);

    const client = await page.context().newCDPSession(page);
    await client.send("WebAuthn.enable");
    await client.send("WebAuthn.addVirtualAuthenticator", {
      options: {
        protocol: "ctap2",
        transport: "internal",
        hasResidentKey: true,
        hasUserVerification: true,
        isUserVerified: true,
        automaticPresenceSimulation: true,
      },
    });

    // 1) Registo em Definições.
    await page.goto(`${LOCAL_ORIGIN}/en/dashboard/settings`);
    await expect(page.getByTestId("passkey-settings")).toBeVisible({ timeout: 20000 });
    await page.getByTestId("passkey-register").click();
    await expect(page.getByTestId("passkey-ok")).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId("passkey-item").first()).toBeVisible();
    // Já há chave neste dispositivo: a UI não pode voltar a oferecer "Ativar"
    // (era o caminho que originava NotAllowedError/timeout no Android).
    await expect(page.getByTestId("passkey-device-active")).toBeVisible();
    await expect(page.getByTestId("passkey-register")).toContainText(
      /Replace passkey|Substituir/i
    );

    // 2) Sessão local limpa (o proxy E2E continua a encaminhar /api).
    //    Este init script corre depois do init do proxy, por isso apaga o token.
    await page.addInitScript(() => {
      try {
        window.localStorage.removeItem("garimpador.token");
      } catch {
        /* noop */
      }
    });
    await page.goto(`${LOCAL_ORIGIN}/en/auth`);
    await expect(page.getByTestId("passkey-login")).toBeVisible({ timeout: 20000 });

    // 3) Login só com a passkey: o virtual authenticator responde sozinho.
    await page.getByTestId("passkey-login").click();
    await expect(page).toHaveURL(/\/en\/dashboard/, { timeout: 20000 });
  });

  test("substituir não duplica: nova credencial e a antiga sai do servidor", async ({
    page,
  }) => {
    await installApiProxy(page, { token: E2E_CYCLE_TOKEN });
    await page.context().addCookies([
      { name: "garimpador_auth", value: E2E_CYCLE_TOKEN, url: LOCAL_ORIGIN },
      { name: "garimpador_token", value: E2E_CYCLE_TOKEN, url: LOCAL_ORIGIN },
    ]);
    const client = await page.context().newCDPSession(page);
    await client.send("WebAuthn.enable");
    await client.send("WebAuthn.addVirtualAuthenticator", {
      options: {
        protocol: "ctap2",
        transport: "internal",
        hasResidentKey: true,
        hasUserVerification: true,
        isUserVerified: true,
        automaticPresenceSimulation: true,
      },
    });

    const ids = () =>
      page.evaluate(async () => {
        const res = await fetch("/api/users/me/passkeys", {
          credentials: "include",
        });
        const data = await res.json();
        return (data.passkeys || []).map((p: any) => p.credential_id as string);
      });

    // Este teste partilha a conta E2E; começa sem chaves.
    await page.goto(`${LOCAL_ORIGIN}/en/dashboard/settings`);
    await expect(page.getByTestId("passkey-settings")).toBeVisible({ timeout: 20000 });
    for (const id of await ids()) {
      await page.evaluate(
        async (credentialId) => {
          await fetch(`/api/users/me/passkeys/${encodeURIComponent(credentialId)}`, {
            method: "DELETE",
            credentials: "include",
          });
        },
        id
      );
    }
    await page.reload();
    await expect(page.getByTestId("passkey-device-active")).toHaveCount(0);

    await page.getByTestId("passkey-register").click();
    await expect(page.getByTestId("passkey-ok")).toBeVisible({ timeout: 20000 });
    const before = await ids();
    expect(before).toHaveLength(1);
    await expect(page.getByTestId("passkey-device-active")).toBeVisible();

    page.once("dialog", (dialog) => dialog.accept());
    await page.getByTestId("passkey-register").click();
    await expect
      .poll(async () => (await ids()).length, { timeout: 20000 })
      .toBe(1);
    await expect.poll(async () => (await ids())[0]).not.toBe(before[0]);
  });
});
