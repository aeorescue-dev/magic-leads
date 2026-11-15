"use client";

import { useMemo, useState } from "react";
import {
  ArrowUpRight,
  Clock,
  Layers,
  LayoutGrid,
  Map as MapIcon,
  MapPin,
  ShieldAlert,
  Table2,
} from "lucide-react";

import { useI18n } from "@/lib/i18n";

import {
  CITY_LABELS,
  CITY_ORDER,
  TERRITORY_SNAPSHOT,
  daysUntil,
  formatDeadline,
  formatSnapshotDate,
  nicheColor,
  nicheLabel,
  topNiches,
  zoneTitle,
} from "./data";
import { TerritoryMap } from "./TerritoryMap";
import { TerritoryMatrix } from "./TerritoryMatrix";
import type { TerritorySnapshot, TerritoryView, Zone } from "./types";

type ZoneWithFocus = Zone & { focus?: number };

function Kpi({
  label,
  value,
  hint,
  icon,
  tone = "text",
}: {
  label: string;
  value: string;
  hint?: string;
  icon: React.ReactNode;
  tone?: "text" | "accent" | "urgent";
}) {
  const toneClass =
    tone === "accent"
      ? "text-[var(--sd-accent)]"
      : tone === "urgent"
        ? "text-[var(--sd-urgent)]"
        : "text-[var(--sd-text)]";
  return (
    <div className="rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface)] px-3.5 py-3">
      <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-[0.08em] text-[var(--sd-faint)]">
        <span>{label}</span>
        {icon}
      </div>
      <div className={`mt-2 text-[26px] font-black leading-none ${toneClass}`}>{value}</div>
      {hint ? <div className="mt-1.5 text-[10px] text-[var(--sd-muted)]">{hint}</div> : null}
    </div>
  );
}

function NicheBars({ zone, limit = 3 }: { zone: Zone; limit?: number }) {
  const { t } = useI18n();
  const max = Math.max(...zone.niches.map((n) => n.n), 1);
  return (
    <div className="mt-2.5 space-y-1">
      {zone.niches.slice(0, limit).map((niche) => (
        <div key={niche.key} className="grid grid-cols-[1fr_58px_26px] items-center gap-2">
          <span className="truncate text-[9.5px] font-semibold text-[var(--sd-muted)]">
            {nicheLabel(niche.key, t)}
          </span>
          <span className="h-1.5 overflow-hidden rounded-full bg-[var(--sd-surface-3)]">
            <span
              className="block h-full rounded-full"
              style={{
                width: `${Math.max(6, (niche.n / max) * 100)}%`,
                background: nicheColor(niche.key),
              }}
            />
          </span>
          <b className="text-right text-[10px] text-[var(--sd-text)]">{niche.n}</b>
        </div>
      ))}
    </div>
  );
}

