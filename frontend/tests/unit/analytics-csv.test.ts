import { describe, expect, it } from "vitest";

import { buildAnalyticsCsv } from "@/lib/analytics-csv";
import type { AdminAnalytics } from "@/lib/admin-api";

function fixture(): AdminAnalytics {
  return {
    generated_at: "2026-11-02T12:00:00+00:00",
    range: "custom",
    start: "2026-10-01",
    end: "2026-10-31",
    window_start: "2026-10-01T00:00:00+00:00",
    window_end: "2026-11-01T00:00:00+00:00",
    overall: {
      score: 90,
      status: "ok",
      status_label: "Saudável",
      reasons: [],
      volume: 100,
      engagement: 80,
      conversion: 70,
    },
    cards: {
      visits: { value: 10, delta_pct: 5, spark: [1, 2] },
      visitors: { value: 8, delta_pct: 4, spark: [1, 2] },
      pageviews: { value: 12, delta_pct: 2, spark: [1, 2] },
      cta_clicks: { value: 3, delta_pct: 1, spark: [1, 0] },
      form_submits: { value: 1, delta_pct: 0, spark: [1, 0] },
      avg_engagement_s: { value: 42, delta_pct: 3, spark: [] },
      bounce_rate: { value: 20, delta_pct: -2, spark: [] },
    },
    series: [
      {
        t: "2026-10-01",
        visits: 2,
        visitors: 2,
        pageviews: 3,
        cta: 1,
        forms: 0,
      },
    ],
    sources: [
      {
        source: "email",
        medium: "outreach",
        visits: 5,
        visitors: 4,
        pageviews: 6,
        cta_clicks: 2,
        form_submits: 1,
      },
    ],
    campaigns: [
      {
        source: "email",
        medium: "outreach",
        campaign: "dallas,roofing",
        content: "step1",
        visits: 5,
        visitors: 4,
        cta_clicks: 2,
        form_submits: 1,
        form_rate: 20,
        cta_rate: 40,
      },
    ],
    email_attribution: {
      visits: 5,
      cta_clicks: 2,
      form_submits: 1,
      form_rate: 20,
      rows: [
        {
          campaign: "dallas,roofing",
          content: "step1",
          city: "Dallas",
          visits: 5,
          visitors: 4,
          cta_clicks: 2,
          form_submits: 1,
          form_rate: 20,
          cta_rate: 40,
        },
      ],
    },
    geo: [
      {
        country: "US",
        region: "TX",
        city: "Dallas",
        visits: 5,
        visitors: 4,
        cta_clicks: 2,
        form_submits: 1,
      },
    ],
    funnel: [
      { step: "Visitas", count: 10, rate: 100 },
      { step: "CTA click", count: 3, rate: 30 },
    ],
    events: [{ name: "cta_click", count: 3, sessions: 2 }],
    devices: [{ device: "desktop", visits: 9 }],
    locales: [{ locale: "en", visits: 10 }],
    recent: [
      {
        ts: "2026-10-31T12:00:00+00:00",
        name: "cta_click",
        path: "/en",
        label: "hero_cta",
        source: "email",
        medium: "outreach",
        campaign: "dallas,roofing",
        content: "step1",
        city: "Dallas",
      },
    ],
  };
}

describe("Analytics CSV", () => {
  it("exporta metadados, totais e séries no período escolhido", () => {
    const csv = buildAnalyticsCsv(fixture());
    expect(csv.split("\n")[0]).toBe("section,metric,label,value");
    expect(csv).toContain("meta,start,,2026-10-01");
    expect(csv).toContain("meta,end,,2026-10-31");
    expect(csv).toContain("totals,visits,,10");
    expect(csv).toContain("series,visits,2026-10-01,2");
    expect(csv).toContain("email,form_rate,,20");
    expect(csv).toContain("geo,cta_clicks,US/TX/Dallas,2");
  });

  it("faz escape de vírgulas e aspas", () => {
    const csv = buildAnalyticsCsv(fixture());
    expect(csv).toContain(
      '"dallas,roofing/step1 (email/outreach)"'
    );
  });
});
