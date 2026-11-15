"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, MapPin } from "lucide-react";

import { useI18n, formatNumber } from "@/lib/i18n";
import {
  fetchLiveMap,
  type LiveMapCity,
  type LiveMapResponse,
  type LiveMapZone,
} from "@/lib/api-client";

const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const TILES_BASE =
  "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}";
const TILES_LABELS =
  "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}";
const ATTRIBUTION =
  'Tiles &copy; <a href="https://www.esri.com/">Esri</a> &mdash; Esri, DeLorme, NAVTEQ';

const CITY_CENTERS: Record<string, [number, number]> = {
  "New York": [40.7128, -74.006],
  Boston: [42.3601, -71.0589],
  Dallas: [32.7767, -96.797],
  Chicago: [41.8781, -87.6298],
};

let leafletPromise: Promise<unknown> | null = null;

function injectAsset(tag: "script" | "link", url: string, attr: string) {
  return new Promise<void>((resolve, reject) => {
    const selector = `${tag}[${attr}]`;
    if (document.querySelector(selector)) {
      resolve();
      return;
    }
    const element = document.createElement(tag);
    if (tag === "script") {
      (element as HTMLScriptElement).src = url;
      (element as HTMLScriptElement).async = true;
      element.addEventListener("load", () => resolve());
    } else {
      (element as HTMLLinkElement).rel = "stylesheet";
      (element as HTMLLinkElement).href = url;
      element.addEventListener("load", () => resolve());
    }
    element.addEventListener("error", () => reject(new Error(url)));
    element.setAttribute(attr, "1");
    document.head.appendChild(element);
  });
}

function loadLeaflet(): Promise<any> {
  if (typeof window === "undefined") return Promise.reject(new Error("no_window"));
  const win = window as any;
  if (win.L) return Promise.resolve(win.L);
  if (leafletPromise) return leafletPromise;
  leafletPromise = Promise.all([
    injectAsset("link", LEAFLET_CSS, "data-leaflet-pub"),
    injectAsset("script", LEAFLET_JS, "data-leaflet-pub"),
  ])
    .then(() => (window as any).L)
    .catch((error) => {
      leafletPromise = null;
      throw error;
    });
  return leafletPromise as Promise<any>;
}

