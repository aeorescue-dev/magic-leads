"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { ChevronDown, Crosshair, MapPin, SlidersHorizontal } from "lucide-react";

import { useI18n } from "@/lib/i18n";
import { fetchLeadNeighborhoods } from "@/lib/api-client";

import { CityMap } from "./CityMap";
import { NeighborhoodList, type NeighborhoodRow } from "./NeighborhoodList";
import { CITY_META, distanceMiles } from "./neighborhoods";
import { buildLeadZones, type LeadZone } from "./leadZones";
import { nicheLabel } from "./data";

type GeoState = "idle" | "loading" | "denied";

/**
 * Mapa + bairros da aba Opportunities (leads reativos).
 *
 * A agregação vem de `/api/leads/neighborhoods` (GROUP BY no SQLite, com o
 * mesmo WHERE do feed). Clicar numa zona devolve o filtro para a dashboard,
 * que filtra os cartões abaixo no servidor.
 */
export function LeadsNeighborhoodPanel({
  city,
  category,
  type,
  urgency,
  includeClosed,
  deadlineOnly,
  layer,
  ownerType,
  search,
  activeName,
  onSelect,
}: {
  city: string;
  category: string;
  type: string;
  urgency?: string;
  includeClosed: boolean;
  deadlineOnly: boolean;
  layer: string;
  ownerType: string;
  search: string;
  activeName: string | null;
  onSelect: (zone: LeadZone) => void;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(true);
  const [sort, setSort] = useState<"leads" | "nearest">("leads");
  const [user, setUser] = useState<{ lat: number; lng: number } | null>(null);
  const [geoState, setGeoState] = useState<GeoState>("idle");

  const enabled = city !== "all";
  const { data, isLoading } = useSWR(
    enabled
      ? [
          "lead-zones",
          city,
          category,
          type,
          urgency ?? "",
          includeClosed,
          deadlineOnly,
          layer,
          ownerType,
          search,
        ]
      : null,
    () =>
      fetchLeadNeighborhoods({
        city,
        category,
        type,
        urgency,
        includeClosed,
        deadlineOnly,
        layer,
        ownerType,
        search,
      }),
    { revalidateOnFocus: false, keepPreviousData: true }
  );

  const zones = useMemo(
    () => (data ? buildLeadZones(city, data.groups) : []),
    [city, data]
  );

  const rows = useMemo<NeighborhoodRow[]>(() => {
    const list = zones.map((zone) => ({
      item: zone,
      distance:
        user && zone.lat !== null && zone.lng !== null
          ? distanceMiles(user.lat, user.lng, zone.lat, zone.lng)
          : null,
    }));
    if (sort === "nearest" && user) {
      list.sort((a, b) => (a.distance ?? Infinity) - (b.distance ?? Infinity));
    }
    return list;
  }, [zones, sort, user]);

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

  const meta = CITY_META[city];
  const total = data?.total ?? 0;
  const cityLabel = meta?.label ?? city;
  const niche = category === "all" ? t("dashboard.oppmap.all") : nicheLabel(category, t);

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
              {enabled
                ? `${niche} · ${cityLabel}`
                : t("dashboard.oppmap.choose_city")}
            </p>
          </div>
        </div>
        <div className="ml-auto">
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
          {!enabled ? (
            <div className="grid h-[140px] place-items-center rounded-xl border border-dashed border-[var(--sd-border)] text-center">
              <div className="px-6">
                <MapPin className="mx-auto h-5 w-5 text-[var(--sd-faint)]" />
                <p className="mt-2 text-[12px] font-semibold text-[var(--sd-text)]">
                  {t("dashboard.oppmap.choose_city")}
                </p>
              </div>
            </div>
          ) : isLoading && !data ? (
            <div className="grid h-[340px] animate-pulse place-items-center rounded-xl bg-[var(--sd-surface-2)] text-[11px] text-[var(--sd-muted)]">
              {t("dashboard.feed.loading")}
            </div>
          ) : zones.length === 0 ? (
            <div className="grid h-[140px] place-items-center rounded-xl border border-dashed border-[var(--sd-border)] text-center">
              <div className="px-6">
                <MapPin className="mx-auto h-5 w-5 text-[var(--sd-faint)]" />
                <p className="mt-2 text-[12px] font-semibold text-[var(--sd-text)]">
                  {t("dashboard.oppmap.no_leads")}
                </p>
              </div>
            </div>
          ) : (
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_300px]">
              <div className="relative h-[340px] overflow-hidden rounded-xl border border-[var(--sd-border)]">
                <CityMap
                  city={city}
                  center={meta?.center ?? [42.3601, -71.0589]}
                  zoom={meta?.zoom ?? 12}
                  neighborhoods={zones}
                  activeName={activeName}
                  onSelect={(name) => {
                    const zone = zones.find((item) => item.name === name);
                    if (zone) onSelect(zone);
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
                  total={total}
                  activeName={activeName}
                  onSelect={(name) => {
                    const zone = zones.find((item) => item.name === name);
                    if (zone) onSelect(zone);
                  }}
                  onView={(name) => {
                    const zone = zones.find((item) => item.name === name);
                    if (zone) onSelect(zone);
                  }}
                  hasUser={Boolean(user)}
                  sort={sort}
                  onSortChange={setSort}
                  city={cityLabel}
                />
              </div>
            </div>
          )}

          {enabled && zones.length > 0 ? (
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
