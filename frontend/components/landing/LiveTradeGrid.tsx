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
import { ActivityTicker } from "@/components/landing/ActivityTicker";

const MIN_ACTIVE = 10;

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

const ICON_STYLE: Record<string, { bg: string; text: string; ring: string }> = {
  Roof: { bg: "bg-[#fff7ed]", text: "text-[#c2410c]", ring: "ring-[#fed7aa]" },
  Structure: { bg: "bg-[#eff6ff]", text: "text-[#1d4ed8]", ring: "ring-[#bfdbfe]" },
  Plumbing: { bg: "bg-[#ecfeff]", text: "text-[#0e7490]", ring: "ring-[#a5f3fc]" },
  Grass: { bg: "bg-[#f0fdf4]", text: "text-[#15803d]", ring: "ring-[#bbf7d0]" },
  Paint: { bg: "bg-[#f5f3ff]", text: "text-[#6d28d9]", ring: "ring-[#ddd6fe]" },
  Permit_Rejected: { bg: "bg-[#eef2ff]", text: "text-[#4338ca]", ring: "ring-[#c7d2fe]" },
  Heating: { bg: "bg-[#fff7ed]", text: "text-[#ea580c]", ring: "ring-[#fed7aa]" },
  Electrical: { bg: "bg-[#fefce8]", text: "text-[#a16207]", ring: "ring-[#fef08a]" },
  Elevator: { bg: "bg-[#f8fafc]", text: "text-[#475569]", ring: "ring-[#e2e8f0]" },
  Gas: { bg: "bg-[#fef2f2]", text: "text-[#b91c1c]", ring: "ring-[#fecaca]" },
  Rodent: { bg: "bg-[#f7fee7]", text: "text-[#4d7c0f]", ring: "ring-[#d9f99d]" },
  Mold: { bg: "bg-[#f0fdfa]", text: "text-[#0f766e]", ring: "ring-[#99f6e4]" },
  Lead: { bg: "bg-[#fff1f2]", text: "text-[#be123c]", ring: "ring-[#fecdd3]" },
  Unsanitary: { bg: "bg-[#fafaf9]", text: "text-[#57534e]", ring: "ring-[#e7e5e4]" },
  Door_Window: { bg: "bg-[#ecfeff]", text: "text-[#0891b2]", ring: "ring-[#a5f3fc]" },
  Debris: { bg: "bg-[#f8fafc]", text: "text-[#64748b]", ring: "ring-[#e2e8f0]" },
};

const ICON_STYLE_DARK: Record<string, { bg: string; text: string; ring: string }> = {
  Roof: { bg: "bg-[#fb923c]/15", text: "text-[#fdba74]", ring: "ring-[#fb923c]/25" },
  Structure: { bg: "bg-[#60a5fa]/15", text: "text-[#93c5fd]", ring: "ring-[#60a5fa]/25" },
  Plumbing: { bg: "bg-[#22d3ee]/15", text: "text-[#67e8f9]", ring: "ring-[#22d3ee]/25" },
  Grass: { bg: "bg-[#4ade80]/15", text: "text-[#86efac]", ring: "ring-[#4ade80]/25" },
  Paint: { bg: "bg-[#a78bfa]/15", text: "text-[#c4b5fd]", ring: "ring-[#a78bfa]/25" },
  Permit_Rejected: { bg: "bg-[#818cf8]/15", text: "text-[#a5b4fc]", ring: "ring-[#818cf8]/25" },
  Heating: { bg: "bg-[#fb923c]/15", text: "text-[#fdba74]", ring: "ring-[#fb923c]/25" },
  Electrical: { bg: "bg-[#facc15]/15", text: "text-[#fde047]", ring: "ring-[#facc15]/25" },
  Elevator: { bg: "bg-[#94a3b8]/15", text: "text-[#cbd5e1]", ring: "ring-[#94a3b8]/25" },
  Gas: { bg: "bg-[#f87171]/15", text: "text-[#fca5a5]", ring: "ring-[#f87171]/25" },
  Rodent: { bg: "bg-[#a3e635]/15", text: "text-[#bef264]", ring: "ring-[#a3e635]/25" },
  Mold: { bg: "bg-[#2dd4bf]/15", text: "text-[#5eead4]", ring: "ring-[#2dd4bf]/25" },
  Lead: { bg: "bg-[#fb7185]/15", text: "text-[#fda4af]", ring: "ring-[#fb7185]/25" },
  Unsanitary: { bg: "bg-[#a8a29e]/15", text: "text-[#d6d3d1]", ring: "ring-[#a8a29e]/25" },
  Door_Window: { bg: "bg-[#22d3ee]/15", text: "text-[#67e8f9]", ring: "ring-[#22d3ee]/25" },
  Debris: { bg: "bg-[#94a3b8]/15", text: "text-[#cbd5e1]", ring: "ring-[#94a3b8]/25" },
};

