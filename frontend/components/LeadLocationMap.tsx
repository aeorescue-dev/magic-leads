"use client";

import { MapPin, Navigation2 } from "lucide-react";

interface LeadLocationMapProps {
  address: string;
  city?: string;
  compact?: boolean;
  isDark?: boolean;
  mapLabel?: string;
  googleLabel?: string;
  appleLabel?: string;
}

function buildFullAddress(address: string, city?: string): string {
  const parts = [address, city].filter(Boolean);
  return parts.join(", ");
}

function mapsGoogleEmbedUrl(addr: string): string {
  return `https://maps.google.com/maps?q=${encodeURIComponent(addr)}&t=&z=16&ie=UTF8&iwloc=&output=embed`;
}

function mapsGoogleNavUrl(addr: string): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(addr)}`;
}

function mapsAppleNavUrl(addr: string): string {
  return `https://maps.apple.com/?daddr=${encodeURIComponent(addr)}`;
}

export function LeadLocationMap({
  address,
  city,
  compact = false,
  isDark = true,
  mapLabel = "Mapa",
  googleLabel = "Google Maps",
  appleLabel = "Apple Maps",
}: LeadLocationMapProps) {
  const fullAddr = buildFullAddress(address, city);
  const height = compact ? 180 : 300;

  return (
    <div
      className={`rounded-xl border overflow-hidden ${
        isDark ? "border-white/10 bg-white/5" : "border-slate-200 bg-slate-50"
      }`}
    >
      {/* Embedded Map */}
      <div className="relative" style={{ height }}>
        <iframe
          src={mapsGoogleEmbedUrl(fullAddr)}
          width="100%"
          height={height}
          style={{ border: 0 }}
          loading="lazy"
          allowFullScreen
          referrerPolicy="no-referrer-when-downgrade"
          title={mapLabel}
        />
      </div>

      {/* Navigation Buttons */}
      <div className={`flex items-center gap-2 px-3 py-2 border-t ${
        isDark ? "border-white/5" : "border-slate-200"
      }`}>
        <MapPin className={`h-3.5 w-3.5 shrink-0 ${isDark ? "text-slate-400" : "text-slate-500"}`} />
        <span className={`text-xs truncate flex-1 ${isDark ? "text-slate-400" : "text-slate-500"}`}>
          {fullAddr}
        </span>
        <a
          href={mapsGoogleNavUrl(fullAddr)}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-[11px] font-semibold text-sky-400 hover:text-sky-300 transition shrink-0"
        >
          <Navigation2 className="h-3 w-3" /> {googleLabel}
        </a>
        <a
          href={mapsAppleNavUrl(fullAddr)}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-[11px] font-semibold text-slate-400 hover:text-slate-300 transition shrink-0"
        >
          <Navigation2 className="h-3 w-3" /> {appleLabel}
        </a>
      </div>
    </div>
  );
}

export default LeadLocationMap;