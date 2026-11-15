"use client";

import { useEffect, useMemo, useState } from "react";
import { Crosshair, Map as MapIcon, List as ListIcon } from "lucide-react";

import { useI18n } from "@/lib/i18n";

import { CityMap } from "./CityMap";
import { NeighborhoodList, type NeighborhoodRow } from "./NeighborhoodList";
import {
  CITY_META,
  CITY_ORDER,
  buildNeighborhoods,
  distanceMiles,
} from "./neighborhoods";
import { SNAPSHOT, nicheLabel } from "./data";

type GeoState = "idle" | "loading" | "denied";

export function OpportunitiesMap() {
  const { t } = useI18n();

  const [city, setCity] = useState<string>("Boston");
  const [niche, setNiche] = useState<string>("all");
  const [activeName, setActiveName] = useState<string | null>(null);
  const [sort, setSort] = useState<"leads" | "nearest">("leads");
  const [user, setUser] = useState<{ lat: number; lng: number } | null>(null);
  const [geoState, setGeoState] = useState<GeoState>("idle");
  const [applied, setApplied] = useState<string | null>(null);
  const [mobileView, setMobileView] = useState<"map" | "list">("map");

  const data = SNAPSHOT.cities[city];
  const meta = CITY_META[city] ?? CITY_META.Boston;

  const niches = useMemo(
    () => (data ? data.niches.slice(0, 8) : []),
    [data]
  );

  const neighborhoods = useMemo(
    () => (data ? buildNeighborhoods(city, data.zones, niche) : []),
    [city, data, niche]
  );

  const rows = useMemo<NeighborhoodRow[]>(() => {
    const withDistance = neighborhoods.map((item) => ({
      item,
      distance: user
        ? distanceMiles(user.lat, user.lng, item.lat, item.lng)
        : null,
    }));
    if (sort === "nearest" && user) {
      withDistance.sort(
        (a, b) => (a.distance ?? Infinity) - (b.distance ?? Infinity)
      );
    }
    return withDistance;
  }, [neighborhoods, sort, user]);

  const total = neighborhoods.reduce((sum, item) => sum + item.count, 0);
  const active = neighborhoods.find((item) => item.name === activeName) ?? null;

  useEffect(() => {
    if (!applied) return;
    const timer = setTimeout(() => setApplied(null), 4200);
    return () => clearTimeout(timer);
  }, [applied]);

  const requestLocation = () => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setGeoState("denied");
      return;
    }
    setGeoState("loading");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setUser({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        });
        setGeoState("idle");
        setSort("nearest");
      },
      () => setGeoState("denied"),
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 300_000 }
    );
  };

  const selectCity = (next: string) => {
    setCity(next);
    setActiveName(null);
    setApplied(null);
    const available = (SNAPSHOT.cities[next]?.niches ?? []).some(
      (item) => item.key === niche
    );
    if (!available) setNiche("all");
  };

  const viewLeads = (name: string) => {
    const item = neighborhoods.find((entry) => entry.name === name);
    if (!item) return;
    setApplied(
      t("dashboard.oppmap.opening")
        .replace("{n}", item.count.toLocaleString("en-US"))
        .replace("{name}", item.name)
    );
  };

  const summaryNiche =
    niche === "all" ? t("dashboard.oppmap.all") : nicheLabel(niche, t);

  if (!data) {
    return (
      <div className="grid min-h-screen place-items-center bg-[var(--sd-bg)] text-sm text-[var(--sd-muted)]">
        {t("dashboard.oppmap.empty").replace("{city}", city)}
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--sd-bg)] text-[var(--sd-text)]">
      <header className="border-b border-[var(--sd-border)] bg-[var(--sd-bg)]">
        <div className="mx-auto flex max-w-[1400px] items-center gap-4 px-5 py-2.5">
          <div className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-[var(--sd-accent)] text-[11px] font-black text-[var(--sd-accent-text)]">
              ML
            </span>
            <span className="text-[12px] font-black tracking-tight">MAGIC LEADS</span>
          </div>
          <nav className="hidden items-center gap-1 text-[11.5px] font-semibold text-[var(--sd-muted)] md:flex">
            <span className="rounded-md px-2.5 py-1">{t("dashboard.nav.overview")}</span>
            <span className="rounded-md bg-[var(--sd-surface-2)] px-2.5 py-1 text-[var(--sd-text)]">
              {t("dashboard.nav.opportunities")}
            </span>
            <span className="rounded-md px-2.5 py-1">{t("dashboard.nav.prevention")}</span>
          </nav>
          <span className="ml-auto rounded-full border border-[var(--sd-warn)]/40 bg-[var(--sd-warn-soft)] px-2 py-0.5 text-[9px] font-black uppercase tracking-[0.1em] text-[var(--sd-warn)]">
            {t("dashboard.oppmap.preview")}
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-4 pb-6 pt-4 sm:px-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[24px] font-black leading-none tracking-tight">
              {t("dashboard.nav.opportunities")}
            </h1>
            <p className="mt-1.5 text-[13px] text-[var(--sd-muted)]">
              {t("dashboard.oppmap.subtitle")
                .replace("{niche}", summaryNiche)
                .replace("{city}", meta.label)}
            </p>
          </div>

          <div className="flex items-center gap-1 rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-1">
            {CITY_ORDER.filter((name) => SNAPSHOT.cities[name]).map((name) => {
              const isActive = name === city;
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => selectCity(name)}
                  className={`rounded-lg px-3 py-1.5 text-[12px] font-bold transition ${
                    isActive
                      ? "bg-[var(--sd-accent)] text-[var(--sd-accent-text)]"
                      : "text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
                  }`}
                >
                  {CITY_META[name]?.label ?? name}
                </button>
              );
            })}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setNiche("all")}
            className={`rounded-full border px-3 py-1.5 text-[12px] font-bold transition ${
              niche === "all"
                ? "border-[var(--sd-accent)] bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"
                : "border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
            }`}
          >
            {t("dashboard.oppmap.all")}
          </button>
          {niches.map((item) => {
            const isActive = niche === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => {
                  setNiche(isActive ? "all" : item.key);
                  setActiveName(null);
                  setApplied(null);
                }}
                className={`rounded-full border px-3 py-1.5 text-[12px] font-bold transition ${
                  isActive
                    ? "border-[var(--sd-accent)] bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"
                    : "border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
                }`}
              >
                {nicheLabel(item.key, t)}
              </button>
            );
          })}
        </div>

        <div className="mt-3 flex items-center gap-1 lg:hidden">
          {(["map", "list"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setMobileView(value)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-[12px] font-bold ${
                mobileView === value
                  ? "bg-[var(--sd-surface-3)] text-[var(--sd-text)]"
                  : "text-[var(--sd-muted)]"
              }`}
            >
              {value === "map" ? (
                <MapIcon className="h-3.5 w-3.5" />
              ) : (
                <ListIcon className="h-3.5 w-3.5" />
              )}
              {value === "map"
                ? t("dashboard.oppmap.map")
                : t("dashboard.oppmap.list")}
            </button>
          ))}
        </div>

        {applied ? (
          <div className="mt-3 rounded-lg border border-[var(--sd-accent)]/40 bg-[var(--sd-accent-soft)] px-3 py-2 text-[12px] font-semibold text-[var(--sd-accent)]">
            {applied}
          </div>
        ) : null}

        <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_400px]">
          <section
            className={`relative overflow-hidden rounded-2xl border border-[var(--sd-border)] ${
              mobileView === "list" ? "hidden lg:block" : "block"
            }`}
          >
            <div className="h-[430px] w-full lg:h-[calc(100vh-260px)] lg:min-h-[460px]">
              <CityMap
                city={city}
                center={meta.center}
                zoom={meta.zoom}
                neighborhoods={neighborhoods}
                activeName={activeName}
                onSelect={setActiveName}
                user={user}
                labels={{
                  aria: t("dashboard.oppmap.map_aria"),
                  unavailable: t("dashboard.oppmap.map_error"),
                }}
              />
            </div>

            <div className="absolute left-3 top-3 z-[900] flex flex-col items-start gap-1.5">
              <button
                type="button"
                onClick={requestLocation}
                disabled={geoState === "loading"}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--sd-border-strong)] bg-[var(--sd-surface)]/95 px-3 py-2 text-[12px] font-bold text-[var(--sd-text)] shadow-lg backdrop-blur transition hover:border-[var(--sd-accent)] disabled:opacity-70"
              >
                <Crosshair
                  className={`h-3.5 w-3.5 ${
                    user ? "text-[var(--sd-accent)]" : "text-[var(--sd-muted)]"
                  }`}
                />
                {geoState === "loading"
                  ? t("dashboard.oppmap.locating")
                  : geoState === "denied"
                    ? t("dashboard.oppmap.location_off")
                    : t("dashboard.oppmap.near_me")}
              </button>
              {geoState === "denied" ? (
                <span className="max-w-[220px] rounded-md bg-[var(--sd-surface)]/95 px-2 py-1 text-[10px] leading-snug text-[var(--sd-muted)] shadow">
                  {t("dashboard.oppmap.location_help")}
                </span>
              ) : null}
            </div>

            {active ? (
              <div className="absolute bottom-3 left-3 z-[900] flex max-w-[340px] items-center justify-between gap-3 rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface)]/95 px-3 py-2 shadow-lg backdrop-blur">
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-bold">{active.name}</div>
                  <div className="text-[11px] text-[var(--sd-muted)]">
                    {active.count.toLocaleString("en-US")}{" "}
                    {active.count === 1
                      ? t("dashboard.oppmap.opportunity")
                      : t("dashboard.oppmap.opportunities")}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => viewLeads(active.name)}
                  className="shrink-0 rounded-lg bg-[var(--sd-accent)] px-3 py-1.5 text-[11.5px] font-black text-[var(--sd-accent-text)]"
                >
                  {t("dashboard.oppmap.view")}
                </button>
              </div>
            ) : null}
          </section>

          <aside
            className={`min-h-0 overflow-hidden rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] lg:h-[calc(100vh-260px)] ${
              mobileView === "map" ? "hidden lg:flex" : "flex"
            } h-[430px] flex-col lg:min-h-[460px]`}
          >
            <NeighborhoodList
              rows={rows}
              total={total}
              activeName={activeName}
              onSelect={setActiveName}
              onView={viewLeads}
              hasUser={Boolean(user)}
              sort={sort}
              onSortChange={setSort}
              city={meta.label}
            />
          </aside>
        </div>
      </main>
    </div>
  );
}
