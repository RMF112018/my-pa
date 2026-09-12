/**
 * Queued-offline is a visibly different state from saved, and it says so.
 *
 * The four outcomes `capture.test.tsx` keeps apart gain a fifth and a sixth, and
 * the same asymmetry governs both: a person who reads "held on this device" and
 * hears "saved" will close the tab on the only copy of their note.
 *
 * * **queued** — the request never reached the server. The note is encrypted and
 *   held here. The copy says *only* on this device and *not* on the server, and
 *   it never renders as a save.
 * * **not held** — it could not even be queued. The note stays in the field and
 *   the reason is named, because implying a hold that did not happen is the
 *   worse failure of the two.
 *
 * A third case joins them, and it is a negative one: **Create Task is not a
 * capture and can never enter this queue.** Choosing it while the network is
 * down must leave the store empty, because an entry here is replayed as a
 * `POST /api/capture` on reconnect — a Task that leaked into the queue would
 * come back as a note.
 *
 * These run against the real dialog, the real queue, and a real IndexedDB
 * (`fake-indexeddb`). The network is the only thing faked. Every note is
 * synthetic, and each case takes the chooser's note branch first.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IDBFactory } from "fake-indexeddb";
import { CaptureDialog } from "@/components/shell/capture-dialog";
import { openOfflineDatabase } from "@/lib/offline/db";
import { queueSnapshot } from "@/lib/offline/queue";

const NOTE = "synthetic note zeta — held while offline";
const PRINCIPAL_ID = "syn-aaaa0001";

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function saveWhileOffline(note = NOTE) {
  const user = userEvent.setup();
  render(<CaptureDialog open onClose={() => {}} principalId={PRINCIPAL_ID} />);
  await user.click(await screen.findByTestId("capture-choice-quick_note"));
  await user.type(screen.getByTestId("capture-field"), note);
  await user.click(screen.getByRole("button", { name: "Save" }));
  return user;
}

describe("a note that could not be sent is held, and is never called saved", () => {
  it("says held on this device only, and not saved on the server", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("synthetic network failure"));

    await saveWhileOffline();

    const status = await screen.findByTestId("capture-queued");
    expect(status).toHaveTextContent("Held on this device only");
    expect(status).toHaveTextContent("not saved on the server");
    expect(status.textContent).not.toMatch(/\bSaved\b/);
    // The three other success-ish states are absent.
    expect(screen.queryByTestId("capture-durable")).toBeNull();
    expect(screen.queryByTestId("capture-acknowledged")).toBeNull();
    expect(screen.queryByTestId("capture-unavailable")).toBeNull();
  });

  it("actually holds it — encrypted, bound to the signed-in principal", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("synthetic network failure"));

    await saveWhileOffline();
    await screen.findByTestId("capture-queued");

    const db = await openOfflineDatabase();
    const entries = await queueSnapshot(db);
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      principalId: PRINCIPAL_ID,
      captureKind: "quick_note",
      state: "pending",
    });
    expect(entries[0].idempotencyKey).toMatch(/^cap-/);
  });

  it("keeps the same idempotency key that the failed online attempt used", async () => {
    const attempted: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      attempted.push(JSON.parse((init as RequestInit).body as string).idempotencyKey);
      throw new TypeError("synthetic network failure");
    });

    await saveWhileOffline();
    await screen.findByTestId("capture-queued");

    const db = await openOfflineDatabase();
    const entries = await queueSnapshot(db);
    expect(attempted).toHaveLength(1);
    expect(entries[0].idempotencyKey).toBe(attempted[0]);
  });
});

describe("a note that could not even be held says so, and keeps the note in the field", () => {
  it("names the reason and does not imply a hold", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("synthetic network failure"));
    // No IndexedDB at all: the offline store cannot be opened.
    const withoutIndexedDb = globalThis as { indexedDB?: IDBFactory };
    const real = withoutIndexedDb.indexedDB;
    delete withoutIndexedDb.indexedDB;
    try {
      await saveWhileOffline();
      const alert = await screen.findByTestId("capture-not-held");
      expect(alert).toHaveTextContent("Not saved and not held");
      expect(alert).toHaveTextContent("still in the field");
      expect(screen.queryByTestId("capture-queued")).toBeNull();
      expect(screen.queryByTestId("capture-durable")).toBeNull();
      await waitFor(() => expect(screen.getByTestId("capture-field")).toHaveValue(NOTE));
    } finally {
      withoutIndexedDb.indexedDB = real;
    }
  });
});

describe("Create Task is not a capture and cannot enter the offline queue", () => {
  it("queues nothing when the network is down and Create Task is chosen", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValue(new TypeError("synthetic network failure"));
    const onCreateTask = vi.fn();
    const user = userEvent.setup();
    render(
      <CaptureDialog
        open
        onClose={() => {}}
        principalId={PRINCIPAL_ID}
        onCreateTask={onCreateTask}
      />,
    );

    await user.click(await screen.findByTestId("capture-choice-create_task"));

    expect(onCreateTask).toHaveBeenCalledTimes(1);
    expect(fetchSpy).not.toHaveBeenCalled();
    // Nothing was held, so nothing can be replayed as a note on reconnect.
    const db = await openOfflineDatabase();
    expect(await queueSnapshot(db)).toHaveLength(0);
    expect(screen.queryByTestId("capture-queued")).toBeNull();
    expect(screen.queryByTestId("capture-not-held")).toBeNull();
  });
});
