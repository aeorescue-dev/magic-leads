'use client';

// Rota canônica /auth do grupo (auth) — layout limpo (sem rodapé antigo).
import { AuthForm } from '@/components/AuthForm';
import { useI18n } from '@/lib/i18n';

export default function AuthPage() {
  // AUTH_PAGE_BUILD_V2 (marcador de versão no console client-side)
  console.log('AUTH_PAGE_BUILD_V2');

  const { t } = useI18n();

  return (
    <div className="w-full max-w-md">
      <div className="text-center mb-8">
        <h1 className="text-3xl font-extrabold tracking-tight text-foreground">
          {t('dashboard.auth.brand_sub') || 'Magic Leads'}
        </h1>
        <p className="text-muted-foreground mt-2">
          {t('dashboard.auth.register_sub') || 'Cadastre-se para receber alertas de oportunidades no seu interesse.'}
        </p>
      </div>
      <AuthForm />
    </div>
  );
}