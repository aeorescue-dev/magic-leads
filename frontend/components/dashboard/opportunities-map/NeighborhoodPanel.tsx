"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  ChevronDown,
  Crosshair,
  MapPin,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";

import { useI18n } from "@/lib/i18n";
import { fetchOpportunityTerritories } from "@/lib/api-client";
import type { CityOption } from "@/components/dashboard/CityPicker";

import { CityMap } from "./CityMap";
import { NeighborhoodList, type NeighborhoodRow } from "./NeighborhoodList";
import {
  CITY_META,
  buildNeighborhoods,
  distanceMiles,
  type Zone,
} from "./neighborhoods";
import { SNAPSHOT, nicheLabel } from "./data";

type GeoState = "idle" | "loading" | "denied";

/**
 * Bloco superior da tela de oportunidades: mapa + bairros.
 * Lê e escreve os filtros reais da dashboard (cidade, ofício) e devolve o
 * bairro escolhido para o feed filtrar os cards abaixo.
 */
export function NeighborhoodPanel({
  cities,
  city,
  onCityChange,
  category,
  onCategoryChange,
  activeName,
  onSelect,
}: {
  cities: CityOption[];
  city: string;
  onCityChange: (value: string) => void;
  category: string;
  onCategoryChange: (value: string) => void;
  activeName: string | null;
  onSelect: (name: string, zips: string[]) => void;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(true);
  const [sort, setSort] = useState<"leads" | "nearest">("leads");
  const [freshOnly, setFreshOnly] = useState(false);
  const [user, setUser] = useState<{ lat: number; lng: number } | null>(null);
  const [geoState, setGeoState] = useState<GeoState>("idle");

  // Trocar de cidade não pode deixar o filtro "New" preso numa lista vazia.
  useEffect(() => {
    setFreshOnly(false);
  }, [city]);

  const snapshot = city !== "all" ? SNAPSHOT.cities[city] : undefined;

  // Agregado ao vivo (mesma query do feed preventivo). O snapshot é o fallback
  // offline: mantém o mapa útil se a API falhar, mas sem frescos.
  const { data: live } = useSWR(
    city !== "all"
      ? ["territories", city, "preventive", 30, category]
      : null,
    () =>
      fetchOpportunityTerritories({
        city,
        kind: "preventive",
        days: 30,
        category,
      }),
    { revalidateOnFocus: false, keepPreviousData: true }
  );

  const zones = useMemo<Zone[]>(() => {
    const liveZones = live?.zones ?? [];
    // Sem preventivos ao vivo (ex.: mercado ainda sem ingestão), mantém o mapa
    // útil com o snapshot real em vez de mostrar "Map unavailable".
    if (liveZones.length === 0) return snapshot?.zones ?? [];
    const centroids = new Map(
      (snapshot?.zones ?? []).map((zone) => [zone.zip, zone])
    );
    return liveZones.map((zone) => {
      const geo = centroids.get(zone.zip);
      return {
        zip: zone.zip,
        label: null,
        total: zone.total,
        fresh: zone.fresh,
        niches: zone.niches,
        lat: geo?.lat ?? null,
        lng: geo?.lng ?? null,
        geo_source: geo ? "snapshot" : "",
      };
    });
  }, [live, snapshot]);

  const meta = CITY_META[city];
  const mapAvailable = Boolean(meta);

  const niches = useMemo(
    () => (snapshot ? snapshot.niches.slice(0, 8) : []),
    [snapshot]
  );

  const neighborhoods = useMemo(
    () => (mapAvailable ? buildNeighborhoods(city, zones, category) : []),
    [city, zones, category, mapAvailable]
  );

  const freshTotal = useMemo(
    () => neighborhoods.reduce((sum, item) => sum + item.fresh, 0),
    [neighborhoods]
  );

  // Frescos primeiro; o toggle mostra só bairros com entradas/prazos novos.
  const visibleNeighborhoods = useMemo(() => {
    const base = freshOnly
      ? neighborhoods.filter((item) => item.fresh > 0)
      : neighborhoods;
    return [...base].sort(
      (a, b) =>
        b.fresh - a.fresh ||
        b.count - a.count ||
        a.name.localeCompare(b.name)
    );
  }, [neighborhoods, freshOnly]);

  const rows = useMemo<NeighborhoodRow[]>(() => {
    const list = visibleNeighborhoods.map((item) => ({
      item,
      distance:
        user && item.lat !== null && item.lng !== null
          ? distanceMiles(user.lat, user.lng, item.lat, item.lng)
          : null,
    }));
    if (sort === "nearest" && user) {
      list.sort((a, b) => (a.distance ?? Infinity) - (b.distance ?? Infinity));
    }
    return list;
  }, [visibleNeighborhoods, sort, user]);

  const requestLocation = () => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setGeoState("denied");
      return;
    }
    setGeoState("loading");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setUser({ lat: position.coords.latitude, lng: position.coords.longitude });
        setGeoState("idle");
        setSort("nearest");
      },
      () => setGeoState("denied"),
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 300_000 }
    );
  };

  const cityLabel =
    cities.find((option) => option.value === city)?.label ?? city;
  const nicheLabelText =
    category === "all" ? t("dashboard.oppmap.all") : nicheLabel(category, t);

  return (
    <section className="rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)]">
      <header className="flex flex-wrap items-center gap-3 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]">
            <MapPin className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-[13px] font-bold text-[var(--sd-text)]">
              {t("dashboard.oppmap.panel_title")}
            </h2>
            <p className="truncate text-[11px] text-[var(--sd-muted)]">
              {city === "all"
                ? t("dashboard.oppmap.choose_city")
                : `${nicheLabelText} · ${cityLabel}`}
            </p>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          {freshTotal > 0 ? (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-amber-400/50 bg-amber-400/15 px-2 py-1 text-[10px] font-extrabold uppercase tracking-wide text-amber-300"
              title={t("dashboard.oppmap.fresh_tip")}
            >
              <Sparkles className="h-3 w-3" />
              {freshTotal.toLocaleString("en-US")} {t("dashboard.oppmap.fresh_badge")}
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            className="inline-flex items-center gap-1 rounded-lg border border-[var(--sd-border)] px-2.5 py-1.5 text-[10.5px] font-bold text-[var(--sd-muted)] transition hover:text-[var(--sd-text)]"
          >
            {expanded
              ? t("dashboard.oppmap.hide")
              : t("dashboard.oppmap.show")}
            <ChevronDown
              className={`h-3.5 w-3.5 transition-transform ${
                expanded ? "rotate-180" : ""
              }`}
            />
          </button>
        </div>
      </header>

      {expanded ? (
        <div className="border-t border-[var(--sd-border)] px-4 pb-4 pt-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {cities
              .filter((option) => option.value !== "all")
              .map((option) => {
                const active = option.value === city;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => onCityChange(option.value)}
                    className={`rounded-full border px-3 py-1 text-[11px] font-bold transition ${
                      active
                        ? "border-[var(--sd-accent)] bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"
                        : "border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            {niches.length > 0 ? (
              <span className="mx-1 hidden h-4 w-px bg-[var(--sd-border)] sm:block" />
            ) : null}
            {niches.length > 0 ? (
              <button
                type="button"
                onClick={() => onCategoryChange("all")}
                className={`rounded-full border px-3 py-1 text-[11px] font-bold transition ${
                  category === "all"
                    ? "border-[var(--sd-accent)] bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"
                    : "border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
                }`}
              >
                {t("dashboard.oppmap.all")}
              </button>
            ) : null}
            {niches.map((item) => {
              const active = category === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => onCategoryChange(active ? "all" : item.key)}
                  className={`rounded-full border px-3 py-1 text-[11px] font-bold transition ${
                    active
                      ? "border-[var(--sd-accent)] bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"
                      : "border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
                  }`}
                >
                  {nicheLabel(item.key, t)}
                </button>
              );
            })}
          </div>

          {city === "all" ? (
            <div className="mt-3 grid h-[140px] place-items-center rounded-xl border border-dashed border-[var(--sd-border)] text-center">
              <div className="px-6">
                <MapPin className="mx-auto h-5 w-5 text-[var(--sd-faint)]" />
                <p className="mt-2 text-[12px] font-semibold text-[var(--sd-text)]">
                  {t("dashboard.oppmap.choose_city")}
                </p>
              </div>
            </div>
          ) : !mapAvailable ? (
            <div className="mt-3 grid h-[140px] place-items-center rounded-xl border border-dashed border-[var(--sd-border)] text-center">
              <div className="px-6">
                <MapPin className="mx-auto h-5 w-5 text-[var(--sd-faint)]" />
                <p className="mt-2 text-[12px] font-semibold text-[var(--sd-text)]">
                  {t("dashboard.oppmap.no_map")}
                </p>
                <p className="mt-1 text-[10.5px] text-[var(--sd-muted)]">
                  {t("dashboard.oppmap.no_map_hint")}
                </p>
              </div>
            </div>
          ) : (
            <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_300px]">
              <div className="relative h-[340px] overflow-hidden rounded-xl border border-[var(--sd-border)]">
                <CityMap
                  city={city}
                  center={meta.center}
                  zoom={meta.zoom}
                  neighborhoods={visibleNeighborhoods}
                  activeName={activeName}
                  onSelect={(name) => {
                    const item = neighborhoods.find((entry) => entry.name === name);
                    if (item) onSelect(item.name, item.zips);
                  }}
                  user={user}
                  labels={{
                    aria: t("dashboard.oppmap.map_aria"),
                    unavailable: t("dashboard.oppmap.map_error"),
                  }}
                />

                <div className="absolute left-2.5 top-2.5 z-[900] flex flex-col items-start gap-1">
                  <button
                    type="button"
                    onClick={requestLocation}
                    disabled={geoState === "loading"}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--sd-border-strong)] bg-[var(--sd-surface)]/95 px-2.5 py-1.5 text-[11px] font-bold text-[var(--sd-text)] shadow backdrop-blur transition hover:border-[var(--sd-accent)] disabled:opacity-70"
                  >
                    <Crosshair
                      className={`h-3 w-3 ${
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
                    <span className="max-w-[210px] rounded bg-[var(--sd-surface)]/95 px-1.5 py-1 text-[9px] leading-snug text-[var(--sd-muted)] shadow">
                      {t("dashboard.oppmap.location_help")}
                    </span>
                  ) : null}
                </div>
              </div>

              <div className="max-h-[340px] overflow-hidden rounded-xl border border-[var(--sd-border)]">
                <NeighborhoodList
                  rows={rows}
                  total={
                    freshOnly
                      ? freshTotal
                      : rows.reduce((sum, row) => sum + row.item.count, 0)
                  }
                  activeName={activeName}
                  onSelect={(name) => {
                    const item = neighborhoods.find((entry) => entry.name === name);
                    if (item) onSelect(item.name, item.zips);
                  }}
                  onView={(name) => {
                    const item = neighborhoods.find((entry) => entry.name === name);
                    if (item) onSelect(item.name, item.zips);
                  }}
                  hasUser={Boolean(user)}
                  sort={sort}
                  onSortChange={setSort}
                  freshOnly={freshOnly}
                  onFreshOnlyChange={setFreshOnly}
                  freshCount={freshTotal}
                  city={cityLabel}
                />
              </div>
            </div>
          )}

          {mapAvailable ? (
            <p className="mt-2 flex items-center gap-1 text-[9px] text-[var(--sd-faint)]">
              <SlidersHorizontal className="h-2.5 w-2.5" />
              {t("dashboard.oppmap.hint")}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
