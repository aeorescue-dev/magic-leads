'use client';

import { HeroSection } from "@/components/HeroSection";
import { ServicesSection } from "@/components/ServicesSection";
import { ComparisonTable } from "@/components/ComparisonTable";
import { HowItWorks } from "@/components/HowItWorks";
import { LiveLeadsSection } from "@/components/LiveLeadsSection";
import { TestimonialsSection } from "@/components/TestimonialsSection";
import { PricingSection } from "@/components/PricingSection";
import { DemoLoginButton } from "@/components/DemoLoginButton";
import { AuthForm } from "@/components/AuthForm";
import { useI18n } from "@/lib/i18n";
import { ArrowRight } from "lucide-react";

export default function Home() {
  const { t } = useI18n();

  return (
    <div className="bg-background">
      {/* HERO */}
      <HeroSection />

      {/* SERVIÇOS */}
      <ServicesSection />

      {/* COMPARAÇÃO REAL */}
      <ComparisonTable />

      {/* COMO FUNCIONA + ROI */}
      <HowItWorks />

      {/* LEADS REAIS CHEGANDO AGORA */}
      <LiveLeadsSection />

      {/* QUEM USA - DEPOIMENTOS */}
      <TestimonialsSection />

      {/* PREÇO SIMPLIFICADO */}
      <PricingSection />

      {/* CTA FINAL - PREMIUM DARK */}
      <section className="section relative overflow-hidden bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950" aria-labelledby="cta-final-title">
        {/* Background Effects */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/4 left-1/4 w-[600px] h-[600px] bg-emerald-500/10 rounded-full blur-3xl animate-pulse-slow" />
          <div className="absolute bottom-1/4 right-1/4 w-[600px] h-[600px] bg-cyan-500/10 rounded-full blur-3xl animate-pulse-slow delay-1000" />
          <div className="absolute inset-0 opacity-5" style={{ 
            backgroundImage: "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.05) 1px, transparent 0)",
            backgroundSize: "40px 40px"
          }} />
        </div>

        <div className="container-custom relative py-20 md:py-28">
          <div className="text-center max-w-3xl mx-auto relative z-10">
            <h2 id="cta-final-title" className="text-3xl md:text-4xl lg:text-5xl font-extrabold tracking-tight mb-4 text-white">
              {t("cta.title")}
            </h2>
            <p className="text-slate-400 text-lg mb-8 max-w-2xl mx-auto leading-relaxed">
              {t("cta.sub")}
            </p>
            <div className="max-w-md mx-auto">
              <AuthForm />
              <div className="relative my-6">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-white/10" />
                </div>
                <div className="relative flex justify-center text-sm">
                  <span className="bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 px-4 text-slate-500">{t('auth.or_demo') || 'ou'}</span>
                </div>
              </div>
              <DemoLoginButton className="btn-secondary w-full sm:w-auto text-lg px-10 py-4">
                {t("cta.demo_btn") || 'Entrar como Demo'}
              </DemoLoginButton>
            </div>
            <p className="text-slate-500 text-sm mt-4">{t("cta.note")}</p>
          </div>
        </div>
      </section>
    </div>
  );
}