"use client";

import { useEffect, useRef, useState } from "react";

export interface MapZone {
  name: string;
  count: number;
  /** Oportunidades frescas (<24 h). */
  fresh?: number;
  lat: number | null;
  lng: number | null;
}

const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const CLUSTER_JS =
  "https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js";
const CLUSTER_CSS =
  "https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css";
const TILES_BASE =
  "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}";
const TILES_LABELS =
  "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}";
const ATTRIBUTION =
  'Tiles &copy; <a href="https://www.esri.com/">Esri</a> &mdash; Esri, DeLorme, NAVTEQ';

let leafletPromise: Promise<unknown> | null = null;

function injectAsset(
  tag: "script" | "link",
  url: string,
  attr: string
): Promise<void> {
  return new Promise((resolve, reject) => {
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

/** Carrega Leaflet + MarkerCluster do CDN uma única vez (sem dependências npm). */
function loadLeaflet(): Promise<any> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("no_window"));
  }
  const win = window as any;
  if (win.L?.markerClusterGroup) return Promise.resolve(win.L);
  if (leafletPromise) return leafletPromise;

  leafletPromise = Promise.all([
    injectAsset("link", LEAFLET_CSS, "data-leaflet"),
    injectAsset("link", CLUSTER_CSS, "data-leaflet-cluster"),
    injectAsset("script", LEAFLET_JS, "data-leaflet"),
  ])
    .then(() => injectAsset("script", CLUSTER_JS, "data-leaflet-cluster"))
    .then(() => (window as any).L)
    .catch((error) => {
      leafletPromise = null;
      throw error;
    });
  return leafletPromise as Promise<any>;
}

export function CityMap({
  city,
  center,
  zoom,
  neighborhoods,
  activeName,
  onSelect,
  user,
  labels,
}: {
  city: string;
  center: [number, number];
  zoom: number;
  neighborhoods: MapZone[];
  activeName: string | null;
  onSelect: (name: string) => void;
  user: { lat: number; lng: number } | null;
  labels: { aria: string; unavailable: string };
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const layerRef = useRef<any>(null);
  const userLayerRef = useRef<any>(null);
  const selectRef = useRef(onSelect);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    selectRef.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    let alive = true;
    let map: any;

    loadLeaflet()
      .then((L) => {
        if (!alive || !containerRef.current) return;
        map = L.map(containerRef.current, {
          zoomControl: false,
          attributionControl: true,
          scrollWheelZoom: true,
          minZoom: 9,
          maxZoom: 16,
        }).setView(center, zoom);

        L.control.zoom({ position: "bottomright" }).addTo(map);

        L.tileLayer(TILES_BASE, {
          maxZoom: 16,
          attribution: ATTRIBUTION,
        }).addTo(map);
        L.tileLayer(TILES_LABELS, { maxZoom: 16 }).addTo(map);

        mapRef.current = map;
        layerRef.current = L.markerClusterGroup({
          showCoverageOnHover: false,
          spiderfyOnMaxZoom: true,
          maxClusterRadius: 46,
          disableClusteringAtZoom: 14,
          iconCreateFunction: (group: any) => {
            const markers = group.getAllChildMarkers();
            const count = markers.reduce(
              (sum: number, marker: any) =>
                sum + Number(marker.options.opportunityCount ?? 0),
              0
            );
            const fresh = markers.reduce(
              (sum: number, marker: any) =>
                sum + Number(marker.options.freshCount ?? 0),
              0
            );
            return L.divIcon({
              html: `<div class="opp-cluster${fresh > 0 ? " is-fresh" : ""}">${count}</div>`,
              className: "opp-cluster-wrap",
              iconSize: [52, 52],
              iconAnchor: [26, 26],
            });
          },
        }).addTo(map);
        setReady(true);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });

    return () => {
      alive = false;
      map?.remove();
      mapRef.current = null;
      layerRef.current = null;
      userLayerRef.current = null;
      setReady(false);
    };
    // O mapa é criado uma vez; centro, zoom e pins são sincronizados nos
    // efeitos seguintes para não perder a instância ao trocar de cidade.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.setView(center, zoom);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [city, ready]);

  useEffect(() => {
    const L = (window as any).L;
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!L || !map || !layer || !ready) return;

    layer.clearLayers();
    const bounds: Array<[number, number]> = [];

    for (const item of neighborhoods) {
      // "Other areas" fica na lista (e filtra o feed), mas não no mapa:
      // o centroide do catch-all estica o enquadramento até aos subúrbios.
      if (item.name === "Other areas" || item.name === "Other area") continue;
      if (item.lat === null || item.lng === null) continue;
      const active = item.name === activeName;
      const fresh = (item.fresh ?? 0) > 0;
      const icon = L.divIcon({
        className: "opp-pin-wrap",
        html: `<div class="opp-pin${active ? " is-active" : ""}${
          fresh ? " is-fresh" : ""
        }"${fresh ? ` title="${item.fresh} new in the last 24h"` : ""}>${
          item.count
        }${fresh ? '<span class="opp-pin-fresh" aria-hidden="true"></span>' : ""}</div>`,
        iconSize: [44, 28],
        iconAnchor: [22, 14],
      });
      const marker = L.marker([item.lat, item.lng], {
        icon,
        title: `${item.name} · ${item.count}${fresh ? ` · ${item.fresh} new` : ""}`,
        riseOnHover: true,
        opportunityCount: item.count,
        freshCount: item.fresh ?? 0,
      });
      marker.on("click", () => selectRef.current(item.name));
      marker.addTo(layer);
      bounds.push([item.lat, item.lng]);
    }

    if (bounds.length === 1) {
      map.setView(bounds[0], 13);
    } else if (bounds.length > 1) {
      map.fitBounds(bounds, { padding: [48, 48], maxZoom: 13 });
    }
  }, [neighborhoods, activeName, ready]);

  useEffect(() => {
    const L = (window as any).L;
    const map = mapRef.current;
    if (!L || !map) return;

    if (!user) {
      userLayerRef.current?.clearLayers();
      return;
    }
    if (!userLayerRef.current) {
      userLayerRef.current = L.layerGroup().addTo(map);
    }
    userLayerRef.current.clearLayers();
    L.marker([user.lat, user.lng], {
      icon: L.divIcon({
        className: "opp-user-wrap",
        html: '<div class="opp-user-dot"></div>',
        iconSize: [18, 18],
        iconAnchor: [9, 9],
      }),
      interactive: false,
      zIndexOffset: 5000,
    }).addTo(userLayerRef.current);
    map.setView([user.lat, user.lng], 12);
  }, [user, ready]);

  if (failed) {
    return (
      <div className="grid h-full place-items-center rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] text-xs text-[var(--sd-muted)]">
        {labels.unavailable}
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="opp-map h-full w-full"
      role="application"
      aria-label={labels.aria.replace("{city}", city)}
    />
  );
}
