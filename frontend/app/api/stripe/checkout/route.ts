import type { LucideIcon } from 'lucide-react';

export { LucideIcon };

export async function createCheckoutSession({ plan }: { plan: 'monthly' | 'yearly' }) {
  try {
    const res = await fetch('/api/stripe/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan, locale: 'pt' }),
    });
    if (!res.ok) throw new Error('checkout_failed');
    const data = await res.json();
    return data?.url as string | undefined;
  } catch {
    return undefined;
  }
}
