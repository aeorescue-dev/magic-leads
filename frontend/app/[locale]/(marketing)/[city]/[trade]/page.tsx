import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  LockKeyhole,
  MapPin,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { ShowcaseCta } from "./ShowcaseCta";

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ||
  "https://magic-leads-production.up.railway.app"
).replace(/\/$/, "");

type ShowcaseItem = {
  masked_title: string;
  neighborhood: string | null;
  zip_prefix: string | null;
  observed_at: string | null;
  value_band: string | null;
  signal_type: string | null;
};

type ShowcasePayload = {
  page: {
    city: string;
    state: string;
    city_slug: string;
    trade_code: string;
    trade_label: string;
    title: string;
    subtitle: string;
    count: number;
    signal_label: string;
    last_built_at: string | null;
    fallback: "city" | "trade" | null;
    fallback_label: string | null;
  };
  items: ShowcaseItem[];
  cta: { price_usd: number; period: string; checkout_enabled: boolean };
  attribution?: { token?: string; token_valid?: boolean };
};

async function getShowcase(
  city: string,
  trade: string,
  vt: string
): Promise<ShowcasePayload | null> {
  const query = vt ? `?vt=${encodeURIComponent(vt)}` : "";
  try {
    const response = await fetch(
      `${API_URL}/api/showcase/${encodeURIComponent(city)}/${encodeURIComponent(
        trade
      )}${query}`,
      vt ? { cache: "no-store" } : { next: { revalidate: 300 } }
    );
    if (!response.ok) return null;
    return (await response.json()) as ShowcasePayload;
  } catch {
    return null;
  }
}

function fmtDate(value: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; city: string; trade: string }>;
}): Promise<Metadata> {
  const { city, trade } = await params;
  const data = await getShowcase(city, trade, "");
  if (!data) return { title: "Magic Leads" };
  return {
    title: `${data.page.title} | Magic Leads`,
    description: data.page.subtitle,
    robots: data.page.fallback
      ? { index: false, follow: true }
      : { index: true, follow: true },
  };
}

