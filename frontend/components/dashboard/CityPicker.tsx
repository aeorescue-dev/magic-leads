"use client";

import { useMemo, useState } from "react";
import { MapPin, Search } from "lucide-react";
import {
  Popover,
  SignalButton,
  SignalChevron,
  SignalMenuCheck,
} from "@/components/ui/signal";

export interface CityOption {
  value: string;
  label: string;
  count?: number;
}

export function CityPicker({
  value,
  options,
  onChange,
  allLabel = "Todas as cidades",
}: {
  value: string;
  options: CityOption[];
  onChange: (value: string) => void;
  allLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const current = options.find((option) => option.value === value);
  const label =
    value === "all" ? allLabel : current?.label || value;

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return options;
    return options.filter((option) =>
      option.label.toLowerCase().includes(term)
    );
  }, [options, query]);

  return (
    <Popover
      open={open}
      onClose={() => {
        setOpen(false);
        setQuery("");
      }}
      align="start"
      className="w-[300px]"
      trigger={
        <SignalButton
          type="button"
          variant="secondary"
          size="sm"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen((prev) => !prev)}
          className="max-w-[190px] justify-between"
        >
          <MapPin className="h-3.5 w-3.5 text-[var(--sd-accent)]" />
          <span className="truncate">{label}</span>
          <SignalChevron />
        </SignalButton>
      }
    >
      <div className="p-1">
        <div className="flex items-center gap-2 rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] px-2.5 py-2">
          <Search className="h-3.5 w-3.5 text-[var(--sd-faint)]" />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Buscar cidade…"
            className="w-full bg-transparent text-xs text-[var(--sd-text)] outline-none placeholder:text-[var(--sd-faint)]"
          />
        </div>
        <div className="mt-1 max-h-64 overflow-y-auto">
          {filtered.map((option) => {
            const active = option.value === value;
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                  setQuery("");
                }}
                className="sd-focus flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs font-medium text-[var(--sd-text)] transition hover:bg-[var(--sd-surface-2)]"
              >
                <SignalMenuCheck active={active} />
                <span className="flex-1 truncate">
                  {option.value === "all" ? allLabel : option.label}
                </span>
                {typeof option.count === "number" ? (
                  <span className="sd-tabular text-[10px] text-[var(--sd-faint)]">
                    {option.count.toLocaleString()}
                  </span>
                ) : null}
              </button>
            );
          })}
          {filtered.length === 0 ? (
            <p className="px-2.5 py-6 text-center text-xs text-[var(--sd-muted)]">
              Sem cidades correspondentes.
            </p>
          ) : null}
        </div>
      </div>
    </Popover>
  );
}
