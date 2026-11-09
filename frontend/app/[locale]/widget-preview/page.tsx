import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { isLpWidgetPreviewEnabled } from "@/lib/lp-widget";
import LpWidgetPreview from "./LpWidgetPreview";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "LP Widget Preview · Magic Leads",
  description: "Pré-visualização isolada do widget de captação. Não indexar.",
  robots: { index: false, follow: false },
};

/**
 * Rota de validação isolada. Não é a landing page oficial e não é linked a
 * partir dela. Só existe quando `LP_WIDGET_PREVIEW=true` ou quando a flag
 * pública `NEXT_PUBLIC_LP_WIDGET=true` está ligada.
 */
export default function LpWidgetPreviewPage() {
  if (!isLpWidgetPreviewEnabled()) {
    notFound();
  }
  return <LpWidgetPreview />;
}
