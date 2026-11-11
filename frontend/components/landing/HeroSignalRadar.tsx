"use client";

import { useEffect, useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { fetchActivity, type ActivityEvent } from "@/lib/api-client";

export function HeroSignalRadar({
  labelsByKey,
  onOpen,
}: {
  labelsByKey: Record<string, string>;
  onOpen: () => void;
}) {
  const { t } = useI18n();
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchActivity()
      .then((res) => {
        if (cancelled) return;
        setEvents(res.events);
        setIndex(0);
      })
      .catch(() => {
        if (!cancelled) setEvents([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (events.length <= 1) return;
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % events.length);
    }, 7000);
    return () => window.clearInterval(timer);
  }, [events]);

  const event = events[index % Math.max(1, events.length)];
  const trade = event ? labelsByKey[event.trade] || event.trade : "";
  const place = event ? `${event.place || event.city}${event.zip ? ` · ${event.zip}` : ""}` : "";
  const time = useMemo(() => {
    if (!event) return "";
    if (event.minutes_ago < 1) return t("landing.activityJustNow");
    if (event.minutes_ago < 60) {
      return t("landing.activityMinAgo").replace("{n}", String(event.minutes_ago));
    }
    return t("landing.activityHourAgo").replace(
      "{n}",
      String(Math.round(event.minutes_ago / 60))
    );
  }, [event, t]);

  return (
    <div className="relative overflow-hidden rounded-[1.9rem] border border-white/10 bg-[#06090f] text-white shadow-[0_50px_120px_-55px_rgba(2,6,23,0.9)]">
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px)",
          backgroundSize: "34px 34px",
        }}
      />
      <span className="pointer-events-none absolute left-3 top-3 h-4 w-4 border-l border-t border-[#34e0a1]/50" />
      <span className="pointer-events-none absolute right-3 top-3 h-4 w-4 border-r border-t border-[#34e0a1]/50" />
      <span className="pointer-events-none absolute bottom-3 left-3 h-4 w-4 border-b border-l border-[#34e0a1]/50" />
      <span className="pointer-events-none absolute bottom-3 right-3 h-4 w-4 border-b border-r border-[#34e0a1]/50" />

      <div className="relative p-5 sm:p-6">
        <div className="flex items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2 text-[8.5px] font-black uppercase tracking-[0.18em] text-[#34e0a1]">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#34e0a1] opacity-50" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-[#34e0a1]" />
            </span>
            {t("landing.hudKicker")}
          </span>
          <span className="rounded-full border border-white/10 px-2.5 py-1 text-[7.5px] font-black uppercase tracking-[0.14em] text-white/35">
            {t("landing.hudSecure")}
          </span>
        </div>

        <div className="relative mx-auto mt-5 aspect-square w-full max-w-[310px]">
          <div className="absolute inset-0 rounded-full border border-white/10" />
          <div className="absolute inset-[13%] rounded-full border border-white/10" />
          <div className="absolute inset-[27%] rounded-full border border-white/10" />
          <div className="absolute inset-[41%] rounded-full border border-white/10" />
          <div className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-white/[0.07]" />
          <div className="absolute left-0 top-1/2 h-px w-full -translate-y-1/2 bg-white/[0.07]" />
          <div className="absolute inset-0 overflow-hidden rounded-full">
            <div
              className="radar-sweep absolute inset-0"
              style={{
                background:
                  "conic-gradient(from 0deg, rgba(52,224,161,0.32), rgba(52,224,161,0.06) 24%, transparent 42%, transparent 100%)",
              }}
            />
            <div
              className="absolute inset-0 rounded-full"
              style={{
                background:
                  "radial-gradient(circle, transparent 48%, rgba(6,9,15,0.8) 100%)",
              }}
            />
          </div>
          <span className="absolute left-[64%] top-[28%] h-1.5 w-1.5 rounded-full bg-[#34e0a1] shadow-[0_0_14px_#34e0a1]" />
          <span className="radar-ping absolute left-[64%] top-[28%] h-1.5 w-1.5 rounded-full bg-[#34e0a1]" />
          <span className="absolute left-[32%] top-[62%] h-1 w-1 rounded-full bg-[#a78bfa]/80" />
          <span className="absolute left-[72%] top-[70%] h-1 w-1 rounded-full bg-[#34e0a1]/60" />
          <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
            <span className="absolute -inset-3 rounded-full bg-[#34e0a1]/10 blur-md" />
            <span className="relative grid h-9 w-9 place-items-center rounded-full border border-[#34e0a1]/40 bg-[#07110d]">
              <span className="h-2 w-2 rounded-full bg-[#34e0a1] shadow-[0_0_16px_#34e0a1]" />
            </span>
          </div>
        </div>

        <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.045] p-3.5 backdrop-blur-md">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[8px] font-black uppercase tracking-[0.16em] text-[#34e0a1]">
              {t("landing.hudLocked")}
            </span>
            <span className="text-[8px] font-bold uppercase tracking-[0.1em] text-white/35">
              {event ? time : t("landing.hudScanning")}
            </span>
          </div>
          <p className="mt-1.5 truncate text-[14px] font-bold text-white">
            {event ? `${trade} · ${place}` : t("landing.hudScanning")}
          </p>
        </div>

        <div className="mt-3 grid grid-cols-3 gap-2">
          <div className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-2.5 text-center">
            <p className="mono-data text-[11px] font-black text-[#34e0a1]">1/1</p>
            <p className="mt-1 text-[6.5px] font-bold uppercase tracking-[0.08em] text-white/35">
              {t("landing.hudExclusive")}
            </p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-2.5 text-center">
            <p className="mono-data text-[11px] font-black text-white">✓</p>
            <p className="mt-1 text-[6.5px] font-bold uppercase tracking-[0.08em] text-white/35">
              {t("landing.hudOwner")}
            </p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.03] px-2 py-2.5 text-center">
            <p className="mono-data text-[11px] font-black text-white">01h</p>
            <p className="mt-1 text-[6.5px] font-bold uppercase tracking-[0.08em] text-white/35">
              {t("landing.hudFirst")}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={onOpen}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl border border-[#34e0a1]/25 bg-[#34e0a1]/10 px-4 py-3 text-[9.5px] font-black uppercase tracking-[0.12em] text-[#34e0a1] transition hover:bg-[#34e0a1] hover:text-[#04120d]"
        >
          {t("landing.hudCta")}
          <span aria-hidden>→</span>
        </button>
      </div>
    </div>
  );
}
