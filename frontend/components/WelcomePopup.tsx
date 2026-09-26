"use client";

import { useEffect } from "react";
import { X, ShieldCheck, AlertCircle } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

interface WelcomePopupProps {
  open: boolean;
  onClose: () => void;
  isDark?: boolean;
}

export default function WelcomePopup({ open, onClose, isDark = false }: WelcomePopupProps) {
  const { t } = useI18n();
  const { user, updateUser } = useAuth();

  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.body.style.overflow = "unset";
    };
  }, [open]);

  const handleAccept = async () => {
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("garimpador_token") : null;
      if (token) {
        await fetch("/api/user/welcome-popup", {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
      }
    } catch (e) {
      console.error("Erro ao marcar welcome popup:", e);
    }
    try {
      const storageKey = user ? `magic_leads_notice_seen_${user.id}` : "magic_leads_notice_seen";
      localStorage.setItem(storageKey, "true");
    } catch (e) {
      console.error("Erro ao salvar welcome popup no localStorage:", e);
    }
    onClose();
  };

  if (!open) return null;

  const c = {
    overlay: isDark
      ? "fixed inset-0 z-[90] bg-black/60 backdrop-blur-sm"
      : "fixed inset-0 z-[90] bg-black/50",
    modal: isDark
      ? "bg-[#14161d] border-white/10 text-slate-100"
      : "bg-white border-slate-200 text-slate-900",
    button: "bg-emerald-500 hover:bg-emerald-400 text-slate-900",
    iconBg: isDark ? "bg-emerald-500/20" : "bg-emerald-500/10",
    textSecondary: isDark ? "text-slate-400" : "text-slate-600",
    divider: isDark ? "border-white/10" : "border-slate-200",
  };

  return (
    <div className={c.overlay}>
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className={`w-full max-w-md rounded-2xl ${c.modal} border p-6 shadow-2xl animate-in fade-in zoom-in-95`}>
          <div className="flex items-start gap-3">
            <div className={`flex-shrink-0 w-12 h-12 rounded-xl ${c.iconBg} flex items-center justify-center`}>
              <AlertCircle className="w-6 h-6 text-emerald-500" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-lg font-semibold">{t("dashboard.welcome.title")}</h2>
            </div>
            <button
              onClick={onClose}
              className="flex-shrink-0 p-1 rounded-lg hover:bg-slate-200 dark:hover:bg-white/10 text-slate-400"
              aria-label="Fechar"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className={`my-4 ${c.divider}`} />

          <div className="space-y-3 text-sm">
            <p className={c.textSecondary} style={{ whiteSpace: "pre-line" }}>
              {t("dashboard.welcome.body")}
            </p>

            <div className="grid gap-2 sm:grid-cols-2">
              <div className={`flex items-start gap-2 p-3 rounded-lg bg-emerald-500/10`}>
                <ShieldCheck className="w-5 h-5 text-emerald-500 shrink-0 mt-0.5" />
                <span className="text-sm">{t("dashboard.welcome.bullet_accuracy")}</span>
              </div>
              <div className={`flex items-start gap-2 p-3 rounded-lg bg-emerald-500/10`}>
                <ShieldCheck className="w-5 h-5 text-emerald-500 shrink-0 mt-0.5" />
                <span className="text-sm">{t("dashboard.welcome.bullet_refund")}</span>
              </div>
              <div className={`flex items-start gap-2 p-3 rounded-lg bg-emerald-500/10`}>
                <ShieldCheck className="w-5 h-5 text-emerald-500 shrink-0 mt-0.5" />
                <span className="text-sm">{t("dashboard.welcome.bullet_no_cost")}</span>
              </div>
              <div className={`flex items-start gap-2 p-3 rounded-lg bg-emerald-500/10`}>
                <ShieldCheck className="w-5 h-5 text-emerald-500 shrink-0 mt-0.5" />
                <span className="text-sm">{t("dashboard.welcome.bullet_validate")}</span>
              </div>
            </div>
          </div>

          <div className="mt-6">
            <button
              onClick={handleAccept}
              className={`w-full py-3 rounded-xl font-semibold text-sm bg-emerald-500 hover:bg-emerald-400 text-slate-900 transition-colors flex items-center justify-center gap-2`}
            >
              <ShieldCheck className="w-4 h-4" />
              {t("dashboard.welcome.button")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}