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
 * **What is cached is an allow-list of exact static prefixes, and it is written
 * as one because the previous rule was not one.** This file used to cache every
 * same-origin `GET` that was not `/api/*` and not `request.destination ===
 * "document"`, describing the result as "in practice the Next.js build assets,
 * the icon, and the manifest". That description was wrong, and a real browser
 * found it: **an App Router RSC navigation is a `GET` to the page's own path
 * with `?_rsc=…` and `destination: "empty"`** — not a document — so the
 * server-rendered payload of `/today` was matching every one of those checks and
 * being written to a shared cache. That payload carries exactly what the
 * paragraph above says must never be cached: the signed-in principal's own
 * rendered page. Worse, when the payload was a redirect to `/sign-in` (a session
 * that had gone), the redirect was cached under the page's URL and served back
 * indefinitely — which is how it was noticed, as a signed-in browser bouncing
 * to the sign-in screen.
 *
 * The rule is now an allow-list of prefixes that are static by construction —
 * `/_next/static/`, `/icons/`, and the manifest — plus a refusal of anything
 * carrying a query string, anything a navigation produced, and any redirected
 * response. A path this worker does not recognise is fetched from the network
 * and not stored, which is the direction that costs a round trip rather than a
 * disclosure.
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
const CACHE_NAME = "mypa-static-v2";

/**
 * Precached at install. Static, principal-free, and short by design.
 *
 * No path here may be under `/api`, and no path here may be an HTML document.
 */
const PRECACHE = [
  "/manifest.webmanifest",
  "/icons/icon.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png",
];

/** Whether a path is part of the principal-bound API surface. */
function isApiPath(pathname) {
  return pathname === "/api" || pathname.startsWith("/api/");
}

/**
 * The only paths this worker may store, as prefixes.
 *
 * Every entry is a build artefact or a fixed asset: content-addressed Next.js
 * chunks, the icons, and the manifest. Nothing under any of these is produced
 * per-session, per-principal, or per-request, which is the property that makes
 * a shared cache safe for them and unsafe for everything else.
 */
const CACHEABLE_PREFIXES = ["/_next/static/", "/icons/"];

/** The one exact path outside those prefixes. */
const CACHEABLE_PATHS = ["/manifest.webmanifest"];

/**
 * Whether this request may be answered from, or written to, the cache.
 *
 * **An allow-list, not a deny-list, and the difference is the whole of the
 * guarantee.** A deny-list has to anticipate every principal-bound shape the
 * framework might invent; this one had not anticipated RSC payloads and cached
 * them for months. An allow-list is wrong in the harmless direction: a shape it
 * does not recognise goes to the network.
 *
 * The three refusals after the allow-list are belt and braces for shapes that
 * could otherwise sneak *into* it: a query string (nothing static here is
 * parameterised, and `?_rsc=` is exactly the parameter that started this), and a
 * navigation, by either signal the platform offers.
 */
function isCacheable(request, url) {
  if (request.method !== "GET") return false;
  if (url.origin !== self.location.origin) return false;
  if (isApiPath(url.pathname)) return false;
  if (request.destination === "document") return false;
  if (request.mode === "navigate") return false;
  if (url.search !== "") return false;
  const allowed =
    CACHEABLE_PATHS.includes(url.pathname) ||
    CACHEABLE_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));
  return allowed;
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
  // `redirected` is refused as well as checked for `ok`: a request that was
  // answered somewhere else was answered by a decision — a session redirect, an
  // auth bounce — and storing that decision under the original URL replays it to
  // every later visitor of this browser profile.
  if (response && response.ok && response.type === "basic" && response.redirected !== true) {
    cache.put(request, response.clone()).catch(() => undefined);
  }
  return response;
}