const CITIES = ["New York", "Boston", "Dallas", "Chicago"] as const;

export function LiveTradeGrid({
  categories,
  onCta,
  variant = "section",
}: {
  categories: string[];
  onCta: (trade?: string) => void;
  variant?: "section" | "hero";
}) {
  const { t } = useI18n();
  const dark = variant === "hero";
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

  const tradeLabels = useMemo(
    () => Object.fromEntries(DB_KEYS.map((key, index) => [key, categories[index] || key])),
    [categories]
  );

  // Critical display rule: never show a trade below the 10-opportunity floor.
  const visibleRows = useMemo(
    () => rows.filter((row) => row.count >= MIN_ACTIVE),
    [rows]
  );

  const maxCount = useMemo(
    () => Math.max(1, ...visibleRows.map((row) => row.count)),
    [visibleRows]
  );

  const topKey = visibleRows.length
    ? visibleRows.reduce((best, row) => (row.count > best.count ? row : best), visibleRows[0]).key
    : undefined;
  const activeKey =
    selected && visibleRows.some((row) => row.key === selected) ? selected : topKey;
  const activeRow = visibleRows.find((row) => row.key === activeKey);

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

  const visibleTotal = visibleRows.reduce((sum, row) => sum + row.count, 0);

  return (
    <section
      id="p1-grid"
      className={
        dark
          ? "relative scroll-mt-24"
          : "relative scroll-mt-24 overflow-hidden bg-[#f6f8fc] py-16 md:py-24"
      }
    >
      <div
        className={
          dark
            ? "pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(52,224,161,0.10),transparent_58%)]"
            : "pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(16,185,129,0.09),transparent_55%)]"
        }
      />
      {!dark && (
        <div className="pointer-events-none absolute inset-0 opacity-40" style={{ backgroundImage: "radial-gradient(#cbd5e1 1px, transparent 1px)", backgroundSize: "26px 26px" }} />
      )}

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6">
        {!dark && (
        <div className="mx-auto max-w-4xl text-center">
          <span className="eyebrow eyebrow-light mx-auto"><span className="dot" />{t("landing.p1Kicker")}</span>
          <h2 className="font-display mx-auto mt-5 max-w-3xl text-[1.95rem] font-black leading-[1.02] tracking-[-0.03em] text-[#0b1220] sm:text-[2.7rem] lg:text-[3.05rem]">
            {t("landing.p1Title")}
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-[14px] leading-relaxed text-[#54617a] sm:text-[15px]">{t("landing.p1Sub")}</p>

          <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#10b981]/25 bg-[#10b981]/[0.08] px-3.5 py-1.5 text-[10px] font-black uppercase tracking-[0.1em] text-[#0a8f65]">
              <Clock className="h-3.5 w-3.5" /> {t("landing.p1Exclusive")}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#dbe3ec] bg-white px-3.5 py-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-[#64748b]">
              <ShieldCheck className="h-3.5 w-3.5" /> {t("landing.p1NoAuction")}
            </span>
          </div>
        </div>
        )}

        {/* ZIP is the primary control: large, central, impossible to miss. */}
        <form
          onSubmit={submitZip}
          className={`mx-auto flex w-full items-center gap-2 rounded-2xl border p-2 transition ${
            dark
              ? "mt-0 max-w-3xl border-white/15 bg-white/[0.06] shadow-[0_30px_90px_-40px_rgba(0,0,0,0.9)] backdrop-blur-xl focus-within:border-[#34e0a1]/60 focus-within:shadow-[0_30px_90px_-35px_rgba(52,224,161,0.28)]"
              : "mt-8 max-w-2xl border-[#dfe6ef] bg-white shadow-[0_24px_60px_-34px_rgba(15,23,42,0.35)] focus-within:border-[#10b981]/55 focus-within:shadow-[0_24px_60px_-30px_rgba(16,185,129,0.35)]"
          }`}
        >
          <div className="flex min-w-0 flex-1 items-center gap-2">
          <MapPin className="ml-3 h-5 w-5 shrink-0 text-[#34e0a1]" />
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
            className={`h-12 min-w-0 flex-1 border-0 bg-transparent text-[14px] font-semibold focus:outline-none sm:text-[15px] ${
              dark
                ? "text-white placeholder:font-medium placeholder:text-white/35"
                : "text-[#0b1220] placeholder:font-medium placeholder:text-[#94a3b8]"
            }`}
          />
          </div>
          <button type="submit" data-track="p1_zip_submit" className="btn-mint h-12 shrink-0 px-4 text-[12px] uppercase tracking-[0.06em] sm:px-6">
            {t("landing.p1Search")}
          </button>
        </form>
        {zipError && (
          <p className={`mt-2 text-center text-[11px] font-semibold ${dark ? "text-[#fbbf24]" : "text-[#b45309]"}`}>
            {zipError}
          </p>
        )}
        {activeZip && (
          <div className="mt-3 flex justify-center">
            <button
              type="button"
              onClick={clearZip}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[10px] font-bold shadow-sm ${
                dark
                  ? "border-white/15 bg-white/[0.06] text-white/70 hover:border-[#34e0a1]/50"
                  : "border-[#dbe3ec] bg-white text-[#475569] hover:border-[#10b981]/40"
              }`}
            >
              ZIP {activeZip} <X className="h-3 w-3" />
            </button>
          </div>
        )}

        <div className="mx-auto mt-4 grid max-w-md grid-cols-2 gap-1.5 sm:flex sm:max-w-none sm:flex-wrap sm:justify-center">
          <button
            type="button"
            onClick={() => pickCity("")}
            data-track="p1_city_all"
            className={`col-span-2 inline-flex items-center justify-center gap-1.5 rounded-full border px-3.5 py-1.5 text-[11.5px] font-bold transition sm:col-span-1 sm:py-2 ${
              !city && !activeZip
                ? dark
                  ? "border-[#34e0a1] bg-[#34e0a1] text-[#04120d] shadow-[0_10px_30px_-12px_rgba(52,224,161,0.55)]"
                  : "border-[#0b1220] bg-[#0b1220] text-white shadow-sm"
                : dark
                  ? "border-white/10 bg-white/[0.04] text-white/65 hover:border-[#34e0a1]/50 hover:text-white"
                  : "border-[#dfe6ef] bg-white text-[#54617a] hover:border-[#10b981]/40 hover:text-[#0b1220]"
            }`}
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
                className={`inline-flex items-center justify-center gap-1.5 rounded-full border px-3.5 py-1.5 text-[11.5px] font-bold transition sm:py-2 ${
                  active
                    ? dark
                      ? "border-[#34e0a1] bg-[#34e0a1] text-[#04120d] shadow-[0_10px_30px_-12px_rgba(52,224,161,0.55)]"
                      : "border-[#0b1220] bg-[#0b1220] text-white shadow-sm"
                    : dark
                      ? "border-white/10 bg-white/[0.04] text-white/65 hover:border-[#34e0a1]/50 hover:text-white"
                      : "border-[#dfe6ef] bg-white text-[#54617a] hover:border-[#10b981]/40 hover:text-[#0b1220]"
                }`}
              >
                {option}
                {count > 0 && (
                  <span className={`rounded-full px-1.5 py-0.5 text-[9px] ${
                    active
                      ? dark
                        ? "bg-[#04120d]/10 text-[#04120d]/70"
                        : "bg-white/15 text-white/70"
                      : dark
                        ? "bg-white/10 text-white/50"
                        : "bg-[#f1f5f9] text-[#94a3b8]"
                  }`}>
                    {count.toLocaleString("en-US")}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <ActivityTicker labelsByKey={tradeLabels} />

        <div className="mt-4 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[10.5px] font-bold uppercase tracking-[0.13em]">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#10b981] opacity-50" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[#10b981]" />
          </span>
          <span className={dark ? "text-white" : "text-[#0b1220]"}>
            {loading
              ? t("landing.p1Loading")
              : error
                ? t("landing.p1Error")
                : `${(data?.total ?? 0).toLocaleString("en-US")} ${t("landing.p1Opportunities")} · ${regionLabel}`}
          </span>
          <span className={dark ? "text-white/40" : "text-[#94a3b8]"}>{t("landing.p1Last7")}</span>
        </div>
        {!loading && !error && visibleRows.length > 0 && (
          <p className={`mt-1.5 text-center text-[10px] ${dark ? "text-white/35" : "text-[#94a3b8]"}`}>
            {t("landing.p1MinNotice").replace("{n}", String(visibleRows.length))}
          </p>
        )}

        {error && (
          <div className={`mx-auto mt-4 flex max-w-2xl flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-2.5 text-[11px] ${
            dark
              ? "border-[#f59e0b]/30 bg-[#f59e0b]/10 text-[#fcd34d]"
              : "border-[#f59e0b]/25 bg-[#fffbeb] text-[#92702a]"
          }`}>
            <span>{t("landing.p1Error")}</span>
            <button type="button" onClick={() => setReload((value) => value + 1)} className={`font-bold underline underline-offset-2 ${dark ? "text-[#fbbf24]" : "text-[#b45309]"}`}>
              {t("landing.p1Retry")}
            </button>
          </div>
        )}

        {loading ? (
          <div className={`mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 ${dark ? "xl:grid-cols-5" : ""}`}>
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={`p1-skeleton-${index}`} className={`rounded-2xl border p-4 ${dark ? "border-white/10 bg-white/[0.04]" : "border-[#e8eef6] bg-white"}`}>
                <div className={`h-10 w-10 animate-pulse rounded-xl ${dark ? "bg-white/10" : "bg-[#eef2f7]"}`} />
                <div className={`mt-5 h-8 w-20 animate-pulse rounded ${dark ? "bg-white/10" : "bg-[#eef2f7]"}`} />
                <div className={`mt-2 h-3 w-28 animate-pulse rounded ${dark ? "bg-white/10" : "bg-[#eef2f7]"}`} />
                <div className={`mt-4 h-1 w-full animate-pulse rounded-full ${dark ? "bg-white/10" : "bg-[#eef2f7]"}`} />
              </div>
            ))}
          </div>
        ) : !error && visibleRows.length === 0 ? (
          <div className={`mx-auto mt-6 max-w-2xl rounded-2xl border p-8 text-center ${
            dark
              ? "border-white/10 bg-white/[0.04] shadow-[0_20px_50px_-35px_rgba(0,0,0,0.8)] backdrop-blur-xl"
              : "border-[#e2e8f0] bg-white shadow-[0_20px_50px_-35px_rgba(15,23,42,0.35)]"
          }`}>
            <span className={`mx-auto grid h-12 w-12 place-items-center rounded-2xl ${dark ? "bg-[#f59e0b]/15 text-[#fbbf24]" : "bg-[#fff7ed] text-[#c2410c]"}`}>
              <MapPin className="h-5 w-5" />
            </span>
            <p className={`mt-4 text-[15px] font-bold ${dark ? "text-white" : "text-[#0b1220]"}`}>{t("landing.p1NoResults")}</p>
            <p className={`mt-1.5 text-[12px] ${dark ? "text-white/50" : "text-[#64748b]"}`}>{t("landing.p1EmptyHint")}</p>
            <button type="button" onClick={clearZip} className="btn-mint mt-4 px-5 py-2.5 text-[11px] uppercase tracking-[0.06em]">
              {t("landing.p1ClearZip")}
            </button>
          </div>
        ) : (
          <div className={`mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 ${dark ? "lg:grid-cols-4 xl:grid-cols-5" : "lg:grid-cols-4"}`}>
            {visibleRows.map((row, index) => {
              const Icon = ICONS[row.key] ?? Wrench;
              const palette = (dark ? ICON_STYLE_DARK : ICON_STYLE)[row.key] ?? (dark ? ICON_STYLE_DARK : ICON_STYLE).Structure;
              const active = activeRow?.key === row.key;
              const barWidth = Math.max(7, Math.round((row.count / maxCount) * 100));
              return (
                <button
                  key={`${activeZip || city}-${row.key}`}
                  type="button"
                  onClick={() => setSelected(row.key)}
                  data-track={`p1_trade_${row.key.toLowerCase()}`}
                  style={{ animationDelay: `${index * 35}ms` }}
                  className={`p1-card-in group relative overflow-hidden rounded-2xl border text-left transition duration-300 hover:-translate-y-0.5 ${
                    dark ? "p-3.5" : "p-4"
                  } ${
                    active
                      ? dark
                        ? "border-[#34e0a1] bg-[#34e0a1] text-[#04120d] shadow-[0_28px_70px_-30px_rgba(52,224,161,0.55)]"
                        : "border-[#0b1220] bg-[#0b1220] text-white shadow-[0_24px_60px_-28px_rgba(15,23,42,0.65)]"
                      : dark
                        ? "border-white/10 bg-white/[0.035] text-white hover:border-[#34e0a1]/45 hover:bg-white/[0.06] hover:shadow-[0_24px_60px_-35px_rgba(0,0,0,0.8)]"
                        : "border-[#e2e8f0] bg-white hover:border-[#10b981]/45 hover:shadow-[0_20px_50px_-30px_rgba(15,23,42,0.4)]"
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <span className={`grid h-10 w-10 place-items-center rounded-xl ring-1 transition ${
                      active
                        ? dark
                          ? "bg-[#04120d]/10 text-[#04120d] ring-[#04120d]/15"
                          : "bg-[#34e0a1]/15 text-[#34e0a1] ring-[#34e0a1]/25"
                        : `${palette.bg} ${palette.text} ${palette.ring}`
                    }`}>
                      <Icon className="h-[18px] w-[18px]" />
                    </span>
                    <span className={`mt-1 h-1.5 w-1.5 rounded-full ${active ? (dark ? "bg-[#04120d]" : "bg-[#34e0a1]") : "bg-[#34e0a1]/70"}`} />
                  </div>
                  <p className={`mono-data mt-4 font-black leading-none tracking-[-0.04em] tabular-nums ${dark ? "text-[1.7rem]" : "text-[2rem]"} ${
                    active ? (dark ? "text-[#04120d]" : "text-white") : dark ? "text-white" : "text-[#0b1220]"
                  }`}>
                    {row.count.toLocaleString("en-US")}
                  </p>
                  <p className={`mt-1.5 font-bold leading-tight ${dark ? "text-[10.5px]" : "text-[11.5px]"} ${
                    active ? (dark ? "text-[#04120d]" : "text-white") : dark ? "text-white/75" : "text-[#0b1220]"
                  }`}>{row.label}</p>
                  <p className={`mt-0.5 text-[8.5px] font-bold uppercase tracking-[0.12em] ${
                    active ? (dark ? "text-[#04120d]/60" : "text-white/40") : dark ? "text-white/35" : "text-[#94a3b8]"
                  }`}>{t("landing.p1Active")}</p>
                  <div className={`mt-3 h-1 overflow-hidden rounded-full ${
                    active ? (dark ? "bg-[#04120d]/15" : "bg-white/10") : dark ? "bg-white/10" : "bg-[#f1f5f9]"
                  }`}>
                    <div className={`h-full rounded-full ${active ? (dark ? "bg-[#04120d]" : "bg-[#34e0a1]") : "bg-[#34e0a1]"}`} style={{ width: `${barWidth}%` }} />
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {!loading && !error && activeRow && (
          <div className={`relative mt-4 overflow-hidden rounded-2xl p-5 text-white sm:p-6 ${
            dark
              ? "border border-white/10 bg-white/[0.055] shadow-[0_30px_80px_-40px_rgba(0,0,0,0.9)] backdrop-blur-xl"
              : "bg-[#0b1220] shadow-[0_30px_80px_-40px_rgba(15,23,42,0.8)]"
          }`}>
            <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#34e0a1]/60 to-transparent" />
            <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-[9px] font-bold uppercase tracking-[0.14em] text-[#34e0a1]">{t("landing.p1Selected")}</p>
                <p className="mt-1.5 text-lg font-bold tracking-[-0.01em]">
                  {activeRow.label} <span className="text-white/30">·</span>{" "}
                  <span className="mono-data">{activeRow.count.toLocaleString("en-US")}</span>{" "}
                  <span className="text-[12px] font-medium text-white/45">{t("landing.p1Active")}</span>
                </p>
                <p className="mt-1 text-[10.5px] text-white/40">{regionLabel} · {t("landing.p1Last7")} · {visibleTotal.toLocaleString("en-US")} {t("landing.p1Opportunities")}</p>
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
        )}

        <p className={`mt-3 text-center text-[10px] leading-relaxed ${dark ? "text-white/35" : "text-[#94a3b8]"}`}>{t("landing.p1Note")}</p>
      </div>
    </section>
  );
}
