'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, Eye, EyeOff, Mail, Lock, Building2, ArrowRight, CheckCircle } from 'lucide-react';
import { useAuth } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';

interface FormErrors {
  email?: string;
  password?: string;
  company_name?: string;
  general?: string;
}

export function AuthForm() {
  const router = useRouter();
  const { t } = useI18n();
  const { signIn, loading: authLoading } = useAuth();

  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

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

    setSubmitting(true);
    setErrors({});

    try {
      const user = await signIn(email.trim(), password, isRegister ? companyName.trim() : undefined);
      setSuccess(true);
      setTimeout(() => {
        router.push('/dashboard');
        router.refresh();
      }, 800);
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || t('dashboard.auth.error_generic') || 'Erro ao autenticar';
      if (msg.includes('Email já cadastrado') || msg.includes('already registered')) {
        setErrors({ email: t('dashboard.auth.email_exists') || 'Email já cadastrado. Tente entrar.' });
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

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-md mx-auto space-y-4">
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
            aria-label={showPassword ? 'Ocultar senha' : 'Mostrar senha'}
          >
            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
          {errors.password && <p className="mt-1 text-xs text-red-400 ml-1">{errors.password}</p>}
        </div>

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