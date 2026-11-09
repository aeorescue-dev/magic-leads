"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";

import LpFlag from "./LpFlag";
import { WIDGET_LANGS, type WidgetLang } from "./i18n";

interface Props {
  lang: WidgetLang;
  onChange: (lang: WidgetLang) => void;
  title: string;
  searchPlaceholder: string;
  emptyLabel: string;
}

export default function LpLanguagePicker({
  lang,
  onChange,
  title,
  searchPlaceholder,
  emptyLabel,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const current = WIDGET_LANGS.find((item) => item.code === lang) ?? WIDGET_LANGS[0];

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return WIDGET_LANGS;
    return WIDGET_LANGS.filter((item) =>
      `${item.label} ${item.native} ${item.code}`.toLowerCase().includes(needle)
    );
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => inputRef.current?.focus(), 30);
    const onDoc = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function select(code: WidgetLang) {
    onChange(code);
    setOpen(false);
    setQuery("");
  }

  return (
    <div ref={wrapRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={title}
        className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[10px] font-bold text-slate-600 transition hover:border-emerald-300 hover:text-slate-900"
      >
        <LpFlag code={current.flag} className="h-3 w-4" />
        <span className="uppercase">{current.code}</span>
        <ChevronDown
          className={`h-3 w-3 text-slate-400 transition ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-[95] mt-1 w-60 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl shadow-slate-900/10">
          <div className="border-b border-slate-100 p-2">
            <div className="flex items-center gap-1.5 rounded-lg bg-slate-50 px-2 py-1.5">
              <Search className="h-3.5 w-3.5 shrink-0 text-slate-400" />
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={searchPlaceholder}
                aria-label={searchPlaceholder}
                className="w-full bg-transparent text-[11px] text-slate-800 outline-none placeholder:text-slate-400"
              />
            </div>
          </div>
          <ul role="listbox" aria-label={title} className="max-h-56 overflow-y-auto p-1">
            {filtered.map((item) => (
              <li key={item.code}>
                <button
                  type="button"
                  role="option"
                  aria-selected={item.code === lang}
                  onClick={() => select(item.code)}
                  className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[11.5px] transition ${
                    item.code === lang
                      ? "bg-emerald-50 text-emerald-900"
                      : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <LpFlag code={item.flag} className="h-3.5 w-5 shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold">{item.native}</span>
                    <span className="block text-[9.5px] text-slate-400">
                      {item.label}
                    </span>
                  </span>
                  {item.code === lang && (
                    <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
                  )}
                </button>
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="px-3 py-4 text-center text-[10.5px] text-slate-400">
                {emptyLabel}
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
