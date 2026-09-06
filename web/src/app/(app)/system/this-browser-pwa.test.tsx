/**
 * This-browser PWA observations — never presented as server truth.
 *
 * The System page may show controller, Cache Storage, online bit, and IndexedDB
 * queue counts only as facts about this browser profile. `GET /api/system` must
 * not carry those fields; these tests cover the client component that does.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { ThisBrowserPwaStatus } from "./this-browser-pwa";
import { openOfflineDatabase } from "@/lib/offline/db";
import { principalContentKey } from "@/lib/offline/key";
import { enqueueCapture } from "@/lib/offline/queue";

const PRINCIPAL = "syn-aaaa0001";

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("this-browser PWA observations", () => {
  it("labels controller, caches, online bit, and queue as this browser", async () => {
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => true });
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: { controller: { scriptURL: "https://synthetic.example/sw.js" } },
    });
    vi.stubGlobal("caches", { keys: async () => ["mypa-static-v2"] });
    const db = await openOfflineDatabase();
    const key = await principalContentKey(db, PRINCIPAL);
    await enqueueCapture(db, key, {
      principalId: PRINCIPAL,
      text: "synthetic held note",
      captureKind: "quick_note",
      idempotencyKey: "cap-synthetic-pwa-obs",
    });

    render(<ThisBrowserPwaStatus />);

    await waitFor(() => expect(screen.queryByTestId("system-pwa-observing")).toBeNull());
    expect(screen.getByTestId("system-pwa-this-browser").textContent).toMatch(/This browser/);
    expect(screen.getByTestId("system-pwa-online").textContent).toMatch(/online \(this browser\)/);
    expect(screen.getByTestId("system-pwa-sw").textContent).toMatch(/controlling this page/);
    expect(screen.getByTestId("system-pwa-sw").textContent).toMatch(/\/sw\.js/);
    expect(screen.getByTestId("system-pwa-caches").textContent).toBe("mypa-static-v2");
    expect(screen.getByTestId("system-pwa-queue").textContent).toMatch(/1 pending/);
    expect(screen.getByTestId("system-pwa-queue").textContent).toMatch(/this browser/);
    expect(screen.getByTestId("system-pwa-queue").textContent).toMatch(/not the server/);
    expect(screen.getByTestId("system-pwa-limits").textContent).toMatch(/no Background Sync/i);
    expect(screen.getByTestId("system-pwa-limits").textContent).toMatch(/cold start/i);
    expect(document.body.textContent).not.toMatch(/PWA_FIELDS_PENDING_WP26/);
  });

  it("does not invent a controller or cache when this browser has neither", async () => {
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => false });
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: { controller: null },
    });
    vi.stubGlobal("caches", { keys: async () => [] });

    render(<ThisBrowserPwaStatus />);

    await waitFor(() => expect(screen.getByTestId("system-pwa-online")).toBeTruthy());
    expect(screen.getByTestId("system-pwa-online").textContent).toMatch(/offline \(this browser\)/);
    expect(screen.getByTestId("system-pwa-sw").textContent).toMatch(/not controlling this page/);
    expect(screen.getByTestId("system-pwa-caches").textContent).toMatch(
      /no Cache Storage entries in this browser/,
    );
    expect(screen.getByTestId("system-pwa-queue").textContent).toMatch(/0 pending/);
  });
});
