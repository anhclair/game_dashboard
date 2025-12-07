const CACHE_NAME = "dashboard-cache-v11";
const ASSETS = [
  "/",
  "/static/index.html",
  "/static/styles.css",
  "/static/script.js",
  "/static/manifest.webmanifest",
  "/static/icons/app-192.png",
  "/static/icons/app-512.png",
  "/static/apple-touch-icon.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  const isSameOrigin = url.origin === self.location.origin;
  const isStatic =
    isSameOrigin &&
    (ASSETS.includes(url.pathname) ||
      url.pathname.startsWith("/static/") ||
      url.pathname.startsWith("/assets/"));
  if (!isStatic) return;
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          return resp;
        })
        .catch(() => cached);
    })
  );
});
