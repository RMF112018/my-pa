/**
 * The capture surface keeps four outcomes apart, and never says "saved" wrongly.
 *
 * This is the acceptance control the screen itself owns. The Python side proves
 * that a receipt means a committed row; what this file proves is that the
 * *person* is told which of the four things happened, because that is what they
 * act on. The dangerous direction is asymmetric and every assertion below is
 * written for it: showing "saved" for something that was not stored tells someone
 * to stop worrying about a note that is gone, while showing a refusal for a note
 * that *was* stored merely annoys them.
 *
 * Four outcomes, four different instructions:
 *
 * * **durable** — the backend's own receipt. The only state that says "saved".
 * * **acknowledged, not persisted** — the synthetic provider. Says so plainly and
 *   keeps the note in the field.
 * * **refused** — nothing stored, reason shown, note kept.
 * * **unavailable** — nothing stored, retry worth doing, same attempt key reused
 *   so the retry cannot become a second capture.
 *
 * Capture now opens on a three-way chooser (Create Task, Quick note,
 * Conversation log), so every case below picks a note kind first. That first
 * click is the *only* thing that changed: past it, the field, the attempt key,
 * the request shape and all six outcomes are the surface this file has always
 * asserted on, and each assertion still carries its original guarantee.
 *
 * Everything here is synthetic: no real note text and no real identifier.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CaptureDialog } from "@/components/shell/capture-dialog";

// The offline hold is proved in `capture-offline.test.tsx` against the real
// queue; here the module is a spy so the chooser can be held to writing nothing.
const queueSpy = vi.hoisted(() => ({ queueCaptureOffline: vi.fn() }));
vi.mock("@/lib/offline/capture-queue", () => queueSpy);

const NOTE = "synthetic note epsilon — flange tolerance review";

/**
 * The signed-in principal the shell supplies.
 *
 * Required by the dialog since WP-08: a note that has to be held offline is
 * bound to the principal that was authenticated when it was queued, and there is
 * no path that queues one without an identity to bind it to. The outcomes below
 * are unchanged — this prop is only read on the offline path.
 */
const PRINCIPAL_ID = "syn-aaaa0001";

function respond(body: unknown, status = 200) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

/** Open Capture and take the chooser's Quick note branch into data entry. */
async function enterNoteEntry(kind: "quick_note" | "conversation_log" = "quick_note") {
  const user = userEvent.setup();
  render(<CaptureDialog open onClose={() => {}} principalId={PRINCIPAL_ID} />);
  await user.click(await screen.findByTestId(`capture-choice-${kind}`));
  return user;
}

async function saveOnce(note = NOTE) {
  const user = await enterNoteEntry();
  await user.type(screen.getByTestId("capture-field"), note);
  await user.click(screen.getByRole("button", { name: "Save" }));
  return user;
}

afterEach(() => {
  cleanup();
  queueSpy.queueCaptureOffline.mockClear();
  vi.restoreAllMocks();
});

describe("a durable save", () => {
  it("says saved, and only for a persisted receipt", async () => {
    respond({
      shape: "backend",
      status: "persisted",
      created: true,
      receipt: { receiptId: "rcpt_aaaaaaaa11111111" },
    });
    await saveOnce();

    const status = await screen.findByTestId("capture-durable");
    expect(status).toHaveTextContent("Saved. Your note is stored");
    expect(status).toHaveTextContent("rcpt_aaaaaaaa11111111");
    // The receipt is read out of the backend's nested shape rather than a flat
    // field that path never carries.
    expect(status.textContent).not.toContain("undefined");
    // A durable save clears the field; nothing else does.
    await waitFor(() => expect(screen.getByTestId("capture-field")).toHaveValue(""));
  });

  it("distinguishes a replay from a first save without calling it a failure", async () => {
    respond({
      shape: "backend",
      status: "persisted",
      created: false,
      receipt: { receiptId: "rcpt_aaaaaaaa11111111" },
    });
    await saveOnce();

    const status = await screen.findByTestId("capture-durable");
    expect(status).toHaveTextContent("Already saved");
    expect(status).toHaveTextContent("Nothing was stored twice");
  });
});

