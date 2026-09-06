// ESA deliberately does not provide offline/PWA caching. This worker exists
// only to retire older Flutter service workers that may still be serving a
// stale application shell after a deployment.
const CLEANUP_VERSION = 'esa-web-cleanup-20260905-1';

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const cacheKeys = await caches.keys();
    await Promise.all(
      cacheKeys
        .filter((key) => key.startsWith('flutter-'))
        .map((key) => caches.delete(key)),
    );

    await self.clients.claim();

    // Tabs controlled by the previous worker may still be displaying its
    // cached index.html. Navigate those tabs once so the network copy and its
    // content-hashed Flutter entrypoint are loaded immediately.
    const scopeUrl = new URL(self.registration.scope);
    const windows = await self.clients.matchAll({
      type: 'window',
      includeUncontrolled: true,
    });
    await Promise.all(windows.map(async (client) => {
      const clientUrl = new URL(client.url);
      if (
        clientUrl.origin !== scopeUrl.origin ||
        !clientUrl.pathname.startsWith(scopeUrl.pathname)
      ) {
        return;
      }
      clientUrl.searchParams.set('__esa_cleanup', CLEANUP_VERSION);
      await client.navigate(clientUrl.href);
    }));
  })());
});

// Stay network-only after taking over the old registration. This prevents a
// stale Flutter application shell from being introduced again.
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request, { cache: 'no-store' }));
});
