import type { Metadata } from "next";
import LegalDocument from "@/components/legal/LegalDocument";

const COPY = {
  pt: {
    title: "Política de Privacidade · Magic Leads",
    description: "Como a Magic Leads coleta, usa e protege dados pessoais, incluindo o consentimento de SMS transacional.",
  },
  en: {
    title: "Privacy Policy · Magic Leads",
    description: "How Magic Leads collects, uses and protects personal data, including transactional SMS consent.",
  },
  es: {
    title: "Política de Privacidad · Magic Leads",
    description: "Cómo Magic Leads recopila, usa y protege datos personales, incluido el consentimiento de SMS transaccional.",
  },
} as const;

type Locale = keyof typeof COPY;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const copy = COPY[locale as Locale] ?? COPY.en;
  return { title: copy.title, description: copy.description };
}

export default function PrivacyPage() {
  return <LegalDocument kind="privacy" />;
}
