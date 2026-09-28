import type { Metadata } from "next";
import LandingShell from "@/components/landing/LandingShell";

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: "Magic Leads - Obras reais com dono identificado",
  description: "Capturamos oportunidades de reforma e correção (telhado, estrutura, encanamento, pintura) direto de registros públicos atualizados continuamente, com dono identificado e reserva exclusiva de 60 minutos por $79/semana. Sistema disponível 24/7.",
  manifest: "/manifest.json",
  themeColor: "#10b981",
  viewport: {
    width: "device-width",
    initialScale: 1,
    maximumScale: 1,
  },
};

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <LandingShell>{children}</LandingShell>;
}