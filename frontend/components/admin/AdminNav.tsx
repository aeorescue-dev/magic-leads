"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Activity,
  BarChart3,
  Database,
  Inbox,
  LayoutDashboard,
  Phone,
  Sparkles,
  Wallet,
} from "lucide-react";

const LINKS = [
  { href: "/admin", label: "Overview", icon: LayoutDashboard },
  { href: "/admin/lp-inbox", label: "LP Inbox", icon: Inbox },
  { href: "/admin/data-plane", label: "Data Plane", icon: Database },
  { href: "/admin/voice", label: "Voice B2B", icon: Phone },
  { href: "/admin/system-health", label: "System Health", icon: Activity },
  { href: "/admin/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/admin/investor-room", label: "Investor Room", icon: Wallet },
];

export default function AdminNav() {
  const pathname = usePathname();
  const [clock, setClock] = useState("");

  useEffect(() => {
    const tick = () =>
      setClock(
        new Date().toLocaleTimeString("pt-PT", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header
      data-admin-nav
      className="sticky top-0 z-50 border-b border-white/[0.06] bg-[#080a0f]/80 backdrop-blur-2xl"
    >
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5">
        <Link href="/admin" className="group flex items-center gap-2.5">
          <span className="relative flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-sky-500 text-[#06110d] shadow-[0_0_30px_-8px_rgba(16,185,129,0.8)]">
            <Sparkles className="h-4 w-4" />
          </span>
          <span className="leading-tight">
            <span className="block text-[13px] font-black tracking-tight text-white">
              Magic Leads
            </span>
            <span className="block text-[9px] font-bold uppercase tracking-[0.22em] text-emerald-300/70">
              Control Tower
            </span>
          </span>
        </Link>

        <nav className="order-3 flex w-full flex-wrap items-center gap-1 pb-1 md:order-none md:w-auto md:pb-0">
          {LINKS.map((link) => {
            const active =
              link.href === "/admin"
                ? pathname === "/admin"
                : pathname?.startsWith(link.href);
            const Icon = link.icon;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={[
                  "inline-flex shrink-0 items-center gap-1.5 rounded-xl px-3 py-1.5 text-[11px] font-bold transition",
                  active
                    ? "bg-white/[0.08] text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]"
                    : "text-slate-500 hover:bg-white/[0.04] hover:text-slate-200",
                ].join(" ")}
              >
                <Icon className="h-3.5 w-3.5" />
                {link.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span className="hidden items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-500/[0.07] px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.16em] text-emerald-200 sm:inline-flex">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
            </span>
            live
          </span>
          <span className="font-mono text-[10px] tabular-nums text-slate-600">
            {clock || "--:--:--"}
          </span>
        </div>
      </div>
    </header>
  );
}
