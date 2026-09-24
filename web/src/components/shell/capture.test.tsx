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

/**
 * WP07 — the receipt identifier and the backend's own refusal string are
 * technical receipts governed by the global diagnostics policy. Which of the
 * four outcomes happened, and what the person should do about it, is product
 * truth and renders in both modes. This file's subject includes the receipts,
 * so it runs with diagnostics on; the OFF side is asserted explicitly below.
 */
const { diagnostics } = vi.hoisted(() => ({ diagnostics: { enabled: true } }));
vi.mock("@/components/diagnostics/diagnostics-provider", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/diagnostics/diagnostics-provider")>();
  return {
    ...actual,
    useDiagnosticsEnabled: () => diagnostics.enabled,
    WhenDiagnostics: ({ children }: { children: React.ReactNode }) =>
      diagnostics.enabled ? children : null,
  };
});
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useReducer, type ComponentProps } from "react";
import { contentSha256 } from "@/lib/capture/receipt";
import { CaptureDialog } from "@/components/shell/capture-dialog";
import { beginCaptureExperience, captureSessionReducer } from "@/lib/capture/session";
import { ConstraintRuntimeProvider } from "@/components/project-controls/constraint-runtime-provider";
import { ProjectScopeProvider } from "@/components/shell/project-scope-provider";
import { MutationFeedbackProvider } from "@/components/ui/mutation-feedback";

// R02-WP10 Phase 7: `CaptureConstraintForm`, mounted for the Constraint
// branch below, reaches its runtime through `useConstraintRuntime()` /
// `useMutationFeedback()`. This harness wraps the same real provider stack
// `AppShell` mounts (`ConstraintRuntimeProvider` under `ProjectScopeProvider`
// and `MutationFeedbackProvider`) so this file exercises the real wiring
// rather than a stub of it. Every pre-existing (note/conversation) test below
// never reaches that branch and is unaffected.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/today",
}));

/**
 * The dialog no longer owns its draft, kind or Project — the shell does. This
 * harness is that owner, so these tests exercise the real reducer rather than a
 * stub of it.
 */
function CaptureHarness(
  props: Omit<ComponentProps<typeof CaptureDialog>, "session" | "dispatch">,
) {
  const [session, dispatch] = useReducer(captureSessionReducer, undefined, () =>
    beginCaptureExperience({
      experienceId: "capture-test",
      principalId: props.principalId,
      sessionEpoch: 0,
      projectId: null,
    }),
  );
  return (
    <ProjectScopeProvider principalId={props.principalId} sessionEpoch="capture-test-binding">
      <MutationFeedbackProvider>
        <ConstraintRuntimeProvider principalId={props.principalId} sessionEpoch="capture-test-binding">
          <CaptureDialog {...props} session={session} dispatch={dispatch} />
        </ConstraintRuntimeProvider>
      </MutationFeedbackProvider>
    </ProjectScopeProvider>
  );
}


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

/**
 * Answer the capture POST with `body`, and every other request with an empty
 * Project page.
 *
 * A fresh `Response` per call rather than one shared instance: the dialog now
 * also reads `/api/projects` for its Project chooser, and a body can only be
 * consumed once — a single shared Response made the second read fail as
 * unreadable content.
 */
function respond(body: unknown, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (!String(input).startsWith("/api/capture")) {
      return new Response(JSON.stringify({ projects: [], nextCursor: null }), { status: 200 });
    }
    return new Response(JSON.stringify(body), { status });
  });
}

/** The parsed body of the one capture POST, ignoring Project reads. */
function capturePostBody(spy: ReturnType<typeof respond>): Record<string, unknown> {
  const call = spy.mock.calls.find(
    ([input, init]) =>
      String(input).startsWith("/api/capture") &&
      String((init as RequestInit | undefined)?.method).toUpperCase() === "POST",
  );
  if (!call) throw new Error("no capture POST was issued");
  return JSON.parse(String((call[1] as RequestInit).body));
}

