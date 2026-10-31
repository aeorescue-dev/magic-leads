"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Bell,
  BellRing,
  Check,
  Loader2,
  MapPin,
  ShieldCheck,
  Smartphone,
  Zap,
} from "lucide-react";

import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import {
  completeOnboarding,
  fetchCities,
  fetchOnboardingState,
} from "@/lib/api-client";
import { TRADE_CATEGORIES } from "@/lib/categories";
import { usePushNotifications } from "@/lib/usePushNotifications";

const DEFAULT_CITIES = ["NYC", "Chicago", "Dallas", "Boston"];

/**
 * Onboarding Wizard (3 passos, 2 ecrãs + gravação/redireccionamento).
 *
 * Gate: quem chega aqui sem sessão vai para o login; quem JÁ tem ofícios
 * escolhidos é devolvido ao dashboard (o wizard nunca reabre em loop).
 */
export default function OnboardingPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { t, lang } = useI18n();
  const push = usePushNotifications();

  const localePath = useCallback((href: string) => `/${lang}${href}`, [lang]);

  const [step, setStep] = useState(0);
  const [bootLoading, setBootLoading] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [cities, setCities] = useState<string[]>([]);
  const [cityOptions, setCityOptions] = useState<string[]>(DEFAULT_CITIES);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDark, setIsDark] = useState(true);

  // Tema: respeita a escolha feita na dashboard (mesma chave `pro.theme`).
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem("pro.theme");
      if (saved === "light") setIsDark(false);
    } catch {
      /* storage indisponível */
    }
  }, []);

  // Sem sessão -> login. Já configurado -> dashboard (gate inverso).
  useEffect(() => {
    if (authLoading) return;
    if (!user?.id) {
      router.replace(localePath("/auth"));
      return;
    }
    let cancelled = false;
    fetchOnboardingState()
      .then((state) => {
        if (cancelled) return;
        if (state.completed) {
          router.replace(localePath("/dashboard"));
          return;
        }
        setSelected(new Set(state.categories || []));
        setCities(state.cities || []);
      })
      .catch(() => {
        /* sem estado: segue o wizard com selecção vazia */
      })
      .finally(() => {
        if (!cancelled) setBootLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [authLoading, user?.id, router, localePath]);

  // Cidades reais da plataforma (fallback estático se a chamada falhar).
  useEffect(() => {
    fetchCities()
      .then((list) => {
        const clean = (list || []).filter(Boolean);
        if (clean.length > 0) setCityOptions(clean);
      })
      .catch(() => {});
  }, []);

  const T = useMemo(
    () =>
      isDark
        ? {
            bg: "bg-[#0b0d12]",
            card: "bg-[#10121a] border-white/10",
            text: "text-slate-100",
            sub: "text-slate-400",
            chip: "bg-white/[0.03] border-white/10 hover:border-emerald-500/40",
            chipOn: "bg-emerald-500/15 border-emerald-500/50",
          }
        : {
            bg: "bg-slate-50",
            card: "bg-white border-slate-200",
            text: "text-slate-900",
            sub: "text-slate-500",
            chip: "bg-white border-slate-200 hover:border-emerald-500/50",
            chipOn: "bg-emerald-50 border-emerald-500/60",
          },
    [isDark]
  );

  const toggleCategory = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        // Nunca permitir zero: "sem categorias" = todas no backend.
        if (next.size === 1) return prev;
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
    setError(null);
  };

  const toggleCity = (city: string) => {
    setCities((prev) =>
      prev.includes(city) ? prev.filter((c) => c !== city) : [...prev, city]
    );
  };

  const finish = async () => {
    if (selected.size === 0) {
      setError(t("onboarding.error.categories"));
      setStep(0);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await completeOnboarding(Array.from(selected), cities);
      router.push(localePath("/dashboard"));
    } catch {
      setError(t("onboarding.error.save"));
      setSaving(false);
    }
  };

  if (authLoading || bootLoading) {
    return (
      <div className={`min-h-screen ${T.bg} flex items-center justify-center`}>
        <Loader2 className="h-6 w-6 animate-spin text-emerald-500" />
      </div>
    );
  }

  const totalSteps = 2;

  return (
    <div className={`min-h-screen ${T.bg} px-4 py-10`}>
      <div className="mx-auto w-full max-w-2xl">
        {/* Cabeçalho / progresso */}
        <div className="mb-6">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-emerald-500">
              {t("onboarding.step", { current: step + 1, total: totalSteps })}
            </span>
            <div className="flex gap-1.5" aria-hidden>
              {Array.from({ length: totalSteps }).map((_, i) => (
                <span
                  key={i}
                  className={`h-1.5 w-8 rounded-full ${
                    i <= step ? "bg-emerald-500" : isDark ? "bg-white/10" : "bg-slate-200"
                  }`}
                />
              ))}
            </div>
          </div>
          <h1 className={`mt-3 text-2xl font-bold ${T.text}`}>{t("onboarding.title")}</h1>
          <p className={`mt-1 text-sm ${T.sub}`}>{t("onboarding.sub")}</p>
        </div>

        <div className={`rounded-2xl border p-5 sm:p-6 ${T.card}`}>
          {step === 0 && (
            <div className="space-y-6">
              <div>
                <h2 className={`text-base font-bold ${T.text}`}>{t("onboarding.step1.title")}</h2>
                <p className={`mt-1 text-xs ${T.sub}`}>{t("onboarding.step1.sub")}</p>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className={`text-xs font-semibold uppercase tracking-wider ${T.sub}`}>
                    {t("onboarding.step1.categories")}
                  </h3>
                  <span className="text-[11px] font-medium text-emerald-500">
                    {t("onboarding.step1.selected", { count: selected.size })}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {TRADE_CATEGORIES.map((cat) => {
                    const on = selected.has(cat.key);
                    return (
                      <button
                        key={cat.key}
                        type="button"
                        onClick={() => toggleCategory(cat.key)}
                        aria-pressed={on}
                        data-testid={`onboarding-cat-${cat.key}`}
                        className={`relative flex items-center gap-2 rounded-xl border px-3 py-2.5 text-left text-xs font-medium transition ${
                          on ? T.chipOn : T.chip
                        } ${T.text}`}
                      >
                        <span
                          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                            on
                              ? "border-emerald-500 bg-emerald-500 text-white"
                              : isDark
                              ? "border-white/20"
                              : "border-slate-300"
                          }`}
                        >
                          {on && <Check className="h-3 w-3" />}
                        </span>
                        <span className="leading-tight">{t(cat.labelKey)}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <h3 className={`mb-2 text-xs font-semibold uppercase tracking-wider ${T.sub}`}>
                  {t("onboarding.step1.cities")}
                </h3>
                <div className="flex flex-wrap gap-2">
                  {cityOptions.map((city) => {
                    const on = cities.includes(city);
                    return (
                      <button
                        key={city}
                        type="button"
                        onClick={() => toggleCity(city)}
                        aria-pressed={on}
                        data-testid={`onboarding-city-${city}`}
                        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                          on ? T.chipOn : T.chip
                        } ${T.text}`}
                      >
                        <MapPin className="h-3.5 w-3.5" />
                        {city}
                      </button>
                    );
                  })}
                  <span className={`inline-flex items-center px-2 text-[11px] ${T.sub}`}>
                    {cities.length === 0 ? t("onboarding.step1.city_all") : ""}
                  </span>
                </div>
              </div>

              {error && (
                <p className="rounded-lg bg-red-500/10 px-3 py-2 text-xs font-medium text-red-400">
                  {error}
                </p>
              )}

              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => {
                    if (selected.size === 0) {
                      setError(t("onboarding.error.categories"));
                      return;
                    }
                    setStep(1);
                  }}
                  data-testid="onboarding-next"
                  className="inline-flex items-center gap-2 rounded-xl bg-emerald-500 px-5 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-emerald-400"
                >
                  {t("onboarding.next")}
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-6" data-testid="onboarding-push-step">
              <div className="flex items-start gap-3">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-emerald-500/15 text-emerald-500">
                  <BellRing className="h-5 w-5" />
                </span>
                <div>
                  <h2 className={`text-base font-bold ${T.text}`}>{t("onboarding.step2.title")}</h2>
                  <p className={`mt-1 text-xs ${T.sub}`}>{t("onboarding.step2.sub")}</p>
                </div>
              </div>

              <ul className="space-y-2">
                {[
                  { icon: Zap, key: "onboarding.step2.benefit_1" },
                  { icon: MapPin, key: "onboarding.step2.benefit_2" },
                  { icon: ShieldCheck, key: "onboarding.step2.benefit_3" },
                ].map(({ icon: Icon, key }) => (
                  <li key={key} className="flex items-center gap-2.5 text-sm">
                    <Icon className="h-4 w-4 shrink-0 text-emerald-500" />
                    <span className={T.sub}>{t(key)}</span>
                  </li>
                ))}
              </ul>

              {push.isIOSNeedsInstall && (
                <p className={`flex items-start gap-2 rounded-lg px-3 py-2 text-xs ${
                  isDark ? "bg-amber-500/10 text-amber-400" : "bg-amber-50 text-amber-700"
                }`}>
                  <Smartphone className="mt-0.5 h-4 w-4 shrink-0" />
                  {t("onboarding.step2.ios_hint")}
                </p>
              )}

              {push.error && (
                <p className="rounded-lg bg-red-500/10 px-3 py-2 text-xs font-medium text-red-400">
                  {push.error}
                </p>
              )}

              {error && (
                <p className="rounded-lg bg-red-500/10 px-3 py-2 text-xs font-medium text-red-400">
                  {error}
                </p>
              )}

              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => push.subscribe()}
                  disabled={saving || push.loading || push.subscribed}
                  data-testid="onboarding-enable-push"
                  className={`inline-flex w-full items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-bold transition disabled:opacity-60 ${
                    push.subscribed
                      ? "bg-emerald-500/15 text-emerald-500"
                      : "bg-emerald-500 text-slate-950 hover:bg-emerald-400"
                  }`}
                >
                  {push.loading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : push.subscribed ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <Bell className="h-4 w-4" />
                  )}
                  {push.subscribed
                    ? t("onboarding.step2.enabled")
                    : t("onboarding.step2.enable")}
                </button>
                <button
                  type="button"
                  onClick={finish}
                  disabled={saving}
                  className={`w-full text-center text-[11px] underline-offset-2 hover:underline ${T.sub}`}
                >
                  {t("onboarding.step2.skip")}
                </button>
              </div>

              <div className="flex items-center justify-between gap-3">
                <button
                  type="button"
                  onClick={() => setStep(0)}
                  className={`inline-flex items-center gap-1.5 text-sm font-medium ${T.sub} hover:opacity-80`}
                >
                  <ArrowLeft className="h-4 w-4" />
                  {t("onboarding.back")}
                </button>
                <button
                  type="button"
                  onClick={finish}
                  disabled={saving}
                  data-testid="onboarding-finish"
                  className="inline-flex items-center gap-2 rounded-xl border border-emerald-500/40 px-5 py-2.5 text-sm font-bold text-emerald-500 transition hover:bg-emerald-500/10 disabled:opacity-60"
                >
                  {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                  {saving ? t("onboarding.saving") : t("onboarding.finish")}
                  {!saving && <ArrowRight className="h-4 w-4" />}
                </button>
              </div>
            </div>
          )}
        </div>

        <p className={`mt-4 text-center text-[11px] ${T.sub}`}>
          {t("onboarding.step2.benefit_3")}
        </p>
      </div>
    </div>
  );
}
