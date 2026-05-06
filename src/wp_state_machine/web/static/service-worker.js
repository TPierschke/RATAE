// WP State Machine Service Worker — PWA offline-faehig
const CACHE_NAME = 'wp-sm-v1';
const STATIC_ASSETS = [
  '/',
  '/static/app.css',
  '/static/app.js',
  '/static/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API und SSE-Stream immer live
  if (url.pathname.startsWith('/api') || url.pathname === '/stream' ||
      url.pathname.startsWith('/health') || url.pathname.startsWith('/state') ||
      url.pathname.startsWith('/functions') || url.pathname.startsWith('/telemetry')) {
    return;
  }

  // Static Assets aus Cache
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (response && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => {
        // Offline: Root-Seite aus Cache
        if (url.pathname === '/') return caches.match('/');
      });
    })
  );
});
