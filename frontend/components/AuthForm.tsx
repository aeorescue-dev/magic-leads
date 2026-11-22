'use client';

import { useState, useEffect, useRef, useSyncExternalStore } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { Loader2, Eye, EyeOff, Mail, Lock, Building2, ArrowRight, CheckCircle, AlertTriangle, X, Fingerprint } from 'lucide-react';
import { useAuth } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';
import { useStartCheckout } from '@/lib/billing';
import { trackEvent } from '@/lib/analytics';
import { requestPasswordReset, setAuthCookie, setToken } from '@/lib/api-client';
import { mockPlanCheckout } from '@/lib/subscription-api';
import { hasPasskeyHint, isPasskeySupported, loginWithPasskey, PasskeyError, passkeyMessageKey, passkeyPlatform, passkeyPlatformSuffix, setPasskeyHint } from '@/lib/webauthn';

const subscribeNoop = () => () => {};

// Quando o bónus de boas-vindas está ativo, o registo vai direto à dashboard
// (sem checkout obrigatório); o utilizador só vê os planos quando esgota.
const FREE_UNLOCKS_UI = process.env.NEXT_PUBLIC_FREE_UNLOCKS === '1';

function TurnstileWidget({ onToken }: { onToken: (token: string) => void }) {
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || '';
  const holder = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!siteKey || !holder.current) return;
    let cancelled = false;
    const render = () => {
      const w = window as any;
      if (cancelled || !w.turnstile || !holder.current) return;
      holder.current.innerHTML = '';
      w.turnstile.render(holder.current, {
        sitekey: siteKey,
        callback: (token: string) => onToken(token),
        'expired-callback': () => onToken(''),
        'error-callback': () => onToken(''),
      });
    };
    const w = window as any;
    if (w.turnstile) {
      render();
      return;
    }
    const existing = document.querySelector('script[data-turnstile]');
    if (existing) {
      existing.addEventListener('load', render);
      return () => existing.removeEventListener('load', render);
    }
    const script = document.createElement('script');
    script.src =
      'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    script.async = true;
    script.defer = true;
    script.setAttribute('data-turnstile', '1');
    script.addEventListener('load', render);
    document.head.appendChild(script);
    return () => {
      cancelled = true;
    };
  }, [siteKey, onToken]);

  if (!siteKey) return null;
  return <div ref={holder} className="flex justify-center py-1" />;
}

interface FormErrors {
  email?: string;
  password?: string;
  company_name?: string;
  general?: string;
}

function ForgotPasswordForm({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setSubmitting(true);
    try {
      await requestPasswordReset(email);
      setSuccess(true);
      setTimeout(onClose, 2000);
    } catch (err) {
      alert(err instanceof Error ? err.message : t("auth.reset_error"));
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="text-center py-8">
        <CheckCircle className="h-12 w-12 text-emerald-500 mx-auto mb-3" />
        <h3 className="text-lg font-semibold">{t("auth.email_sent")}</h3>
        <p className="text-sm text-muted-foreground mt-1">{t("auth.check_inbox")}</p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} data-track-form="auth" className="space-y-4">
      <div className="relative">
        <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t('dashboard.auth.email_placeholder') || 'seu@email.com'}
          className="w-full pl-10 pr-4 py-2.5 rounded-lg border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
          disabled={submitting}
          autoComplete="email"
          required
        />
      </div>
      <button
        type="submit"
        disabled={submitting || !email.trim()}
        className="w-full py-3 rounded-lg bg-primary text-primary-foreground font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
      >
        {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
        <ArrowRight className="h-4 w-4" />
        {t('dashboard.auth.reset_password')}
      </button>
      <button
        type="button"
        onClick={onClose}
        className="w-full py-2 text-sm text-muted-foreground hover:text-foreground"
      >
        {t('dashboard.auth.cancel')}
      </button>
    </form>
  );
}

