'use client';

import { useI18n } from "@/lib/i18n";
import { Button } from "./ui/Button";
import { Search } from "lucide-react";

interface LocationHierarchy {
  [country: string]: {
    name: string;
    states: Record<string, {
      name: string;
      cities: Record<string, { name: string; count: number }>;
      count: number;
    }>;
  };
}

interface HierarchicalFilterProps {
  hierarchy: LocationHierarchy;
  selectedCountry: string;
  setSelectedCountry: (country: string) => void;
  selectedState: string;
  setSelectedState: (state: string) => void;
  selectedCity: string;
  setSelectedCity: (city: string) => void;
  onSearch: () => void;
}

const selectCls =
  "h-10 w-full rounded-lg border bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-colors";

export function HierarchicalFilter({
  hierarchy,
  selectedCountry,
  setSelectedCountry,
  selectedState,
  setSelectedState,
  selectedCity,
  setSelectedCity,
  onSearch,
}: HierarchicalFilterProps) {
  const { t } = useI18n();

  const states = hierarchy[selectedCountry]?.states || {};
  const cities = states[selectedState]?.cities || {};
  const effectiveState = selectedState || Object.keys(states)[0] || "";
  const effectiveCity = selectedCity || Object.keys(cities)[0] || "";

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 items-end">
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">{t("db.filter.country")}</label>
        <select
          value={selectedCountry}
          onChange={(e) => {
            const c = e.target.value;
            setSelectedCountry(c);
            const newStates = hierarchy[c]?.states || {};
            const fState = Object.keys(newStates)[0] || "";
            setSelectedState(fState);
            setSelectedCity(newStates[fState]?.cities ? Object.keys(newStates[fState].cities)[0] : "");
          }}
          className={selectCls}
        >
          {Object.entries(hierarchy).map(([code, data]) => (
            <option key={code} value={code}>{data.name}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">{t("db.filter.state")}</label>
        <select
          value={effectiveState}
          onChange={(e) => {
            const s = e.target.value;
            setSelectedState(s);
            const newCities = states[s]?.cities || {};
            setSelectedCity(Object.keys(newCities)[0] || "");
          }}
          className={selectCls}
        >
          {Object.entries(states).map(([code, data]) => (
            <option key={code} value={code}>{data.name} ({data.count})</option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">{t("db.filter.city")}</label>
        <select
          value={effectiveCity}
          onChange={(e) => setSelectedCity(e.target.value)}
          className={selectCls}
        >
          {Object.entries(cities).map(([c, data]) => (
            <option key={c} value={c}>{c} ({data.count})</option>
          ))}
        </select>
      </div>

      <div>
        <Button onClick={onSearch} className="w-full" icon={Search}>
          {t("db.search")}
        </Button>
      </div>
    </div>
  );
}
