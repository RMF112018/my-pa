/**
 * T14 — the held-note indicator under session change and queue events (C06/C07).
 *
 * The number this component renders is a claim about whose notes exist on this
 * device. Three things therefore matter more than layout: it must never publish
 * a previous Principal's counts into a new session, it must refresh when a
 * mutation commits, and it must never be the thing that creates a key.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { OfflineQueueStatus } from "@/components/offline/offline-queue-status";
import { KEY_STORE, openOfflineDatabase, request, transactionDone } from "@/lib/offline/db";
import { getOrCreatePrincipalKey } from "@/lib/offline/key";
import {
  CAPTURE_QUEUE_CHANGED_EVENT as QUEUE_CHANGED_EVENT_FROM_QUEUE,
  enqueueCapture,
  markReplayFailed,
  queueSnapshot,
} from "@/lib/offline/queue";
import { CAPTURE_QUEUE_CHANGED_EVENT } from "@/lib/offline/capture-queue";
import { installTestWebLocks } from "@/lib/offline/testing/web-locks";

/**
 * A controllable gate over the one read the indicator performs.
 *
 * The facade is otherwise the real one; `gate` lets a single test hold a read
 * open across a Principal change, which is the only way to observe what the
 * component does with a result that arrives too late.
 */
const gate = vi.hoisted(() => ({ pending: null as null | (() => void) }));
vi.mock("@/lib/offline/capture-queue", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/offline/capture-queue")>();
  return {
    ...actual,
    heldCaptureCounts: async () => {
      const counts = await actual.heldCaptureCounts();
      if (gate.pending !== null) {
        await new Promise<void>((resolve) => {
          const release = gate.pending!;
          gate.pending = null;
          resolve satisfies () => void;
          // Hand the releaser to the test and wait for it.
          holdUntil = resolve;
          release();
        });
      }
      return counts;
    },
  };
});
let holdUntil: (() => void) | null = null;

const PRINCIPAL_A = "syn-aaaa0001";
const PRINCIPAL_B = "syn-bbbb0002";
const PROJECT_A = "prj_aaaaaaaa11111111";

let locks: ReturnType<typeof installTestWebLocks>;

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  locks = installTestWebLocks();
  // No network in these tests: a rejected fetch is an offline device, which is
  // the state the indicator exists for.
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("synthetic network failure"));
});

afterEach(() => {
  cleanup();
  locks.restore();
  vi.restoreAllMocks();
});

async function queueFor(principalId: string, text: string, idempotencyKey: string) {
  const db = await openOfflineDatabase();
  const key = await getOrCreatePrincipalKey(db, principalId);
  return enqueueCapture(db, key, {
    principalId,
    text,
    captureKind: "quick_note",
    idempotencyKey,
    projectId: PROJECT_A,
  });
}

async function storedKeyCount(): Promise<number> {
  const db = await openOfflineDatabase();
  const tx = db.transaction(KEY_STORE, "readonly");
  const keys = (await request(tx.objectStore(KEY_STORE).getAllKeys())) as readonly IDBValidKey[];
  await transactionDone(tx).catch(() => undefined);
  return keys.length;
}

describe("held is held, and ambiguity is said out loud", () => {
  it("counts held notes and never calls them saved", async () => {
    await queueFor(PRINCIPAL_A, "synthetic note alpha", "cap-synthetic-alpha");

    render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);

    const held = await screen.findByTestId("offline-queue-held");
    expect(held).toHaveTextContent("held on this device only");
    expect(held).toHaveTextContent("not saved on the server");
  });

  it("says that an interrupted send leaves the outcome unknown", async () => {
    await queueFor(PRINCIPAL_A, "synthetic note beta", "cap-synthetic-beta");

    render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);

    const ambiguity = await screen.findByTestId("offline-queue-ambiguity");
    expect(ambiguity).toHaveTextContent("unknown until the next attempt confirms it");
    // Never the false certainty in either direction.
    expect(ambiguity.textContent).not.toMatch(/was not (stored|saved)/i);
    expect(ambiguity.textContent).not.toMatch(/\bfailed to save\b/i);
  });

  it("renders no authored text, Project identifier or failure detail", async () => {
    const entry = await queueFor(PRINCIPAL_A, "synthetic secret content", "cap-synthetic-secret");
    const db = await openOfflineDatabase();
    await markReplayFailed(db, entry.entryId, "authentication_failed");

    render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);
    await screen.findByTestId("offline-queue-status");

    const rendered = document.body.textContent ?? "";
    expect(rendered).not.toContain("synthetic secret content");
    expect(rendered).not.toContain(PROJECT_A);
    expect(rendered).not.toContain("authentication_failed");
  });
});

