// Service Worker for Magic Leads PWA Push Notifications
// Seve exclusivamente para push e notificationclick.
// Nao intercepta requisicoes de rede/navegacao para evitar net::ERR_FAILED.

// Fetch event - explicitly do NOT intercept any request.
// Page navigations, Next.js assets and API calls all go straight to the
// network, so no redirected/error response ever leaks through respondWith.
self.addEventListener('fetch', (event) => {
  return;
});

// Push event - show notification
// try/catch global: qualquer exception e capturada e o worker NAO e encerrado.
self.addEventListener('push', (event) => {
  const promiseChain = (async () => {
    try {
      let data = { title: 'Nova Oportunidade!', body: 'Novo lead disponível.' };
      if (event.data) {
        try {
          const parsed = event.data.json();
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            data = { ...data, ...parsed };
          }
        } catch (e) {
          try {
            const text = event.data.text();
            if (text && typeof text === 'string') {
              data = { ...data, body: text };
            }
          } catch (textErr) {
            // Payload ilegivel — mantem os defaults.
          }
        }
      }

      await self.registration.showNotification(
        typeof data.title === 'string' && data.title ? data.title : 'Magic Leads',
        {
          body: typeof data.body === 'string' && data.body ? data.body : 'Nova oportunidade disponível.',
          icon: '/icon-192.png',
          badge: '/icon-192.png',
          vibrate: [200, 100, 200],
          tag: typeof data.tag === 'string' && data.tag ? data.tag : 'magic-leads-notification',
          renotify: true,
          requireInteraction: true,
          actions: [
            { action: 'open', title: 'Ver oportunidade' },
            { action: 'dismiss', title: 'Dispensar' }
          ],
          data: {
            leadId: data.leadId != null ? String(data.leadId) : undefined,
            url: typeof data.url === 'string' ? data.url : '/dashboard'
          }
        }
      );
    } catch (err) {
      console.error('Erro ao exibir notificação:', err);
    }
  })();
  event.waitUntil(promiseChain);
});

// Notification click event
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  if (event.action === 'dismiss') {
    return;
  }

  const leadId = event.notification.data?.leadId;
  const url = event.notification.data?.url || '/dashboard';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        // Try to find existing window
        for (const client of clientList) {
          if (client.url.includes('/dashboard') && 'focus' in client) {
            // Navigate existing window
            client.postMessage({
              type: 'NOTIFICATION_CLICK',
              leadId: event.notification.data?.leadId,
              url: url
            });
            return client.focus();
          }
        }
        // Open new window
        return clients.openWindow(url);
      })
  );
});