"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Bell, BellOff, Check, CreditCard, Fingerprint, Loader2, LogOut, MapPin, Pencil, ShieldCheck, Trash2, X } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import {
  deleteMyPasskey,
  fetchMyPasskeys,
  isPasskeySupported,
  PasskeyError,
  PasskeyInfo,
  registerPasskey,
  setPasskeyHint,
} from "@/lib/webauthn";
import {
  clearBaseLocation,
  fetchInterestPushSettings,
  InterestPushSetting,
  setBaseLocation,
  setInterestPush,
  setPushPreferences,
  updateCompanyName,
} from "@/lib/api-client";
import CheckoutModal from "@/components/CheckoutModal";

const subscribeNoop = () => () => {};

const CATEGORY_LABEL_KEYS: Record<string, string> = {
  Roof: "dashboard.cat.telhado",
  Structure: "dashboard.cat.estrutura",
  Plumbing: "dashboard.cat.encanamento",
  Grass: "dashboard.cat.mato",
  Paint: "dashboard.cat.pintura",
  Permit_Rejected: "dashboard.cat.obras",
  Heating: "dashboard.cat.heating",
  Electrical: "dashboard.cat.electrical",
  Elevator: "dashboard.cat.elevator",
  Gas: "dashboard.cat.gas",
  Rodent: "dashboard.cat.rodent",
  Mold: "dashboard.cat.mold",
  Lead: "dashboard.cat.lead",
  Unsanitary: "dashboard.cat.unsanitary",
  Door_Window: "dashboard.cat.door_window",
  Debris: "dashboard.cat.debris",
};

// Centroides estaticos (sem APIs de mapas): fallback para quando o utilizador
// nao quer partilhar a localizacao GPS. A distancia fica "na sua cidade".
const CITY_CENTROIDS: Record<string, { lat: number; lng: number }> = {
  NYC: { lat: 40.7128, lng: -74.006 },
  Chicago: { lat: 41.8781, lng: -87.6298 },
  Boston: { lat: 42.3601, lng: -71.0589 },
  Dallas: { lat: 32.7767, lng: -96.797 },
};

// Toggle acessivel reutilizavel (B2). Mantem o mesmo aspeto do interruptor de
// privacidade, para a pagina nao acumular variantes visuais.
function Toggle({
  on,
  disabled,
  label,
  onToggle,
}: {
  on: boolean;
  disabled?: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-50 ${on ? "bg-emerald-500" : "bg-white/15"}`}
    >
      <span
        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${on ? "left-[22px]" : "left-0.5"}`}
      />
    </button>
  );
}

