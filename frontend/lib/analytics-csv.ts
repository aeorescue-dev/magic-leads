// Export CSV (long format) do resumo de analytics.
//
// Uma linha por métrica permite abrir em Excel/Sheets e pivotar por
// section/label sem perder as tabelas (origem, campanha, geo, funil, ...).

import type { AdminAnalytics } from "./admin-api";

type Row = [section: string, metric: string, label: string, value: string | number];

function escapeCsv(value: string | number): string {
  const text = String(value ?? "");
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

export function buildAnalyticsCsv(data: AdminAnalytics): string {
  const rows: Row[] = [];
  const push = (
    section: string,
    metric: string,
    label: string,
    value: string | number
  ) => rows.push([section, metric, label, value]);

  push("meta", "range", "", data.range);
  push("meta", "start", "", data.start);
  push("meta", "end", "", data.end);
  push("meta", "generated_at", "", data.generated_at);

  const totals = data.cards;
  for (const key of [
    "visits",
    "visitors",
    "pageviews",
    "cta_clicks",
    "form_submits",
    "avg_engagement_s",
    "bounce_rate",
  ]) {
    push("totals", key, "", totals[key]?.value ?? 0);
  }
  push("health", "score", "", data.overall.score);
  push("health", "volume", "", data.overall.volume);
  push("health", "engagement", "", data.overall.engagement);
  push("health", "conversion", "", data.overall.conversion);

  for (const point of data.series) {
    push("series", "visits", point.t, point.visits);
    push("series", "visitors", point.t, point.visitors);
    push("series", "pageviews", point.t, point.pageviews);
    push("series", "cta_clicks", point.t, point.cta);
    push("series", "form_submits", point.t, point.forms);
  }

  for (const row of data.sources) {
    const label = `${row.source}/${row.medium}`;
    push("source", "visits", label, row.visits);
    push("source", "visitors", label, row.visitors);
    push("source", "pageviews", label, row.pageviews);
    push("source", "cta_clicks", label, row.cta_clicks);
    push("source", "form_submits", label, row.form_submits);
  }

  for (const row of data.campaigns) {
    const label = `${row.campaign}/${row.content} (${row.source}/${row.medium})`;
    push("campaign", "visits", label, row.visits);
    push("campaign", "visitors", label, row.visitors);
    push("campaign", "cta_clicks", label, row.cta_clicks);
    push("campaign", "form_submits", label, row.form_submits);
    push("campaign", "cta_rate", label, row.cta_rate);
    push("campaign", "form_rate", label, row.form_rate);
  }

  for (const row of data.geo) {
    const label = `${row.country}/${row.region}/${row.city}`;
    push("geo", "visits", label, row.visits);
    push("geo", "visitors", label, row.visitors);
    push("geo", "cta_clicks", label, row.cta_clicks);
    push("geo", "form_submits", label, row.form_submits);
  }

  for (const step of data.funnel) {
    push("funnel", "count", step.step, step.count);
    push("funnel", "rate", step.step, step.rate);
  }

  const email = data.email_attribution;
  push("email", "visits", "", email.visits);
  push("email", "cta_clicks", "", email.cta_clicks);
  push("email", "form_submits", "", email.form_submits);
  push("email", "form_rate", "", email.form_rate);
  for (const row of email.rows) {
    const label = `${row.campaign}/${row.content}/${row.city}`;
    push("email", "visits", label, row.visits);
    push("email", "cta_clicks", label, row.cta_clicks);
    push("email", "form_submits", label, row.form_submits);
    push("email", "form_rate", label, row.form_rate);
  }

  for (const row of data.events) {
    push("event", "count", row.name, row.count);
    push("event", "sessions", row.name, row.sessions);
  }
  for (const row of data.devices) {
    push("device", "visits", row.device, row.visits);
  }
  for (const row of data.locales) {
    push("locale", "visits", row.locale, row.visits);
  }
  for (const row of data.recent) {
    const label = [
      row.ts,
      row.source,
      row.campaign,
      row.content,
      row.city,
      row.label || "",
      row.path || "",
    ].join(" | ");
    push("recent", "event", label, row.name);
  }

  const header = "section,metric,label,value";
  const body = rows
    .map((row) => row.map((value) => escapeCsv(value)).join(","))
    .join("\n");
  return `${header}\n${body}\n`;
}

export function downloadAnalyticsCsv(data: AdminAnalytics): void {
  if (typeof window === "undefined") return;
  const csv = "\uFEFF" + buildAnalyticsCsv(data);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `magicleads-analytics_${data.start}_${data.end}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
