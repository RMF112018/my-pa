"use client";

/**
 * This-browser PWA observations. The server cannot know any of these.
 *
 * `GET /api/system` refuses to invent a service-worker controller, Cache Storage
 * contents, the online bit, or IndexedDB queue counts: those are facts about
 * *this* browser profile, not about the application process. This component is
 * the place those facts may appear, and it labels them as this-browser
 * observations rather than as server truth.
 *
 * Observation is read-only. The encrypted capture queue stays in
 * `src/lib/offline/` and is never drained from this page; the service worker is
 * not rewritten here.
 */
import { useEffect, useState } from "react";
import { openOfflineDatabase } from "@/lib/offline/db";
import { countStates, queueSnapshot, type QueueCounts } from "@/lib/offline/queue";

type ServiceWorkerObservation =
  | { kind: "unsupported" }
  | { kind: "not_controlling" }
  | { kind: "controlling"; scriptUrl: string };

type CacheObservation =
  | { kind: "unsupported" }
  | { kind: "ready"; names: readonly string[] };

type QueueObservation =
  | { kind: "unavailable"; detail: string }
  | { kind: "ready"; counts: QueueCounts };

type Observation = {
  readonly online: boolean | "unknown";
  readonly serviceWorker: ServiceWorkerObservation;
  readonly caches: CacheObservation;
  readonly queue: QueueObservation;
};

function observeServiceWorker(): ServiceWorkerObservation {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) {
    return { kind: "unsupported" };
  }
  const controller = navigator.serviceWorker.controller;
  if (!controller) return { kind: "not_controlling" };
  return { kind: "controlling", scriptUrl: controller.scriptURL };
}

async function observeCaches(): Promise<CacheObservation> {
  if (typeof caches === "undefined") return { kind: "unsupported" };
  return { kind: "ready", names: await caches.keys() };
}

async function observeQueue(): Promise<QueueObservation> {
  try {
    const db = await openOfflineDatabase();
    return { kind: "ready", counts: countStates(await queueSnapshot(db)) };
  } catch (error) {
    return {
      kind: "unavailable",
      detail: error instanceof Error ? error.message : "IndexedDB queue counts could not be read",
    };
  }
}

function observeOnline(): boolean | "unknown" {
  if (typeof navigator === "undefined" || typeof navigator.onLine !== "boolean") {
    return "unknown";
  }
  return navigator.onLine;
}

export function ThisBrowserPwaStatus() {
  const [observation, setObservation] = useState<Observation | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function readThisBrowser() {
      const next: Observation = {
        online: observeOnline(),
        serviceWorker: observeServiceWorker(),
        caches: await observeCaches(),
        queue: await observeQueue(),
      };
      if (!cancelled) setObservation(next);
    }

    void readThisBrowser().catch((error: unknown) => {
      if (cancelled) return;
      setObservation({
        online: observeOnline(),
        serviceWorker: observeServiceWorker(),
        caches: { kind: "unsupported" },
        queue: {
          kind: "unavailable",
          detail: error instanceof Error ? error.message : "this browser could not be observed",
        },
      });
    });

    const onNetwork = () => {
      setObservation((current) =>
        current ? { ...current, online: observeOnline() } : current,
      );
    };
    window.addEventListener("online", onNetwork);
    window.addEventListener("offline", onNetwork);
    return () => {
      cancelled = true;
      window.removeEventListener("online", onNetwork);
      window.removeEventListener("offline", onNetwork);
    };
  }, []);

  return (
    <div className="mt-3" data-testid="system-pwa-this-browser">
      <p className="font-medium text-moss-slate">This browser</p>
      {observation === null ? (
        <p className="mt-1" data-testid="system-pwa-observing">
          Observing this browser&rsquo;s service worker, Cache Storage, online bit, and
          IndexedDB queue&hellip;
        </p>
      ) : (
        <dl className="mt-1 grid grid-cols-[8rem_1fr] gap-1 font-mono text-xs break-all">
          <dt className="text-muted">network</dt>
          <dd data-testid="system-pwa-online">
            {observation.online === "unknown"
              ? "unknown in this browser"
              : observation.online
                ? "online (this browser)"
                : "offline (this browser)"}
          </dd>
          <dt className="text-muted">service worker</dt>
          <dd data-testid="system-pwa-sw">
            {observation.serviceWorker.kind === "unsupported"
              ? "not supported in this browser"
              : observation.serviceWorker.kind === "not_controlling"
                ? "installed worker is not controlling this page"
                : `controlling this page (${observation.serviceWorker.scriptUrl})`}
          </dd>
          <dt className="text-muted">Cache Storage</dt>
          <dd data-testid="system-pwa-caches">
            {observation.caches.kind === "unsupported"
              ? "not supported in this browser"
              : observation.caches.names.length === 0
                ? "no Cache Storage entries in this browser"
                : observation.caches.names.join(", ")}
          </dd>
          <dt className="text-muted">held queue</dt>
          <dd data-testid="system-pwa-queue">
            {observation.queue.kind === "unavailable" ? (
              <>could not be read in this browser — {observation.queue.detail}</>
            ) : (
              <>
                {observation.queue.counts.pending} pending, {observation.queue.counts.stalled}{" "}
                stalled, {observation.queue.counts.quarantined} quarantined,{" "}
                {observation.queue.counts.needsReauth} need re-auth — this browser&rsquo;s
                IndexedDB, not the server
              </>
            )}
          </dd>
        </dl>
      )}
      <p className="mt-2" data-testid="system-pwa-limits">
        The shipped worker caches static assets only and never <code>/api</code>, documents,
        RSC payloads, query strings, or redirects. There is no Background Sync, and a cold
        start with no network still needs the document from the server. Held notes live in
        this page&rsquo;s JavaScript queue, not in the worker.
      </p>
    </div>
  );
}
