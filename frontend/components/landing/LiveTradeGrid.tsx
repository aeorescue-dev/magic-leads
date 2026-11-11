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

export const DB_KEYS = [
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

const CITIES = ["New York", "Boston", "Dallas", "Chicago"] as const;

export function LiveTradeGrid({
  categories,
  onCta,
  city: controlledCity,
  activeZip: controlledZip,
  showControls = true,
  showTicker = true,
  featuredLimit,
  preview = false,
}: {
  categories: string[];
  onCta: (trade?: string) => void;
  city?: string;
  activeZip?: string;
  showControls?: boolean;
  showTicker?: boolean;
  featuredLimit?: number;
  preview?: boolean;
}) {
  const { t } = useI18n();
  const [cityState, setCityState] = useState<string>("New York");
  const [zipInput, setZipInput] = useState("");
  const [zipState, setZipState] = useState("");
  const city = controlledCity ?? cityState;
  const activeZip = controlledZip ?? zipState;
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

  const displayedRows = useMemo(
    () => (featuredLimit ? visibleRows.slice(0, featuredLimit) : visibleRows),
    [visibleRows, featuredLimit]
  );

  const maxCount = useMemo(
    () => Math.max(1, ...visibleRows.map((row) => row.count)),
    [visibleRows]
  );

  const topKey = displayedRows.length
    ? displayedRows.reduce((best, row) => (row.count > best.count ? row : best), displayedRows[0]).key
    : undefined;
  const activeKey =
    selected && displayedRows.some((row) => row.key === selected) ? selected : topKey;
  const activeRow = displayedRows.find((row) => row.key === activeKey);

  const regionLabel = activeZip ? `ZIP ${activeZip}` : city || t("landing.p1AllCities");
  const cityCount = (label: string) => data?.cities?.find((c) => c.label === label)?.count ?? 0;

  const pickCity = (next: string) => {
    setCityState(next);
    setZipState("");
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
    setCityState("");
    setZipState(digits);
    setZipInput("");
    setSelected(null);
  };

  const clearZip = () => {
    setZipState("");
    setZipInput("");
    setZipError("");
    setCityState("New York");
    setSelected(null);
  };

  const visibleTotal = visibleRows.reduce((sum, row) => sum + row.count, 0);

  return (
    <section
      id="p1-grid"
      className={
        preview
          ? "relative w-full"
          : "relative scroll-mt-24 overflow-hidden bg-[#fbfaf7] py-20 md:py-28"
      }
    >
      {!preview && (
        <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(ellipse_at_top,rgba(16,185,129,0.07),transparent_65%)]" />
      )}

      <div className={preview ? "relative w-full" : "relative mx-auto max-w-7xl px-4 sm:px-6"}>
        <div className="mx-auto max-w-4xl text-center">
          <span className="eyebrow eyebrow-light mx-auto"><span className="dot" />{t("landing.p1Kicker")}</span>
          <h2 className={`font-display mx-auto max-w-3xl font-black leading-[1.02] tracking-[-0.03em] text-[#0b1220] ${
            preview ? "mt-2 text-[1.3rem] sm:text-[1.45rem]" : "mt-5 text-[1.95rem] sm:text-[2.7rem] lg:text-[3.05rem]"
          }`}>
            {t("landing.p1Title")}
          </h2>
          <p className={`mx-auto max-w-xl leading-relaxed text-[#54617a] ${
            preview ? "mt-2 text-[10.5px]" : "mt-4 text-[14px] sm:text-[15px]"
          }`}>{t("landing.p1Sub")}</p>

          <div className={`flex flex-wrap items-center justify-center ${preview ? "mt-2.5 gap-1.5" : "mt-5 gap-2"}`}>
            <span className={`inline-flex items-center gap-1 rounded-full border border-[#10b981]/25 bg-[#10b981]/[0.08] font-black uppercase tracking-[0.1em] text-[#0a8f65] ${
              preview ? "px-2.5 py-1 text-[8px]" : "px-3.5 py-1.5 text-[10px]"
            }`}>
              <Clock className={preview ? "h-2.5 w-2.5" : "h-3.5 w-3.5"} /> {t("landing.p1Exclusive")}
            </span>
            <span className={`inline-flex items-center gap-1 rounded-full border border-[#dbe3ec] bg-white font-bold uppercase tracking-[0.1em] text-[#64748b] ${
              preview ? "px-2.5 py-1 text-[8px]" : "px-3.5 py-1.5 text-[10px]"
            }`}>
              <ShieldCheck className={preview ? "h-2.5 w-2.5" : "h-3.5 w-3.5"} /> {t("landing.p1NoAuction")}
            </span>
          </div>
        </div>

        {showControls && (
          <>
        {/* ZIP is the primary control: large, central, impossible to miss. */}
        <form onSubmit={submitZip} className="mx-auto mt-8 flex w-full max-w-2xl items-center gap-2 rounded-2xl border border-[#dfe6ef] bg-white p-2 shadow-[0_24px_60px_-34px_rgba(15,23,42,0.35)] transition focus-within:border-[#10b981]/55 focus-within:shadow-[0_24px_60px_-30px_rgba(16,185,129,0.35)]">
          <MapPin className="ml-3 h-5 w-5 shrink-0 text-[#10b981]" />
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
            className="h-12 min-w-0 flex-1 border-0 bg-transparent text-[15px] font-semibold text-[#0b1220] placeholder:font-medium placeholder:text-[#94a3b8] focus:outline-none"
          />
          <button type="submit" data-track="p1_zip_submit" className="btn-mint h-12 shrink-0 px-6 text-[12px] uppercase tracking-[0.06em]">
            {t("landing.p1Search")}
          </button>
        </form>
        {zipError && <p className="mt-2 text-center text-[11px] font-semibold text-[#b45309]">{zipError}</p>}
        {activeZip && (
          <div className="mt-3 flex justify-center">
            <button
              type="button"
              onClick={clearZip}
              className="inline-flex items-center gap-1.5 rounded-full border border-[#dbe3ec] bg-white px-3 py-1.5 text-[10px] font-bold text-[#475569] shadow-sm hover:border-[#10b981]/40"
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
            className={`col-span-2 inline-flex items-center justify-center gap-1.5 rounded-full border px-3.5 py-2 text-[11.5px] font-bold transition sm:col-span-1 ${!city && !activeZip ? "border-[#0b1220] bg-[#0b1220] text-white shadow-sm" : "border-[#dfe6ef] bg-white text-[#54617a] hover:border-[#10b981]/40 hover:text-[#0b1220]"}`}
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
                className={`inline-flex items-center justify-center gap-1.5 rounded-full border px-3.5 py-2 text-[11.5px] font-bold transition ${active ? "border-[#0b1220] bg-[#0b1220] text-white shadow-sm" : "border-[#dfe6ef] bg-white text-[#54617a] hover:border-[#10b981]/40 hover:text-[#0b1220]"}`}
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
          </>
        )}

        {showTicker && <ActivityTicker labelsByKey={tradeLabels} />}

        <div className={`flex flex-wrap items-center justify-center gap-x-2 gap-y-1 font-bold uppercase tracking-[0.13em] ${
          preview ? "mt-2.5 text-[8px]" : "mt-6 text-[10.5px]"
        }`}>
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#10b981] opacity-50" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[#10b981]" />
          </span>
          <span className="text-[#0b1220]">
            {loading
              ? t("landing.p1Loading")
              : error
                ? t("landing.p1Error")
                : `${(data?.total ?? 0).toLocaleString("en-US")} ${t("landing.p1Opportunities")} · ${regionLabel}`}
          </span>
          <span className="text-[#94a3b8]">{t("landing.p1Last7")}</span>
        </div>
        {!loading && !error && visibleRows.length > 0 && (
          <p className={`text-center text-[#94a3b8] ${preview ? "mt-1 text-[8px]" : "mt-1.5 text-[10px]"}`}>
            {featuredLimit && visibleRows.length > featuredLimit
              ? t("landing.p1MinNoticeLimited")
                  .replace("{n}", String(displayedRows.length))
                  .replace("{total}", String(visibleRows.length))
              : t("landing.p1MinNotice").replace("{n}", String(displayedRows.length))}
          </p>
        )}

        {error && (
          <div className="mx-auto mt-4 flex max-w-2xl flex-wrap items-center justify-between gap-2 rounded-xl border border-[#f59e0b]/25 bg-[#fffbeb] px-4 py-2.5 text-[11px] text-[#92702a]">
            <span>{t("landing.p1Error")}</span>
            <button type="button" onClick={() => setReload((value) => value + 1)} className="font-bold text-[#b45309] underline underline-offset-2">
              {t("landing.p1Retry")}
            </button>
          </div>
        )}

        {loading ? (
          <div className={preview ? "mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-2.5" : "mt-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4"}>
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={`p1-skeleton-${index}`} className="rounded-2xl border border-[#e8eef6] bg-white p-4">
                <div className="h-10 w-10 animate-pulse rounded-xl bg-[#eef2f7]" />
                <div className="mt-5 h-8 w-20 animate-pulse rounded bg-[#eef2f7]" />
                <div className="mt-2 h-3 w-28 animate-pulse rounded bg-[#eef2f7]" />
                <div className="mt-4 h-1 w-full animate-pulse rounded-full bg-[#eef2f7]" />
              </div>
            ))}
          </div>
        ) : !error && visibleRows.length === 0 ? (
          <div className="mx-auto mt-8 max-w-2xl rounded-2xl border border-[#e2e8f0] bg-white p-8 text-center shadow-[0_20px_50px_-35px_rgba(15,23,42,0.35)]">
            <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-[#fff7ed] text-[#c2410c]">
              <MapPin className="h-5 w-5" />
            </span>
            <p className="mt-4 text-[15px] font-bold text-[#0b1220]">{t("landing.p1NoResults")}</p>
            <p className="mt-1.5 text-[12px] text-[#64748b]">{t("landing.p1EmptyHint")}</p>
            <button type="button" onClick={clearZip} className="btn-mint mt-4 px-5 py-2.5 text-[11px] uppercase tracking-[0.06em]">
              {t("landing.p1ClearZip")}
            </button>
          </div>
        ) : (
          <div className={preview ? "mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-2.5" : "mt-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4"}>
            {displayedRows.map((row, index) => {
              const Icon = ICONS[row.key] ?? Wrench;
              const palette = ICON_STYLE[row.key] ?? ICON_STYLE.Structure;
              const active = activeRow?.key === row.key;
              const barWidth = Math.max(7, Math.round((row.count / maxCount) * 100));
              return (
                <button
                  key={`${activeZip || city}-${row.key}`}
                  type="button"
                  onClick={() => setSelected(row.key)}
                  data-track={`p1_trade_${row.key.toLowerCase()}`}
                  style={{ animationDelay: `${index * 35}ms` }}
                  className={`p1-card-in group relative overflow-hidden border text-left transition duration-300 hover:-translate-y-0.5 ${
                    preview ? "rounded-xl p-3.5" : "rounded-2xl p-5"
                  } ${
                    active
                      ? "border-[#10b981] bg-[#10b981] text-[#04120d] shadow-[0_24px_60px_-30px_rgba(16,185,129,0.55)]"
                      : "border-[#e7e3d9] bg-white shadow-[0_14px_40px_-32px_rgba(15,23,42,0.35)] hover:border-[#10b981]/45 hover:shadow-[0_22px_55px_-32px_rgba(15,23,42,0.3)]"
                  } ${preview && index >= 4 ? "hidden sm:block" : ""}`}
                >
                  <div className="flex items-start justify-between">
                    <span className={`grid place-items-center ring-1 transition ${preview ? "h-8 w-8 rounded-lg" : "h-10 w-10 rounded-xl"} ${active ? "bg-[#04120d]/10 text-[#04120d] ring-[#04120d]/15" : `${palette.bg} ${palette.text} ${palette.ring}`}`}>
                      <Icon className={preview ? "h-3.5 w-3.5" : "h-[18px] w-[18px]"} />
                    </span>
                    <span className={`mt-1 rounded-full ${preview ? "h-1 w-1" : "h-1.5 w-1.5"} ${active ? "bg-[#04120d]" : "bg-[#10b981]/70"}`} />
                  </div>
                  <p className={`mono-data font-black leading-none tracking-[-0.04em] tabular-nums ${preview ? "mt-2 text-[1.45rem]" : "mt-4 text-[2rem]"} ${active ? "text-[#04120d]" : "text-[#0b1220]"}`}>
                    {row.count.toLocaleString("en-US")}
                  </p>
                  <p className={`font-bold leading-tight ${preview ? "mt-1.5 text-[10px]" : "mt-1.5 text-[11.5px]"} ${active ? "text-[#04120d]" : "text-[#0b1220]"}`}>{row.label}</p>
                  <p className={`mt-0.5 font-bold uppercase tracking-[0.12em] ${preview ? "text-[6.5px]" : "text-[8.5px]"} ${active ? "text-[#04120d]/60" : "text-[#94a3b8]"}`}>{t("landing.p1Active")}</p>
                  <div className={`overflow-hidden rounded-full ${preview ? "mt-2 h-1" : "mt-3 h-1"} ${active ? "bg-[#04120d]/15" : "bg-[#f1f5f9]"}`}>
                    <div className={`h-full rounded-full ${active ? "bg-[#04120d]" : "bg-[#10b981]"}`} style={{ width: `${barWidth}%` }} />
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {!loading && !error && activeRow && (
          <div className={`relative overflow-hidden rounded-2xl bg-[#0b1220] text-white shadow-[0_30px_80px_-40px_rgba(15,23,42,0.8)] ${
            preview ? "mt-3 p-3.5" : "mt-5 p-5 sm:p-6"
          }`}>
            <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#34e0a1]/60 to-transparent" />
            <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className={`font-bold uppercase tracking-[0.14em] text-[#34e0a1] ${preview ? "text-[7px]" : "text-[9px]"}`}>{t("landing.p1Selected")}</p>
                <p className={`font-bold tracking-[-0.01em] ${preview ? "mt-1 text-[13px]" : "mt-1.5 text-lg"}`}>
                  {activeRow.label} <span className="text-white/30">·</span>{" "}
                  <span className="mono-data">{activeRow.count.toLocaleString("en-US")}</span>{" "}
                  <span className={`font-medium text-white/45 ${preview ? "text-[9px]" : "text-[12px]"}`}>{t("landing.p1Active")}</span>
                </p>
                <p className={`text-white/40 ${preview ? "mt-1 text-[8.5px]" : "mt-1 text-[10.5px]"}`}>{regionLabel} · {t("landing.p1Last7")} · {visibleTotal.toLocaleString("en-US")} {t("landing.p1Opportunities")}</p>
                <div className={`flex flex-wrap gap-x-5 gap-y-1.5 font-bold uppercase tracking-[0.1em] text-white/55 ${preview ? "hidden" : "mt-3 text-[10px]"}`}>
                  <span className="inline-flex items-center gap-1.5"><Clock className="h-3.5 w-3.5 text-[#34e0a1]" /> {t("landing.p1Exclusive")}</span>
                  <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5 text-[#34e0a1]" /> {t("landing.p1NoAuction")}</span>
                </div>
              </div>
              <button type="button" onClick={() => onCta(activeRow.label)} data-track="p1_trade_cta" className={`btn-mint shrink-0 uppercase tracking-[0.06em] ${preview ? "px-3 py-2.5 text-[9px]" : "px-6 py-3 text-[12px]"}`}>
                {t("landing.p1Cta")}
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        <p className={preview ? "hidden" : "mt-3 text-center text-[10px] leading-relaxed text-[#94a3b8]"}>{t("landing.p1Note")}</p>
      </div>
    </section>
  );
}
