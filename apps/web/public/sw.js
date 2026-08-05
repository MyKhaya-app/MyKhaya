// MyKhaya service worker.
//
// Deliberately caches only the app shell's static, non-personalised assets
// (offline fallback page, icons, hashed Next.js build assets). Never caches
// page HTML or API responses: those carry signed-in, household-scoped data,
// and a shared/kiosk device must not risk serving one account's cached data
// after another account signs in. Navigation requests always go to the
// network first; the cached offline page is only a fallback when the
// network is unreachable.

const CACHE_NAME = "mykhaya-shell-v1";
const OFFLINE_URL = "/offline";
const PRECACHE_URLS = [OFFLINE_URL];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Next.js build output is content-hashed and immutable — safe to cache
  // aggressively and indefinitely.
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.open(CACHE_NAME).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      }),
    );
    return;
  }

  // Page navigations: network first, offline fallback only on network failure.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() =>
        caches.open(CACHE_NAME).then((cache) => cache.match(OFFLINE_URL)),
      ),
    );
    return;
  }

  // Everything else (API calls, etc.) is passed through untouched — never cached.
});