export function PublicLiveMap({
  city,
  onZoneSelect,
  onTotalChange,
  onUnavailable,
  className = "h-[300px]",
}: {
  city: string;
  onZoneSelect: (zone: LiveMapZone, cityLabel: string) => void;
  onTotalChange?: (total: number) => void;
  onUnavailable?: () => void;
  className?: string;
}) {
  const { t, lang } = useI18n();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const layerRef = useRef<any>(null);
  const selectRef = useRef(onZoneSelect);
  const unavailableRef = useRef(onUnavailable);
  const [data, setData] = useState<LiveMapResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  const [showAllZones, setShowAllZones] = useState(false);

  useEffect(() => {
    selectRef.current = onZoneSelect;
  }, [onZoneSelect]);

  useEffect(() => {
    unavailableRef.current = onUnavailable;
  }, [onUnavailable]);

  useEffect(() => {
    let alive = true;
    fetchLiveMap()
      .then((payload) => {
        if (alive) setData(payload);
      })
      .catch(() => {
        if (alive) {
          setFailed(true);
          unavailableRef.current?.();
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  const active: LiveMapCity | undefined = data?.cities.find(
    (item) => item.label === city
  );

  useEffect(() => {
    setShowAllZones(false);
  }, [city]);

  useEffect(() => {
    if (active) onTotalChange?.(active.totals.count);
  }, [active, onTotalChange]);

  useEffect(() => {
    let alive = true;
    let map: any;
    let observer: ResizeObserver | null = null;
    loadLeaflet()
      .then((L) => {
        if (!alive || !containerRef.current) return;
        map = L.map(containerRef.current, {
          zoomControl: false,
          attributionControl: true,
          scrollWheelZoom: false,
          dragging: true,
          minZoom: 9,
          maxZoom: 15,
        }).setView(CITY_CENTERS[city] ?? CITY_CENTERS["New York"], 11);
        L.tileLayer(TILES_BASE, { maxZoom: 15, attribution: ATTRIBUTION }).addTo(map);
        L.tileLayer(TILES_LABELS, { maxZoom: 15 }).addTo(map);
        layerRef.current = L.layerGroup().addTo(map);
        mapRef.current = map;
        setReady(true);
        requestAnimationFrame(() => map.invalidateSize());
        if (typeof ResizeObserver !== "undefined" && containerRef.current) {
          observer = new ResizeObserver(() => map.invalidateSize());
          observer.observe(containerRef.current);
        }
      })
      .catch(() => {
        if (alive) setFailed(true);
      });

    return () => {
      alive = false;
      observer?.disconnect();
      map?.remove();
      mapRef.current = null;
      layerRef.current = null;
      setReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const L = (window as any).L;
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!L || !map || !layer || !ready) return;

    layer.clearLayers();
    const zones = (active?.zones ?? [])
      .filter((zone) => zone.lat !== null && zone.lng !== null)
      .slice(0, 3);
    const bounds: Array<[number, number]> = [];

    for (const zone of zones) {
      const countLabel = formatNumber(zone.count, lang);
      const size = Math.min(54, 34 + Math.round(Math.log2(zone.count + 1) * 4));
      const icon = L.divIcon({
        className: "pub-bubble-wrap",
        html: `<div class="pub-bubble${zone.fresh > 0 ? " is-fresh" : ""}">${
          countLabel
        }${zone.fresh > 0 ? '<i class="pub-fresh-dot" aria-hidden="true"></i>' : ""}</div>`,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
      });
      const marker = L.marker([zone.lat as number, zone.lng as number], {
        icon,
        title: `${zone.label} · ${countLabel}`,
        riseOnHover: true,
      });
      marker.on("click", () => selectRef.current(zone, active?.label ?? city));
      marker.addTo(layer);
      bounds.push([zone.lat as number, zone.lng as number]);
    }

    if (bounds.length === 1) {
      map.setView(bounds[0], 13);
    } else if (bounds.length > 1) {
      map.fitBounds(bounds, { padding: [34, 34], maxZoom: 13 });
    } else {
      map.setView(CITY_CENTERS[city] ?? CITY_CENTERS["New York"], 11);
    }
  }, [active, city, ready]);

  if (failed && !data) {
    return (
      <div className="grid h-full place-items-center rounded-2xl bg-[#f1f5f9] text-[11px] font-semibold text-[#64748b]">
        {t("landing.liveMap.unavailable")}
      </div>
    );
  }

  const allZones = active?.zones ?? [];
  const topZones = allZones.slice(0, 3);
  const extraCount = Math.max(0, allZones.length - topZones.length);
  const chipZones = showAllZones ? allZones : topZones;
  const fresh = active?.totals.fresh ?? 0;

  return (
    <div className="relative isolate z-0 flex h-full min-h-0 flex-col">
      <div className="relative min-h-0 flex-1 overflow-hidden rounded-2xl border border-[#e7e3d9] bg-[#e9eef3]">
        <div
          ref={containerRef}
          className={`pub-map w-full ${className}`}
          role="region"
          aria-label={t("landing.liveMap.aria")}
        />
        {!data ? (
          <div className="absolute inset-0 grid place-items-center bg-[#f1f5f9]/80 text-[11px] font-semibold text-[#64748b]">
            {t("landing.p1Loading")}
          </div>
        ) : null}
        {active ? (
          <div className="pointer-events-none absolute left-2.5 top-2.5 z-[500] flex flex-wrap items-center gap-1.5">
            <span
              data-map-total={active.totals.count}
              className="rounded-full bg-white/95 px-2.5 py-1 text-[10px] font-black text-[#0b1220] shadow-sm"
            >
              {formatNumber(active.totals.count, lang)}{" "}
              {t("landing.p1Opportunities")}
            </span>
            {fresh > 0 ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-[#f59e0b]/40 bg-[#fffbeb]/95 px-2 py-1 text-[9.5px] font-black uppercase tracking-[0.06em] text-[#b45309] shadow-sm">
                <span className="h-1.5 w-1.5 rounded-full bg-[#f59e0b]" />
                {formatNumber(fresh, lang)} {t("landing.statNew24")}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      {fresh > 0 ? (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[9.5px] font-semibold text-[#64748b]">
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-[#f59e0b] shadow-[0_0_8px_rgba(245,158,11,0.65)]" />
            {t("landing.liveMap.fresh_legend")}
          </span>
        </div>
      ) : null}

      {topZones.length > 0 ? (
        <div
          className={`mt-2 flex flex-wrap gap-1.5 ${
            showAllZones ? "max-h-28 overflow-y-auto pr-1" : ""
          }`}
        >
          {chipZones.map((zone) => (
            <button
              key={zone.slug}
              type="button"
              data-map-zone={zone.slug}
              onClick={() => onZoneSelect(zone, active?.label ?? city)}
              aria-label={t("landing.liveMap.explore").replace(
                "{zone}",
                zone.label
              )}
              title={t("landing.liveMap.explore").replace("{zone}", zone.label)}
              className="group inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-[#e7e3d9] bg-white px-2.5 py-1 text-[10.5px] font-bold text-[#0b1220] shadow-sm transition active:scale-95 hover:border-[#0a8f65] hover:bg-[#0a8f65] hover:text-white hover:shadow"
            >
              <MapPin className="h-3 w-3 text-[#10b981] transition group-hover:text-white" />
              {zone.label}
              <span className="text-[#64748b] transition group-hover:text-white/80">
                {formatNumber(zone.count, lang)}
              </span>
              {zone.fresh > 0 ? (
                <span className="rounded-full bg-[#fef3c7] px-1 text-[9px] font-black text-[#b45309] transition group-hover:bg-white/20 group-hover:text-white">
                  +{formatNumber(zone.fresh, lang)}
                </span>
              ) : null}
              <ArrowRight className="h-3 w-3 opacity-50 transition group-hover:translate-x-0.5 group-hover:opacity-100" />
            </button>
          ))}
          {extraCount > 0 && !showAllZones ? (
            <button
              type="button"
              data-map-more
              onClick={() => setShowAllZones(true)}
              aria-expanded={showAllZones}
              className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-dashed border-[#10b981]/50 bg-[#effbf5] px-2.5 py-1 text-[10.5px] font-black text-[#0a8f65] transition hover:border-[#10b981] hover:bg-[#e6f9f0] active:scale-95"
            >
              {t("landing.liveMap.more_areas").replace(
                "{n}",
                formatNumber(extraCount, lang)
              )}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
