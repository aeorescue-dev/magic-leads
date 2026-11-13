import { describe, expect, it } from "vitest";
import EN from "./i18n/en";
import PT from "./i18n/pt";
import ES from "./i18n/es";
import { normalizeLocale, pathWithLocale } from "./i18n";
import { apiErrorKey } from "./api-errors";

const dicts: Record<string, Record<string, string>> = {
  en: EN as Record<string, string>,
  pt: PT as Record<string, string>,
  es: ES as Record<string, string>,
};

const REQUIRED_KEYS = [
  "dashboard.feed.tab_all",
  "dashboard.feed.tab_reactive",
  "dashboard.feed.tab_preventive",
  "dashboard.feed.tab_works",
  "dashboard.preinspection.badge",
  "dashboard.preinspection.title",
  "dashboard.preinspection.subtitle",
  "dashboard.preinspection.awaiting",
  "dashboard.preinspection.possible",
  "dashboard.signal.preventive",
  "dashboard.signal.reactive",
  "dashboard.signal.permit",
  "dashboard.severity.critical",
  "dashboard.severity.high",
  "dashboard.severity.medium",
  "dashboard.severity.routine",
  "dashboard.deadline.none",
  "dashboard.deadline.not_published",
  "dashboard.deadline.in_days",
  "dashboard.deadline.inspection_until",
  "dashboard.deadline.hearing_in",
  "dashboard.status.awaiting_inspection",
  "dashboard.status.inspection_possible",
  "dashboard.status.fine_active",
  "dashboard.status.work_approved",
  "dashboard.status.selected",
  "dashboard.outcome.won",
  "dashboard.outcome.lost",
  "dashboard.outcome.no_decision",
  "dashboard.outcome.contract_value",
  "dashboard.outcome.record",
  "dashboard.outcome.won_at",
  "dashboard.outcome.lost_at",
  "dashboard.outcome.lost_reason",
  "dashboard.opportunity.not_found",
  "dashboard.opportunity.property_locked",
  "dashboard.opportunity.already_converted",
  "dashboard.opportunity.not_owner",
  "dashboard.opportunity.daily_limit",
  "dashboard.opportunity.consent_required",
  "dashboard.opportunity.not_reserved",
  "dashboard.opportunity.reserved",
  "dashboard.toast.reveal_reserved",
  "dashboard.nav.prevention",
  "dashboard.reveal.title",
  "dashboard.reveal.confirm",
  "dashboard.reveal.consent",
  "dashboard.reserve.step1.title",
  "dashboard.reserve.step2.title",
  "dashboard.reserve.step3.title",
  "dashboard.reserve.step4.title",
] as const;

describe("i18n dictionary parity", () => {
  it("has the same keys in EN, PT and ES", () => {
    const en = Object.keys(EN).sort();
    expect(Object.keys(PT).sort()).toEqual(en);
    expect(Object.keys(ES).sort()).toEqual(en);
  });

  it("contains every key required by the preventive/reactive layer", () => {
    for (const [lang, dict] of Object.entries(dicts)) {
      for (const key of REQUIRED_KEYS) {
        expect(dict[key], `${lang} is missing ${key}`).toBeTruthy();
      }
    }
  });

  it("does not use the old 'credits' wording in the reveal modal", () => {
    for (const [lang, dict] of Object.entries(dicts)) {
      const copy = [
        dict["dashboard.reveal.consent_corporate"],
        dict["dashboard.reveal.confirm_corporate"],
      ].join(" ").toLowerCase();
      expect(copy, `${lang} still mentions credits`).not.toMatch(/credit|crédito|credito/);
    }
  });

  it("maps every API error code to an existing translation key", () => {
    const codes = [
      "CONSENT_REQUIRED",
      "NOT_FOUND",
      "PROPERTY_LOCKED",
      "ALREADY_RESERVED",
      "ALREADY_CONVERTED",
      "NOT_OWNER",
      "DAILY_LIMIT_REACHED",
      "NOT_RESERVED",
    ];
    for (const code of codes) {
      const key = apiErrorKey(code);
      expect(key, `${code} has no i18n key`).toBeTruthy();
      for (const [lang, dict] of Object.entries(dicts)) {
        expect(dict[key as string], `${lang} is missing ${key}`).toBeTruthy();
      }
    }
  });
});

describe("locale path helpers", () => {
  it("normalizes supported and unsupported locales", () => {
    expect(normalizeLocale("pt-BR")).toBe("pt");
    expect(normalizeLocale("EN")).toBe("en");
    expect(normalizeLocale("es-MX")).toBe("es");
    expect(normalizeLocale("fr")).toBeNull();
    expect(normalizeLocale(null)).toBeNull();
  });

  it("replaces or inserts the locale segment", () => {
    expect(pathWithLocale("/en/dashboard", "pt")).toBe("/pt/dashboard");
    expect(pathWithLocale("/pt", "es")).toBe("/es");
    expect(pathWithLocale("/dashboard", "en")).toBe("/en/dashboard");
    expect(pathWithLocale("/", "pt")).toBe("/pt");
  });
});
