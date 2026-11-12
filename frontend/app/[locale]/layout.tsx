import type { Metadata, Viewport } from "next";
import { LanguageProvider } from "@/lib/i18n";
import AuthProvider from "@/components/AuthProvider";
import ErrorBoundary from "@/components/ErrorBoundary";
import ServiceWorkerRegistration from "@/components/ServiceWorkerRegistration";
import { PwaSessionRedirect } from "@/components/PwaSessionRedirect";
import "../globals.css";

export const metadata: Metadata = {
  title: "Magic Leads - Obras reais com dono identificado",
  description:
    "Oportunidades de reforma e correção com dono identificado, prioridade exclusiva e contato pronto para agir. Plano de $120 por semana, sem fidelidade. Sistema disponível 24/7.",
  manifest: "/manifest.json",
};

export const viewport: Viewport = {
  themeColor: "#10b981",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

const LOCALE_LANG_MAP: Record<string, string> = {
  pt: "pt-BR",
  en: "en-US",
  es: "es-ES",
};

interface LocaleLayoutProps {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}

export default async function LocaleLayout({
  children,
  params,
}: LocaleLayoutProps) {
  const { locale } = await params;
  const validLocales = ["pt", "en", "es"] as const;
  const localeStr = validLocales.includes(locale as any) ? locale : "pt";
  const htmlLang = LOCALE_LANG_MAP[localeStr] || "pt-BR";

  return (
    <html lang={htmlLang}>
      <head>
        <link rel="apple-touch-icon" href="/icons/magicleads-icon-192.png" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
      </head>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <LanguageProvider initialLocale={localeStr as "pt" | "en" | "es"}>
          <AuthProvider>
            <PwaSessionRedirect />
            <ServiceWorkerRegistration />
            <ErrorBoundary>{children}</ErrorBoundary>
          </AuthProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}