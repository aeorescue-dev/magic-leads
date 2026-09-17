'use client';

import { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2, Lock, CheckCircle, AlertTriangle, Eye, EyeOff, ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import { useI18n } from '@/lib/i18n';

export default function ResetPasswordPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useI18n();

  const token = searchParams.get('token');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
        <div className="w-full max-w-md bg-slate-900 rounded-2xl border border-slate-700 p-8">
          <AlertTriangle className="h-12 w-12 text-red-400 mx-auto mb-4" />
          <h1 className="text-xl font-semibold text-center text-white mb-2">
            {t('dashboard.auth.reset_token_invalid') || 'Token inválido ou ausente'}
          </h1>
          <p className="text-slate-400 text-center mb-6">
            {t('dashboard.auth.reset_token_invalid') || 'Token inválido ou expirado. Solicite um novo e-mail.'}
          </p>
          <Link
            href="/auth"
            className="w-full py-3 rounded-lg bg-emerald-500 text-slate-950 font-medium hover:bg-emerald-400 transition-colors text-center block"
          >
            {t('dashboard.auth.forgot_password') || 'Solicitar novo link'}
          </Link>
        </div>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) {
      setError(t('dashboard.auth.password_mismatch') || 'As senhas não coincidem.');
      return;
    }
    if (password.length < 6) {
      setError(t('dashboard.auth.password_min') || 'A senha deve ter pelo menos 6 caracteres.');
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password, confirm_password: confirmPassword }),
      });
      const data = await res.json();
      if (res.ok) {
        setSuccess(true);
        setTimeout(() => router.push('/auth?reset=success'), 2000);
      } else {
        setError(data.message || t('dashboard.auth.reset_token_invalid') || 'Token inválido ou expirado.');
      }
    } catch {
      setError('Erro ao redefinir senha. Tente novamente.');
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
        <div className="w-full max-w-md bg-slate-900 rounded-2xl border border-slate-700 p-8 text-center">
          <CheckCircle className="h-16 w-16 text-emerald-500 mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-white mb-2">
            {t('dashboard.auth.reset_success') || 'Senha redefinida com sucesso!'}
          </h1>
          <p className="text-slate-400 mb-6">
            Faça login com sua nova senha.
          </p>
          <Link
            href="/auth"
            className="w-full py-3 rounded-lg bg-emerald-500 text-slate-950 font-medium hover:bg-emerald-400 transition-colors text-center block"
          >
            Ir para login
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-md bg-slate-900 rounded-2xl border border-slate-700 p-8">
        <div className="flex items-center justify-between mb-6">
          <Link
            href="/auth"
            className="text-slate-400 hover:text-white transition-colors"
            aria-label="Voltar"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div className="w-8" />
        </div>

        <h1 className="text-2xl font-bold text-white text-center mb-2">
          {t('dashboard.auth.reset_password') || 'Redefinir senha'}
        </h1>
        <p className="text-slate-400 text-center mb-6">
          {t('dashboard.auth.new_password') || 'Digite sua nova senha abaixo'}
        </p>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/20 border border-red-500/30 text-red-300 text-sm flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t('dashboard.auth.new_password') || 'Nova senha'}
              className="w-full pl-10 pr-4 py-3 rounded-lg border border-slate-700 bg-slate-800 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              disabled={submitting}
              autoComplete="new-password"
              required
              minLength={6}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
              aria-label={showPassword ? 'Ocultar senha' : 'Mostrar senha'}
            >
              {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
            </button>
          </div>

          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
            <input
              type={showPassword ? 'text' : 'password'}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder={t('dashboard.auth.confirm_password') || 'Confirmar nova senha'}
              className="w-full pl-10 pr-4 py-3 rounded-lg border border-slate-700 bg-slate-800 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              disabled={submitting}
              autoComplete="new-password"
              required
              minLength={6}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
              aria-label={showPassword ? 'Ocultar senha' : 'Mostrar senha'}
            >
              {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
            </button>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full py-3.5 rounded-xl bg-emerald-500 text-slate-950 font-semibold hover:bg-emerald-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            {submitting && <Loader2 className="h-5 w-5 animate-spin" />}
            {!submitting && <Lock className="h-5 w-5" />}
            <span className="font-semibold">{t('dashboard.auth.reset_password') || 'Redefinir senha'}</span>
          </button>

          <p className="text-center text-sm text-slate-500 mt-4">
            <Link href="/auth" className="text-emerald-400 hover:underline">
              {t('dashboard.auth.back_to_login') || 'Voltar ao login'}
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}