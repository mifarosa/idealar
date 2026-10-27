// Idealar service worker: caches the app shell; ideas themselves always come from the server.
const CACHE_NAME = "idealar-shell-v4";
const PRECACHE_URLS = {{ precache_json|safe }};
const OFFLINE_URL = "{{ offline_url }}";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(deleteOldCaches().then(() => self.clients.claim()));
});

async function deleteOldCaches() {
  const names = await caches.keys();
  await Promise.all(names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name)));
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(networkOrOfflinePage(request));
  } else if (url.pathname.startsWith("/static/")) {
    event.respondWith(staleWhileRevalidate(request));
  }
});

// Pages hold private data and depend on the session, so they are never cached.
async function networkOrOfflinePage(request) {
  try {
    return await fetch(request);
  } catch (error) {
    return caches.match(OFFLINE_URL);
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  const refresh = fetch(request).then((response) => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  });
  return cached || refresh;
}
