'use client';

// Rota canônica /auth do grupo (auth) — layout limpo (sem rodapé antigo).
// Gatilho de redeploy Vercel: adicionado comentário sem impacto funcional.
import { AuthForm } from '@/components/AuthForm';
import { useI18n } from '@/lib/i18n';

export default function AuthPage() {
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