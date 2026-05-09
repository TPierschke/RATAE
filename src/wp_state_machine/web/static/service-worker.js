// WP State Machine Service Worker — Network-First (kein stale Cache mehr)
// Cache-Version hochzaehlen invalidiert den alten Cache beim Activate.
const CACHE_NAME = 'wp-sm-v3';
const STATIC_ASSETS = [
  '/',
  '/static/app.css',
  '/static/app.js',
  '/static/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
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
      url.pathname.startsWith('/functions') || url.pathname.startsWith('/telemetry') ||
      url.pathname.startsWith('/scrape')) {
    return;
  }

  // Static Assets: NETWORK FIRST. Cache nur als Offline-Fallback.
  event.respondWith(
    fetch(event.request).then((response) => {
      if (response && response.status === 200) {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
      }
      return response;
    }).catch(() => {
      return caches.match(event.request).then((cached) => {
        if (cached) return cached;
        if (url.pathname === '/') return caches.match('/');
      });
    })
  );
});
