"use client";

import { useEffect, useMemo, useState } from "react";
import { Building2, CreditCard, Loader2, ShieldCheck, X } from "lucide-react";
import { useStartCheckout, SUBSCRIPTION_PLAN } from "@/lib/billing";
import { updateCompanyName } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

interface CheckoutModalProps {
  open: boolean;
  onClose: () => void;
  onActivated?: () => void;
  isDark?: boolean;
}

export default function CheckoutModal({ open, onClose, isDark = false }: CheckoutModalProps) {
  const { user, updateUser } = useAuth();
  const { t } = useI18n();
  const startCheckout = useStartCheckout();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [companyName, setCompanyName] = useState("");

  useEffect(() => {
    if (user?.company_name && !companyName) setCompanyName(user.company_name);
  }, [user, companyName]);

  const c = useMemo(
    () => ({
      card: isDark ? "bg-[#14161d] border-white/10" : "bg-white border-slate-200",
      box: isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200",
      text: isDark ? "text-slate-300" : "text-slate-600",
      textSoft: isDark ? "text-slate-400" : "text-slate-500",
      strong: isDark ? "text-white" : "text-slate-900",
      btn: "bg-emerald-500 hover:bg-emerald-400 text-slate-900",
      input: isDark
        ? "bg-white/10 border-white/15 text-white placeholder-slate-500 focus:border-emerald-500"
        : "bg-white border-slate-300 text-slate-900 placeholder-slate-400 focus:border-emerald-500",
    }),
    [isDark]
  );

  if (!open) return null;

  const handleSubscribe = async () => {
    const name = companyName.trim();
    if (!name) {
      setError(t("checkout.error_company_req"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (user) {
        if (name !== (user.company_name || "")) {
          const updated = await updateCompanyName(user.id, name);
          updateUser(updated);
        }
      }
      const res = await startCheckout();
      if (res.checkout_url) {
        // Popups após await são bloqueados pelo navegador; redirecionamos na
        // mesma aba para a página hospedada do Stripe Checkout.
        window.location.href = res.checkout_url;
        return;
      }
      setError(t("checkout.error_payment_fail"));
      setBusy(false);
    } catch (e: any) {
      setError(e?.message || t("checkout.error_generic_fail"));
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={busy ? undefined : onClose} />
      <div className={`relative w-full max-w-md border rounded-2xl p-6 space-y-5 shadow-2xl animate-scale-in ${c.card}`}>
        <button
          onClick={onClose}
          disabled={busy}
          className="absolute right-4 top-4 p-1 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 disabled:opacity-40"
        >
          <X className="w-5 h-5" />
        </button>

        <>
          <div className="flex items-center gap-2">
              <CreditCard className="w-5 h-5 text-emerald-500" />
              <h3 className={`text-lg font-semibold ${c.strong}`}>{t("checkout.title")}</h3>
            </div>

            <div className={`rounded-xl border p-4 flex items-center justify-between ${c.box}`}>
              <div>
                <p className={`text-sm font-semibold ${c.strong}`}>{t("checkout.plan_label")} {SUBSCRIPTION_PLAN.name}</p>
                <p className={`text-xs ${c.textSoft}`}>{t("checkout.pay_once")}</p>
              </div>
              <div className="text-right">
                <p className={`text-2xl font-bold text-emerald-500`}>
                  ${SUBSCRIPTION_PLAN.amount}
                  <span className={`text-sm font-medium ${c.textSoft}`}>{t("checkout.per_week")}</span>
                </p>
                <p className={`text-xs ${c.textSoft}`}>{t("checkout.annual_short").replace("${amount}", String(SUBSCRIPTION_PLAN.annual))}</p>
              </div>
            </div>

            <ul className={`space-y-2 text-sm ${c.text}`}>
              <li className="flex items-start gap-2">
                <ShieldCheck className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                {t("checkout.feat1")}
              </li>
              <li className="flex items-start gap-2">
                <ShieldCheck className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                {t("checkout.feat2")}
              </li>
              <li className="flex items-start gap-2">
                <ShieldCheck className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                {t("checkout.feat3")}
              </li>
            </ul>

            <div className={`rounded-xl border p-4 space-y-2 ${c.box}`}>
              <label className={`flex items-center gap-2 text-sm font-semibold ${c.strong}`}>
                <Building2 className="w-4 h-4 text-emerald-500" />
                {t("checkout.company_name.label")}
              </label>
              <input
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder={t("checkout.company_name.placeholder")}
                disabled={busy}
                maxLength={120}
                className={`w-full px-3 py-2.5 rounded-lg border text-sm outline-none transition-colors focus:ring-2 focus:ring-emerald-500/30 disabled:opacity-50 ${c.input}`}
              />
              <p className={`text-[11px] leading-relaxed ${c.textSoft}`}>
                {t("checkout.company_name.help")}
              </p>
            </div>

            {error && <p className="text-sm text-red-500">{error}</p>}

            <button
              onClick={handleSubscribe}
              disabled={busy}
              className={`w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm ${c.btn} disabled:opacity-50`}
            >
              {busy ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t("checkout.btn_processing")}
                </>
              ) : (
                <>
                  <CreditCard className="w-4 h-4" />
                  {t("checkout.btn_pay_label").replace("${amount}", String(SUBSCRIPTION_PLAN.amount))}
                </>
              )}
            </button>

            <p className={`text-[11px] text-center ${c.textSoft}`}>
              {t("checkout.payment_secure")}
            </p>
          </>
      </div>
    </div>
  );
}