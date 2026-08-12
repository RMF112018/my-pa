"use client";

import { useEffect } from "react";

/**
 * Registers the service worker. Silent no-op when unsupported.
 *
 * Registration failure is non-fatal and deliberately so: the worker caches
 * static assets and nothing else, and the offline capture queue does not depend
 * on it. A browser that refuses the worker still queues notes — the queue lives
 * in `src/lib/offline/` and is reached from the page, not from the worker.
 */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // Non-fatal: see above. Nothing in the capture path requires the worker.
      });
    }
  }, []);
  return null;
}
