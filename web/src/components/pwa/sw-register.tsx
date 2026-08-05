"use client";

import { useEffect } from "react";

/** Registers the minimal WP-02 service worker. Silent no-op when unsupported. */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // Registration failure is non-fatal in WP-02; the app is network-only.
      });
    }
  }, []);
  return null;
}
