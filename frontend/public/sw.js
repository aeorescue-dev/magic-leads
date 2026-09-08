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

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', (event) => {
  // Skip non-GET requests
  if (event.request.method !== 'GET') return;
  
  // Skip chrome-extension and other non-http requests
  if (!event.request.url.startsWith('http')) return;
  
  event.respondWith(
    caches.match(event.request)
      .then((cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }
        return fetch(event.request)
          .then((response) => {
            // Don't cache non-success responses
            if (!response || response.status !== 200 || response.type !== 'basic') {
              return response;
            }
            // Clone and cache
            const responseToCache = response.clone();
            caches.open(CACHE_NAME)
              .then((cache) => cache.put(event.request, responseToCache));
            return response;
          })
          .catch(() => {
            // Offline fallback for navigation requests
            if (event.request.mode === 'navigate') {
              return caches.match('/');
            }
          });
      })
  );
});

// Push event - show notification
self.addEventListener('push', (event) => {
  if (!event.data) return;
  
  const data = event.data.json();
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