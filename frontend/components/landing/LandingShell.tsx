'use client';

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useI18n, type Lang } from "@/lib/i18n";
import { AuthForm } from "@/components/AuthForm";
import AnalyticsBeacon from "@/components/AnalyticsBeacon";
import LpWidgetMount from "@/components/landing/LpWidget/LpWidgetMount";
import { readStoredUser, useAuth } from "@/lib/auth";
import { updateUserLocale } from "@/lib/api-client";

// ------------------------------------------------------------------
// Shared helpers
// ------------------------------------------------------------------
function listOf(s: string): string[] {
  return (s || "").split(",").map((x) => x.trim()).filter(Boolean);
}

export function FoldWave({ from, to }: { from: string; to: string }) {
  return (
    <div className="relative -mt-px" style={{ background: from, lineHeight: 0 }}>
      <svg viewBox="0 0 1440 80" preserveAspectRatio="none" className="block h-[60px] w-full sm:h-[80px]">
        <path d="M0,40 C240,80 480,0 720,32 C960,64 1200,16 1440,40 L1440,80 L0,80 Z" fill={to} />
      </svg>
    </div>
  );
}

const LANGS: { id: Lang; label: string }[] = [
  { id: "pt", label: "Português (BR)" },
  { id: "en", label: "English (US)" },
  { id: "es", label: "Español (ES)" },
];

function Flag({ id, className = "h-5 w-7" }: { id: Lang; className?: string }) {
  if (id === "pt") {
    return (
      <svg className={className} viewBox="0 0 28 20" aria-hidden>
        <rect width="28" height="20" rx="3" fill="#009B3A" />
        <polygon points="14,3 25,10 14,17 3,10" fill="#FEDD00" />
        <circle cx="14" cy="10" r="4" fill="#002776" />
      </svg>
    );
  }
  if (id === "en") {
    return (
      <svg className={className} viewBox="0 0 28 20" aria-hidden>
        <rect width="28" height="20" rx="3" fill="#B22234" />
        <rect y="1.54" width="28" height="1.54" fill="#fff" />
        <rect y="4.62" width="28" height="1.54" fill="#fff" />
        <rect y="7.7" width="28" height="1.54" fill="#fff" />
        <rect y="10.77" width="28" height="1.54" fill="#fff" />
        <rect y="13.85" width="28" height="1.54" fill="#fff" />
        <rect y="16.92" width="28" height="1.54" fill="#fff" />
        <rect width="12" height="10.8" rx="2" fill="#3C3B6E" />
      </svg>
    );
  }
  return (
    <svg className={className} viewBox="0 0 28 20" aria-hidden>
      <rect width="28" height="20" rx="3" fill="#AA151B" />
      <rect y="5.5" width="28" height="9" fill="#F1BF00" />
    </svg>
  );
}

