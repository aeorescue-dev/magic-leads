import type { Metadata, Viewport } from "next";
import LandingShell from "@/components/landing/LandingShell";

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: "Magic Leads · Obras reais com dono identificado",
  description: "Oportunidades de reforma e correção com dono identificado, prioridade exclusiva e contato pronto para agir. Plano de $120 por semana, sem fidelidade. Sistema disponível 24/7.",
  manifest: "/manifest.json",
};

export const viewport: Viewport = {
  themeColor: "#10b981",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <LandingShell>{children}</LandingShell>;
}