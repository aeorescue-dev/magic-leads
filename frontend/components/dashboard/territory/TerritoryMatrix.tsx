"use client";

import { useMemo } from "react";

import { nicheColor, nicheLabel, topNiches } from "./data";
import type { Zone } from "./types";

export function TerritoryMatrix({
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
  const columns = useMemo(() => topNiches(zones, 7), [zones]);
  const maxCell = useMemo(() => {
    let max = 1;
    for (const zone of zones) {
      for (const column of columns) {
        const value = zone.niches.find((n) => n.key === column.key)?.n ?? 0;
        if (value > max) max = value;
      }
    }
    return max;
  }, [zones, columns]);

  if (zones.length === 0 || columns.length === 0) {
    return (
      <div className="grid h-[320px] place-items-center rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] text-xs text-[var(--sd-muted)]">
        {t("dashboard.territory.matrix.empty")}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)]">
      <div className="flex items-center justify-between border-b border-[var(--sd-border)] px-4 py-3">
        <div>
          <h3 className="text-sm font-bold">{t("dashboard.territory.matrix.title")}</h3>
          <p className="mt-0.5 text-[10px] text-[var(--sd-muted)]">
            {t("dashboard.territory.matrix.note")}
          </p>
        </div>
        <span className="text-[10px] text-[var(--sd-faint)]">
          {t("dashboard.territory.matrix.zones")}: {zones.length}
        </span>
      </div>

      <div className="max-h-[560px] overflow-auto">
        <table className="w-full border-separate border-spacing-0 text-left">
          <thead>
            <tr>
              <th className="sticky left-0 top-0 z-20 min-w-[132px] border-b border-[var(--sd-border)] bg-[var(--sd-surface)] px-3 py-2 text-[10px] font-bold uppercase tracking-[0.06em] text-[var(--sd-faint)]">
                {t("dashboard.territory.matrix.zone")}
              </th>
              {columns.map((column) => (
                <th
                  key={column.key}
                  title={nicheLabel(column.key, t)}
                  className="sticky top-0 z-10 min-w-[76px] border-b border-[var(--sd-border)] bg-[var(--sd-surface)] px-1.5 py-2 align-bottom text-[9px] font-bold leading-tight text-[var(--sd-muted)]"
                >
                  <span
                    className="mx-auto mb-1 block h-1.5 w-1.5 rounded-full"
                    style={{ background: nicheColor(column.key) }}
                  />
                  {nicheLabel(column.key, t)}
                </th>
              ))}
              <th className="sticky right-0 top-0 z-20 min-w-[58px] border-b border-[var(--sd-border)] bg-[var(--sd-surface)] px-2 py-2 text-right text-[10px] font-bold uppercase tracking-[0.06em] text-[var(--sd-faint)]">
                {t("dashboard.territory.matrix.total")}
              </th>
            </tr>
          </thead>
          <tbody>
            {zones.map((zone) => {
              const selected = zone.zip === selectedZip;
              return (
                <tr
                  key={zone.zip}
                  onClick={() => onSelect(zone.zip)}
                  className={`cursor-pointer transition-colors ${
                    selected ? "bg-[var(--sd-surface-2)]" : "hover:bg-[var(--sd-surface-2)]"
                  }`}
                >
                  <th
                    scope="row"
                    className={`sticky left-0 z-10 border-b border-[var(--sd-border)] px-3 py-2 text-left ${
                      selected ? "bg-[var(--sd-surface-2)]" : "bg-[var(--sd-surface)]"
                    }`}
                  >
                    <span className="block text-[11px] font-bold text-[var(--sd-text)]">
                      {zone.label ?? zone.zip}
                    </span>
                    <span className="block text-[9px] text-[var(--sd-faint)]">
                      {zone.label ? zone.zip : t("dashboard.territory.matrix.zone")}
                    </span>
                  </th>
                  {columns.map((column) => {
                    const value = zone.niches.find((n) => n.key === column.key)?.n ?? 0;
                    const alpha = value === 0 ? 0 : 0.08 + 0.34 * (value / maxCell);
                    return (
                      <td
                        key={column.key}
                        className="border-b border-[var(--sd-border)] px-1 py-1.5 text-center"
                      >
                        <span
                          className="mx-auto grid h-7 min-w-[46px] place-items-center rounded-md text-[10px] font-bold"
                          style={{
                            background:
                              value === 0
                                ? "transparent"
                                : `rgba(94, 234, 212, ${alpha.toFixed(3)})`,
                            color: value === 0 ? "var(--sd-faint)" : "var(--sd-text)",
                          }}
                        >
                          {value === 0 ? "·" : value}
                        </span>
                      </td>
                    );
                  })}
                  <td
                    className={`sticky right-0 z-10 border-b border-[var(--sd-border)] px-2 py-2 text-right text-[11px] font-black ${
                      selected ? "bg-[var(--sd-surface-2)]" : "bg-[var(--sd-surface)]"
                    }`}
                  >
                    {zone.total}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