function PasskeySettings() {
  const { t } = useI18n();
  const supported = useSyncExternalStore(
    subscribeNoop,
    () => isPasskeySupported(),
    () => false
  );
  const [passkeys, setPasskeys] = useState<PasskeyInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const refresh = async () => {
    try {
      setPasskeys(await fetchMyPasskeys());
    } catch (e) {
      setError(
        e instanceof PasskeyError ? e.message : t("settings.passkey.load_error")
      );
    }
  };

  useEffect(() => {
    let alive = true;
    fetchMyPasskeys()
      .then((rows) => {
        if (alive) setPasskeys(rows);
      })
      .catch((e) => {
        if (!alive) return;
        setError(
          e instanceof PasskeyError ? e.message : t("settings.passkey.load_error")
        );
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const add = async () => {
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      const out = await registerPasskey();
      setPasskeyHint(true);
      setOk(
        t("settings.passkey.added", { device: out.device_label }) ||
          `Face ID ativo neste ${out.device_label}.`
      );
      await refresh();
    } catch (e) {
      const code = e instanceof PasskeyError ? e.code : "failed";
      setError(
        code === "unsupported"
          ? t("settings.passkey.unsupported")
          : code === "cancelled"
            ? t("settings.passkey.cancelled")
            : t("settings.passkey.add_error")
      );
    } finally {
      setBusy(false);
    }
  };

  const remove = async (credentialId: string) => {
    if (!window.confirm(t("settings.passkey.remove_confirm"))) return;
    setError(null);
    setOk(null);
    try {
      await deleteMyPasskey(credentialId);
      await refresh();
      if (!(await fetchMyPasskeys()).length) setPasskeyHint(false);
    } catch {
      setError(t("settings.passkey.remove_error"));
    }
  };

  return (
    <div className="rounded-2xl border border-white/10 bg-[#14161d] p-5 space-y-4" data-testid="passkey-settings">
      <div className="flex items-center gap-2">
        <Fingerprint className="w-4 h-4 text-indigo-400" />
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">
          {t("settings.passkey.title")}
        </h2>
      </div>
      <p className="text-xs text-slate-400 leading-relaxed">
        {t("settings.passkey.sub")}
      </p>

      {!supported ? (
        <p className="text-xs text-amber-400">{t("settings.passkey.unsupported")}</p>
      ) : (
        <button
          onClick={() => void add()}
          disabled={busy}
          data-testid="passkey-register"
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-3 py-2 text-xs font-semibold text-white"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Fingerprint className="w-3.5 h-3.5" />}
          {busy ? t("settings.passkey.adding") : t("settings.passkey.add")}
        </button>
      )}

      {ok && <p className="text-xs text-emerald-400" data-testid="passkey-ok">{ok}</p>}
      {error && <p role="alert" className="text-xs text-amber-400" data-testid="passkey-error">{error}</p>}

      {passkeys.length > 0 && (
        <ul className="divide-y divide-white/5 rounded-xl border border-white/10">
          {passkeys.map((p) => (
            <li key={p.id} className="flex items-center gap-2 px-3 py-2 text-xs" data-testid="passkey-item">
              <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
              <div className="min-w-0">
                <p className="font-medium text-slate-200">{p.device_label}</p>
                <p className="text-[10px] text-slate-500">
                  {p.last_used_at
                    ? `${t("settings.passkey.last_used")} ${new Date(
                        p.last_used_at.includes("T") ? p.last_used_at : p.last_used_at.replace(" ", "T") + "Z"
                      ).toLocaleDateString()}`
                    : t("settings.passkey.never_used")}
                </p>
              </div>
              <button
                onClick={() => void remove(p.credential_id)}
                className="ml-auto inline-flex items-center gap-1 rounded-md border border-rose-500/30 px-2 py-1 text-[10px] font-semibold text-rose-300 hover:bg-rose-500/10"
              >
                <Trash2 className="w-3 h-3" /> {t("settings.passkey.remove")}
              </button>
            </li>
          ))}
        </ul>
      )}
      {passkeys.length === 0 && supported && (
        <p className="text-[11px] text-slate-500">{t("settings.passkey.none")}</p>
      )}
    </div>
  );
}

export default function DashboardSettingsPage() {
  const { user, loading, signOut, updateUser } = useAuth();
  const { t, lang } = useI18n();
  const router = useRouter();
  const [showCheckout, setShowCheckout] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [editingCompany, setEditingCompany] = useState(false);
  const [companyDraft, setCompanyDraft] = useState("");
  const [companyError, setCompanyError] = useState("");
  const [savingCompany, setSavingCompany] = useState(false);
  const [geoBusy, setGeoBusy] = useState(false);
  const [geoMsg, setGeoMsg] = useState("");
  const [geoError, setGeoError] = useState("");
  const [interestPush, setInterestPushState] = useState<InterestPushSetting[]>([]);
  const [pushBusyCat, setPushBusyCat] = useState<string | null>(null);

  useEffect(() => {
    if (!user?.id) return;
    let cancelled = false;
    fetchInterestPushSettings(user.id)
      .then((settings) => {
        if (!cancelled) setInterestPushState(settings);
      })
      .catch(() => {
        /* preferencias sao secundarias; a pagina continua utilizavel */
      });
    return () => {
      cancelled = true;
    };
  }, [user?.id]);

  const planLabel = (plan: string) => t(`plan.${plan}`);

  const handleLogout = async () => {
    setLoggingOut(true);
    await signOut();
    router.push("/");
  };

  const startEditCompany = () => {
    setCompanyDraft(user?.company_name || "");
    setCompanyError("");
    setEditingCompany(true);
  };

  const cancelEditCompany = () => {
    setEditingCompany(false);
    setCompanyError("");
  };

  const saveCompany = async () => {
    if (!user) return;
    const name = companyDraft.trim();
    if (!name) {
      setCompanyError(t("dashboard.settings.company_required"));
      return;
    }
    setSavingCompany(true);
    setCompanyError("");
    try {
      const updated = await updateCompanyName(user.id, name);
      updateUser(updated);
      setEditingCompany(false);
    } catch (e: any) {
      setCompanyError(e?.message || t("dashboard.settings.company_error"));
    } finally {
      setSavingCompany(false);
    }
  };

  const applyGpsBase = () => {
    if (!user) return;
    if (!navigator.geolocation) {
      setGeoError(t("dashboard.settings.base_error"));
      return;
    }
    setGeoBusy(true);
    setGeoMsg("");
    setGeoError("");
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const updated = await setBaseLocation(user.id, {
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            source: "gps",
            label: t("dashboard.settings.base_gps_label"),
          });
          updateUser(updated);
          setGeoMsg(t("dashboard.settings.base_saved"));
        } catch (e: any) {
          setGeoError(e?.message || t("dashboard.settings.base_error"));
        } finally {
          setGeoBusy(false);
        }
      },
      () => {
        setGeoError(t("dashboard.settings.base_denied"));
        setGeoBusy(false);
      },
      { timeout: 10000, maximumAge: 300000 }
    );
  };

  const applyCityBase = async (city: string) => {
    if (!user) return;
    const c = CITY_CENTROIDS[city];
    if (!c) return;
    setGeoBusy(true);
    setGeoMsg("");
    setGeoError("");
    try {
      const updated = await setBaseLocation(user.id, {
        lat: c.lat,
        lng: c.lng,
        source: "city",
        label: city,
      });
      updateUser(updated);
      setGeoMsg(t("dashboard.settings.base_saved"));
    } catch (e: any) {
      setGeoError(e?.message || t("dashboard.settings.base_error"));
    } finally {
      setGeoBusy(false);
    }
  };

  const removeBase = async () => {
    if (!user) return;
    setGeoBusy(true);
    setGeoError("");
    try {
      const updated = await clearBaseLocation(user.id);
      updateUser(updated);
      setGeoMsg("");
    } catch (e: any) {
      setGeoError(e?.message || t("dashboard.settings.base_error"));
    } finally {
      setGeoBusy(false);
    }
  };

  const toggleShowAddress = async () => {
    if (!user) return;
    setGeoBusy(true);
    setGeoError("");
    try {
      const updated = await setPushPreferences(user.id, {
        show_address_in_push: user.show_address_in_push === false,
      });
      updateUser(updated);
    } catch (e: any) {
      setGeoError(e?.message || t("dashboard.settings.base_error"));
    } finally {
      setGeoBusy(false);
    }
  };

  const toggleDigest = async () => {
    if (!user) return;
    setGeoBusy(true);
    setGeoError("");
    try {
      const updated = await setPushPreferences(user.id, {
        digest_enabled: user.digest_enabled === false,
      });
      updateUser(updated);
    } catch (e: any) {
      setGeoError(e?.message || t("dashboard.settings.base_error"));
    } finally {
      setGeoBusy(false);
    }
  };

  const toggleLifecycle = async () => {
    if (!user) return;
    setGeoBusy(true);
    setGeoError("");
    try {
      const updated = await setPushPreferences(user.id, {
        lifecycle_push_enabled: user.lifecycle_push_enabled !== true,
      });
      updateUser(updated);
    } catch (e: any) {
      setGeoError(e?.message || t("dashboard.settings.base_error"));
    } finally {
      setGeoBusy(false);
    }
  };

  const toggleChime = async () => {
    if (!user) return;
    setGeoBusy(true);
    setGeoError("");
    try {
      const updated = await setPushPreferences(user.id, {
        chime_enabled: user.chime_enabled === false,
      });
      updateUser(updated);
    } catch (e: any) {
      setGeoError(e?.message || t("dashboard.settings.base_error"));
    } finally {
      setGeoBusy(false);
    }
  };

  const toggleCategoryPush = async (category: string, enabled: boolean) => {
    if (!user) return;
    setPushBusyCat(category);
    setGeoError("");
    try {
      const settings = await setInterestPush(user.id, category, !enabled);
      setInterestPushState(settings);
    } catch (e: any) {
      setGeoError(e?.message || t("dashboard.settings.base_error"));
    } finally {
      setPushBusyCat(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-xl font-semibold">{t("dashboard.nav.settings")}</h1>
            <p className="text-sm text-slate-400">{t("dashboard.settings.sub")}</p>
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-emerald-500" /></div>
        ) : !user ? (
          <p className="text-slate-400">{t("dashboard.settings.logged_out")}</p>
        ) : (
          <>
            <div className="rounded-2xl border border-white/10 bg-[#14161d] p-5 space-y-4">
              <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">{t("dashboard.settings.account")}</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.auth.company")}</p>
                  {editingCompany ? (
                    <div className="mt-1 space-y-2">
                      <input
                        type="text"
                        value={companyDraft}
                        onChange={(e) => setCompanyDraft(e.target.value)}
                        disabled={savingCompany}
                        maxLength={120}
                        autoFocus
                        className="w-full px-3 py-1.5 rounded-lg bg-white/10 border border-white/15 text-sm text-white placeholder-slate-500 outline-none focus:border-emerald-500"
                      />
                      <p className="text-[11px] text-slate-400 leading-relaxed">{t("dashboard.settings.company_hint")}</p>
                      {companyError && <p className="text-xs text-red-400">{companyError}</p>}
                      <div className="flex items-center gap-2">
                        <button
                          onClick={saveCompany}
                          disabled={savingCompany}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-900 text-xs font-semibold disabled:opacity-50"
                        >
                          {savingCompany ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                          {t("dashboard.settings.save")}
                        </button>
                        <button
                          onClick={cancelEditCompany}
                          disabled={savingCompany}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 text-xs font-medium disabled:opacity-50"
                        >
                          <X className="w-3.5 h-3.5" /> {t("dashboard.settings.cancel")}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-medium break-all">{user.company_name || "—"}</p>
                      <button
                        onClick={startEditCompany}
                        className="flex items-center gap-1 px-2 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 text-xs"
                      >
                        <Pencil className="w-3 h-3" /> {t("dashboard.settings.edit")}
                      </button>
                    </div>
                  )}
                </div>
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.field.email")}</p>
                  <p className="font-medium break-all">{user.email}</p>
                </div>
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.settings.plan")}</p>
                  <p className="font-medium capitalize">{planLabel(user.plan || "free")}</p>
                </div>
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.settings.status")}</p>
                  <p className="font-medium capitalize">{user.subscription_status || user.plan}</p>
                </div>
              </div>
              <div className="rounded-xl bg-white/5 border border-white/10 p-3 text-sm">
                <p className="text-xs text-slate-400">{t("dashboard.settings.access_until")}</p>
                <p className="font-medium">
                  {user.plan_until ? new Date(user.plan_until.replace(" ", "T")).toLocaleDateString(lang === "en" ? "en-US" : lang === "es" ? "es-ES" : "pt-BR") : "—"}
                </p>
              </div>
            </div>

            <PasskeySettings />

            <div className="rounded-2xl border border-white/10 bg-[#14161d] p-5 space-y-4">
              <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">{t("dashboard.settings.alerts")}</h2>

              {/* Base para distancia (informativa, sem filtro de raio) */}
              <div className="rounded-xl bg-white/5 border border-white/10 p-3 space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <MapPin className="w-4 h-4 text-emerald-400" /> {t("dashboard.settings.base_title")}
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">{t("dashboard.settings.base_hint")}</p>
                <p className="text-xs text-slate-300">
                  {user.base_lat !== null && user.base_lat !== undefined
                    ? `${t("dashboard.settings.base_current")}: ${user.base_label || "GPS"}`
                    : t("dashboard.settings.base_none")}
                </p>
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <button
                    onClick={applyGpsBase}
                    disabled={geoBusy}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-900 text-xs font-semibold disabled:opacity-50"
                  >
                    {geoBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <MapPin className="w-3.5 h-3.5" />}
                    {t("dashboard.settings.base_gps")}
                  </button>
                  {Object.keys(CITY_CENTROIDS).map((city) => (
                    <button
                      key={city}
                      onClick={() => applyCityBase(city)}
                      disabled={geoBusy}
                      className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-xs font-medium disabled:opacity-50"
                    >
                      {city}
                    </button>
                  ))}
                  {user.base_lat !== null && user.base_lat !== undefined && (
                    <button
                      onClick={removeBase}
                      disabled={geoBusy}
                      className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-rose-500/10 text-slate-400 hover:text-rose-300 text-xs font-medium disabled:opacity-50"
                    >
                      {t("dashboard.settings.base_clear")}
                    </button>
                  )}
                </div>
                <p className="text-[11px] text-emerald-300/80 leading-relaxed">
                  {t("dashboard.settings.distance_note")}
                </p>
                {geoMsg && <p className="text-[11px] text-emerald-400">{geoMsg}</p>}
                {geoError && <p className="text-[11px] text-red-400">{geoError}</p>}
              </div>

              {/* Quiet hours (politica fixa) */}
              <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <ShieldCheck className="w-4 h-4 text-indigo-400" /> {t("dashboard.settings.quiet_title")}
                </div>
                <p className="text-xs text-slate-400 leading-relaxed mt-1">{t("dashboard.settings.quiet_body")}</p>
              </div>

              {/* Privacidade da morada */}
              <div className="rounded-xl bg-white/5 border border-white/10 p-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{t("dashboard.settings.show_address")}</p>
                  <p className="text-xs text-slate-400 leading-relaxed mt-0.5">{t("dashboard.settings.show_address_hint")}</p>
                </div>
                <Toggle
                  on={user.show_address_in_push !== false}
                  disabled={geoBusy}
                  label={t("dashboard.settings.show_address")}
                  onToggle={toggleShowAddress}
                />
              </div>

              {/* Resumo diario (B2, default ligado) */}
              <div className="rounded-xl bg-white/5 border border-white/10 p-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{t("dashboard.settings.digest_title")}</p>
                  <p className="text-xs text-slate-400 leading-relaxed mt-0.5">{t("dashboard.settings.digest_hint")}</p>
                </div>
                <Toggle
                  on={user.digest_enabled !== false}
                  disabled={geoBusy}
                  label={t("dashboard.settings.digest_title")}
                  onToggle={toggleDigest}
                />
              </div>

              {/* Avisos de reserva (B2, opt-in; 60 min fura o silencio) */}
              <div className="rounded-xl bg-white/5 border border-white/10 p-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{t("dashboard.settings.lifecycle_title")}</p>
                  <p className="text-xs text-slate-400 leading-relaxed mt-0.5">{t("dashboard.settings.lifecycle_hint")}</p>
                </div>
                <Toggle
                  on={user.lifecycle_push_enabled === true}
                  disabled={geoBusy}
                  label={t("dashboard.settings.lifecycle_title")}
                  onToggle={toggleLifecycle}
                />
              </div>

              {/* Chime in-app (B3, default ligado) */}
              <div className="rounded-xl bg-white/5 border border-white/10 p-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{t("dashboard.settings.chime_title")}</p>
                  <p className="text-xs text-slate-400 leading-relaxed mt-0.5">{t("dashboard.settings.chime_hint")}</p>
                </div>
                <Toggle
                  on={user.chime_enabled !== false}
                  disabled={geoBusy}
                  label={t("dashboard.settings.chime_title")}
                  onToggle={toggleChime}
                />
              </div>

              {/* Push por oficio (B2): o sino desliga so o push, o in-app fica */}
              <div className="rounded-xl bg-white/5 border border-white/10 p-3 space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Bell className="w-4 h-4 text-emerald-400" /> {t("dashboard.settings.trades_title")}
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">{t("dashboard.settings.trades_hint")}</p>
                {interestPush.length === 0 ? (
                  <p className="text-xs text-slate-400 italic">{t("dashboard.settings.trades_empty")}</p>
                ) : (
                  <ul className="divide-y divide-white/5">
                    {interestPush.map((s) => (
                      <li key={s.category} className="flex items-center justify-between gap-3 py-2">
                        <span className="flex items-center gap-2 text-sm text-slate-200 min-w-0">
                          {s.push_enabled ? (
                            <Bell className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                          ) : (
                            <BellOff className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                          )}
                          <span className="truncate">
                            {CATEGORY_LABEL_KEYS[s.category]
                              ? t(CATEGORY_LABEL_KEYS[s.category])
                              : s.category}
                          </span>
                        </span>
                        <Toggle
                          on={s.push_enabled}
                          disabled={pushBusyCat === s.category}
                          label={s.category}
                          onToggle={() => toggleCategoryPush(s.category, s.push_enabled)}
                        />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-[#14161d] p-5 space-y-4">
              <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">{t("dashboard.settings.reputation")}</h2>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.kpi.score.delta")}</p>
                  <p className="font-medium text-fuchsia-300">{user.score || 100} pts</p>
                </div>
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.kpi.taken")}</p>
                  <p className="font-medium">{user.leads_taken || 0}</p>
                </div>
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.kpi.conversions")}</p>
                  <p className="font-medium">{user.conversions || 0}</p>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-[#14161d] p-5 flex flex-col sm:flex-row sm:items-center gap-4">
              <div className="flex-1">
                <h2 className="text-sm font-semibold text-slate-300">{t("dashboard.settings.subscription_title")}</h2>
                <p className="text-sm text-slate-400">
                  {t("dashboard.settings.subscription_body")}
                </p>
              </div>
              <button
                onClick={() => setShowCheckout(true)}
                className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-900 font-semibold text-sm"
              >
                <CreditCard className="w-4 h-4" /> {t("dashboard.settings.renew")}
              </button>
            </div>

            <button
              onClick={handleLogout}
              disabled={loggingOut}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 font-medium text-sm disabled:opacity-50"
            >
              {loggingOut ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogOut className="w-4 h-4" />} {t("dashboard.settings.logout")}
            </button>
          </>
        )}

        <CheckoutModal
          open={showCheckout}
          onClose={() => setShowCheckout(false)}
          onActivated={() => window.location.reload()}
          isDark
          mode={user?.subscription_status === "expired" || user?.subscription_status === "pending_payment" ? "new" : "reactivate"}
        />
      </div>
    </div>
  );
}