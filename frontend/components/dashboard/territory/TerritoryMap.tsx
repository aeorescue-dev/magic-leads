"use client";

import { useMemo } from "react";

import { nicheColor, zoneTitle } from "./data";
import type { Zone } from "./types";

const WIDTH = 1000;
const HEIGHT = 620;
const PAD = 58;

interface Point {
  zone: Zone;
  x: number;
  y: number;
  r: number;
  color: string;
}

export function TerritoryMap({
  zones,
  selectedZip,
  onSelect,
  t,
}: {
  zones: Zone[];
  selectedZip: string | null;
  onSelect: (zip: string) => void;
  t: (key: string) => string;
}) {
  const { points, maxTotal } = useMemo(() => {
    const geo = zones.filter(
      (zone) =>
        Number.isFinite(zone.lat) &&
        Number.isFinite(zone.lng) &&
        zone.geo_source !== "city_center"
    );
    if (geo.length === 0) {
      return { points: [] as Point[], maxTotal: 1 };
    }
    const lats = geo.map((zone) => zone.lat);
    const lngs = geo.map((zone) => zone.lng);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);
    const spanLat = Math.max(maxLat - minLat, 0.01);
    const spanLng = Math.max(maxLng - minLng, 0.01);
    const max = Math.max(...geo.map((zone) => zone.total), 1);

    const projected: Point[] = geo
      .slice()
      .sort((a, b) => a.total - b.total)
      .map((zone) => ({
        zone,
        x: PAD + ((zone.lng - minLng) / spanLng) * (WIDTH - PAD * 2),
        y: PAD + ((maxLat - zone.lat) / spanLat) * (HEIGHT - PAD * 2),
        r: 9 + 30 * Math.sqrt(zone.total / max),
        color: nicheColor(zone.niches[0]?.key ?? "Unclassified"),
      }));

    return { points: projected, maxTotal: max };
  }, [zones]);

  const labelled = useMemo(
    () => new Set([...zones].sort((a, b) => b.total - a.total).slice(0, 5).map((z) => z.zip)),
    [zones]
  );
  const omitted = Math.max(
    0,
    zones.filter((zone) => zone.total > 0).length - points.length
  );

  if (points.length === 0) {
    return (
      <div className="grid h-[420px] place-items-center rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] text-xs text-[var(--sd-muted)]">
        {t("dashboard.territory.map.empty")}
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-3">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full"
        role="img"
        aria-label={t("dashboard.territory.map.aria")}
      >
        <defs>
          <pattern id="territory-grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" fill="var(--sd-border-strong)" opacity="0.5" />
          </pattern>
          <radialGradient id="territory-glow">
            <stop offset="0%" stopColor="var(--sd-accent)" stopOpacity="0.16" />
            <stop offset="100%" stopColor="var(--sd-accent)" stopOpacity="0" />
          </radialGradient>
        </defs>

        <rect x="0" y="0" width={WIDTH} height={HEIGHT} fill="url(#territory-grid)" />
        <circle cx={WIDTH / 2} cy={HEIGHT / 2} r={HEIGHT * 0.62} fill="url(#territory-glow)" />

        {points.map((point, index) => {
          const selected = point.zone.zip === selectedZip;
          const rank = points.length - 1 - index;
          const above = rank % 2 === 1;
          const labelY = Math.min(
            HEIGHT - 10,
            Math.max(14, point.y + (above ? -(point.r + 6) : point.r + 14))
          );
          return (
            <g
              key={point.zone.zip}
              className="cursor-pointer"
              onClick={() => onSelect(point.zone.zip)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(point.zone.zip);
                }
              }}
              role="button"
              tabIndex={0}
              aria-label={`${zoneTitle(point.zone, t)} · ${point.zone.total}`}
            >
              <circle
                cx={point.x}
                cy={point.y}
                r={point.r}
                fill={point.color}
                fillOpacity={selected ? 0.85 : 0.32}
                stroke={selected ? "#f8fafc" : point.color}
                strokeWidth={selected ? 3 : 1.4}
              />
              <circle
                cx={point.x}
                cy={point.y}
                r={Math.max(2.5, point.r * 0.13)}
                fill={point.color}
              />
              <text
                x={point.x}
                y={labelY}
                textAnchor="middle"
                className="fill-[var(--sd-muted)] text-[11px] font-semibold"
                stroke="var(--sd-bg)"
                strokeWidth={3}
                paintOrder="stroke"
              >
                {labelled.has(point.zone.zip)
                  ? `${point.zone.label ?? point.zone.zip} · ${point.zone.total}`
                  : ""}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="mt-1 flex flex-wrap items-center justify-between gap-2 px-2 pb-1 text-[10px] text-[var(--sd-faint)]">
        <span>
          {t("dashboard.territory.map.note")}
          {omitted > 0
            ? ` · ${omitted} ${t("dashboard.territory.map.omitted")}`
            : ""}
        </span>
        <span className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1">
            <i className="h-1.5 w-1.5 rounded-full bg-[var(--sd-accent)]" />
            {t("dashboard.territory.map.scale")}
          </span>
          <span>
            {t("dashboard.territory.map.max")}: {maxTotal}
          </span>
        </span>
      </div>
    </div>
  );
}
