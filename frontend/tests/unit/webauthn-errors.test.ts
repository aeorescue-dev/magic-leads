import { afterEach, describe, expect, it, vi } from "vitest";
import {
  PasskeyError,
  passkeyErrorFromException,
  passkeyMessageKey,
  passkeyPlatform,
} from "@/lib/webauthn";

/**
 * O erro real do browser não pode virar "tente novamente".
 * SecurityError = RP ID/origem errados (ex.: preview Vercel);
 * InvalidStateError = este dispositivo já tem passkey;
 * NotAllowedError = utilizador cancelou ou o SO negou.
 */
function domError(name: string) {
  const err = new Error(`${name} aconteceu`);
  err.name = name;
  return err;
}

describe("passkeyErrorFromException", () => {
  it("mapeia SecurityError para origin (RP ID/domínio)", () => {
    const out = passkeyErrorFromException(domError("SecurityError"), "register");
    expect(out).toBeInstanceOf(PasskeyError);
    expect(out.code).toBe("origin");
    expect(out.detail?.browserError).toContain("SecurityError");
  });

  it("mapeia InvalidStateError para already_registered", () => {
    const out = passkeyErrorFromException(domError("InvalidStateError"), "register");
    expect(out.code).toBe("already_registered");
  });

  it("mapeia NotAllowedError e AbortError para cancelled", () => {
    expect(passkeyErrorFromException(domError("NotAllowedError"), "login").code).toBe(
      "cancelled"
    );
    expect(passkeyErrorFromException(domError("AbortError"), "login").code).toBe(
      "cancelled"
    );
  });

  it("distingue timeout de cancelamento pelo texto do NotAllowedError", () => {
    const err = new Error(
      "The operation either timed out or was not allowed. See: https://www.w3.org/TR/webauthn-2/"
    );
    err.name = "NotAllowedError";
    expect(passkeyErrorFromException(err, "register").code).toBe("timeout");
    expect(
      passkeyErrorFromException(domError("NotAllowedError"), "register").code
    ).toBe("cancelled");
  });

  it("mapeia NotSupportedError para unsupported", () => {
    expect(
      passkeyErrorFromException(domError("NotSupportedError"), "register").code
    ).toBe("unsupported");
  });

  it("mapeia NotReadableError/UnknownError para unreadable (Android)", () => {
    const a = passkeyErrorFromException(domError("NotReadableError"), "register");
    expect(a.code).toBe("unreadable");
    expect(a.detail?.browserError).toContain("NotReadableError");
    expect(
      passkeyErrorFromException(domError("UnknownError"), "register").code
    ).toBe("unreadable");
  });

  it("preserva a mensagem do browser no detalhe técnico", () => {
    const out = passkeyErrorFromException(domError("UnknownError"), "register");
    expect(out.detail?.browserError).toBe("UnknownError: UnknownError aconteceu");
  });

  it("não rebenta com valores não-Error", () => {
    expect(passkeyErrorFromException(null, "login").code).toBe("failed");
    expect(passkeyErrorFromException("x", "login").code).toBe("failed");
  });
});

describe("passkeyMessageKey", () => {
  it("traduz códigos para chaves i18n", () => {
    expect(passkeyMessageKey("origin")).toBe("origin");
    expect(passkeyMessageKey("already_registered")).toBe("already_registered");
    expect(passkeyMessageKey("unreadable")).toBe("unreadable");
    expect(passkeyMessageKey("timeout")).toBe("timeout");
    expect(passkeyMessageKey("no_credential")).toBe("not_setup");
    expect(passkeyMessageKey("server")).toBe("failed");
  });
});

describe("passkeyPlatform", () => {
  afterEach(() => vi.unstubAllGlobals());

  const withUA = (ua: string) => vi.stubGlobal("navigator", { userAgent: ua });

  it("distingue Android, Apple e Windows (rótulos honestos)", () => {
    withUA("Mozilla/5.0 (Linux; Android 14; SM-S918B) Chrome/140 Mobile");
    expect(passkeyPlatform()).toBe("android");

    withUA("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1");
    expect(passkeyPlatform()).toBe("apple");

    withUA("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140");
    expect(passkeyPlatform()).toBe("windows");

    withUA("Mozilla/5.0 (X11; Linux x86_64) Firefox/140");
    expect(passkeyPlatform()).toBe("other");
  });
});
