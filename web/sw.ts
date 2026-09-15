/// <reference lib="webworker" />

declare const self: ServiceWorkerGlobalScope;

// Replaced at build time by the closeBundle hook in vite.config.ts
const PRECACHE_URLS: string[] = ["__PRECACHE_URLS__"];
const CACHE_NAME = "__CACHE_NAME__";

self.addEventListener("install", (event: ExtendableEvent) => {
  void self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      // Resolve URLs relative to the worker scope
      const urlsToCache = PRECACHE_URLS.map((url) => new URL(url, self.location.href).href);
      await cache.addAll(urlsToCache);
    }),
  );
});

self.addEventListener("activate", (event: ExtendableEvent) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.map((key) => {
            if (key !== CACHE_NAME) {
              return caches.delete(key);
            }
            return Promise.resolve(false);
          }),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event: FetchEvent) => {
  const request = event.request;

  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  // Only handle same-origin requests
  if (url.origin !== self.location.origin) {
    return;
  }

  // Never cache sw.js itself
  if (url.pathname.endsWith("/sw.js") || url.pathname === "/sw.js") {
    return;
  }

  event.respondWith(
    caches.match(request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }

      // For page navigations, fall back to cached index.html
      if (request.mode === "navigate") {
        return caches
          .match(new URL("index.html", self.location.href).href)
          .then((fallback) => fallback || fetch(request));
      }

      return fetch(request).then((networkResponse) => {
        if (networkResponse.status === 200) {
          const responseToCache = networkResponse.clone();
          void caches.open(CACHE_NAME).then((cache) => {
            void cache.put(request, responseToCache);
          });
        }
        return networkResponse;
      });
    }),
  );
});
