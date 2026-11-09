"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Command, CornerDownLeft, Search } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface PaletteAction {
  id: string;
  label: string;
  group: string;
  icon: LucideIcon;
  hint?: string;
  run: () => void;
}

export function CommandPalette({
  open,
  onClose,
  actions,
}: {
  open: boolean;
  onClose: () => void;
  actions: PaletteAction[];
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return actions.slice(0, 14);
    return actions
      .filter((action) =>
        `${action.group} ${action.label} ${action.hint || ""}`
          .toLowerCase()
          .includes(term)
      )
      .slice(0, 14);
  }, [actions, query]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    const timer = window.setTimeout(() => inputRef.current?.focus(), 30);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive((prev) => Math.min(prev + 1, Math.max(filtered.length - 1, 0)));
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive((prev) => Math.max(prev - 1, 0));
      }
      if (event.key === "Enter" && filtered[active]) {
        event.preventDefault();
        filtered[active].run();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [active, filtered, onClose, open]);

  if (!open) return null;

  let lastGroup = "";

  return (
    <div className="fixed inset-0 z-[130]" role="dialog" aria-modal="true" aria-label="Command palette">
      <div className="absolute inset-0 bg-black/65 backdrop-blur-[3px]" onClick={onClose} />
      <div className="sd-elevated absolute left-1/2 top-[12vh] w-[min(640px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-2xl">
        <div className="flex items-center gap-2.5 border-b border-[var(--sd-border)] px-4 py-3">
          <Search className="h-4 w-4 text-[var(--sd-faint)]" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            placeholder="Buscar lead, cidade, ofício ou ação…"
            className="w-full bg-transparent text-sm text-[var(--sd-text)] outline-none placeholder:text-[var(--sd-faint)]"
          />
          <kbd className="hidden rounded-md border border-[var(--sd-border)] px-1.5 py-0.5 text-[10px] text-[var(--sd-faint)] sm:inline">
            ESC
          </kbd>
        </div>

        <div className="max-h-[52vh] overflow-y-auto p-1.5">
          {filtered.length === 0 ? (
            <p className="px-3 py-10 text-center text-xs text-[var(--sd-muted)]">
              Nada encontrado para “{query}”.
            </p>
          ) : (
            filtered.map((action, index) => {
              const Icon = action.icon;
              const showGroup = action.group !== lastGroup;
              lastGroup = action.group;
              return (
                <div key={action.id}>
                  {showGroup ? (
                    <div className="px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--sd-faint)]">
                      {action.group}
                    </div>
                  ) : null}
                  <button
                    type="button"
                    onMouseEnter={() => setActive(index)}
                    onClick={() => {
                      action.run();
                      onClose();
                    }}
                    className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition ${
                      index === active
                        ? "bg-[var(--sd-surface-3)] text-[var(--sd-text)]"
                        : "text-[var(--sd-muted)] hover:bg-[var(--sd-surface-2)] hover:text-[var(--sd-text)]"
                    }`}
                  >
                    <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)]">
                      <Icon className="h-3.5 w-3.5" />
                    </span>
                    <span className="flex-1 truncate text-sm font-medium">
                      {action.label}
                    </span>
                    {action.hint ? (
                      <span className="hidden truncate text-[10px] text-[var(--sd-faint)] sm:block">
                        {action.hint}
                      </span>
                    ) : null}
                    {index === active ? (
                      <CornerDownLeft className="h-3.5 w-3.5 text-[var(--sd-faint)]" />
                    ) : null}
                  </button>
                </div>
              );
            })
          )}
        </div>

        <div className="flex items-center justify-between border-t border-[var(--sd-border)] px-4 py-2 text-[10px] text-[var(--sd-faint)]">
          <span className="inline-flex items-center gap-1.5">
            <Command className="h-3 w-3" /> Command palette
          </span>
          <span className="hidden sm:inline">↑ ↓ navegar · Enter abrir · Esc fechar</span>
        </div>
      </div>
    </div>
  );
}
