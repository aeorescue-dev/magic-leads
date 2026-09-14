"use client";

import { useI18n } from "@/lib/i18n";
import { usePushNotifications } from "@/lib/usePushNotifications";
import { Bell, BellOff, Loader2, ShieldAlert } from "lucide-react";

export function PushNotificationButton() {
  const { t } = useI18n();
  const {
    supported,
    permission,
    subscribed,
    loading,
    error,
    hasUser,
    subscribe,
    unsubscribe,
  } = usePushNotifications();

  if (!hasUser || !supported) {
    return null;
  }

  if (permission === "denied") {
    return (
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-2">
        <span className="flex items-center gap-1.5 text-xs text-amber-400">
          <ShieldAlert className="h-3.5 w-3.5" />
          {t("push.permission_denied") || "Notificações bloqueadas no navegador"}
        </span>
        <span className="text-[11px] text-slate-400">
          {t("push.permission_instructions") ||
            "Habilite no cadeado/escudo da barra de endereço > Notificações > Permitir e recarregue a página."}
        </span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      {subscribed ? (
        <button
          onClick={unsubscribe}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-500/10 text-slate-400 hover:bg-slate-500/20 hover:text-slate-300 transition disabled:opacity-50"
        >
          <BellOff className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">{t("push.disable") || "Desativar alertas"}</span>
        </button>
      ) : (
        <button
          onClick={subscribe}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/30 transition disabled:opacity-50"
        >
          <Loader2 className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          <Bell className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">{t("push.enable") || "Ativar alertas no celular/desktop"}</span>
        </button>
      )}
      {error && (
        <span className="text-xs text-red-400 ml-2">{error}</span>
      )}
    </div>
  );
}

export default PushNotificationButton;