describe("a stale session can never publish its counts", () => {
  it("discards a read that resolves after the Principal changed", async () => {
    await queueFor(PRINCIPAL_A, "synthetic note gamma", "cap-synthetic-gamma");
    await queueFor(PRINCIPAL_A, "synthetic note delta", "cap-synthetic-delta");

    const view = render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);
    await screen.findByTestId("offline-queue-held");
    expect(screen.getByTestId("offline-queue-held")).toHaveTextContent("2");

    // B has nothing of its own. A's two notes are quarantined rather than shown
    // as B's, and A's earlier counts must not survive the switch.
    view.rerender(<OfflineQueueStatus principalId={PRINCIPAL_B} />);

    await waitFor(() => {
      const held = screen.queryByTestId("offline-queue-held");
      expect(held?.textContent ?? "").not.toMatch(/\b2\b.*waiting/);
    });
    await waitFor(async () => {
      const entries = await queueSnapshot(await openOfflineDatabase());
      expect(entries.every((entry) => entry.principalId === PRINCIPAL_A)).toBe(true);
      expect(entries.every((entry) => entry.state === "quarantined")).toBe(true);
    });
  });

  it("clears what it was showing the moment the Principal changes", async () => {
    await queueFor(PRINCIPAL_A, "synthetic note epsilon", "cap-synthetic-epsilon");
    const view = render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);
    await screen.findByTestId("offline-queue-held");

    view.rerender(<OfflineQueueStatus principalId={PRINCIPAL_B} />);
    // Synchronously after the switch there is nothing on screen claiming to
    // describe B's device.
    expect(screen.queryByTestId("offline-queue-held")).toBeNull();
  });
});

describe("a committed mutation refreshes the counts", () => {
  it("names one event, reachable from the queue and from the facade", () => {
    // The listener would silently never fire if these drifted apart, and the
    // symptom would be a count that quietly stops updating.
    expect(CAPTURE_QUEUE_CHANGED_EVENT).toBe(QUEUE_CHANGED_EVENT_FROM_QUEUE);
    expect(typeof CAPTURE_QUEUE_CHANGED_EVENT).toBe("string");
  });

  it("re-reads on the queue-changed event without starting a replay", async () => {
    await queueFor(PRINCIPAL_A, "synthetic note zeta", "cap-synthetic-zeta");
    render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);
    await screen.findByTestId("offline-queue-held");
    expect(screen.getByTestId("offline-queue-held")).toHaveTextContent("1");

    await queueFor(PRINCIPAL_A, "synthetic note eta", "cap-synthetic-eta");
    const fetchCalls = vi.mocked(globalThis.fetch).mock.calls.length;

    await act(async () => {
      window.dispatchEvent(new Event(CAPTURE_QUEUE_CHANGED_EVENT));
    });

    await waitFor(() => {
      expect(screen.getByTestId("offline-queue-held")).toHaveTextContent("2");
    });
    // A change event refreshes counts. It is not a reason to send anything.
    expect(vi.mocked(globalThis.fetch).mock.calls.length).toBe(fetchCalls);
  });

  it("refreshes counts on focus without replaying", async () => {
    await queueFor(PRINCIPAL_A, "synthetic note theta", "cap-synthetic-theta");
    render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);
    await screen.findByTestId("offline-queue-held");
    const fetchCalls = vi.mocked(globalThis.fetch).mock.calls.length;

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("offline-queue-held")).toHaveTextContent("1");
    });
    expect(vi.mocked(globalThis.fetch).mock.calls.length).toBe(fetchCalls);
  });
});

describe("a read that arrives too late is discarded", () => {
  it("does not publish counts resolved after the Principal changed", async () => {
    await queueFor(PRINCIPAL_A, "synthetic note kappa", "cap-synthetic-kappa");
    await queueFor(PRINCIPAL_A, "synthetic note lambda", "cap-synthetic-lambda");

    const view = render(<OfflineQueueStatus principalId={PRINCIPAL_A} />);
    await screen.findByTestId("offline-queue-held");
    expect(screen.getByTestId("offline-queue-held")).toHaveTextContent("2");

    // Start a read for A and hold it open.
    const started = new Promise<void>((resolve) => {
      gate.pending = resolve;
    });
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await started;

    // Switch to B while A's read is still in flight, then let it finish.
    view.rerender(<OfflineQueueStatus principalId={PRINCIPAL_B} />);
    expect(screen.queryByTestId("offline-queue-held")).toBeNull();
    await act(async () => {
      holdUntil?.();
      holdUntil = null;
      await Promise.resolve();
    });

    // A's two notes must not appear as B's. They are quarantined and counted
    // only once B's own read has run.
    await waitFor(() => {
      const held = screen.queryByTestId("offline-queue-held");
      expect(held?.textContent ?? "").not.toContain("2 notes");
    });
  });
});

describe("reading never creates a key", () => {
  it("renders for a Principal with no key and writes none", async () => {
    const generate = vi.spyOn(crypto.subtle, "generateKey");

    render(<OfflineQueueStatus principalId={PRINCIPAL_B} />);
    await waitFor(() => expect(screen.queryByTestId("offline-queue-failure")).toBeNull());

    expect(generate).not.toHaveBeenCalled();
    expect(await storedKeyCount()).toBe(0);
  });

  it("counts another Principal's held notes without minting a key for the viewer", async () => {
    await queueFor(PRINCIPAL_A, "synthetic note iota", "cap-synthetic-iota");
    const keysBefore = await storedKeyCount();
    const generate = vi.spyOn(crypto.subtle, "generateKey");

    render(<OfflineQueueStatus principalId={PRINCIPAL_B} />);
    await waitFor(async () => {
      const entries = await queueSnapshot(await openOfflineDatabase());
      expect(entries[0]!.state).toBe("quarantined");
    });

    expect(generate).not.toHaveBeenCalled();
    expect(await storedKeyCount()).toBe(keysBefore);
  });
});
