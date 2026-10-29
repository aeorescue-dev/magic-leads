// Service Worker for Magic Leads PWA Push Notifications
// Seve exclusivamente para push e notificationclick.
// Nao intercepta requisicoes de rede/navegacao para evitar net::ERR_FAILED.

// Ciclo de vida do Service Worker.
//
// IMPORTANTE: sem `skipWaiting` + `clients.claim` uma versão NOVA do sw.js
// fica presa em estado "waiting" até TODOS os clientes (abas/PWA) fecharem.
// Num PWA/aba de longa duração o SW antigo continua a controlar a página, pelo
// que correções do handler `notificationclick` (o deep link) nunca chegavam a
// produzir efeito para quem já tinha o SW antigo instalado.
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

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
      icon: '/icons/magicleads-brand.svg',
      badge: '/icons/magicleads-brand.svg',
      tag: 'magic-leads-notification',
      data: {}
    };

    if (event.data) {
      try {
        const payload = event.data.json();
        if (payload && typeof payload === 'object') {
          title = payload.title || title;
          options.body = payload.body || options.body;
          if (payload.icon) options.icon = payload.icon;
          if (payload.badge) options.badge = payload.badge;
          if (payload.tag) options.tag = payload.tag;
          if (Array.isArray(payload.actions)) options.actions = payload.actions;
          if (Array.isArray(payload.vibrate)) options.vibrate = payload.vibrate;
          if (payload.requireInteraction) options.requireInteraction = true;
          if (payload.renotify) options.renotify = true;
          if (payload.timestamp) options.timestamp = payload.timestamp;
          // Preserva o destino para o notificationclick: sem isto o clique
          // abria sempre /dashboard e o leadId chegava undefined.
          if (payload.url) options.data.url = payload.url;
          if (payload.leadId !== undefined && payload.leadId !== null) {
            options.data.leadId = payload.leadId;
          }
          if (payload.nid !== undefined && payload.nid !== null) {
            options.data.nid = payload.nid;
          }
          if (payload.sig) options.data.sig = payload.sig;
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

  const rawUrl = event.notification.data?.url || '/dashboard';
  const leadId = event.notification.data?.leadId;
  const nid = event.notification.data?.nid;
  const sig = event.notification.data?.sig;

  // Resolve o destino para URL absoluto (o payload traz `/dashboard?lead=42`).
  let target;
  try {
    target = new URL(rawUrl, self.location.origin).href;
  } catch (e) {
    target = new URL('/dashboard', self.location.origin).href;
  }

  event.waitUntil((async () => {
    // B1: regista o clique (HMAC) antes de abrir. Nunca bloqueia a navegacao.
    if (nid && sig) {
      try {
        await fetch(
          `/api/push/click?nid=${encodeURIComponent(nid)}&sig=${encodeURIComponent(sig)}`,
          { method: 'GET', keepalive: true, credentials: 'omit' }
        );
      } catch (e) {
        // sem rede: o deep link leva nid/sig e a dashboard tenta de novo
      }
    }

    const clientList = await clients.matchAll({ type: 'window', includeUncontrolled: true });

    // Prefere uma janela já aberta no dashboard; senão, qualquer janela nossa.
    const targetClient =
      clientList.find((c) => c.url.includes('/dashboard')) ||
      clientList.find((c) => c.url.startsWith(self.location.origin));

    if (targetClient) {
      // FIX CRÍTICO: navegar a aba existente para o deep link. Antes só se
      // fazia postMessage (sem listener na página) + focus(), pelo que o
      // utilizador ficava preso no dashboard e o URL nunca mudava.
      try {
        if ('navigate' in targetClient) {
          const navigated = await targetClient.navigate(target);
          return await (navigated || targetClient).focus();
        }
        targetClient.postMessage({ type: 'NOTIFICATION_CLICK', leadId, url: rawUrl });
        return await targetClient.focus();
      } catch {
        // navigate pode falhar (cliente não controlado/cross-origin): abre nova aba.
      }
    }
    return clients.openWindow(target);
  })());
});