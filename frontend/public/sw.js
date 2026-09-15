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
self.addEventListener('push', (event) => {
  const promiseChain = (async () => {
    let title = 'Magic Leads';
    let options = {
      body: 'Nova oportunidade disponível.',
      icon: '/icons/magicleads-icon-192.png',
      badge: '/icons/magicleads-icon-192.png',
      tag: 'magic-leads-alert'
    };

    if (event.data) {
      try {
        const payload = event.data.json();
        if (payload && typeof payload === 'object') {
          title = payload.title || title;
          options.body = payload.body || options.body;
          if (payload.icon) options.icon = payload.icon;
          if (payload.tag) options.tag = payload.tag;
        }
      } catch (e) {
        // Se falhar o parse do JSON (ex: texto puro do DevTools), usa o texto puro como body
        options.body = event.data.text() || options.body;
      }
    }

    try {
      await self.registration.showNotification(title, options);
    } catch (err) {
      console.error('Erro no showNotification:', err);
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