function ZoneCard({
  zone,
  activeNiche,
  selected,
  now,
  onSelect,
}: {
  zone: ZoneWithFocus;
  activeNiche: string;
  selected: boolean;
  now: Date;
  onSelect: () => void;
}) {
  const { t } = useI18n();
  const deadline = formatDeadline(zone.next_deadline);
  const days = daysUntil(zone.next_deadline, now);
  const dueSoon = days !== null && days <= 14;
  const focus = zone.focus ?? zone.total;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`group flex w-full flex-col rounded-xl border p-3 text-left transition ${
        selected
          ? "border-[var(--sd-accent)] bg-[var(--sd-surface-2)]"
          : "border-[var(--sd-border)] bg-[var(--sd-surface)] hover:border-[var(--sd-border-strong)] hover:bg-[var(--sd-surface-2)]"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[12.5px] font-bold text-[var(--sd-text)]">
            {zoneTitle(zone, t)}
          </div>
          <div className="mt-0.5 flex items-center gap-1 text-[9.5px] text-[var(--sd-faint)]">
            {zone.label ? (
              <>
                <MapPin className="h-2.5 w-2.5" />
                {zone.zip}
              </>
            ) : null}
            {zone.critical > 0 ? (
              <span className="ml-1 inline-flex items-center gap-0.5 rounded-full bg-[var(--sd-urgent-soft)] px-1.5 py-0.5 text-[8.5px] font-bold text-[var(--sd-urgent)]">
                <ShieldAlert className="h-2.5 w-2.5" />
                {zone.critical}
              </span>
            ) : null}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[22px] font-black leading-none text-[var(--sd-text)]">
            {activeNiche === "all" ? zone.total : focus}
          </div>
          {activeNiche === "all" ? null : (
            <div className="text-[8.5px] text-[var(--sd-faint)]">
              {t("dashboard.territory.card.of")} {zone.total}
            </div>
          )}
        </div>
      </div>

      {activeNiche === "all" ? (
        <NicheBars zone={zone} />
      ) : (
        <div className="mt-2.5 flex items-center gap-2">
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: nicheColor(activeNiche) }}
          />
          <span className="truncate text-[10px] font-semibold text-[var(--sd-muted)]">
            {nicheLabel(activeNiche, t)}
          </span>
        </div>
      )}

      <div className="mt-2.5 flex items-center justify-between border-t border-[var(--sd-border)] pt-2 text-[9px] text-[var(--sd-faint)]">
        <span className="inline-flex items-center gap-1">
          <Clock className="h-2.5 w-2.5" />
          {deadline ? (
            <span className={dueSoon ? "font-bold text-[var(--sd-warn)]" : ""}>
              {t("dashboard.territory.card.next")} {deadline}
            </span>
          ) : (
            t("dashboard.territory.card.no_deadline")
          )}
        </span>
        <span className="inline-flex items-center gap-0.5 font-bold text-[var(--sd-accent)] opacity-0 transition group-hover:opacity-100">
          {t("dashboard.territory.card.open")}
          <ArrowUpRight className="h-2.5 w-2.5" />
        </span>
      </div>
    </button>
  );
}

export function TerritoryBoard({ snapshot = TERRITORY_SNAPSHOT }: { snapshot?: TerritorySnapshot }) {
  const { t } = useI18n();
  const [city, setCity] = useState<string>("Boston");
  const [view, setView] = useState<TerritoryView>("zones");
  const [niche, setNiche] = useState<string>("all");
  const [selectedZip, setSelectedZip] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(null);

  const current = snapshot.cities[city] ?? snapshot.cities.Boston;
  const now = useMemo(() => new Date(snapshot.generated_at), [snapshot.generated_at]);

  const zones = useMemo<ZoneWithFocus[]>(() => {
    const all = current.zones;
    if (niche === "all") return all;
    return all
      .map((zone) => ({
        ...zone,
        focus: zone.niches.find((item) => item.key === niche)?.n ?? 0,
      }))
      .filter((zone) => (zone.focus ?? 0) > 0)
      .sort((a, b) => (b.focus ?? 0) - (a.focus ?? 0));
  }, [current.zones, niche]);

  const effectiveTotal =
    niche === "all"
      ? zones.reduce((sum, zone) => sum + zone.total, 0)
      : zones.reduce((sum, zone) => sum + (zone.focus ?? 0), 0);

  const niches = useMemo(() => topNiches(current.zones, 9), [current.zones]);
  const leadNiche = niches[0];
  const selected = zones.find((zone) => zone.zip === selectedZip) ?? null;

  const views: Array<{ key: TerritoryView; label: string; icon: React.ReactNode }> = [
    { key: "zones", label: t("dashboard.territory.view.zones"), icon: <LayoutGrid className="h-3 w-3" /> },
    { key: "map", label: t("dashboard.territory.view.map"), icon: <MapIcon className="h-3 w-3" /> },
    { key: "matrix", label: t("dashboard.territory.view.matrix"), icon: <Table2 className="h-3 w-3" /> },
  ];

  const selectCity = (next: string) => {
    setCity(next);
    setNiche("all");
    setSelectedZip(null);
    setApplied(null);
  };

  return (
    <div className="min-h-screen bg-[var(--sd-bg)] text-[var(--sd-text)]">
      <header className="sticky top-0 z-30 border-b border-[var(--sd-border)] bg-[var(--sd-bg)]/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1320px] items-center gap-4 px-5 py-2.5">
          <div className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-[var(--sd-accent)] text-[11px] font-black text-[var(--sd-accent-text)]">
              ML
            </span>
            <span className="text-[12px] font-black tracking-tight">MAGIC LEADS</span>
          </div>
          <nav className="hidden items-center gap-1 text-[11px] font-semibold text-[var(--sd-muted)] md:flex">
            {["Overview", "Opportunities", "Territory", "Alerts", "History"].map((item) => (
              <span
                key={item}
                className={
                  item === "Territory"
                    ? "rounded-md bg-[var(--sd-surface-2)] px-2.5 py-1 text-[var(--sd-text)]"
                    : "rounded-md px-2.5 py-1"
                }
              >
                {item === "Territory" ? t("dashboard.territory.title") : item}
              </span>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <span className="rounded-full border border-[var(--sd-warn)]/40 bg-[var(--sd-warn-soft)] px-2 py-0.5 text-[9px] font-black uppercase tracking-[0.1em] text-[var(--sd-warn)]">
              {t("dashboard.territory.preview")}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1320px] px-5 py-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[22px] font-black leading-tight tracking-tight">
              {t("dashboard.territory.heading")}
            </h1>
            <p className="mt-1 max-w-[640px] text-[11.5px] text-[var(--sd-muted)]">
              {t("dashboard.territory.subtitle")}
            </p>
          </div>
          <div className="flex items-center gap-1 rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] p-0.5">
            {CITY_ORDER.filter((name) => snapshot.cities[name]).map((name) => {
              const count = snapshot.cities[name]?.total ?? 0;
              const active = name === city;
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => selectCity(name)}
                  className={`rounded-md px-2.5 py-1 text-[10.5px] font-bold transition ${
                    active
                      ? "bg-[var(--sd-accent)] text-[var(--sd-accent-text)]"
                      : "text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
                  }`}
                >
                  {CITY_LABELS[name] ?? name}
                  <span className={`ml-1 text-[9px] font-black ${active ? "opacity-70" : "text-[var(--sd-faint)]"}`}>
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="mt-3.5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          <Kpi
            label={t("dashboard.territory.kpi.total")}
            value={effectiveTotal.toLocaleString("en-US")}
            hint={`${t("dashboard.territory.kpi.window")}: ${snapshot.window_days}d`}
            icon={<Layers className="h-3.5 w-3.5" />}
            tone="accent"
          />
          <Kpi
            label={t("dashboard.territory.kpi.zones")}
            value={String(zones.length)}
            hint={`${t("dashboard.territory.kpi.coverage")}: ${current.coverage.zones}`}
            icon={<MapPin className="h-3.5 w-3.5" />}
          />
          <Kpi
            label={t("dashboard.territory.kpi.critical")}
            value={String(current.critical)}
            hint={t("dashboard.territory.kpi.critical_hint")}
            icon={<ShieldAlert className="h-3.5 w-3.5" />}
            tone={current.critical > 0 ? "urgent" : "text"}
          />
          <Kpi
            label={t("dashboard.territory.kpi.top_niche")}
            value={leadNiche ? nicheLabel(leadNiche.key, t) : "—"}
            hint={leadNiche ? `${leadNiche.n.toLocaleString("en-US")} ${t("dashboard.territory.kpi.signals")}` : undefined}
            icon={<Table2 className="h-3.5 w-3.5" />}
          />
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => setNiche("all")}
              className={`rounded-full border px-2.5 py-1 text-[10px] font-bold transition ${
                niche === "all"
                  ? "border-[var(--sd-accent)] bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"
                  : "border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
              }`}
            >
              {t("dashboard.territory.filter.all")}
              <span className="ml-1 text-[9px] text-[var(--sd-faint)]">{current.total}</span>
            </button>
            {niches.map((item) => {
              const active = niche === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => {
                    setNiche(active ? "all" : item.key);
                    setApplied(null);
                  }}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold transition ${
                    active
                      ? "border-[var(--sd-accent)] bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"
                      : "border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
                  }`}
                >
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: nicheColor(item.key) }}
                  />
                  {nicheLabel(item.key, t)}
                  <span className="text-[9px] text-[var(--sd-faint)]">{item.n}</span>
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-1 rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] p-0.5">
            {views.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setView(item.key)}
                className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[10px] font-bold transition ${
                  view === item.key
                    ? "bg-[var(--sd-surface-3)] text-[var(--sd-text)]"
                    : "text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
                }`}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {applied ? (
          <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-[var(--sd-accent)]/40 bg-[var(--sd-accent-soft)] px-3 py-2 text-[10.5px] font-semibold text-[var(--sd-accent)]">
            <span>{applied}</span>
            <button type="button" onClick={() => setApplied(null)} className="text-[9px] uppercase tracking-[0.08em] opacity-80">
              {t("dashboard.territory.banner.dismiss")}
            </button>
          </div>
        ) : null}

        <div className="mt-3 grid grid-cols-1 items-start gap-3 xl:grid-cols-[minmax(0,1fr)_318px]">
          <section className="min-w-0">
            {view === "zones" ? (
              zones.length === 0 ? (
                <div className="grid h-[320px] place-items-center rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] text-center">
                  <div className="px-6">
                    <MapPin className="mx-auto h-7 w-7 text-[var(--sd-faint)]" />
                    <p className="mt-2 text-[12px] font-bold">{t("dashboard.territory.empty.title")}</p>
                    <p className="mt-1 text-[10.5px] text-[var(--sd-muted)]">
                      {t("dashboard.territory.empty.body")}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 2xl:grid-cols-3">
                  {zones.map((zone) => (
                    <ZoneCard
                      key={zone.zip}
                      zone={zone}
                      activeNiche={niche}
                      selected={zone.zip === selectedZip}
                      now={now}
                      onSelect={() => {
                        setSelectedZip(zone.zip);
                        setApplied(null);
                      }}
                    />
                  ))}
                </div>
              )
            ) : view === "map" ? (
              <TerritoryMap
                zones={zones}
                selectedZip={selectedZip}
                onSelect={(zip) => {
                  setSelectedZip(zip);
                  setApplied(null);
                }}
                t={t}
              />
            ) : (
              <TerritoryMatrix
                zones={zones}
                selectedZip={selectedZip}
                onSelect={(zip) => {
                  setSelectedZip(zip);
                  setApplied(null);
                }}
                t={t}
              />
            )}
          </section>

          <aside className="rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-3.5 xl:sticky xl:top-[58px]">
            {selected ? (
              <>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h2 className="text-[13px] font-bold leading-tight">{zoneTitle(selected, t)}</h2>
                    <p className="mt-0.5 flex items-center gap-1 text-[9.5px] text-[var(--sd-faint)]">
                      <MapPin className="h-2.5 w-2.5" />
                      {selected.label ? `${selected.zip} · ${city}` : city}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setSelectedZip(null)}
                    className="text-[9px] font-bold uppercase tracking-[0.07em] text-[var(--sd-faint)] hover:text-[var(--sd-text)]"
                  >
                    {t("dashboard.territory.detail.close")}
                  </button>
                </div>

                <div className="mt-3 grid grid-cols-3 gap-1.5">
                  {[
                    { label: t("dashboard.territory.detail.total"), value: selected.total },
                    { label: t("dashboard.territory.detail.available"), value: selected.available },
                    { label: t("dashboard.territory.detail.critical"), value: selected.critical },
                  ].map((item) => (
                    <div key={item.label} className="rounded-lg bg-[var(--sd-surface-2)] px-2 py-1.5">
                      <div className="text-[8.5px] uppercase tracking-[0.05em] text-[var(--sd-faint)]">
                        {item.label}
                      </div>
                      <div className="text-[16px] font-black leading-tight">{item.value}</div>
                    </div>
                  ))}
                </div>

                <div className="mt-2.5 flex items-center gap-1.5 rounded-lg bg-[var(--sd-surface-2)] px-2 py-1.5 text-[9.5px] text-[var(--sd-muted)]">
                  <Clock className="h-3 w-3 text-[var(--sd-faint)]" />
                  {selected.next_deadline
                    ? `${t("dashboard.territory.detail.deadline")}: ${formatDeadline(selected.next_deadline)}`
                    : t("dashboard.territory.card.no_deadline")}
                </div>

                <div className="mt-3">
                  <div className="flex items-center justify-between text-[9px] font-bold uppercase tracking-[0.07em] text-[var(--sd-faint)]">
                    <span>{t("dashboard.territory.detail.niches")}</span>
                    <span>{selected.niches.length}</span>
                  </div>
                  <div className="mt-2 space-y-1.5">
                    {selected.niches.map((item) => {
                      const pct = Math.max(4, (item.n / Math.max(selected.total, 1)) * 100);
                      return (
                        <div key={item.key} className="grid grid-cols-[1fr_46px_24px] items-center gap-2">
                          <span className="truncate text-[10px] font-semibold text-[var(--sd-muted)]">
                            {nicheLabel(item.key, t)}
                          </span>
                          <span className="h-1.5 overflow-hidden rounded-full bg-[var(--sd-surface-3)]">
                            <span
                              className="block h-full rounded-full"
                              style={{ width: `${pct}%`, background: nicheColor(item.key) }}
                            />
                          </span>
                          <b className="text-right text-[10px]">{item.n}</b>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() =>
                    setApplied(
                      t("dashboard.territory.detail.applied")
                        .replace("{city}", city)
                        .replace("{zip}", selected.zip)
                        .replace("{niche}", niche === "all" ? t("dashboard.territory.filter.all") : nicheLabel(niche, t))
                    )
                  }
                  className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg bg-[var(--sd-accent)] px-3 py-2 text-[10.5px] font-black text-[var(--sd-accent-text)] transition hover:bg-[var(--sd-accent-strong)]"
                >
                  {t("dashboard.territory.detail.apply")}
                  <ArrowUpRight className="h-3 w-3" />
                </button>
                <p className="mt-1.5 text-center text-[8.5px] leading-snug text-[var(--sd-faint)]">
                  {t("dashboard.territory.detail.apply_note")}
                </p>
              </>
            ) : (
              <>
                <h2 className="text-[11px] font-bold uppercase tracking-[0.07em] text-[var(--sd-faint)]">
                  {t("dashboard.territory.detail.ranking")}
                </h2>
                <p className="mt-1 text-[9.5px] text-[var(--sd-muted)]">{t("dashboard.territory.detail.hint")}</p>
                <div className="mt-2.5 space-y-0.5">
                  {zones.slice(0, 7).map((zone, index) => (
                    <button
                      key={zone.zip}
                      type="button"
                      onClick={() => setSelectedZip(zone.zip)}
                      className="flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left transition hover:bg-[var(--sd-surface-2)]"
                    >
                      <span className="w-3 text-[9px] font-black text-[var(--sd-faint)]">{index + 1}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[10.5px] font-bold">
                          {zoneTitle(zone, t)}
                        </span>
                        {zone.label ? (
                        <span className="block text-[9px] text-[var(--sd-faint)]">{zone.zip}</span>
                      ) : null}
                      </span>
                      <b className="text-[10.5px] text-[var(--sd-accent)]">
                        {niche === "all" ? zone.total : zone.focus}
                      </b>
                    </button>
                  ))}
                </div>
                <div className="mt-3 rounded-lg border border-dashed border-[var(--sd-border)] px-2.5 py-2 text-[9px] leading-snug text-[var(--sd-faint)]">
                  {t("dashboard.territory.detail.empty")}
                </div>
              </>
            )}
          </aside>
        </div>

        <footer className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--sd-border)] pt-2.5 text-[9px] text-[var(--sd-faint)]">
          <span>
            {t("dashboard.territory.footer")
              .replace("{date}", formatSnapshotDate(snapshot.generated_at))
              .replace("{days}", String(snapshot.window_days))}
          </span>
          <span>
            {t("dashboard.territory.coverage")
              .replace("{geo}", String(current.coverage.zones_with_local_geo))
              .replace("{zones}", String(current.coverage.zones))}
          </span>
        </footer>
      </main>
    </div>
  );
}
