"use client";

import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { usePushNotifications } from "@/lib/usePushNotifications";
import { useAuth } from "@/lib/auth";
import { iOSInstallModal as IOSInstallModal } from "@/components/iOSInstallModal";
import { Bell, BellRing, ShieldAlert, Smartphone, X, ArrowUpRight } from "lucide-react";

const DISMISSED_KEY = "garimpador.push.ios_tutorial.dismissed";

function detectBrowser(): "safari" | "chrome" | "other" {
  if (typeof navigator === "undefined") return "other";
  const ua = navigator.userAgent || "";
  if (ua.includes("CriOS")) return "chrome";
  return "other";
}

export function PushOnboardingBanner() {
  const { t } = useI18n();
  const { user, updateUser } = useAuth();
  const {
    mounted,
    supported,
    permission,
    loading,
    error,
    subscribed,
    pushEnabling,
    hasUser,
    isIOSNeedsInstall,
    subscribe,
  } = usePushNotifications();

  const [visible, setVisible] = useState(false);
  const [showInstallHelp, setShowInstallHelp] = useState(false);

  // Se é iOS fora do PWA, sempre mostra o tutorial de instalação
  // (a permissão Web Push nunca funciona numa aba de navegador no iOS).
  useEffect(() => {
    if (!hasUser) return;
    if (isIOSNeedsInstall) {
      try {
        const dismissed = localStorage.getItem(DISMISSED_KEY) === "1";
        setVisible(!dismissed);
      } catch {
        setVisible(true);
      }
      return;
    }
    // Android / Desktop / iOS já em PWA: banner de 1 clique se a permissão
    // ainda é 'default' e o usuário ainda não ativou push.
    setVisible(supported && permission === "default" && !pushEnabling && !subscribed);
  }, [hasUser, isIOSNeedsInstall, supported, permission, pushEnabling, subscribed]);

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      /* ignore */
    }
    setVisible(false);
  };

  // SSR/hydration safety: só renderiza após o mount no cliente,
  // quando isIOSNeedsInstall foi calculado dentro de useEffect no hook.
  if (!mounted) return null;

  if (!visible) return null;

  // ----------------------------------------------------------------
  // CASO A: iOS fora do modo PWA → tutorial de instalação
  // ----------------------------------------------------------------
  if (isIOSNeedsInstall) {
    const browser = detectBrowser();

    return (
      <>
      <div className="fixed inset-x-0 bottom-0 z-[200] sm:absolute sm:left-4 sm:right-4 sm:bottom-4 rounded-t-3xl sm:rounded-2xl border border-emerald-500/30 bg-[#0d1420]/95 backdrop-blur-xl shadow-2xl shadow-emerald-500/10 overflow-hidden">
        {/* Seta animada indicando a ação */}
        <div className="relative">
          <div className="absolute -top-3 right-6 flex items-center gap-1 sm:hidden">
            <ArrowUpRight className="h-5 w-5 text-emerald-400 animate-bounce" />
            <span className="text-[10px] font-semibold text-emerald-400/90 uppercase tracking-wide">
              {t("push.ios.tap_here") || "Toque aqui"}
            </span>
          </div>
        </div>

        <div className="flex items-start gap-3 p-4 sm:p-5">
          <div className="rounded-xl bg-emerald-500/20 p-2 shrink-0">
            <Smartphone className="h-5 w-5 text-emerald-400" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-bold text-white">
                {t("push.ios.title") || "Ative os Alertas de Obras no seu iPhone"}
              </p>
              <button
                onClick={dismiss}
                className="text-slate-400 hover:text-white transition p-1 -mt-1 -mr-1"
                aria-label="Fechar"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="text-xs text-emerald-300/90 mt-1">
              {t("push.ios.subtitle") ||
                "No iPhone, para receber notificações em tempo real, adicione o Magic Leads à sua tela inicial."}
            </p>

            {/* Passo a passo adaptado ao navegador */}
            <ol className="mt-3 space-y-2 text-xs text-slate-300">
              <li className="flex items-start gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 text-[11px] font-bold text-emerald-400">1</span>
                <span>
                  {browser === "chrome"
                    ? (t("push.ios.step1.chrome") ||
                        "Toque no ícone de Compartilhar/Menu no topo ou no rodapé")
                    : (t("push.ios.step1.safari") ||
                        "Toque em Compartilhar (quadrado com seta no rodapé)")}
                </span>
              </li>
              <li className="flex items-start gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 text-[11px] font-bold text-emerald-400">2</span>
                <span>
                  {t("push.ios.step2") || "Selecione 'Adicionar à Tela de Início'"}
                </span>
              </li>
            </ol>

            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={dismiss}
                className="px-3 py-2 rounded-lg text-xs font-medium text-slate-400 hover:text-white transition"
              >
                {t("push.banner.dismiss") || "Agora não"}
              </button>
              <button
                onClick={() => setShowInstallHelp(true)}
                className="px-3 py-2 rounded-lg text-xs font-semibold text-emerald-400 hover:text-emerald-300 transition"
              >
                {t("push.ios.howto") || "Como instalar"} ↗
              </button>
            </div>
          </div>
        </div>
      </div>
      {showInstallHelp && <IOSInstallModal onClose={() => setShowInstallHelp(false)} />}
      </>
    );
  }

  // ----------------------------------------------------------------
  // CASO B: iOS já no PWA OU Android/Desktop → banner de 1 clique
  // ----------------------------------------------------------------
  if (permission === "denied") {
    return (
      <div className="flex items-start gap-3 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3">
        <ShieldAlert className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="text-sm font-medium text-amber-300">
            {t("push.permission_denied") || "Notificações bloqueadas no navegador"}
          </p>
          <p className="text-xs text-amber-400/80 mt-0.5">
            {t("push.banner.denied") ||
              "Para reativar, use o ícone de cadeado/escudo na barra de endereço do navegador e selecione Permitir."}
          </p>
        </div>
        <button onClick={dismiss} className="text-amber-400/70 hover:text-amber-300 transition p-1" aria-label="Fechar">
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  const handleAllow = () => {
    subscribe().then((didSubscribe: boolean) => {
      if (user?.id && didSubscribe) {
        updateUser({ ...user, push_enabled: true });
      }
    });
  };

  return (
    <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-emerald-500/20 p-2">
          {loading ? (
            <BellRing className="h-5 w-5 text-emerald-400 animate-pulse" />
          ) : (
            <Bell className="h-5 w-5 text-emerald-400" />
          )}
        </div>
        <div>
          <p className="text-sm font-semibold text-emerald-300">
            {t("push.onboard.title") || "Deseja receber notificações de novas obras na sua região?"}
          </p>
          <p className="text-xs text-emerald-400/80 mt-0.5 max-w-md">
            {t("push.onboard.text") ||
              "Você será avisado em tempo real assim que surgirem novas oportunidades compatíveis com o seu perfil."}
          </p>
          {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
        </div>
      </div>

      <div className="flex items-center gap-2 sm:ml-auto">
        <button
          onClick={dismiss}
          className="px-3 py-1.5 rounded-lg text-xs font-medium text-emerald-400/80 hover:text-emerald-300 transition"
        >
          {t("push.banner.dismiss") || "Agora não"}
        </button>
        <button
          onClick={handleAllow}
          disabled={loading}
          className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500 text-slate-950 hover:bg-emerald-400 transition disabled:opacity-50"
        >
          {t("push.onboard.cta") || "Ativar notificações"}
        </button>
      </div>
    </div>
  );
}

export default PushOnboardingBanner;