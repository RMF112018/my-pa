/**
 * The service worker never caches, stores, or serves anything from `/api/*`.
 *
 * This drives the **real** `public/sw.js` — the file the browser downloads —
 * rather than a copy of its logic. The source is read off disk and evaluated
 * against a synthetic `ServiceWorkerGlobalScope` that records every cache
 * operation, so "nothing was cached" is an observation of what ran and not a
 * reading of the code.
 *
 * The property matters because a cache is shared across every session that uses
 * this browser profile, while every `/api` response was produced for one
 * signed-in Principal. A cached `/api` response replayed to a later session
 * would be a cross-Principal disclosure with the service worker as the carrier.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SW_SOURCE = readFileSync(
  path.resolve(__dirname, "..", "..", "..", "public", "sw.js"),
  "utf8",
);

const ORIGIN = "https://synthetic.example";

interface CacheCall {
  readonly op: "match" | "put" | "addAll" | "delete";
  readonly key: string;
}

interface FakeRequest {
  readonly method: string;
  readonly url: string;
  readonly destination: string;
}

function requestFor(pathname: string, overrides: Partial<FakeRequest> = {}): FakeRequest {
  return {
    method: "GET",
    url: `${ORIGIN}${pathname}`,
    destination: "empty",
    ...overrides,
  };
}

/** Evaluate `public/sw.js` against a recording scope and hand back its listeners. */
function loadServiceWorker() {
  const calls: CacheCall[] = [];
  const fetched: string[] = [];
  const listeners = new Map<string, (event: unknown) => void>();

  const cache = {
    match: async (request: FakeRequest) => {
      calls.push({ op: "match", key: request.url });
      return undefined;
    },
    put: async (request: FakeRequest) => {
      calls.push({ op: "put", key: request.url });
    },
    addAll: async (urls: string[]) => {
      for (const url of urls) calls.push({ op: "addAll", key: url });
    },
  };
  const caches = {
    open: async () => cache,
    keys: async () => [],
    delete: async (name: string) => {
      calls.push({ op: "delete", key: name });
      return true;
    },
    match: async (request: FakeRequest) => {
      calls.push({ op: "match", key: request.url });
      return undefined;
    },
  };
  const fetchImpl = async (request: FakeRequest) => {
    fetched.push(request.url);
    return { ok: true, type: "basic", clone: () => ({}) };
  };
  const scope = {
    location: { origin: ORIGIN },
    addEventListener(type: string, handler: (event: unknown) => void) {
      listeners.set(type, handler);
    },
    skipWaiting: () => undefined,
    clients: { claim: async () => undefined },
  };

  // The real file, evaluated with the three globals a ServiceWorkerGlobalScope
  // supplies. Recording those three is how "nothing was cached" becomes an
  // observation rather than a reading.
  new Function("self", "caches", "fetch", SW_SOURCE)(scope, caches, fetchImpl);
  return { listeners, calls, fetched };
}

async function dispatchFetch(request: FakeRequest) {
  const worker = loadServiceWorker();
  const handler = worker.listeners.get("fetch");
  expect(handler).toBeTypeOf("function");
  const responses: unknown[] = [];
  handler!({ request, respondWith: (value: unknown) => responses.push(value) });
  await Promise.all(responses.map((value) => Promise.resolve(value).catch(() => undefined)));
  return { ...worker, responses };
}

describe("the precache list", () => {
  it("names no /api path and no HTML document", async () => {
    const worker = loadServiceWorker();
    const install = worker.listeners.get("install");
    expect(install).toBeTypeOf("function");
    const pending: unknown[] = [];
    install!({ waitUntil: (value: unknown) => pending.push(value) });
    await Promise.all(pending.map((value) => Promise.resolve(value).catch(() => undefined)));

    const precached = worker.calls.filter((call) => call.op === "addAll").map((call) => call.key);
    expect(precached.length).toBeGreaterThan(0);
    for (const entry of precached) {
      expect(entry.startsWith("/api")).toBe(false);
      expect(entry).not.toBe("/");
    }
  });
});

describe("no /api response is ever cached, stored, or served from a cache", () => {
  const apiPaths = [
    "/api/capture",
    "/api/library",
    "/api/session",
    "/api/review/synthetic-1/decide",
    "/api/capture?since=1",
    "/api",
  ];

  it.each(apiPaths)("leaves %s entirely alone", async (pathname) => {
    const { calls, responses } = await dispatchFetch(requestFor(pathname));
    // No `respondWith` at all: the request goes to the network exactly as it
    // would with no worker installed.
    expect(responses).toHaveLength(0);
    expect(calls).toEqual([]);
  });

  it("leaves a POST to /api/capture alone", async () => {
    const { calls, responses } = await dispatchFetch(
      requestFor("/api/capture", { method: "POST" }),
    );
    expect(responses).toHaveLength(0);
    expect(calls).toEqual([]);
  });

  it("does not cache an HTML document, which can carry the signed-in principal", async () => {
    const { calls, responses } = await dispatchFetch(
      requestFor("/today", { destination: "document" }),
    );
    expect(responses).toHaveLength(0);
    expect(calls).toEqual([]);
  });

  it("does not cache a cross-origin request", async () => {
    const { calls, responses } = await dispatchFetch({
      method: "GET",
      url: "https://elsewhere.example/asset.js",
      destination: "script",
    });
    expect(responses).toHaveLength(0);
    expect(calls).toEqual([]);
  });
});

describe("static assets are cached, so the guard above is not vacuously true", () => {
  it("caches a same-origin build asset", async () => {
    const { calls, responses, fetched } = await dispatchFetch(
      requestFor("/_next/static/chunks/synthetic.js", { destination: "script" }),
    );
    expect(responses).toHaveLength(1);
    expect(calls.some((call) => call.op === "match")).toBe(true);
    expect(calls.some((call) => call.op === "put")).toBe(true);
    expect(fetched).toContain(`${ORIGIN}/_next/static/chunks/synthetic.js`);
  });
});

describe("the worker holds no queue and no key", () => {
  it("names neither the offline database nor a crypto key anywhere in its source", () => {
    expect(SW_SOURCE).not.toContain("indexedDB");
    expect(SW_SOURCE).not.toContain("mypa-offline");
    expect(SW_SOURCE).not.toContain("subtle");
  });

  it("registers no Background Sync handler, because none is claimed", () => {
    expect(SW_SOURCE).not.toContain("periodicsync");
    expect(SW_SOURCE).not.toMatch(/addEventListener\(\s*["']sync["']/);
  });
});
