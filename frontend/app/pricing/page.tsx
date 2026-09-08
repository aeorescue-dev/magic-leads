'use client';

import { Crown } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { PricingSection } from "@/components/PricingSection";
import { ComparisonTable } from "@/components/ComparisonTable";

export default function Pricing() {
  const { t } = useI18n();

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto px-4 pt-16 pb-4 text-center">
        <span className="inline-flex items-center gap-2 rounded-full bg-primary/10 text-primary px-4 py-1.5 text-xs font-semibold uppercase tracking-wide">
          <Crown className="h-3.5 w-3.5" /> {t("pg.title")}
        </span>
        <p className="text-muted-foreground mt-3">{t("pg.sub")}</p>
      </div>
      <PricingSection />
      <ComparisonTable />
    </div>
  );
}