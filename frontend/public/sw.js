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
  let data = { title: 'Nova Oportunidade!', body: 'Você recebeu um novo lead.' };
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data.body = event.data.text();
    }
  }

  const options = {
    body: data.body || 'Nova oportunidade disponível',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    vibrate: [200, 100, 200],
    tag: data.tag || 'magic-leads-notification',
    renotify: true,
    requireInteraction: true,
    actions: [
      { action: 'open', title: 'Ver oportunidade' },
      { action: 'dismiss', title: 'Dispensar' }
    ],
    data: {
      leadId: data.leadId,
      url: data.url || '/dashboard'
    }
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'Magic Leads', options)
  );
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