/**
 * Answer the capture POST with a complete canonical receipt for what was sent.
 *
 * The browser now verifies the whole acknowledgement — Principal, key, kind,
 * content digest and Project — before it says anything was saved, so a stub with
 * a receipt identifier on it is no longer a stub of a durable save. The digest
 * and the key have to come from the request, because both are minted at runtime.
 */
function respondPersisted(receiptOverrides: Record<string, unknown> = {}, topLevel: Record<string, unknown> = {}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (!path.startsWith("/api/capture")) {
      return new Response(JSON.stringify({ projects: [], nextCursor: null }), { status: 200 });
    }
    const sent = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
    return new Response(
      JSON.stringify({
        shape: "backend",
        status: "persisted",
        captureKind: sent.captureKind,
        created: true,
        receipt: {
          receiptId: "rcpt_aaaaaaaa11111111",
          captureId: "cap_aaaaaaaa11111111",
          versionId: "capver_aaaaaaaa11111111",
          versionNumber: 1,
          idempotencyKey: sent.idempotencyKey,
          contentSha256: await contentSha256(String(sent.text ?? "")),
          principalId: PRINCIPAL_ID,
          issuedAt: "2026-09-22T12:00:00Z",
          projectId: sent.projectId ?? null,
          ...receiptOverrides,
        },
        ...topLevel,
      }),
      { status: 200 },
    );
  });
}

/** Open Capture and take the chooser's Quick note branch into data entry. */
async function enterNoteEntry(kind: "quick_note" | "conversation_log" = "quick_note") {
  const user = userEvent.setup();
  render(<CaptureHarness open onClose={() => {}} principalId={PRINCIPAL_ID} />);
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
  diagnostics.enabled = true;
  cleanup();
  queueSpy.queueCaptureOffline.mockClear();
  vi.restoreAllMocks();
});