export default async function ShowcasePage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string; city: string; trade: string }>;
  searchParams: Promise<{ vt?: string }>;
}) {
  const { locale, city, trade } = await params;
  const { vt = "" } = await searchParams;
  const data = await getShowcase(city, trade, vt);
  if (!data) notFound();

  const token = data.attribution?.token_valid ? vt : "";
  const page = data.page;
  const items = data.items;
  const price = Math.round(data.cta.price_usd);

  return (
    <main className="bg-[#070b10] pb-24 text-slate-200 lg:pb-0">
      <section className="mx-auto max-w-6xl px-4 pb-6 pt-6 sm:pt-10">
        <div className="flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-emerald-300">
          <Sparkles className="h-3.5 w-3.5" />
          Magic Leads · Local opportunity brief
        </div>
        <h1 className="mt-3 max-w-4xl text-2xl font-black tracking-tight text-white sm:text-4xl">
          {page.title}
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-400">
          {page.subtitle}
        </p>

        <div className="mt-5 max-w-md">
          <ShowcaseCta
            token={token}
            city={page.city_slug}
            trade={page.trade_code}
            priceUsd={price}
            locale={locale}
          />
        </div>

        {page.fallback && page.fallback_label ? (
          <div className="mt-4 rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200">
            {page.fallback_label}
          </div>
        ) : null}

        <div className="mt-4 flex flex-wrap gap-2 text-[10px]">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-slate-300">
            <MapPin className="h-3 w-3 text-emerald-300" /> {page.city},{" "}
            {page.state}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-slate-300">
            <CalendarDays className="h-3 w-3 text-emerald-300" /> Updated{" "}
            {fmtDate(page.last_built_at)}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-slate-300">
            <ShieldCheck className="h-3 w-3 text-emerald-300" />{" "}
            {page.signal_label}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-slate-300">
            <LockKeyhole className="h-3 w-3 text-emerald-300" /> Masked samples
          </span>
        </div>
      </section>

      <section className="mx-auto grid max-w-6xl gap-6 px-4 pb-14 lg:grid-cols-[1fr_360px]">
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-bold text-white">
              Sample opportunities
            </h2>
            <span className="text-[10px] text-slate-500">
              {items.length} shown · {page.count} total
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {items.map((item, index) => (
              <article
                key={`${item.masked_title}-${index}`}
                className="rounded-2xl border border-white/10 bg-white/[0.03] p-4"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
                      {page.trade_label}
                    </p>
                    <h3 className="mt-1 text-sm font-bold text-white">
                      {item.masked_title}
                    </h3>
                  </div>
                  <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[9px] font-semibold text-slate-400">
                    {item.signal_type === "authorized_work"
                      ? "Approved work"
                      : "Open opportunity"}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-slate-400">
                  <span className="flex items-center gap-1">
                    <MapPin className="h-3 w-3 text-slate-600" />
                    {item.neighborhood || "Local area"}
                  </span>
                  <span className="flex items-center gap-1">
                    <CalendarDays className="h-3 w-3 text-slate-600" />
                    {fmtDate(item.observed_at)}
                  </span>
                  <span>
                    ZIP {item.zip_prefix || "—"}
                  </span>
                  <span className="text-slate-500">
                    {item.value_band || "Value on request"}
                  </span>
                </div>
                <p className="mt-3 border-t border-white/5 pt-2 text-[9px] text-slate-600">
                  Exact address and owner details unlock with a pass.
                </p>
              </article>
            ))}
          </div>

          <div className="mt-6 rounded-2xl border border-white/10 bg-white/[0.02] p-4">
            <h2 className="text-sm font-bold text-white">
              Why contractors switch from shared lead marketplaces
            </h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              {[
                {
                  title: "One business per address",
                  text: "We do not resell the same opportunity to four other contractors.",
                },
                {
                  title: "Public weekly price",
                  text: "$120 for 7 days. No quote, no annual contract, no per-lead surprise.",
                },
                {
                  title: "Local public records",
                  text: "Opportunities are built from continuously refreshed public data.",
                },
              ].map((item) => (
                <div
                  key={item.title}
                  className="rounded-xl border border-white/5 bg-white/[0.02] p-3"
                >
                  <CheckCircle2 className="h-4 w-4 text-emerald-300" />
                  <p className="mt-2 text-[11px] font-bold text-slate-100">
                    {item.title}
                  </p>
                  <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
                    {item.text}
                  </p>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[9px] text-slate-600">
              Comparison based on Angi&apos;s public Pro Agreement and Help
              Center. See the sources in our{" "}
              <Link
                href="/en"
                className="text-slate-400 underline decoration-white/20 underline-offset-2"
              >
                claims register
              </Link>
              .
            </p>
          </div>
        </div>

        <aside className="lg:sticky lg:top-6 lg:self-start">
          <div className="rounded-2xl border border-emerald-400/20 bg-gradient-to-br from-emerald-500/[0.12] via-[#0d131a] to-[#0a0e13] p-5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-300">
              Full city list
            </p>
            <p className="mt-2 flex items-baseline gap-1">
              <span className="text-3xl font-black text-white">${price}</span>
              <span className="text-xs font-semibold text-slate-400">
                / week
              </span>
            </p>
            <p className="mt-1 text-[11px] text-slate-400">
              7-day pass. One contractor per address. Cancel anytime.
            </p>
            <ul className="mt-4 space-y-2 text-[11px] text-slate-300">
              {[
                "Full addresses and owner details",
                "Trade, date and project context",
                "Exclusive claim per address",
                "New opportunities refreshed continuously",
              ].map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-300" />
                  {item}
                </li>
              ))}
            </ul>
            <div className="mt-5">
              <ShowcaseCta
                token={token}
                city={page.city_slug}
                trade={page.trade_code}
                priceUsd={price}
            locale={locale}
              />
            </div>
            <p className="mt-3 text-center text-[9px] text-slate-600">
              Masked samples. No owner names or exact addresses on this page.
            </p>
          </div>
          <Link
            href="/en"
            className="mt-4 inline-flex items-center gap-1 text-[10px] font-semibold text-slate-500 hover:text-slate-300"
          >
            Back to Magic Leads <ArrowRight className="h-3 w-3" />
          </Link>
        </aside>
      </section>

      <div
        className="fixed inset-x-0 bottom-0 z-50 border-t border-white/10 bg-[#070b10]/95 px-4 py-3 backdrop-blur lg:hidden"
        style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))" }}
      >
        <div className="mx-auto flex max-w-6xl items-center gap-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-[11px] font-bold text-white">
              {page.count} active {page.trade_label.toLowerCase()} opportunities
            </p>
            <p className="text-[10px] text-slate-400">
              ${price}/week · one contractor per address
            </p>
          </div>
          <div className="w-[200px] shrink-0">
            <ShowcaseCta
              token={token}
              city={page.city_slug}
              trade={page.trade_code}
              priceUsd={price}
            locale={locale}
              compact
            />
          </div>
        </div>
      </div>
    </main>
  );
}
