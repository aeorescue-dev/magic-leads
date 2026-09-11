'use client';

import Link from "next/link";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LayoutDashboard, LogOut, Menu, Sparkles, X, UserPlus } from "lucide-react";
import { getToken, logoutUser, demoLogin } from "@/lib/api-client";
import { useI18n, LANGS } from "@/lib/i18n";

const FLAGS: Record<string, string> = { pt: "🇧🇷", en: "🇺🇸", es: "🇪🇸" };

export function Navbar() {
  const router = useRouter();
  const pathname = usePathname();
  const { lang, setLang, t } = useI18n();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isLogged, setIsLogged] = useState(false);

  useEffect(() => {
    setIsLogged(Boolean(getToken()));
  }, []);

  const handleDemoLogin = async () => {
    await demoLogin();
    router.push("/dashboard");
  };

  const handleLogout = () => {
    logoutUser();
    router.push("/");
  };

  const tryLink = (label: string, active: boolean, href: string) => (
    <Link
      href={href}
      className={`text-sm transition-colors ${
        active ? "text-primary font-medium" : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {label}
    </Link>
  );

  return (
    <nav className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur-lg supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto px-4 h-16 flex items-center justify-between gap-4">
        <Link href="/" className="flex items-center gap-2 shrink-0">
          <span className="h-8 w-8 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-white text-sm shadow-sm">
            <Sparkles className="h-4 w-4" />
          </span>
          <span className="font-bold text-foreground text-lg tracking-tight">Magic Leads</span>
        </Link>

        <div className="hidden md:flex items-center gap-6">
          {tryLink(t("nav.pricing"), pathname === "/pricing", "/pricing")}
          {isLogged && tryLink(t("nav.dashboard"), pathname === "/dashboard", "/dashboard")}
        </div>

        <div className="flex items-center gap-3">
          {/* Language selector */}
          <div className="flex items-center gap-1 rounded-lg border bg-secondary p-1" role="group" aria-label="Idioma">
            {LANGS.map((l) => (
              <button
                key={l.code}
                onClick={() => setLang(l.code)}
                title={l.label}
                aria-pressed={l.code === lang}
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-all ${
                  l.code === lang
                    ? "bg-emerald-500/15 text-emerald-400 shadow-[inset_0_0_0_1px_rgba(16,185,129,0.4)]"
                    : "opacity-60 hover:opacity-100 text-foreground hover:bg-accent"
                }`}
              >
                <span>{FLAGS[l.code]}</span>
                <span className="hidden sm:inline">{l.code.toUpperCase()}</span>
              </button>
            ))}
          </div>

          {isLogged ? (
            <div className="hidden md:flex items-center gap-3">
              <button
                onClick={() => router.push("/dashboard")}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                <LayoutDashboard className="h-4 w-4" />
                {t("nav.dashboard")}
              </button>
              <button
                onClick={handleLogout}
                className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
              >
                <LogOut className="h-4 w-4" />
                {t("nav.logout")}
              </button>
            </div>
          ) : (
            <div className="hidden md:flex items-center gap-2">
              <Link
                href="/auth"
                className="inline-flex items-center gap-2 rounded-lg bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground hover:bg-secondary/80 transition-colors"
              >
                <UserPlus className="h-4 w-4" />
                {t("nav.register") || 'Cadastrar'}
              </Link>
              <button
                onClick={handleDemoLogin}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                {t("nav.demo") || 'Demo'}
              </button>
            </div>
          )}

          {/* Mobile toggle */}
          <button
            onClick={() => setMobileOpen((o) => !o)}
            className="md:hidden inline-flex items-center justify-center rounded-lg h-9 w-9 border hover:bg-secondary transition-colors"
            aria-label="Menu"
          >
            {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="md:hidden border-t bg-background px-4 py-4 space-y-3 animate-slide-down">
          <Link href="/pricing" onClick={() => setMobileOpen(false)} className="block text-sm text-muted-foreground hover:text-foreground">
            {t("nav.pricing")}
          </Link>
          {isLogged && (
            <Link href="/dashboard" onClick={() => setMobileOpen(false)} className="block text-sm text-muted-foreground hover:text-foreground">
              {t("nav.dashboard")}
            </Link>
          )}
          <div className="pt-2 border-t">
            {isLogged ? (
              <button onClick={handleLogout} className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-secondary px-4 py-2 text-sm">
                <LogOut className="h-4 w-4" /> {t("nav.logout")}
              </button>
            ) : (
              <div className="space-y-2">
                <Link
                  href="/auth"
                  onClick={() => setMobileOpen(false)}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-secondary px-4 py-2 text-sm"
                >
                  <UserPlus className="h-4 w-4" /> {t("nav.register") || 'Cadastrar'}
                </Link>
                <button onClick={handleDemoLogin} className="w-full rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">
                  {t("nav.demo") || 'Demo'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </nav>
  );
}