describe("a durable save", () => {
  it("says saved, and only for a persisted receipt", async () => {
    respondPersisted();
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
    respondPersisted({}, { created: false });
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

  it("still says saved, and shows no receipt identifier, while diagnostics are off", async () => {
    // WP07 §6.4/§6.2. The dangerous direction this file exists for is unchanged:
    // the person is still told the note is stored. The receipt identifier beside
    // it is a technical receipt and is not rendered in the product default.
    diagnostics.enabled = false;
    respondPersisted();
    await saveOnce();

    const status = await screen.findByTestId("capture-durable");
    expect(status).toHaveTextContent("Saved. Your note is stored");
    expect(status.textContent).not.toContain("rcpt_aaaaaaaa11111111");
    expect(status.textContent).not.toContain("undefined");
    await waitFor(() => expect(screen.getByTestId("capture-field")).toHaveValue(""));
  });

  it("treats an answer it does not recognise as unconfirmed rather than as saved", async () => {
    // The failure direction that matters: an unfamiliar shape must understate.
    // It is now *ambiguous* rather than "acknowledged, not stored" — a shape this
    // tier cannot read is not evidence that nothing was written, and only the
    // synthetic provider's explicit acknowledgement says that.
    respond({ shape: "something-new", created: true });
    await saveOnce();

    expect(await screen.findByTestId("capture-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("capture-durable")).toBeNull();
  });
});

describe("a refusal", () => {
  it("says nothing was stored and keeps the note, without the backend's own words, while diagnostics are off", async () => {
    // The refusal, and that the note survives, are product truth. The backend's
    // message is an unbounded raw string and is governed (WP07 §6.3/§8.4).
    diagnostics.enabled = false;
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
    expect(alert.textContent).not.toContain("bound to different content");
    expect(alert.textContent).not.toContain("idempotency");
    expect(alert.textContent).not.toMatch(/\bSaved\b/);
    expect(screen.getByTestId("capture-field")).toHaveValue(NOTE);
  });

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

/**
 * `PC-CM-CAPTURE-PROJECT-AC-011` corrective (Manager ruling, Drive
 * Artifact 23 §9/§11): a durable Note/Conversation save shows the Project
 * name, resolved from the *persisted receipt's own* `projectId` — never
 * from the picker. `verifyCaptureReceipt` already requires the receipt's
 * `projectId` to exactly equal what was sent before a save is ever shown as
 * durable at all, so a receipt/picker *mismatch at save time* cannot occur
 * here (unlike Quick Constraint's async create). What can be told apart is
 * whether the shown name tracks the *persisted* value afterwards or drifts
 * with a *later* picker change — the dialog does not close or reset on a
 * durable save, so the Project selector stays live right under the
 * confirmation. That is what this test exercises.
 */
describe("a durable save's Project name is the persisted receipt's, never the picker's", () => {
  const NOTE_PROJECT_A = "prj_aaaaaaaa11111111";
  const NOTE_PROJECT_B = "prj_bbbbbbbb22222222";

  function respondPersistedWithProjects() {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.startsWith("/api/capture")) {
        const sent = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
        return new Response(
          JSON.stringify({
            shape: "backend",
            status: "persisted",
            captureKind: sent.captureKind,
            created: true,
            receipt: {
              receiptId: "rcpt_aaaaaaaa11111111",
              captureId: "cap_aaaaaaaa11111111",
              versionId: "capver_aaaaaaaa11111111",
              versionNumber: 1,
              idempotencyKey: sent.idempotencyKey,
              contentSha256: await contentSha256(String(sent.text ?? "")),
              principalId: PRINCIPAL_ID,
              issuedAt: "2026-09-22T12:00:00Z",
              projectId: sent.projectId ?? null,
            },
          }),
          { status: 200 },
        );
      }
      if (path.startsWith("/api/projects/")) {
        const id = path.slice("/api/projects/".length);
        const name =
          id === NOTE_PROJECT_A ? "Harbor Migration" : id === NOTE_PROJECT_B ? "North Tower" : null;
        return name
          ? new Response(JSON.stringify({ project: { name } }), { status: 200 })
          : new Response("{}", { status: 404 });
      }
      return new Response(
        JSON.stringify({
          projects: [
            { projectId: NOTE_PROJECT_A, name: "Harbor Migration" },
            { projectId: NOTE_PROJECT_B, name: "North Tower" },
          ],
          nextCursor: null,
        }),
        { status: 200 },
      );
    });
  }

  it("keeps showing the receipt's Project name after the picker is changed post-save", async () => {
    respondPersistedWithProjects();
    const user = await enterNoteEntry();
    const select = await screen.findByTestId("capture-project-select");
    await waitFor(() => expect(within(select).getByText("Harbor Migration")).toBeInTheDocument());
    await user.selectOptions(select, NOTE_PROJECT_A);
    await user.type(screen.getByTestId("capture-field"), NOTE);
    await user.click(screen.getByRole("button", { name: "Save" }));

    const status = await screen.findByTestId("capture-durable");
    await waitFor(() =>
      expect(within(status).getByTestId("capture-durable-project")).toHaveTextContent(
        "Harbor Migration",
      ),
    );

    // The picker is still live under a durable save (the dialog does not
    // close or reset on success) — changing it must not relabel what was
    // actually persisted.
    await user.selectOptions(select, NOTE_PROJECT_B);
    expect(within(status).getByTestId("capture-durable-project")).toHaveTextContent(
      "Harbor Migration",
    );
    expect(within(status).getByTestId("capture-durable-project")).not.toHaveTextContent(
      "North Tower",
    );
  });

  it("shows no Project line when the persisted receipt carries no Project", async () => {
    respondPersistedWithProjects();
    const user = await enterNoteEntry();
    await user.type(screen.getByTestId("capture-field"), NOTE);
    await user.click(screen.getByRole("button", { name: "Save" }));

    await screen.findByTestId("capture-durable");
    expect(screen.queryByTestId("capture-durable-project")).toBeNull();
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
    const captureCalls = () =>
      spy.mock.calls.filter(
        ([input, init]) =>
          String(input).startsWith("/api/capture") &&
          String((init as RequestInit | undefined)?.method).toUpperCase() === "POST",
      );
    await waitFor(() => expect(captureCalls()).toHaveLength(2));
    const keys = captureCalls().map(
      (call) => JSON.parse(String((call[1] as RequestInit).body)).idempotencyKey,
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
      <CaptureHarness open onClose={() => {}} principalId={PRINCIPAL_ID} />,
    );
    await user.click(await screen.findByTestId("capture-choice-quick_note"));
    await user.type(screen.getByTestId("capture-field"), NOTE);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByTestId("capture-refused")).toBeInTheDocument();

    rerender(<CaptureHarness open={false} onClose={() => {}} principalId={PRINCIPAL_ID} />);
    rerender(<CaptureHarness open onClose={() => {}} principalId={PRINCIPAL_ID} />);

    // A reopened dialog is back at the chooser with the prior outcome cleared.
    await waitFor(() => expect(screen.queryByTestId("capture-refused")).toBeNull());
    await user.click(await screen.findByTestId("capture-choice-quick_note"));
    await waitFor(() => expect(screen.getByTestId("capture-field")).toHaveFocus());
    expect(screen.queryByTestId("capture-refused")).toBeNull();
  });

  it("returns focus to the chooser when reopened from the note branch", async () => {
    /*
      The stale-closure path. Reopening runs two effects on the same `open`
      transition: one resets the stage to the chooser, one moves focus — and the
      focus effect's first run still closes over the previous `stage`, which was
      "entry". It is the effect cleanup cancelling that stale timeout that saves
      this, which is subtle enough to break silently in a refactor. A native
      <dialog> restores focus to its invoker on close by itself, so nothing
      outside this assertion would notice.
    */
    const user = userEvent.setup();
    const { rerender } = render(
      <CaptureHarness open onClose={() => {}} principalId={PRINCIPAL_ID} />,
    );

    await user.click(await screen.findByTestId("capture-choice-quick_note"));
    await waitFor(() => expect(screen.getByTestId("capture-field")).toHaveFocus());

    rerender(<CaptureHarness open={false} onClose={() => {}} principalId={PRINCIPAL_ID} />);
    rerender(<CaptureHarness open onClose={() => {}} principalId={PRINCIPAL_ID} />);

    await waitFor(() =>
      expect(screen.getByTestId("capture-choice-create_task")).toHaveFocus(),
    );
    expect(screen.queryByTestId("capture-field")).toBeNull();
  });

  it("offers the kind as a default rather than a step, and sends the selected one", async () => {
    const spy = respondPersisted();
    const user = await enterNoteEntry();
    expect(screen.getByTestId("capture-kind-quick_note")).toBeChecked();

    // The two forms keep separate drafts (C03), so the note is authored in the
    // form it is sent from rather than carried across the switch.
    await user.click(screen.getByTestId("capture-kind-conversation_log"));
    await user.type(screen.getByTestId("capture-field"), NOTE);
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(spy.mock.calls.some(([input]) => String(input).startsWith("/api/capture"))).toBe(true),
    );
    expect(capturePostBody(spy).captureKind).toBe("conversation_log");
  });
});

describe("one activation is one capture", () => {
  it("issues exactly one request and one key when Save is double-activated", async () => {
    // The mutex is synchronous and claimed before any await, so the second
    // activation cannot arrive between the first one and the pending render.
    let release!: (value: Response) => void;
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (!path.startsWith("/api/capture")) {
        return new Response(JSON.stringify({ projects: [], nextCursor: null }), { status: 200 });
      }
      void init;
      return gate;
    });

    const user = await enterNoteEntry();
    await user.type(screen.getByTestId("capture-field"), NOTE);
    const save = screen.getByRole("button", { name: "Save" });
    // Three activations in one tick, with no render flushed between them: the
    // disabled attribute has not been applied yet, so what stops the second and
    // third from minting a key and issuing a request is the synchronous mutex.
    await act(async () => {
      save.click();
      save.click();
      save.click();
    });

    const captureCalls = spy.mock.calls.filter(([input]) =>
      String(input).startsWith("/api/capture"),
    );
    expect(captureCalls).toHaveLength(1);

    release(new Response(JSON.stringify({ shape: "synthetic", status: "acknowledged_not_persisted" }), { status: 200 }));
    await screen.findByTestId("capture-acknowledged");
    expect(
      spy.mock.calls.filter(([input]) => String(input).startsWith("/api/capture")),
    ).toHaveLength(1);
  });
});

