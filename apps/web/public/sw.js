// MyKhaya service worker.
//
// Deliberately caches only the app shell's static, non-personalised assets
// (offline fallback page, icons, hashed Next.js build assets). Never caches
// page HTML or API responses: those carry signed-in, household-scoped data,
// and a shared/kiosk device must not risk serving one account's cached data
// after another account signs in. Navigation requests always go to the
// network first; the cached offline page is only a fallback when the
// network is unreachable.

// Bump this on any change to this file's caching behaviour — it both names the
// Cache Storage bucket (so activate's cleanup below drops the previous one) and is
// reported back to the app via the "MYKHAYA_GET_VERSION" message below, so a stale
// installed PWA's build/SW version can actually be confirmed from the running app
// rather than guessed at.
const CACHE_NAME = "mykhaya-shell-v2";
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

// Web Push. Payload shape is produced by mykhaya.notifications.push.send_push:
// { title, body, deep_link: {type, id} | null, notification_type }. The lock-screen
// preview level (full/title_only/hidden) is enforced server-side by the payload's
// content, not here — the service worker just displays whatever it was given.
self.addEventListener("push", (event) => {
  let payload = { title: "MyKhaya", body: "You have a new notification.", deep_link: null };
  try {
    if (event.data) payload = { ...payload, ...event.data.json() };
  } catch {
    // Malformed payload must never crash the worker — fall back to a generic notice.
  }
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: "/icons/icon-192",
      badge: "/icons/icon-192",
      data: { deepLink: payload.deep_link, notificationType: payload.notification_type },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const deepLink = event.notification.data && event.notification.data.deepLink;
  const path = resolveDeepLinkPath(deepLink);
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ("focus" in client) {
          client.postMessage({ type: "mykhaya-notification-click", path });
          return client.focus();
        }
      }
      return self.clients.openWindow(path);
    }),
  );
});

// Non-sensitive: lets the running app confirm exactly which service worker version
// it's actually controlled by (see components/app-version.tsx), which is the
// difference between "the deploy didn't reach this device" and "something else is
// wrong" when debugging a stale-looking PWA.
self.addEventListener("message", (event) => {
  if (event.data?.type === "MYKHAYA_GET_VERSION") {
    event.ports[0]?.postMessage({ cacheName: CACHE_NAME });
  }
});

// Mirrors mykhaya/notifications/deep_links.py::resolve_path — a notification always
// navigates to its specific target, never a generic "open the app" for an actionable
// type. Kept intentionally tiny and dependency-free (service workers can't import the
// app's TS modules).
function resolveDeepLinkPath(deepLink) {
  if (!deepLink || !deepLink.type) return "/home";
  if (deepLink.type === "calendar_event" && deepLink.id) return `/calendar?event=${deepLink.id}`;
  if (deepLink.type === "routine" && deepLink.id) return `/home?routine=${deepLink.id}`;
  if (deepLink.type === "member") return "/people";
  if (deepLink.type === "notifications") return "/home?notifications=1";
  if (deepLink.type === "settings") return "/settings/notifications";
  return "/home";
}
