"use client";

import {
  useEffect,
  useRef,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { Check, ChevronDown, X, type LucideIcon } from "lucide-react";

export function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ buttons */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "icon";

const buttonVariant: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--sd-accent)] text-[var(--sd-accent-text)] hover:bg-[var(--sd-accent-strong)]",
  secondary:
    "bg-[var(--sd-surface-2)] text-[var(--sd-text)] border border-[var(--sd-border)] hover:border-[var(--sd-border-strong)]",
  ghost:
    "bg-transparent text-[var(--sd-muted)] hover:text-[var(--sd-text)] hover:bg-[var(--sd-surface-2)]",
  danger:
    "bg-[var(--sd-urgent-soft)] text-[var(--sd-urgent)] border border-[var(--sd-urgent)]/30 hover:bg-[var(--sd-urgent)]/20",
};

const buttonSize: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs gap-1.5 rounded-lg",
  md: "h-10 px-4 text-sm gap-2 rounded-xl",
  icon: "h-9 w-9 rounded-xl",
};

export function SignalButton({
  variant = "primary",
  size = "md",
  icon: Icon,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: LucideIcon;
}) {
  return (
    <button
      className={cn(
        "sd-focus inline-flex items-center justify-center font-semibold transition-all duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-45",
        buttonVariant[variant],
        buttonSize[size],
        className
      )}
      {...props}
    >
      {Icon ? <Icon className={size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"} /> : null}
      {children}
    </button>
  );
}

export function SignalIconButton({
  icon: Icon,
  label,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  icon: LucideIcon;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        "sd-focus inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface)] text-[var(--sd-muted)] transition hover:border-[var(--sd-border-strong)] hover:text-[var(--sd-text)]",
        className
      )}
      {...props}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}

/* --------------------------------------------------------------------- chips */

export function SignalChip({
  active = false,
  icon: Icon,
  count,
  children,
  className,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  active?: boolean;
  icon?: LucideIcon;
  count?: number | string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      className={cn(
        "sd-focus inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 text-xs font-semibold transition-all duration-150",
        active
          ? "border-[var(--sd-accent)]/45 bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"
          : "border-[var(--sd-border)] bg-transparent text-[var(--sd-muted)] hover:border-[var(--sd-border-strong)] hover:text-[var(--sd-text)]",
        disabled && "cursor-not-allowed opacity-35",
        className
      )}
      {...props}
    >
      {Icon ? <Icon className="h-3.5 w-3.5" /> : null}
      {children}
      {count !== undefined && count !== null ? (
        <span className="sd-tabular ml-0.5 text-[10px] opacity-70">{count}</span>
      ) : null}
    </button>
  );
}

/* ------------------------------------------------------------ segmented bars */

export interface SegmentOption {
  value: string;
  label: string;
  icon?: LucideIcon;
  tone?: "default" | "urgent" | "warn" | "muted";
}

export function SegmentedControl({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  options: SegmentOption[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex h-9 items-center gap-0.5 rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-0.5",
        className
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        const Icon = option.icon;
        const tone =
          option.tone === "urgent"
            ? "text-[var(--sd-urgent)]"
            : option.tone === "warn"
              ? "text-[var(--sd-warn)]"
              : option.tone === "muted"
                ? "text-[var(--sd-muted)]"
                : "text-[var(--sd-accent)]";
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "sd-focus inline-flex h-8 items-center gap-1.5 rounded-[10px] px-3 text-xs font-semibold transition-all duration-200",
              active
                ? "bg-[var(--sd-surface-3)] text-[var(--sd-text)] shadow-sm"
                : "text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
            )}
          >
            {Icon ? <Icon className={cn("h-3.5 w-3.5", active && tone)} /> : null}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------- badges */

type BadgeTone = "neutral" | "accent" | "urgent" | "warn" | "info" | "success";

const badgeTone: Record<BadgeTone, string> = {
  neutral: "bg-[var(--sd-surface-2)] text-[var(--sd-muted)] border-[var(--sd-border)]",
  accent: "bg-[var(--sd-accent-soft)] text-[var(--sd-accent)] border-[var(--sd-accent)]/25",
  urgent: "bg-[var(--sd-urgent-soft)] text-[var(--sd-urgent)] border-[var(--sd-urgent)]/25",
  warn: "bg-[var(--sd-warn-soft)] text-[var(--sd-warn)] border-[var(--sd-warn)]/25",
  info: "bg-[var(--sd-info-soft)] text-[var(--sd-info)] border-[var(--sd-info)]/25",
  success: "bg-emerald-500/10 text-[var(--sd-success)] border-emerald-500/25",
};

export function SignalBadge({
  children,
  tone = "neutral",
  icon: Icon,
  className,
}: {
  children: ReactNode;
  tone?: BadgeTone;
  icon?: LucideIcon;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider",
        badgeTone[tone],
        className
      )}
    >
      {Icon ? <Icon className="h-3 w-3" /> : null}
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------- popover */

export function Popover({
  open,
  onClose,
  trigger,
  children,
  align = "start",
  className,
}: {
  open: boolean;
  onClose: () => void;
  trigger: ReactNode;
  children: ReactNode;
  align?: "start" | "end";
  className?: string;
}) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  return (
    <div ref={rootRef} className="relative">
      {trigger}
      {open ? (
        <div
          role="dialog"
          className={cn(
            "sd-elevated absolute top-[calc(100%+8px)] z-[90] min-w-[220px] overflow-hidden rounded-2xl p-1.5",
            align === "end" ? "right-0" : "left-0",
            className
          )}
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}

/* --------------------------------------------------------------------- sheet */

export function Sheet({
  open,
  onClose,
  title,
  description,
  side = "right",
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  side?: "right" | "bottom";
  children: ReactNode;
  footer?: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const timeout = window.setTimeout(() => panelRef.current?.focus(), 20);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.clearTimeout(timeout);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100]" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-[2px]" onClick={onClose} />
      <div
        ref={panelRef}
        tabIndex={-1}
        className={cn(
          "sd-motion absolute flex flex-col border border-[var(--sd-border)] bg-[var(--sd-surface)] text-[var(--sd-text)] shadow-[var(--sd-shadow)] outline-none",
          side === "right"
            ? "right-0 top-0 h-full w-full max-w-[440px] rounded-l-2xl"
            : "bottom-0 left-0 right-0 max-h-[88vh] rounded-t-2xl"
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-[var(--sd-border)] px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold">{title}</h2>
            {description ? (
              <p className="mt-0.5 text-xs text-[var(--sd-muted)]">{description}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="sd-focus rounded-lg p-1.5 text-[var(--sd-muted)] hover:bg-[var(--sd-surface-2)] hover:text-[var(--sd-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? (
          <div className="border-t border-[var(--sd-border)] px-5 py-3">{footer}</div>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ skeleton */

export function SignalSkeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "animate-pulse rounded-lg bg-[var(--sd-surface-2)]",
        className
      )}
    />
  );
}

/* -------------------------------------------------------------- list helpers */

export function SignalMenuCheck({ active }: { active?: boolean }) {
  return (
    <span
      className={cn(
        "flex h-4 w-4 items-center justify-center rounded-full border",
        active
          ? "border-[var(--sd-accent)] bg-[var(--sd-accent)] text-[var(--sd-accent-text)]"
          : "border-[var(--sd-border-strong)] text-transparent"
      )}
    >
      <Check className="h-3 w-3" />
    </span>
  );
}

export function SignalChevron() {
  return <ChevronDown className="h-3.5 w-3.5 opacity-60" />;
}
