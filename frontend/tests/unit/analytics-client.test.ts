import { describe, expect, it } from "vitest";

import {
  isTrackablePath,
  parseUtm,
  sessionExpired,
} from "@/lib/analytics";

describe("Analytics client — privacidade e atribuição", () => {
  it("extrai UTM anónimos", () => {
    expect(
      parseUtm(
        "?utm_source=magicleads&utm_medium=outreach&utm_campaign=dallas_roofing&utm_content=step1"
      )
    ).toEqual({
      source: "magicleads",
      medium: "outreach",
      campaign: "dallas_roofing",
      content: "step1",
    });
    expect(parseUtm("")).toEqual({});
    expect(parseUtm("?city=DALLAS&niche=roofing")).toEqual({});
  });

  it("não rastreia admin, dashboard, API nem assets", () => {
    expect(isTrackablePath("/en")).toBe(true);
    expect(isTrackablePath("/pt")).toBe(true);
    expect(isTrackablePath("/admin/analytics")).toBe(false);
    expect(isTrackablePath("/dashboard/leads")).toBe(false);
    expect(isTrackablePath("/api/track")).toBe(false);
    expect(isTrackablePath("/_next/static/x.js")).toBe(false);
  });

  it("expira sessão após 30 minutos de inatividade", () => {
    const now = Date.parse("2026-11-02T12:00:00Z");
    expect(
      sessionExpired("2026-11-02T11:45:00Z", now)
    ).toBe(false);
    expect(
      sessionExpired("2026-11-02T11:20:00Z", now)
    ).toBe(true);
    expect(sessionExpired("invalido", now)).toBe(true);
  });
});