describe("the chooser in front of capture", () => {
  it("offers exactly Create Task, Quick note, Conversation log and Constraint", async () => {
    render(<CaptureHarness open onClose={() => {}} principalId={PRINCIPAL_ID} />);
    const chooser = await screen.findByTestId("capture-chooser");
    expect(within(chooser).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Create Task",
      "Quick note",
      "Conversation log",
      "Constraint",
    ]);
    // The chooser is a router, not a capture: no field and nothing to save yet.
    expect(screen.queryByTestId("capture-field")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("takes Constraint into its own form, never the note field or /api/capture", async () => {
    const spy = respond({ projects: [], nextCursor: null });
    const user = userEvent.setup();
    render(<CaptureHarness open onClose={() => {}} principalId={PRINCIPAL_ID} />);
    await user.click(await screen.findByTestId("capture-choice-constraint"));

    expect(await screen.findByTestId("capture-constraint-save")).toBeInTheDocument();
    expect(screen.queryByTestId("capture-field")).toBeNull();
    expect(
      spy.mock.calls.some(
        ([input, init]) =>
          String(input).startsWith("/api/capture") &&
          String((init as RequestInit | undefined)?.method).toUpperCase() === "POST",
      ),
    ).toBe(false);
  });

  it("lets a person back out of Constraint and choose again", async () => {
    respond({ projects: [], nextCursor: null });
    const user = userEvent.setup();
    render(<CaptureHarness open onClose={() => {}} principalId={PRINCIPAL_ID} />);
    await user.click(await screen.findByTestId("capture-choice-constraint"));
    await screen.findByTestId("capture-constraint-save");

    await user.click(screen.getByTestId("capture-entry-back"));
    expect(await screen.findByTestId("capture-chooser")).toBeInTheDocument();
    expect(screen.queryByTestId("capture-constraint-save")).toBeNull();
  });

  it("takes Quick note into the unchanged capture branch with that kind selected", async () => {
    const spy = respondPersisted();
    const user = await enterNoteEntry("quick_note");

    expect(screen.getByTestId("capture-kind-quick_note")).toBeChecked();
    await waitFor(() => expect(screen.getByTestId("capture-field")).toHaveFocus());

    await user.type(screen.getByTestId("capture-field"), NOTE);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByTestId("capture-durable")).toHaveTextContent("Saved.");
    const body = capturePostBody(spy);
    expect(body).toMatchObject({ text: NOTE, captureKind: "quick_note" });
    expect(body.idempotencyKey).toMatch(/^cap-/);
    // No Project is sent explicitly rather than omitted.
    expect(body.projectId).toBeNull();
  });

  it("takes Conversation log into the same branch with that kind selected", async () => {
    const spy = respondPersisted();
    const user = await enterNoteEntry("conversation_log");

    expect(screen.getByTestId("capture-kind-conversation_log")).toBeChecked();
    await user.type(screen.getByTestId("capture-field"), NOTE);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByTestId("capture-durable")).toHaveTextContent("Saved.");
    expect(capturePostBody(spy).captureKind).toBe("conversation_log");
  });

  it("reports Create Task without capturing anything at all", async () => {
    const spy = respond({ shape: "backend", status: "persisted", created: true });
    const onCreateTask = vi.fn();
    const user = userEvent.setup();
    render(
      <CaptureHarness
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
