import type { Metadata } from "next";
import LandingShell from "@/components/landing/LandingShell";

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: "Magic Leads - Obras reais com dono identificado",
  description: "Capturamos oportunidades de reforma e correção (telhado, estrutura, encanamento, pintura) direto de registros públicos atualizados diariamente, com dono identificado e 24h de reserva exclusiva por $79/semana.",
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