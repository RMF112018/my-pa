/**
 * Service worker — WP-02 minimal registration.
 * No offline queue or caching strategy yet; that arrives with WP-04 (R3).
 * Registering now pins the PWA install surface and the update lifecycle.
 */
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// Network-only passthrough. WP-04 replaces this with an offline strategy.
self.addEventListener("fetch", () => {});
