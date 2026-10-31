import { describe, expect, it } from "vitest";
import {
  PasskeyError,
  passkeyErrorFromException,
  passkeyMessageKey,
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

  it("mapeia NotSupportedError para unsupported", () => {
    expect(
      passkeyErrorFromException(domError("NotSupportedError"), "register").code
    ).toBe("unsupported");
  });

  it("preserva a mensagem do browser no detalhe técnico", () => {
    const out = passkeyErrorFromException(domError("UnknownError"), "register");
    expect(out.code).toBe("failed");
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
    expect(passkeyMessageKey("no_credential")).toBe("not_setup");
    expect(passkeyMessageKey("server")).toBe("failed");
  });
});
