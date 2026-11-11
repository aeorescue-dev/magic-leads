"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  ArrowRight,
  ArrowUpDown,
  Bug,
  Building2,
  Clock,
  CloudFog,
  DoorOpen,
  FileCheck,
  Flame,
  Fuel,
  Home,
  Leaf,
  MapPin,
  Paintbrush,
  ShieldAlert,
  ShieldCheck,
  Trash,
  Trash2,
  Wrench,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { fetchTradeGrid, type TradeGridResponse } from "@/lib/api-client";

const DB_KEYS = [
  "Roof",
  "Structure",
  "Plumbing",
  "Grass",
  "Paint",
  "Permit_Rejected",
  "Heating",
  "Electrical",
  "Elevator",
  "Gas",
  "Rodent",
  "Mold",
  "Lead",
  "Unsanitary",
  "Door_Window",
  "Debris",
] as const;

const ICONS: Record<string, LucideIcon> = {
  Roof: Home,
  Structure: Building2,
  Plumbing: Wrench,
  Grass: Leaf,
  Paint: Paintbrush,
  Permit_Rejected: FileCheck,
  Heating: Flame,
  Electrical: Zap,
  Elevator: ArrowUpDown,
  Gas: Fuel,
  Rodent: Bug,
  Mold: CloudFog,
  Lead: ShieldAlert,
  Unsanitary: Trash2,
  Door_Window: DoorOpen,
  Debris: Trash,
};

const CITIES = ["New York", "Boston", "Dallas", "Chicago"] as const;

