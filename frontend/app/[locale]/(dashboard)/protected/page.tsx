'use client';

import { useI18n } from '@/lib/i18n';

export default function ProtectedPage() {
  const { t } = useI18n();

  return (
    <div className="min-h-screen flex items-center justify-center">
      <h1 className="text-2xl font-bold">{t("protected.title")}</h1>
    </div>
  );
}