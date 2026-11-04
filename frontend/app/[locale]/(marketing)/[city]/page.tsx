import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, MapPin, Sparkles } from "lucide-react";

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ||
  "https://magic-leads-production.up.railway.app"
).replace(/\/$/, "");

type CityTrade = {
  trade_code: string;
  trade_slug: string;
  trade_label: string;
  item_count: number;
  page_path: string;
};

type CityPayload = {
  city: string;
  state: string;
  city_slug: string;
  built_at: string | null;
  trades: CityTrade[];
};

async function getCity(city: string): Promise<CityPayload | null> {
  try {
    const response = await fetch(
      `${API_URL}/api/showcase/${encodeURIComponent(city)}`,
      { next: { revalidate: 300 } }
    );
    if (!response.ok) return null;
    return (await response.json()) as CityPayload;
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; city: string }>;
}): Promise<Metadata> {
  const { city } = await params;
  const data = await getCity(city);
  if (!data) return { title: "Magic Leads" };
  return {
    title: `Active opportunities in ${data.city} | Magic Leads`,
    description: `See this week's active contractor opportunities in ${data.city}.`,
  };
}

export default async function CityPage({
  params,
}: {
  params: Promise<{ locale: string; city: string }>;
}) {
  const { locale, city } = await params;
  const data = await getCity(city);
  if (!data) notFound();

  return (
    <main className="min-h-screen bg-[#070b10] pb-24 text-slate-200">
      <section className="mx-auto max-w-5xl px-4 pb-8 pt-10 sm:pt-16">
        <div className="flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-emerald-300">
          <Sparkles className="h-3.5 w-3.5" />
          Magic Leads · Local opportunity brief
        </div>
        <h1 className="mt-4 text-3xl font-black tracking-tight text-white sm:text-5xl">
          Active opportunities in {data.city}
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-400 sm:text-base">
          Choose your trade to see this week&apos;s active jobs. Addresses are
          masked until you unlock the full brief.
        </p>
        <div className="mt-4 flex items-center gap-2 text-xs font-semibold text-slate-500">
          <MapPin className="h-4 w-4 text-emerald-400" />
          {data.city}, {data.state}
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-4">
        <div className="grid gap-3 sm:grid-cols-2">
          {data.trades.map((trade) => (
            <Link
              key={trade.trade_slug}
              href={`/${locale}/${data.city_slug}/${trade.trade_slug}`}
              className="group flex items-center justify-between rounded-2xl border border-white/10 bg-white/[0.03] p-5 transition hover:border-emerald-400/40 hover:bg-emerald-400/[0.06]"
            >
              <div>
                <div className="text-base font-bold text-white">
                  {trade.trade_label}
                </div>
                <div className="mt-1 text-xs font-semibold text-slate-500">
                  {trade.item_count.toLocaleString("en-US")} active
                </div>
              </div>
              <ArrowRight className="h-5 w-5 text-slate-600 transition group-hover:text-emerald-300" />
            </Link>
          ))}
        </div>
      </section>
    </main>
  );
}