describe("an acknowledgement that is not a save", () => {
  it("never renders as saved, and keeps the note where the person can copy it", async () => {
    respond({
      shape: "synthetic",
      status: "acknowledged_not_persisted",
      created: true,
      receiptId: "rcpt-synthetic-1",
    });
    await saveOnce();

    const status = await screen.findByTestId("capture-acknowledged");
    expect(status).toHaveTextContent("not stored");
    expect(screen.queryByTestId("capture-durable")).toBeNull();
    expect(status.textContent).not.toMatch(/\bSaved\b/);
    expect(screen.getByTestId("capture-field")).toHaveValue(NOTE);
  });

  it("treats an answer it does not recognise as not-saved rather than as saved", async () => {
    // The failure direction that matters: an unfamiliar shape must understate.
    respond({ shape: "something-new", created: true });
    await saveOnce();

    expect(await screen.findByTestId("capture-acknowledged")).toBeInTheDocument();
    expect(screen.queryByTestId("capture-durable")).toBeNull();
  });
});

describe("a refusal", () => {
  it("says nothing was stored, names the reason, and keeps the note", async () => {
    respond(
      {
        error: {
          errorClass: "conflict",
          code: "conflict",
          message: "this idempotency key is bound to different content",
        },
      },
      409,
    );
    await saveOnce();

    const alert = await screen.findByTestId("capture-refused");
    expect(alert).toHaveTextContent("nothing was stored");
    expect(alert).toHaveTextContent("bound to different content");
    expect(screen.queryByTestId("capture-durable")).toBeNull();
    expect(screen.getByTestId("capture-field")).toHaveValue(NOTE);
  });
});

describe("an unreachable backend", () => {
  it("is a different state from a refusal, and retries the same attempt", async () => {
    const spy = respond(
      {
        error: {
          errorClass: "unavailable",
          code: "gateway_unreachable",
          message: "the gateway did not answer",
        },
      },
      503,
    );
    const user = await saveOnce();

    const alert = await screen.findByTestId("capture-unavailable");
    expect(alert).toHaveTextContent("could not be reached");
    expect(screen.queryByTestId("capture-refused")).toBeNull();
    expect(screen.queryByTestId("capture-durable")).toBeNull();
    expect(screen.getByTestId("capture-field")).toHaveValue(NOTE);

    // The retry carries the *same* idempotency key, so a save that did land on
    // the far side of a lost response cannot become a second capture.
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    const keys = spy.mock.calls.map(
      (call) => JSON.parse((call[1] as RequestInit).body as string).idempotencyKey,
    );
    expect(keys[0]).toBe(keys[1]);
  });
});

