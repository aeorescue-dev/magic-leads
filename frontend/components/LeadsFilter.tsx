'use client';

import { useI18n } from "@/lib/i18n";

interface LeadsFilterProps {
  city: string;
  setCity: (city: string) => void;
  category: string;
  setCategory: (cat: string) => void;
  status: string;
  setStatus: (s: string) => void;
  search: string;
  setSearch: (q: string) => void;
  onSearch: () => void;
  cities: string[];
}

const CATEGORIES = ["", "Roof", "Paint", "Plumbing", "Structure", "Grass", "Permit_Rejected"];
const STATUSES = ["", "new", "contacted", "won", "lost", "no_interest"];

export function LeadsFilter({
  city, setCity, category, setCategory, status, setStatus, search, setSearch, onSearch, cities,
}: LeadsFilterProps) {
  const { t } = useI18n();

  const inputCls = "border rounded-lg px-3 py-2 text-sm bg-white";
  const labelCls = "block text-sm font-medium text-gray-700 mb-1";

  return (
    <div className="flex flex-wrap gap-4 mb-6 items-end">
      <div>
        <label className={labelCls}>{t("db.city")}</label>
        <select value={city} onChange={(e) => setCity(e.target.value)} className={inputCls}>
          {(cities && cities.length > 0 ? cities : ["NYC"]).map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      <div>
        <label className={labelCls}>{t("db.category")}</label>
        <select value={category} onChange={(e) => setCategory(e.target.value)} className={inputCls}>
          <option value="">{t("db.all")}</option>
          {CATEGORIES.filter(Boolean).map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      <div>
        <label className={labelCls}>{t("db.filterStatus")}</label>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputCls}>
          <option value="">{t("db.all")}</option>
          {STATUSES.filter(Boolean).map((s) => (
            <option key={s} value={s}>{t(`db.status.${s}`)}</option>
          ))}
        </select>
      </div>

      <div className="flex-1 min-w-[220px]">
        <label className={labelCls}>{t("db.search")}</label>
        <div className="flex gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSearch()}
            placeholder={t("db.search.placeholder")}
            className={`${inputCls} flex-1`}
          />
          <button
            onClick={onSearch}
            className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm"
          >
            {t("db.search")}
          </button>
        </div>
      </div>
    </div>
  );
}
