import { describe, expect, it } from "vitest";

import { isPaymentRequired } from "@/lib/api-client";

/**
 * A5 — reconhecimento do 402. O envelope do backend é
 * `{detail: {action: "REDIRECT_TO_CHECKOUT"}}`.
 */

describe("isPaymentRequired — gate de assinatura", () => {
  it("reconhece HTTP 402", () => {
    expect(isPaymentRequired(402)).toBe(true);
  });

  it("reconhece o envelope A5 mesmo sem status 402", () => {
    expect(
      isPaymentRequired(403, { detail: { action: "REDIRECT_TO_CHECKOUT" } })
    ).toBe(true);
    expect(isPaymentRequired(undefined, { action: "REDIRECT_TO_CHECKOUT" })).toBe(true);
  });

  it("não confunde erros normais com pagamento", () => {
    expect(isPaymentRequired(401)).toBe(false);
    expect(isPaymentRequired(409, { detail: { error: "already_reserved" } })).toBe(false);
    expect(isPaymentRequired(200, { action: "OTHER" })).toBe(false);
    expect(isPaymentRequired(undefined, null)).toBe(false);
  });
});
