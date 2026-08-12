/**
 * Service worker — static-asset caching only, and never `/api/*`.
 *
 * **The one rule this file exists to enforce: no response from `/api/*` is ever
 * cached, stored, or served from a cache.** Every `/api` response in this
 * application is principal-bound — it was produced for whichever session was
 * signed in when the request went out. A cache is shared by every session that
 * uses this browser profile, so a cached `/api` response handed to a later
 * session would be one Principal reading another's data, and the service worker
 * would be the thing that leaked it. `isApiPath` below is the check, it runs
 * before anything else can decide to cache, and `src/lib/offline/sw.test.ts`
 * drives this exact file to prove it.
 *
 * **What is cached is deliberately narrow.** Only same-origin `GET` requests
 * that are not documents and not `/api/*` — in practice the Next.js build
 * assets, the icon, and the manifest. HTML documents are excluded because a
 * server-rendered page in this application can carry the signed-in principal's
 * display name and other session-derived content, and the same argument that
 * rules out caching `/api` rules out caching those.
 *
 * **So this does not make the app start offline, and it does not claim to.** A
 * cold start with no network still needs the document from the server. What this
 * buys is that an already-open tab keeps its assets when the network drops, so
 * the capture surface stays usable long enough to queue a note — the queue
 * itself is in `src/lib/offline/`, and the service worker never touches it.
 *
 * **No Background Sync.** Replay is a foreground path driven by mount and by the
 * `online` event. This worker holds no queue, holds no key, and performs no
 * replay.
 */

/** Bump to invalidate everything this worker cached. */
const CACHE_NAME = "mypa-static-v1";

/**
 * Precached at install. Static, principal-free, and short by design.
 *
 * No path here may be under `/api`, and no path here may be an HTML document.
 */
const PRECACHE = ["/manifest.webmanifest", "/icons/icon.svg"];

/** Whether a path is part of the principal-bound API surface. */
function isApiPath(pathname) {
  return pathname === "/api" || pathname.startsWith("/api/");
}

/**
 * Whether this request may be answered from, or written to, the cache.
 *
 * Positive checks only. A request whose shape is not recognised is not cached,
 * which is the safe direction: failing to cache a static asset costs a network
 * round trip, and caching something principal-bound costs a cross-Principal
 * disclosure.
 */
function isCacheable(request, url) {
  if (request.method !== "GET") return false;
  if (url.origin !== self.location.origin) return false;
  if (isApiPath(url.pathname)) return false;
  if (request.destination === "document") return false;
  return true;
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name))),
      )
      .catch(() => undefined)
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  // Not cacheable means untouched: no `respondWith`, so the request goes to the
  // network exactly as if this worker were not installed.
  if (!isCacheable(request, url)) return;
  event.respondWith(cacheFirst(request));
});

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok && response.type === "basic") {
    cache.put(request, response.clone()).catch(() => undefined);
  }
  return response;
}