export function LiveTradeGrid({
  categories,
  onCta,
}: {
  categories: string[];
  onCta: (trade?: string) => void;
}) {
  const { t } = useI18n();
  const [city, setCity] = useState<string>("New York");
  const [zipInput, setZipInput] = useState("");
  const [activeZip, setActiveZip] = useState("");
  const [zipError, setZipError] = useState("");
  const [data, setData] = useState<TradeGridResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const requestRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const id = ++requestRef.current;
    setLoading(true);
    setError(false);
    fetchTradeGrid({ city: activeZip ? undefined : city || undefined, zip: activeZip || undefined })
      .then((res) => {
        if (cancelled || id !== requestRef.current) return;
        setData(res);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled || id !== requestRef.current) return;
        setError(true);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [city, activeZip, reload]);

  const rows = useMemo(
    () =>
      DB_KEYS.map((key, index) => ({
        key,
        label: categories[index] || key,
        count: data?.trades?.[key] ?? 0,
      })),
    [categories, data]
  );

  const visibleRows = useMemo(() => {
    if (!activeZip || !data) return rows;
    return rows.filter((row) => row.count > 0);
  }, [activeZip, data, rows]);

  const topKey = useMemo(
    () => visibleRows.reduce((best, row) => (row.count > best.count ? row : best), visibleRows[0])?.key,
    [visibleRows]
  );
  const activeKey =
    selected && visibleRows.some((row) => row.key === selected) ? selected : topKey;
  const activeRow = visibleRows.find((row) => row.key === activeKey) ?? visibleRows[0] ?? rows[0];
  const regionLabel = activeZip ? `ZIP ${activeZip}` : city || t("landing.p1AllCities");
  const cityCount = (label: string) => data?.cities?.find((c) => c.label === label)?.count ?? 0;

  const pickCity = (next: string) => {
    setCity(next);
    setActiveZip("");
    setZipInput("");
    setZipError("");
    setSelected(null);
  };

  const submitZip = (event: FormEvent) => {
    event.preventDefault();
    const digits = zipInput.replace(/\D/g, "").slice(0, 5);
    if (digits.length !== 5) {
      setZipError(t("landing.p1ZipInvalid"));
      return;
    }
    setZipError("");
    setCity("");
    setActiveZip(digits);
    setZipInput("");
    setSelected(null);
  };

  const clearZip = () => {
    setActiveZip("");
    setZipInput("");
    setZipError("");
    setCity("New York");
    setSelected(null);
  };

  return (
    <section id="p1-grid" className="scroll-mt-24 bg-white py-16 md:py-24">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <div className="flex flex-col gap-7 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-2xl">
            <span className="eyebrow eyebrow-light"><span className="dot" />{t("landing.p1Kicker")}</span>
            <h2 className="font-display mt-5 text-[2.1rem] font-black leading-[0.98] tracking-[-0.03em] text-[#0b1220] sm:text-5xl">
              {t("landing.p1Title")}
            </h2>
            <p className="mt-5 text-[15px] leading-relaxed text-[#54617a] sm:text-base">{t("landing.p1Sub")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#10b981]/20 bg-[#10b981]/[0.06] px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-[#0a8f65]">
              <Clock className="h-3.5 w-3.5" /> {t("landing.p1Exclusive")}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#e2e8f0] bg-white px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-[#64748b]">
              <ShieldCheck className="h-3.5 w-3.5" /> {t("landing.p1NoAuction")}
            </span>
          </div>
        </div>

        {/* Location controls */}
        <div className="mt-8 rounded-2xl border border-[#e6ebf2] bg-white p-3 shadow-[0_18px_50px_-38px_rgba(15,23,42,0.35)]">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="grid grid-cols-2 gap-1.5 sm:flex sm:flex-wrap">
              <button
                type="button"
                onClick={() => pickCity("")}
                data-track="p1_city_all"
                className={`col-span-2 inline-flex items-center justify-center rounded-xl px-3.5 py-2 text-[11.5px] font-bold transition sm:col-span-1 ${!city && !activeZip ? "bg-[#0b1220] text-white" : "text-[#54617a] hover:bg-[#f1f5f9]"}`}
              >
                {t("landing.p1AllCities")}
              </button>
              {CITIES.map((option) => {
                const active = !activeZip && city === option;
                const count = cityCount(option);
                return (
                  <button
                    key={option}
                    type="button"
                    onClick={() => pickCity(option)}
                    data-track={`p1_city_${option.toLowerCase().replace(/\s+/g, "_")}`}
                    className={`inline-flex items-center justify-center gap-1.5 rounded-xl px-3.5 py-2 text-[11.5px] font-bold transition ${active ? "bg-[#0b1220] text-white" : "text-[#54617a] hover:bg-[#f1f5f9]"}`}
                  >
                    {option}
                    {count > 0 && (
                      <span className={`rounded-full px-1.5 py-0.5 text-[9px] ${active ? "bg-white/15 text-white/70" : "bg-[#f1f5f9] text-[#94a3b8]"}`}>
                        {count.toLocaleString("en-US")}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            <form onSubmit={submitZip} className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <MapPin className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#94a3b8]" />
                <input
                  value={zipInput}
                  onChange={(event) => {
                    setZipInput(event.target.value.replace(/\D/g, "").slice(0, 5));
                    setZipError("");
                  }}
                  inputMode="numeric"
                  maxLength={5}
                  placeholder={t("landing.p1ZipPlaceholder")}
                  aria-label={t("landing.p1ZipPlaceholder")}
                  className="h-10 w-36 rounded-xl border border-[#e2e8f0] bg-white pl-9 pr-3 text-[12.5px] font-semibold text-[#0b1220] placeholder:text-[#94a3b8] focus:border-[#10b981]/50 focus:outline-none focus:ring-2 focus:ring-[#10b981]/15"
                />
              </div>
              <button type="submit" data-track="p1_zip_submit" className="btn-mint h-10 px-4 text-[11.5px]">
                {t("landing.p1Update")}
              </button>
              {activeZip && (
                <button
                  type="button"
                  onClick={clearZip}
                  aria-label={t("landing.p1ClearZip")}
                  className="inline-flex items-center gap-1 rounded-lg border border-[#e2e8f0] px-2.5 py-2 text-[10px] font-bold text-[#64748b] hover:bg-[#f8fafc]"
                >
                  ZIP {activeZip} <X className="h-3 w-3" />
                </button>
              )}
            </form>
          </div>
          {zipError && <p className="mt-2 pl-1 text-[11px] font-semibold text-[#b45309]">{zipError}</p>}
        </div>

        {/* Totals */}
        <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
          <p className="text-[10.5px] font-bold uppercase tracking-[0.13em] text-[#64748b]">
            {loading ? t("landing.p1Loading") : error ? t("landing.p1Error") : `${(data?.total ?? 0).toLocaleString("en-US")} ${t("landing.p1Opportunities")} · ${regionLabel}`}
          </p>
          <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#94a3b8]">
            {t("landing.p1Last7")}
          </p>
        </div>

        {error && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#f59e0b]/25 bg-[#fff7ed] px-4 py-2.5 text-[11px] text-[#92702a]">
            <span>{t("landing.p1Error")}</span>
            <button type="button" onClick={() => setReload((value) => value + 1)} className="font-bold text-[#b45309] underline underline-offset-2">
              {t("landing.p1Retry")}
            </button>
          </div>
        )}

        {!loading && !error && data && data.total === 0 && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#e2e8f0] bg-[#f8fafc] px-4 py-3 text-[11.5px] text-[#64748b]">
            <span>{t("landing.p1NoResults")}</span>
            <button type="button" onClick={clearZip} className="font-bold text-[#0a8f65]">
              {t("landing.p1ClearZip")}
            </button>
          </div>
        )}

        {/* Trade grid */}
        <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
          {loading
            ? Array.from({ length: 16 }).map((_, index) => (
                <div key={`p1-skeleton-${index}`} className="rounded-2xl border border-[#eef2f7] bg-white p-4">
                  <div className="h-9 w-9 animate-pulse rounded-xl bg-[#f1f5f9]" />
                  <div className="mt-4 h-7 w-16 animate-pulse rounded bg-[#f1f5f9]" />
                  <div className="mt-2 h-3 w-24 animate-pulse rounded bg-[#f1f5f9]" />
                </div>
              ))
            : visibleRows.map((row) => {
                const Icon = ICONS[row.key] ?? Wrench;
                const active = activeKey === row.key;
                const countLabel = data ? row.count.toLocaleString("en-US") : "—";
                return (
                  <button
                    key={row.key}
                    type="button"
                    onClick={() => setSelected(row.key)}
                    data-track={`p1_trade_${row.key.toLowerCase()}`}
                    className={`group relative rounded-2xl border p-4 text-left transition ${
                      active
                        ? "border-[#10b981]/55 bg-[#f0fdf8] shadow-[0_14px_36px_-26px_rgba(16,185,129,0.45)]"
                        : "border-[#e6ebf2] bg-white hover:border-[#10b981]/35 hover:shadow-[0_14px_36px_-30px_rgba(15,23,42,0.35)]"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className={`grid h-9 w-9 place-items-center rounded-xl transition ${active ? "bg-[#10b981]/10 text-[#0a8f65]" : "bg-[#f1f5f9] text-[#64748b] group-hover:bg-[#e8f9ef] group-hover:text-[#0a8f65]"}`}>
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className={`h-1.5 w-1.5 rounded-full ${row.count > 0 ? "bg-[#10b981]/55" : "bg-[#cbd5e1]"}`} />
                    </div>
                    <p className={`mono-data mt-3 text-2xl font-black tracking-[-0.03em] ${row.count > 0 || !data ? "text-[#0b1220]" : "text-[#94a3b8]"}`}>
                      {countLabel}
                    </p>
                    <p className="mt-0.5 text-[11.5px] font-bold leading-tight text-[#0b1220]">{row.label}</p>
                    <p className="mt-1 text-[8.5px] font-bold uppercase tracking-[0.1em] text-[#94a3b8]">
                      {t("landing.p1Active")}
                    </p>
                  </button>
                );
              })}
        </div>

        {/* Exclusive differentiator */}
        <div className="mt-5 overflow-hidden rounded-2xl bg-[#0b1220] p-5 text-white sm:p-6">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-[9px] font-bold uppercase tracking-[0.14em] text-[#34e0a1]">{t("landing.p1Selected")}</p>
              <p className="mt-1.5 text-lg font-bold tracking-[-0.01em]">
                {activeRow.label} <span className="text-white/30">·</span>{" "}
                <span className="mono-data">{data ? activeRow.count.toLocaleString("en-US") : "—"}</span>{" "}
                <span className="text-[12px] font-medium text-white/45">{t("landing.p1Active")}</span>
              </p>
              <p className="mt-1 text-[10.5px] text-white/40">{regionLabel} · {t("landing.p1Last7")}</p>
              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-white/55">
                <span className="inline-flex items-center gap-1.5"><Clock className="h-3.5 w-3.5 text-[#34e0a1]" /> {t("landing.p1Exclusive")}</span>
                <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5 text-[#34e0a1]" /> {t("landing.p1NoAuction")}</span>
              </div>
            </div>
            <button type="button" onClick={() => onCta(activeRow.label)} data-track="p1_trade_cta" className="btn-mint shrink-0 px-6 py-3 text-[12px] uppercase tracking-[0.06em]">
              {t("landing.p1Cta")}
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>

        <p className="mt-3 text-[10px] leading-relaxed text-[#94a3b8]">{t("landing.p1Note")}</p>
      </div>
    </section>
  );
}
