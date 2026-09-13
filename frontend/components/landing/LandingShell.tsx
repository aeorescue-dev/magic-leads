'use client';

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useI18n, type Lang } from "@/lib/i18n";
import { AuthForm } from "@/components/AuthForm";
import { DemoLoginButton } from "@/components/DemoLoginButton";

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
    <div className="flex items-center gap-1 rounded-[18px] bg-[#141820] p-1.5" role="group" aria-label="Language">
      {LANGS.map((l) => (
        <button
          key={l.id}
          onClick={() => setLang(l.id)}
          aria-label={l.label}
          aria-pressed={lang === l.id}
          className={`grid h-10 w-11 place-items-center rounded-[12px] transition ${lang === l.id ? "bg-[#0f2a24] ring-2 ring-[#2feaa8]" : "opacity-70 hover:opacity-100"}`}
        >
          <Flag id={l.id} />
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
      <div className="landing-light min-h-screen bg-white text-[#0b1220]">
        <header className={`sticky top-0 z-40 transition-all duration-300 ${scrolled ? "border-b border-[#eef1f6] bg-white/90 backdrop-blur-xl shadow-sm" : "bg-white/80 backdrop-blur-md"}`}>
          <div className="mx-auto max-w-[1400px] px-4 sm:px-6">
            <div className="flex h-16 items-center justify-between gap-4">
              <button onClick={() => scrollTo("topo")} className="flex shrink-0 items-center gap-2.5">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-tr from-[#7c5cff] to-[#10b981] shadow-md shadow-[#10b981]/20">
                  <svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor"><path d="m13 2-9 12h7l-1 8 10-13h-7V2Z" /></svg>
                </div>
                <span className="font-display text-lg font-black text-[#0b1220]">Magic<span className="text-[#10b981]">Leads</span></span>
              </button>
              <div className="flex shrink-0 items-center gap-3">
                <LangSwitch lang={lang} setLang={setLang} />
                <button onClick={openModal} className="btn-mint hidden px-5 py-2.5 text-[13px] sm:block">{t("landing.start")}</button>
                <button onClick={() => setMenuOpen(!menuOpen)} className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#e2e8f0] text-[#0b1220] lg:hidden" aria-label="Menu">
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    {menuOpen ? <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" /> : <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />}
                  </svg>
                </button>
              </div>
            </div>
            <nav className="hidden h-11 items-center justify-center gap-8 border-t border-[#eef1f6] text-[13px] font-semibold text-[#54617a] lg:flex">
              {navPairs.map(([label, id]) => (
                <button key={id} onClick={() => scrollTo(id)} className="whitespace-nowrap transition hover:text-[#0b1220]">{label}</button>
              ))}
            </nav>
          </div>
          {menuOpen && (
            <div className="border-t border-[#eef1f6] bg-white px-4 py-4 lg:hidden">
              <div className="flex flex-col gap-1">
                {navPairs.map(([label, id]) => (
                  <button key={id} onClick={() => scrollTo(id)} className="rounded-lg px-3 py-2.5 text-left text-sm font-semibold text-[#54617a] hover:bg-[#f1f4f9]">{label}</button>
                ))}
                <button onClick={openModal} className="btn-mint mt-2 py-3 text-sm">{t("landing.start")}</button>
              </div>
            </div>
          )}
        </header>

        {children}

        <FoldWave from="#0b1220" to="#080d16" />
        <footer className="bg-[#080d16] pb-16 pt-8 text-sm text-[#64748b] sm:pb-12">
          <div className="mx-auto max-w-7xl px-4 sm:px-6">
            <div className="grid gap-10 border-b border-white/10 pb-10 md:grid-cols-4">
              <div className="md:col-span-2">
                <div className="flex items-center gap-2.5 text-white">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-tr from-[#7c5cff] to-[#10b981]"><svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor"><path d="m13 2-9 12h7l-1 8 10-13h-7V2Z" /></svg></div>
                  <span className="font-display text-lg font-black">Magic<span className="text-[#34e0a1]">Leads</span></span>
                </div>
                <p className="mt-4 max-w-sm leading-relaxed">{t("landing.footerBio")}</p>
                <p className="mt-4 text-xs font-semibold text-[#9aa7ba]">New York · Boston · Dallas · Chicago</p>
              </div>
              <div>
                <p className="text-xs font-black uppercase tracking-widest text-white">{t("landing.platform")}</p>
                <div className="mt-4 flex flex-col gap-2.5">{navPairs.slice(0, 4).map(([label, id]) => <button key={id} onClick={() => scrollTo(id)} className="text-left hover:text-white">{label}</button>)}</div>
              </div>
              <div>
                <p className="text-xs font-black uppercase tracking-widest text-white">{t("landing.account")}</p>
                <div className="mt-4 flex flex-col gap-2.5">
                  {navPairs.slice(4).map(([label, id]) => <button key={id} onClick={() => scrollTo(id)} className="text-left hover:text-white">{label}</button>)}
                  <a href="mailto:contato@magicleads.app" className="hover:text-white">{t("landing.talk")}</a>
                  <button onClick={openModal} className="text-left font-semibold text-[#34e0a1]">{t("landing.startWeek")}</button>
                </div>
              </div>
            </div>
            <div className="mt-8 flex flex-col justify-between gap-3 text-xs text-[#475569] sm:flex-row">
              <span>© {new Date().getFullYear()} Magic Leads. {t("landing.rights")}</span>
              <span>{t("landing.vary")}</span>
            </div>
          </div>
        </footer>

        {modalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0b1220]/60 p-4 backdrop-blur-md" onClick={() => setModalOpen(false)}>
            <div className="relative w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl sm:p-8" onClick={(e) => e.stopPropagation()}>
              <button onClick={() => setModalOpen(false)} className="absolute right-4 top-4 text-[#94a3b8]">✕</button>
              <div className="flex items-center gap-2">
                <span className="rounded bg-[#e8f9ef] px-2.5 py-0.5 text-[10px] font-black text-[#0a8f65]">{t("landing.modalTag")}</span>
                <span className="text-xs text-[#94a3b8]">{t("landing.noLock")}</span>
              </div>
              <h3 className="font-display mt-3 text-2xl font-black">{t("landing.modalTitle")}</h3>
              <p className="mt-1 text-sm text-[#54617a]">{t("landing.modalSub")}</p>
              <div className="mt-5">
                <AuthForm />
              </div>
              <div className="relative my-6">
                <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-[#eef1f6]" /></div>
                <div className="relative flex justify-center text-sm"><span className="bg-white px-4 text-[#94a3b8]">{t('auth.or_demo') || 'ou'}</span></div>
              </div>
              <div className="w-full">
                <DemoLoginButton className="w-full text-sm py-3.5">{t("nav.demo") || 'Demo'}</DemoLoginButton>
              </div>
              <button onClick={() => { setModalOpen(false); router.push("/auth"); }} className="mt-3 w-full rounded-xl border border-[#e2e8f0] py-3 text-sm font-bold text-[#54617a] hover:border-[#0b1220]">
                {t("landing.enter")}
              </button>
              <p className="mt-4 text-center text-[11px] text-[#94a3b8]">{t("landing.seven")}</p>
            </div>
          </div>
        )}
      </div>
    </Ctx.Provider>
  );
}