function LangSwitch({ lang, setLang }: { lang: Lang; setLang: (l: Lang) => void }) {
  return (
    <div className="flex items-center gap-0.5 rounded-full border border-white/10 bg-white/[0.035] p-1" role="group" aria-label="Language">
      {LANGS.map((l) => (
        <button
          key={l.id}
          onClick={() => setLang(l.id)}
          data-track={`language_${l.id}`}
          aria-label={l.label}
          aria-pressed={lang === l.id}
          className={`grid h-8 w-9 place-items-center rounded-full transition ${lang === l.id ? "bg-white/[0.12] opacity-100" : "opacity-45 hover:opacity-85"}`}
        >
          <Flag id={l.id} className="h-4 w-6" />
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------
// Shell context
// ------------------------------------------------------------------
interface LandingShellCtx {
  openModal: () => void;
  scrollTo: (id: string) => void;
}

const Ctx = createContext<LandingShellCtx | null>(null);

export function useLandingShell() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useLandingShell must be used within LandingShell");
  return ctx;
}

// ------------------------------------------------------------------
// LandingShell
// ------------------------------------------------------------------
export default function LandingShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { lang, setLang, t } = useI18n();
  const { updateUser } = useAuth();

  // O idioma escolhido na landing também persiste na conta (users.locale),
  // para o push/in-app acompanharem. Sem isto, um cliente EN que trocasse
  // idioma aqui continuaria a receber no idioma antigo.
  const changeLang = (next: Lang) => {
    setLang(next);
    const stored = readStoredUser();
    if (stored?.id) {
      updateUserLocale(stored.id, next).then(updateUser).catch(() => {});
    }
  };

  const localePath = (href: string) => `/${lang}${href}`;

  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const navPairs = useMemo(() => {
    const nav = listOf(t("landing.nav"));
    const pairs: [string, string][] = [];
    for (let i = 0; i + 1 < nav.length; i += 2) pairs.push([nav[i], nav[i + 1]]);
    return pairs;
  }, [t]);

  const scrollTo = (id: string) => {
    setMenuOpen(false);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  };

  const openModal = () => setModalOpen(true);

  return (
    <Ctx.Provider value={{ openModal, scrollTo }}>
      <div className="dark-page min-h-screen">
        <header className={`sticky top-0 z-40 border-b transition-colors duration-300 ${scrolled ? "border-white/[0.08] bg-[#06080b]/90 backdrop-blur-xl" : "border-transparent bg-[#06080b]/70 backdrop-blur-md"}`}>
          <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
            <button onClick={() => scrollTo("topo")} className="flex shrink-0 items-center gap-2.5">
              <div className="grid h-9 w-9 place-items-center rounded-xl border border-white/12 bg-white/[0.04]">
                <svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor"><path d="m13 2-9 12h7l-1 8 10-13h-7V2Z" /></svg>
              </div>
              <span className="font-display text-[17px] font-black tracking-[-0.02em] text-white">Magic<span className="text-white/45">Leads</span></span>
            </button>

            <nav className="hidden items-center gap-6 text-[12.5px] font-medium text-white/50 xl:flex">
              {navPairs.map(([label, id]) => (
                <button key={id} onClick={() => scrollTo(id)} className="whitespace-nowrap transition hover:text-white">{label}</button>
              ))}
            </nav>

            <div className="flex shrink-0 items-center gap-2.5">
              <LangSwitch lang={lang} setLang={changeLang} />
              <div className="hidden sm:block">
                <button onClick={openModal} data-track="header_cta" className="btn-emerald px-4 py-2.5 text-[12.5px]">{t("landing.start")}</button>
              </div>
              <button onClick={() => setMenuOpen(!menuOpen)} className="grid h-9 w-9 place-items-center rounded-lg border border-white/12 text-white/80 xl:hidden" aria-label="Menu">
                <svg className="h-4.5 w-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  {menuOpen ? <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" /> : <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />}
                </svg>
              </button>
            </div>
          </div>
          {menuOpen && (
            <div className="border-t border-white/[0.07] bg-[#06080b] px-4 py-3 xl:hidden">
              <div className="flex flex-col gap-0.5">
                {navPairs.map(([label, id]) => (
                  <button key={id} onClick={() => scrollTo(id)} className="rounded-lg px-3 py-2.5 text-left text-sm font-medium text-white/60 hover:bg-white/[0.04] hover:text-white">{label}</button>
                ))}
                <button onClick={openModal} data-track="mobile_menu_cta" className="btn-emerald mt-2 py-3 text-sm">{t("landing.start")}</button>
              </div>
            </div>
          )}
        </header>

        {children}

        <footer className="border-t border-white/[0.06] bg-[#05070a] pb-16 pt-12 text-sm text-white/40 sm:pb-12">
          <div className="mx-auto max-w-7xl px-4 sm:px-6">
            <div className="grid gap-10 border-b border-white/[0.06] pb-10 md:grid-cols-4">
              <div className="md:col-span-2">
                <div className="flex items-center gap-2.5 text-white">
                  <div className="grid h-9 w-9 place-items-center rounded-xl border border-white/12 bg-white/[0.04]"><svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor"><path d="m13 2-9 12h7l-1 8 10-13h-7V2Z" /></svg></div>
                  <span className="font-display text-[17px] font-black tracking-[-0.02em]">Magic<span className="text-white/45">Leads</span></span>
                </div>
                <p className="mt-4 max-w-sm leading-relaxed text-white/35">{t("landing.footerBio")}</p>
                <p className="mt-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-white/25">New York · Boston · Dallas · Chicago</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-white/70">{t("landing.platform")}</p>
                <div className="mt-4 flex flex-col gap-2.5">{navPairs.slice(0, 4).map(([label, id]) => <button key={id} onClick={() => scrollTo(id)} className="text-left transition hover:text-white">{label}</button>)}</div>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-white/70">{t("landing.account")}</p>
                <div className="mt-4 flex flex-col gap-2.5">
                  {navPairs.slice(4).map(([label, id]) => <button key={id} onClick={() => scrollTo(id)} className="text-left transition hover:text-white">{label}</button>)}
                  <a href="mailto:contato@magicleads.app" className="transition hover:text-white">{t("landing.talk")}</a>
                  <button onClick={openModal} data-track="footer_start_week" className="text-left font-semibold text-[#19c37d]">{t("landing.startWeek")}</button>
                </div>
              </div>
            </div>
            <div className="mt-8 flex flex-col justify-between gap-3 text-[11px] text-white/25 sm:flex-row">
              <span>© {new Date().getFullYear()} Magic Leads. {t("landing.rights")}</span>
              <span>{t("landing.vary")}</span>
            </div>
          </div>
        </footer>

        {modalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-md" onClick={() => setModalOpen(false)}>
            <div className="dark-panel relative w-full max-w-md rounded-2xl p-6 sm:p-8" onClick={(e) => e.stopPropagation()}>
              <button onClick={() => setModalOpen(false)} className="absolute right-4 top-4 text-white/35 hover:text-white" aria-label="Close">✕</button>
              <div className="flex items-center gap-2">
                <span className="rounded border border-white/10 bg-white/[0.05] px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-white/60">{t("landing.modalTag")}</span>
                <span className="text-[11px] text-white/35">{t("landing.noLock")}</span>
              </div>
              <h3 className="font-display mt-3 text-2xl font-black tracking-[-0.02em] text-white">{t("landing.modalTitle")}</h3>
              <p className="mt-1 text-sm text-white/45">{t("landing.modalSub")}</p>
              <div className="mt-5">
                <AuthForm />
              </div>
              <button onClick={() => { setModalOpen(false); router.push(localePath("/auth")); }} className="mt-6 w-full rounded-xl border border-white/12 py-3 text-sm font-semibold text-white/55 transition hover:border-white/25 hover:text-white">
                {t("landing.enter")}
              </button>
              <p className="mt-4 text-center text-[11px] text-white/30">{t("landing.seven")}</p>
            </div>
          </div>
        )}
      </div>
      <LpWidgetMount />
      <AnalyticsBeacon />
    </Ctx.Provider>
  );
}