describe("one field is the whole precondition", () => {
  it("disables Save on an empty field and enables it on any text", async () => {
    const user = await enterNoteEntry();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.type(screen.getByTestId("capture-field"), "x");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("resets a prior outcome only when a newly opened dialog is scheduled", async () => {
    respond(
      {
        error: {
          errorClass: "conflict",
          code: "conflict",
          message: "synthetic refusal",
        },
      },
      409,
    );
    const user = userEvent.setup();
    const { rerender } = render(
      <CaptureDialog open onClose={() => {}} principalId={PRINCIPAL_ID} />,
    );
    await user.click(await screen.findByTestId("capture-choice-quick_note"));
    await user.type(screen.getByTestId("capture-field"), NOTE);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByTestId("capture-refused")).toBeInTheDocument();

    rerender(<CaptureDialog open={false} onClose={() => {}} principalId={PRINCIPAL_ID} />);
    rerender(<CaptureDialog open onClose={() => {}} principalId={PRINCIPAL_ID} />);

    // A reopened dialog is back at the chooser with the prior outcome cleared.
    await waitFor(() => expect(screen.queryByTestId("capture-refused")).toBeNull());
    await user.click(await screen.findByTestId("capture-choice-quick_note"));
    await waitFor(() => expect(screen.getByTestId("capture-field")).toHaveFocus());
    expect(screen.queryByTestId("capture-refused")).toBeNull();
  });

  it("offers the kind as a default rather than a step, and sends the selected one", async () => {
    const spy = respond({
      shape: "backend",
      status: "persisted",
      created: true,
      receipt: { receiptId: "rcpt_aaaaaaaa11111111" },
    });
    const user = await enterNoteEntry();
    expect(screen.getByTestId("capture-kind-quick_note")).toBeChecked();

    await user.type(screen.getByTestId("capture-field"), NOTE);
    await user.click(screen.getByTestId("capture-kind-conversation_log"));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(spy).toHaveBeenCalled());
    const body = JSON.parse((spy.mock.calls[0][1] as RequestInit).body as string);
    expect(body.captureKind).toBe("conversation_log");
  });
});

describe("the chooser in front of capture", () => {
  it("offers exactly Create Task, Quick note and Conversation log", async () => {
    render(<CaptureDialog open onClose={() => {}} principalId={PRINCIPAL_ID} />);
    const chooser = await screen.findByTestId("capture-chooser");
    expect(within(chooser).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Create Task",
      "Quick note",
      "Conversation log",
    ]);
    // The chooser is a router, not a capture: no field and nothing to save yet.
    expect(screen.queryByTestId("capture-field")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("takes Quick note into the unchanged capture branch with that kind selected", async () => {
    const spy = respond({
      shape: "backend",
      status: "persisted",
      created: true,
      receipt: { receiptId: "rcpt_aaaaaaaa11111111" },
    });
    const user = await enterNoteEntry("quick_note");

    expect(screen.getByTestId("capture-kind-quick_note")).toBeChecked();
    await waitFor(() => expect(screen.getByTestId("capture-field")).toHaveFocus());

    await user.type(screen.getByTestId("capture-field"), NOTE);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByTestId("capture-durable")).toHaveTextContent("Saved.");
    const body = JSON.parse((spy.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toMatchObject({ text: NOTE, captureKind: "quick_note" });
    expect(body.idempotencyKey).toMatch(/^cap-/);
  });

  it("takes Conversation log into the same branch with that kind selected", async () => {
    const spy = respond({
      shape: "backend",
      status: "persisted",
      created: true,
      receipt: { receiptId: "rcpt_aaaaaaaa11111111" },
    });
    const user = await enterNoteEntry("conversation_log");

    expect(screen.getByTestId("capture-kind-conversation_log")).toBeChecked();
    await user.type(screen.getByTestId("capture-field"), NOTE);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByTestId("capture-durable")).toHaveTextContent("Saved.");
    const body = JSON.parse((spy.mock.calls[0][1] as RequestInit).body as string);
    expect(body.captureKind).toBe("conversation_log");
  });

  it("reports Create Task without capturing anything at all", async () => {
    const spy = respond({ shape: "backend", status: "persisted", created: true });
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
    // Zero capture persistence: no request, no field, no outcome, no key minted.
    expect(spy).not.toHaveBeenCalled();
    expect(queueSpy.queueCaptureOffline).not.toHaveBeenCalled();
    expect(screen.queryByTestId("capture-field")).toBeNull();
    expect(screen.queryByTestId("capture-durable")).toBeNull();
    expect(screen.queryByTestId("capture-queued")).toBeNull();
  });

  it("lets a person back out of a note kind and choose again", async () => {
    const user = await enterNoteEntry("conversation_log");
    await user.click(screen.getByTestId("capture-entry-back"));
    expect(await screen.findByTestId("capture-chooser")).toBeInTheDocument();
    expect(screen.queryByTestId("capture-field")).toBeNull();
  });
});
