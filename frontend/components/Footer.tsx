'use client';

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useI18n } from "@/lib/i18n";

export function Footer() {
  const { t } = useI18n();
  return (
    <footer className="border-t bg-background">
      <div className="container mx-auto px-4 py-10">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div>
            <Link href="/" className="flex items-center gap-2">
              <span className="h-8 w-8 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-white text-sm">
                <Sparkles className="h-4 w-4" />
              </span>
              <span className="font-bold text-foreground">Magic Leads</span>
            </Link>
            <p className="text-sm text-muted-foreground mt-3 max-w-xs">
              {t("hero.sub")}
            </p>
          </div>
          <div>
            <h4 className="text-sm font-semibold mb-3">{t("nav.pricing")}</h4>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li><a href="/pricing" className="hover:text-foreground transition-colors">{t("price.plan")}</a></li>
            </ul>
          </div>
          <div>
            <h4 className="text-sm font-semibold mb-3">{t("nav.dashboard")}</h4>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li><a href="/dashboard" className="hover:text-foreground transition-colors">{t("nav.dashboard")}</a></li>
            </ul>
          </div>
        </div>
        <div className="border-t mt-8 pt-6 flex flex-col sm:flex-row items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground" suppressHydrationWarning>
          </p>
          <p className="text-xs text-muted-foreground">PT · EN · ES</p>
        </div>
      </div>
    </footer>
  );
}
