"use client";

import { X, Smartphone, Share, Plus, Check } from "lucide-react";
import { useI18n } from "@/lib/i18n";

interface iOSInstallModalProps {
  onClose: () => void;
}

export function iOSInstallModal({ onClose }: iOSInstallModalProps) {
  const { t } = useI18n();

  return (
    <div
      className="fixed inset-0 z-[300] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("push.ios.modal.title") || "Como adicionar o Magic Leads na Tela de Início"}
    >
      <div
        className="card w-full max-w-md p-6 shadow-2xl animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-5">
          <div>
            <h2 className="text-lg font-bold">
              {t("push.ios.modal.title") || "Como adicionar o Magic Leads na Tela de Início"}
            </h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              {t("push.ios.modal.subtitle") || "Siga os passos abaixo no seu iPhone"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-secondary transition-colors"
            aria-label={t("push.banner.dismiss") || "Fechar"}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <ol className="space-y-4">
          <li className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground text-[12px] font-bold">1</span>
            <div className="flex-1 min-w-0">
              <span className="flex items-center gap-2 text-sm">
                <Share className="h-4 w-4 text-muted-foreground shrink-0" />
                <span>
                  {t("push.ios.modal.step1") || "No rodapé do Safari, toque no ícone de Compartilhar (quadrado com seta para cima)."}
                </span>
              </span>
            </div>
          </li>
          <li className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground text-[12px] font-bold">2</span>
            <div className="flex-1 min-w-0">
              <span className="flex items-center gap-2 text-sm">
                <Plus className="h-4 w-4 text-muted-foreground shrink-0" />
                <span>
                  {t("push.ios.modal.step2") || "Role o menu e selecione 'Adicionar à Tela de Início' (ícone +)."}
                </span>
              </span>
            </div>
          </li>
          <li className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground text-[12px] font-bold">3</span>
            <div className="flex-1 min-w-0">
              <span className="flex items-center gap-2 text-sm">
                <Check className="h-4 w-4 text-muted-foreground shrink-0" />
                <span>
                  {t("push.ios.modal.step3") || "Toque em 'Adicionar' no canto superior direito."}
                </span>
              </span>
            </div>
          </li>
        </ol>

        <div className="mt-6 rounded-xl bg-muted p-4 flex items-center gap-3">
          <Smartphone className="h-6 w-6 text-primary shrink-0" />
          <p className="text-sm">
            {t("push.ios.modal.done") || "Depois de instalar, abra o Magic Leads pela Tela de Início para receber os alertas."}
          </p>
        </div>

        <button
          onClick={onClose}
          className="mt-6 w-full rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-2.5 transition"
        >
          {t("push.ios.modal.cta") || "Entendi"}
        </button>
      </div>
    </div>
  );
}

export default iOSInstallModal;