function AuthFormInner({
  preselectedTrade,
  preselectedPlan,
  initialRegister,
}: {
  preselectedTrade?: string;
  preselectedPlan?: string;
  initialRegister?: boolean;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const reason = searchParams.get('reason');
  // Compatibilidade: /auth?session_expired=1 (legado) == reason=session_expired
  const sessionReason = reason === 'fifo_evicted'
    ? 'fifo_evicted'
    : reason === 'session_expired' || searchParams.get('session_expired') === '1'
      ? 'session_expired'
      : null;
  const { lang, t } = useI18n();
  const { signIn, loading: authLoading, updateUser, refreshSubscription } = useAuth();
  const startCheckout = useStartCheckout();
  const rawNext = searchParams.get('next');
  const nextPath =
    rawNext && rawNext.startsWith('/') && !rawNext.startsWith('//')
      ? rawNext
      : null;
  const checkoutIntent = searchParams.get('checkout') === '1';

  const localePath = (href: string) => `/${lang}${href}`;

  // Checkout com plano escolhido na landing. Em produção devolve o URL do
  // Stripe; em staging com BILLING_MOCK=1 ativa o plano e segue para o painel.
  const startCheckoutWithPlan = async (): Promise<string | null> => {
    const res = await startCheckout(preselectedTrade, preselectedPlan);
    if (res.checkout_url) return res.checkout_url;
    if (res.mock && preselectedPlan) {
      await mockPlanCheckout(preselectedPlan);
      return localePath('/dashboard');
    }
    return null;
  };

  // Mensagem direta sem depender de t() — evita chave crua mesmo se i18n falhar.
  const sessionMessage = sessionReason === 'fifo_evicted'
    ? t('dashboard.auth.session_fifo')
    : sessionReason === 'session_expired'
      ? t('dashboard.auth.session_expired')
      : null;

  const [isRegister, setIsRegister] = useState(Boolean(initialRegister));
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showForgotPassword, setShowForgotPassword] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [passkeyBusy, setPasskeyBusy] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState('');
  const [passkeyError, setPasskeyError] = useState<string | null>(null);
  const [passkeyDetail, setPasskeyDetail] = useState<string | null>(null);
  // Só depois da hidratação: no servidor não há window/PublicKeyCredential.
  const passkeyReady = useSyncExternalStore(
    subscribeNoop,
    () => isPasskeySupported() && hasPasskeyHint(),
    () => false
  );
  // Rótulo honesto por plataforma (Android não tem Face ID).
  const passkeyPlatformValue = useSyncExternalStore(
    subscribeNoop,
    passkeyPlatform,
    () => 'other' as const
  );
  const passkeyLabelKey = `auth.passkey.login_${passkeyPlatformSuffix(passkeyPlatformValue)}`;
  // Ignora resultados atrasados de uma tentativa anterior (cancelar + repetir).
  const attemptRef = useRef(0);

  const handlePasskeyLogin = async () => {
    const attempt = ++attemptRef.current;
    setPasskeyBusy(true);
    setPasskeyError(null);
    setPasskeyDetail(null);
    try {
      const out = await loginWithPasskey(email.trim() || undefined);
      if (attempt !== attemptRef.current) return;
      setToken(out.token);
      setAuthCookie();
      updateUser(out.user);
      await refreshSubscription();
      const destination = nextPath || (out.user.is_admin ? '/admin/lp-inbox' : localePath('/dashboard'));
      router.push(destination);
      router.refresh();
    } catch (e) {
      if (attempt !== attemptRef.current) return;
      const pe = e instanceof PasskeyError ? e : null;
      const serverCode = pe?.detail?.serverCode;
      const key =
        serverCode === 'passkey_not_recognized'
          ? 'unknown_passkey'
          : passkeyMessageKey(pe?.code ?? 'failed');
      if (serverCode === 'passkey_not_recognized') {
        // Credencial órfã no gestor do telemóvel: o botão deixa de fazer
        // sentido até haver um registo válido no servidor.
        setPasskeyHint(false);
      }
      const message = t(`auth.passkey.${key}`);
      setPasskeyError(message || 'Não foi possível entrar com a chave de acesso. Use a palavra-passe.');
      setPasskeyDetail(
        pe?.detail?.browserError ||
          pe?.detail?.serverCode ||
          (pe?.code === 'server' ? pe.message : null)
      );
    } finally {
      if (attempt === attemptRef.current) setPasskeyBusy(false);
    }
  };

  const validate = () => {
    const newErrors: FormErrors = {};
    if (!email.trim()) {
      newErrors.email = t('dashboard.auth.email_required') || 'Email é obrigatório';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      newErrors.email = t('dashboard.auth.email_invalid') || 'Email inválido';
    }
    if (!password) {
      newErrors.password = t('dashboard.auth.password_required') || 'Senha é obrigatória';
    } else if (password.length < 6) {
      newErrors.password = t('dashboard.auth.password_min') || 'Mínimo 6 caracteres';
    }
    if (isRegister && !companyName.trim()) {
      newErrors.company_name = t('dashboard.auth.company_required') || 'Nome da empresa é obrigatório';
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    if (
      isRegister &&
      process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY &&
      !turnstileToken
    ) {
      setErrors({ general: 'Confirma que não és um robô (Turnstile).' });
      return;
    }

    setSubmitting(true);
    setErrors({});

    try {
      const user = await signIn(email.trim(), password, isRegister ? companyName.trim() : undefined, lang, isRegister ? turnstileToken : undefined);
      if (isRegister && FREE_UNLOCKS_UI) {
        // Bónus free: entra direto na dashboard para usar os desbloqueios.
        setSuccess(true);
        setTimeout(() => {
          window.location.href = `/${lang}/dashboard`;
        }, 600);
        return;
      }
      if (isRegister) {
        // Cadastro concluído: o acesso só é liberado após o pagamento.
        // Cria a sessão do Stripe Checkout e redireciona imediatamente.
        // NUNCA cai em fallback para /dashboard: sem URL real é erro.
        let checkoutUrl: string | null = null;
        try {
          checkoutUrl = await startCheckoutWithPlan();
        } catch (err: any) {
          const msg = err?.response?.data?.detail || err?.message || t('dashboard.auth.error_generic') || 'Erro ao iniciar pagamento';
          setErrors({ general: msg });
          setSubmitting(false);
          return;
        }
        if (!checkoutUrl) {
          setErrors({ general: 'Pagamento indisponível no momento. Tente novamente em instantes ou fale com o suporte para liberar seu acesso.' });
          setSubmitting(false);
          return;
        }
        setSuccess(true);
        trackEvent("checkout_started", "signup");
        setTimeout(() => {
          window.location.href = checkoutUrl;
        }, 600);
      } else if (checkoutIntent || preselectedPlan) {
        setSuccess(true);
        try {
          const checkoutUrl = await startCheckoutWithPlan();
          if (!checkoutUrl) throw new Error("checkout_unavailable");
          trackEvent("checkout_started", "login");
          setTimeout(() => {
            window.location.href = checkoutUrl;
          }, 600);
        } catch (err: any) {
          setSuccess(false);
          const msg =
            err?.response?.data?.detail ||
            err?.message ||
            'Pagamento indisponível no momento. Tente novamente.';
          setErrors({ general: msg });
        }
      } else {
        setSuccess(true);
        const destination = nextPath || (user.is_admin ? '/admin/lp-inbox' : localePath('/dashboard'));
        setTimeout(() => {
          router.push(destination);
          router.refresh();
        }, 800);
      }
    } catch (err: any) {
      const detail = err?.detail ?? err?.response?.data?.detail;
      const code = detail && typeof detail === 'object' ? detail.code : null;
      const msg =
        typeof detail === 'string'
          ? detail
          : detail?.message ||
            err?.message ||
            t('dashboard.auth.error_generic') ||
            'Erro ao autenticar';
      if (code === 'email_exists') {
        setErrors({
          email:
            msg ||
            'Já existe conta com este email. Entra para continuar ou assinar.',
        });
        setIsRegister(false);
      } else if (code === 'disposable_email' || code === 'captcha_failed') {
        setErrors({ general: msg });
      } else if (msg.includes('Email já cadastrado') || msg.includes('already registered')) {
        setErrors({ email: t('dashboard.auth.email_exists') || 'Email já cadastrado. Tente entrar.' });
        setIsRegister(false);
      } else if (msg.includes('inválidos') || msg.includes('invalid')) {
        setErrors({ general: t('dashboard.auth.invalid_credentials') || 'Email ou senha inválidos' });
      } else {
        setErrors({ general: msg });
      }
    } finally {
      setSubmitting(false);
    }
  };

  const toggleMode = () => {
    setIsRegister((prev) => !prev);
    setErrors({});
    setSuccess(false);
  };

  if (success) {
    return (
      <div className="text-center py-8">
        <CheckCircle className="h-12 w-12 text-emerald-500 mx-auto mb-3" />
        <h3 className="text-lg font-semibold text-foreground">{isRegister ? t('dashboard.auth.register_success') || 'Conta criada!' : t('dashboard.auth.login_success') || 'Entrada realizada!'}</h3>
        <p className="text-sm text-muted-foreground mt-1">{t('dashboard.auth.redirecting') || 'Redirecionando para o dashboard...'}</p>
      </div>
    );
  }

  // Forgot Password Modal
  if (showForgotPassword) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" onClick={() => setShowForgotPassword(false)}>
        <div className="w-full max-w-md bg-background rounded-2xl border border-border p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold">{t('dashboard.auth.forgot_password') || 'Esqueci minha senha'}</h2>
            <button onClick={() => setShowForgotPassword(false)} className="text-muted-foreground hover:text-foreground">
              <X className="h-5 w-5" />
            </button>
          </div>
          <p className="text-sm text-muted-foreground mb-6">
            {t('dashboard.auth.reset_email_sent') || 'Digite seu email abaixo e enviaremos um link para redefinir sua senha.'}
          </p>
          <ForgotPasswordForm onClose={() => setShowForgotPassword(false)} />
        </div>
      </div>
    );
  }

  // Render the actual form
  return (
    <form onSubmit={handleSubmit} data-track-form="auth_main" data-auth-register={isRegister} className="w-full max-w-md mx-auto space-y-4">
      {preselectedTrade ? (
        <div className="rounded-lg border border-primary/25 bg-primary/5 px-3 py-2 text-[11.5px] font-semibold text-primary">
          {t('landing.p1Selected')}: {preselectedTrade}
        </div>
      ) : null}
      <div className="flex justify-center gap-2 mb-2">
        <button
          type="button"
          onClick={() => { setIsRegister(false); setErrors({}); }}
          className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
            !isRegister ? 'bg-primary text-primary-foreground' : 'bg-secondary text-secondary-foreground'
          }`}
        >
          {t('dashboard.auth.login_title') || 'Entrar'}
        </button>
        <button
          type="button"
          onClick={() => { setIsRegister(true); setErrors({}); }}
          className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
            isRegister ? 'bg-primary text-primary-foreground' : 'bg-secondary text-secondary-foreground'
          }`}
        >
          {t('dashboard.auth.register_title') || 'Cadastrar'}
        </button>
      </div>

      {errors.general && (
        <div className="text-sm text-red-400 text-center bg-red-400/10 px-3 py-2 rounded-lg">
          {errors.general}
        </div>
      )}

      {sessionReason && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-black/40 border border-white/10 backdrop-blur-sm animate-in fade-in slide-in-from-top-2 duration-300">
          <AlertTriangle className="h-5 w-5 text-amber-400 shrink-0" aria-hidden="true" />
          <p className="text-sm text-gray-200 leading-relaxed">{sessionMessage}</p>
        </div>
      )}

      {!isRegister && passkeyReady && (
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => void handlePasskeyLogin()}
            disabled={passkeyBusy || submitting}
            data-testid="passkey-login"
            className="w-full py-3 rounded-lg bg-emerald-500 text-slate-950 font-semibold hover:bg-emerald-400 disabled:opacity-60 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            {passkeyBusy ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Fingerprint className="h-5 w-5" />
            )}
            {passkeyBusy
              ? t('auth.passkey.confirming') || 'A confirmar…'
              : t(passkeyLabelKey) || t('auth.passkey.login') || 'Entrar com chave de acesso'}
          </button>
          <p className="text-center text-[11px] text-muted-foreground">
            {t('auth.passkey.or_password') || 'ou continue com a palavra-passe'}
          </p>
        </div>
      )}

      {/* Fora do bloco do botão: quando `passkey_not_recognized` limpa o hint,
          o botão desaparece mas a explicação TEM de continuar visível. */}
      {!isRegister && passkeyError && (
        <div className="space-y-1">
          <p role="alert" className="text-xs text-amber-400 text-center">
            {passkeyError}
          </p>
          {passkeyDetail && (
            <p className="text-[10px] text-slate-500 text-center break-words" data-testid="passkey-detail">
              {passkeyDetail}
            </p>
          )}
        </div>
      )}

      <div className="space-y-3">
        <div className="relative">
          <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type="email"
            value={email}
            onChange={(e) => { setEmail(e.target.value); if (errors.email) setErrors({...errors, email: undefined}); }}
            placeholder={t('dashboard.auth.email_placeholder') || 'seu@email.com'}
            className={`w-full pl-10 pr-4 py-2.5 rounded-lg border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 ${
              errors.email ? 'border-red-400' : 'border-border'
            }`}
            disabled={submitting || success}
            autoComplete="email"
            required
          />
          {errors.email && <p className="mt-1 text-xs text-red-400 ml-1">{errors.email}</p>}
        </div>

        <div className="relative">
          <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={(e) => { setPassword(e.target.value); if (errors.password) setErrors({...errors, password: undefined}); }}
            placeholder={t('dashboard.auth.password_placeholder') || '••••••••'}
            className={`w-full pl-10 pr-12 py-2.5 rounded-lg border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 ${
              errors.password ? 'border-red-400' : 'border-border'
            }`}
            disabled={submitting || success}
            autoComplete={isRegister ? 'new-password' : 'current-password'}
            required
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label={showPassword ? t("auth.hide_password") : t("auth.show_password")}
          >
            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
          {errors.password && <p className="mt-1 text-xs text-red-400 ml-1">{errors.password}</p>}
        </div>

        {!isRegister && (
          <div className="text-right">
            <button
              type="button"
              onClick={() => setShowForgotPassword(true)}
              className="text-sm text-primary hover:underline"
            >
              {t('dashboard.auth.forgot_password') || 'Esqueci minha senha'}
            </button>
          </div>
        )}

        {isRegister && (
          <div className="relative">
            <Building2 className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              value={companyName}
              onChange={(e) => { setCompanyName(e.target.value); if (errors.company_name) setErrors({...errors, company_name: undefined}); }}
              placeholder={t('dashboard.auth.company_placeholder') || 'Nome da sua empresa'}
              className={`w-full pl-10 pr-4 py-2.5 rounded-lg border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 ${
                errors.company_name ? 'border-red-400' : 'border-border'
              }`}
              disabled={submitting || success}
              autoComplete="organization"
              required
            />
            {errors.company_name && <p className="mt-1 text-xs text-red-400 ml-1">{errors.company_name}</p>}
          </div>
        )}

        {isRegister && (
          <TurnstileWidget onToken={setTurnstileToken} />
        )}

        <button
          type="submit"
          disabled={submitting || success}
          className="w-full py-3 rounded-lg bg-primary text-primary-foreground font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
          <ArrowRight className="h-4 w-4" />
          {isRegister
            ? (t('dashboard.auth.submit_register') || 'Criar conta e entrar')
            : (t('dashboard.auth.submit_login') || 'Entrar')}
        </button>
      </div>

      <p className="text-center text-sm text-muted-foreground">
        {isRegister
          ? (t('dashboard.auth.toggle_login') || 'Já tem conta? Entrar')
          : (t('dashboard.auth.toggle_register') || 'Não tem conta? Cadastrar')}
      </p>
    </form>
  );
}

export function AuthForm({
  preselectedTrade,
  preselectedPlan,
  initialRegister,
}: { preselectedTrade?: string; preselectedPlan?: string; initialRegister?: boolean } = {}) {
  return (
    <Suspense fallback={null}>
      <AuthFormInner
        preselectedTrade={preselectedTrade}
        preselectedPlan={preselectedPlan}
        initialRegister={initialRegister}
      />
    </Suspense>
  );
}