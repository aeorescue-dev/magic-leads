// Service Worker for Magic Leads PWA Push Notifications
const CACHE_NAME = 'magic-leads-v1';
const STATIC_ASSETS = [
  '/',
  '/dashboard',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Activate event - clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames
            .filter((name) => name !== CACHE_NAME)
            .map((name) => caches.delete(name))
        );
      })
      .then(() => self.clients.claim())
  );
});

// Fetch event - only intercept same-origin GET navigation/static requests.
// API and cross-origin requests pass straight to the network so a failing
// backend never breaks the page with net::ERR_FAILED.
self.addEventListener('fetch', (event) => {
  const requestUrl = new URL(event.request.url);

  if (event.request.method !== 'GET') return;

  // Never intercept cross-origin requests (backend API, external CDNs, etc.)
  if (requestUrl.origin !== self.location.origin) return;

  // Never intercept API requests
  if (requestUrl.pathname.startsWith('/api/')) return;

  // Only handle same-origin navigations and static assets
  if (event.request.mode !== 'navigate' &&
      requestUrl.pathname.startsWith('/_next/') === false &&
      requestUrl.pathname.startsWith('/manifest.json') === false &&
      requestUrl.pathname.startsWith('/icon-') === false) {
    return;
  }

  event.respondWith(
    caches.match(event.request)
      .then((cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }
        return fetch(event.request)
          .then((response) => {
            if (!response || response.status !== 200 || response.type !== 'basic') {
              return response;
            }
            const responseToCache = response.clone();
            caches.open(CACHE_NAME)
              .then((cache) => cache.put(event.request, responseToCache));
            return response;
          })
          .catch(() => {
            // Offline fallback - ALWAYS return a valid Response to avoid
            // net::ERR_FAILED. Fall back to the cached homepage if available.
            return caches.match('/')
              .then((home) => home || new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } }));
          });
      })
  );
});

// Push event - show notification
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    console.error('Push: invalid JSON payload', e);
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

// Notification close event
self.addEventListener('notificationclose', (event) => {
  // Optional: track dismissal analytics
  console.log('Notification closed:', event.notification.tag);
});

// Background sync for offline actions
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-leads') {
    event.waitUntil(syncLeads());
  }
});

async function syncLeads() {
  // Implement offline lead sync if needed
  console.log('Syncing leads...');
}