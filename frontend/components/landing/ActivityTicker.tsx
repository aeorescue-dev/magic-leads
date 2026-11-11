"use client";

import { useEffect, useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { fetchActivity, type ActivityEvent } from "@/lib/api-client";

export function ActivityTicker({
  labelsByKey,
}: {
  labelsByKey: Record<string, string>;
}) {
  const { t } = useI18n();
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let geoCity: string | null = null;
      try {
        const geo = await fetch("/geolocation");
        if (geo.ok) {
          const payload = await geo.json();
          geoCity = typeof payload?.city === "string" ? payload.city : null;
        }
      } catch {
        geoCity = null;
      }

      try {
        let res = await fetchActivity(geoCity ?? undefined);
        if (!res.events.length && geoCity) {
          res = await fetchActivity();
        }
        if (!cancelled) {
          setEvents(res.events);
          setIndex(0);
        }
      } catch {
        if (!cancelled) setEvents([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (events.length <= 1) return;
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % events.length);
    }, 6000);
    return () => window.clearInterval(timer);
  }, [events]);

  const event = events[index % Math.max(1, events.length)];
  const message = useMemo(() => {
    if (!event) return "";
    const mins = event.minutes_ago;
    const time =
      mins < 1
        ? t("landing.activityJustNow")
        : mins < 60
          ? t("landing.activityMinAgo").replace("{n}", String(mins))
          : t("landing.activityHourAgo").replace("{n}", String(Math.round(mins / 60)));
    const place = event.zip ? `${event.place} (ZIP ${event.zip})` : event.place;
    const trade = labelsByKey[event.trade] || event.trade;
    const template =
      event.action === "updated"
        ? t("landing.activityUpdated")
        : t("landing.activityCaptured");
    return template
      .replace("{trade}", trade)
      .replace("{place}", place)
      .replace("{time}", time);
  }, [event, labelsByKey, t]);

  return (
    <div
      className="mx-auto mt-5 flex max-w-4xl items-center gap-3 rounded-2xl border border-[#34e0a1]/20 bg-[#0b1220] px-5 py-3 text-white shadow-[0_18px_45px_-28px_rgba(15,23,42,0.65)]"
      aria-live="polite"
    >
      <span className="relative flex h-2 w-2 shrink-0">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#34e0a1] opacity-50" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-[#34e0a1]" />
      </span>
      <span className="hidden shrink-0 text-[9px] font-bold uppercase tracking-[0.14em] text-[#34e0a1] sm:block">
        {t("landing.activityLive")}
      </span>
      <span key={index} className="p1-ticker-in min-w-0 flex-1 text-[12px] leading-snug text-white/75">
        {event ? message : loading ? t("landing.activityLoading") : t("landing.activityEmpty")}
      </span>
      {event && (
        <span className="hidden shrink-0 rounded-full border border-white/10 px-2 py-0.5 text-[8.5px] font-bold uppercase tracking-[0.1em] text-white/35 sm:block">
          {event.city}
        </span>
      )}
    </div>
  );
}
