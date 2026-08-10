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
 * Everything here is synthetic: no real note text and no real identifier.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CaptureDialog } from "@/components/shell/capture-dialog";

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

async function saveOnce(note = NOTE) {
  const user = userEvent.setup();
  render(<CaptureDialog open onClose={() => {}} principalId={PRINCIPAL_ID} />);
  await user.type(screen.getByTestId("capture-field"), note);
  await user.click(screen.getByRole("button", { name: "Save" }));
  return user;
}

afterEach(() => {
  cleanup();
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
    const user = userEvent.setup();
    render(<CaptureDialog open onClose={() => {}} principalId={PRINCIPAL_ID} />);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.type(screen.getByTestId("capture-field"), "x");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("offers the kind as a default rather than a step, and sends the selected one", async () => {
    const spy = respond({
      shape: "backend",
      status: "persisted",
      created: true,
      receipt: { receiptId: "rcpt_aaaaaaaa11111111" },
    });
    const user = userEvent.setup();
    render(<CaptureDialog open onClose={() => {}} principalId={PRINCIPAL_ID} />);
    expect(screen.getByTestId("capture-kind-quick_note")).toBeChecked();

    await user.type(screen.getByTestId("capture-field"), NOTE);
    await user.click(screen.getByTestId("capture-kind-conversation_log"));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(spy).toHaveBeenCalled());
    const body = JSON.parse((spy.mock.calls[0][1] as RequestInit).body as string);
    expect(body.captureKind).toBe("conversation_log");
  });
});
