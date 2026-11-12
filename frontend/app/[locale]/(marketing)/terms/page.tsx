import type { Metadata } from "next";
import LegalDocument from "@/components/legal/LegalDocument";

const COPY = {
  pt: {
    title: "Termos de Serviço · Magic Leads",
    description: "Termos de uso da Magic Leads, incluindo planos, uso aceitável e SMS transacional com opt-in por tecla 1.",
  },
  en: {
    title: "Terms of Service · Magic Leads",
    description: "Magic Leads terms of use, including plans, acceptable use and transactional SMS with keypress 1 opt-in.",
  },
  es: {
    title: "Términos del Servicio · Magic Leads",
    description: "Términos de uso de Magic Leads, incluidos planes, uso aceptable y SMS transaccional con opt-in por tecla 1.",
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

export default function TermsPage() {
  return <LegalDocument kind="terms" />;
}
