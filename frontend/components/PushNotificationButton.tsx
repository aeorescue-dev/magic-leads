'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';
import { Bell, BellOff, Loader2 } from 'lucide-react';

const AUTH_TOKEN_KEY = 'garimpador.token';

export function PushNotificationButton() {
  const { user, loading: authLoading } = useAuth();
  const { t } = useI18n();
  const [subscribed, setSubscribed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [supported, setSupported] = useState(false);
  const [permission, setPermission] = useState<'default' | 'granted' | 'denied'>('default');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const isSupported = 'serviceWorker' in navigator && 'PushManager' in window;
    setSupported(isSupported);
    
    if (isSupported && Notification.permission) {
      setPermission(Notification.permission);
    }

    checkSubscription();
  }, []);

  const checkSubscription = async () => {
    if (!user) return;
    try {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch('/api/push/subscriptions', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setSubscribed(data.subscriptions && data.subscriptions.length > 0);
      }
    } catch (e) {
      console.error('Error checking subscription:', e);
    }
  };

  const subscribe = async () => {
    if (!user || !supported) return;
    setLoading(true);
    setError(null);

    try {
      // Check current permission first
      if (Notification.permission === 'denied') {
        setError(t('push.permission_denied') || 'Permissão negada. Habilite nas configurações do navegador (ícone de cadeado/escudo na barra de endereço > Notificações > Permitir)');
        setLoading(false);
        return;
      }

      const permission = await Notification.requestPermission();
      setPermission(permission);
      
      if (permission !== 'granted') {
        setError(t('push.permission_denied') || 'Permissão negada. Habilite nas configurações do navegador (ícone de cadeado/escudo na barra de endereço > Notificações > Permitir)');
        return;
      }

      const registration = await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;

      const keyRes = await fetch('/api/push/vapid-public-key', {
        headers: { 'Authorization': `Bearer ${localStorage.getItem(AUTH_TOKEN_KEY)}` }
      });
      if (!keyRes.ok) throw new Error('VAPID key not available');
      const { public_key } = await keyRes.json();

      const urlBase64ToUint8Array = (base64String: string) => {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) {
          outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
      };

      const applicationServerKey = urlBase64ToUint8Array(
        process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || ''
      );

      const swRegistration = await navigator.serviceWorker.ready;
      const subscription = await swRegistration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey
      });

      const subData = {
        endpoint: subscription.endpoint,
        p256dh: btoa(String.fromCharCode(...Array.from(new Uint8Array(subscription.getKey('p256dh')!)))),
        auth: btoa(String.fromCharCode(...Array.from(new Uint8Array(subscription.getKey('auth')!))))
      };

      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const subRes = await fetch('/api/push/subscribe', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(subData)
      });

      if (!subRes.ok) throw new Error('Falha ao inscrever');

      setSubscribed(true);
      setError(null);
    } catch (err: any) {
      console.error('Subscribe error:', err);
      setError(err.message || t('push.error') || 'Erro ao ativar notificações');
    } finally {
      setLoading(false);
    }
  };

  const unsubscribe = async () => {
    if (!user) return;
    setLoading(true);
    try {
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      
      if (subscription) {
        await subscription.unsubscribe();
        
        const token = localStorage.getItem(AUTH_TOKEN_KEY);
        await fetch('/api/push/unsubscribe', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({
            endpoint: subscription.endpoint
          })
        });
        
        setSubscribed(false);
      }
    } catch (err: any) {
      console.error('Unsubscribe error:', err);
      setError(err.message || t('push.error') || 'Erro ao desativar');
    } finally {
      setLoading(false);
    }
  };

  if (authLoading || !user || !supported) {
    return null;
  }

  return (
    <div className="flex items-center gap-2">
      {subscribed ? (
        <button
          onClick={unsubscribe}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-500/10 text-slate-400 hover:bg-slate-500/20 hover:text-slate-300 transition disabled:opacity-50"
        >
          <BellOff className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">{t('push.disable') || 'Desativar alertas'}</span>
        </button>
      ) : (
        <button
          onClick={subscribe}
          disabled={loading || permission === 'denied'}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/30 transition disabled:opacity-50"
        >
          <Loader2 className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          <Bell className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">{t('push.enable') || 'Ativar alertas no celular/desktop'}</span>
        </button>
      )}
      {error && (
        <span className="text-xs text-red-400 ml-2">{error}</span>
      )}
    </div>
  );
}