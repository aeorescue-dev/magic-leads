import type { Metadata } from "next";
import { LanguageProvider } from "@/lib/i18n";
import ErrorBoundary from "@/components/ErrorBoundary";
import ServiceWorkerRegistration from "@/components/ServiceWorkerRegistration";
import { PwaSessionRedirect } from "@/components/PwaSessionRedirect";
import "../globals.css";

export const metadata: Metadata = {
  title: "Magic Leads - Obras reais com dono identificado",
  description:
    "Capturamos oportunidades de reforma e correção (telhado, estrutura, encanamento, pintura) direto de registros públicos atualizados diariamente, com dono identificado e 24h de reserva exclusiva por $79/semana.",
  manifest: "/manifest.json",
  themeColor: "#10b981",
  viewport: {
    width: "device-width",
    initialScale: 1,
    maximumScale: 1,
  },
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
        <link rel="apple-touch-icon" href="/icon-192.png" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
      </head>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <LanguageProvider initialLocale={localeStr as "pt" | "en" | "es"}>
          <PwaSessionRedirect />
          <ServiceWorkerRegistration />
          <ErrorBoundary>{children}</ErrorBoundary>
        </LanguageProvider>
      </body>
    </html>
  );
}