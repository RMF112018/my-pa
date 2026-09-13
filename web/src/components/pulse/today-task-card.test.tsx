import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TodayTaskCard, type TodayTaskCardProps } from "@/components/pulse/today-task-card";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import type { TaskDetail } from "@/contracts/work";
import { NO_DUE_DATE_LABEL, type TaskCivilClock } from "@/lib/tasks/presentation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TASK_ID = "tsk_bbbbbbbb22222222";
const TITLE = "Send the signed lease back";
const REASON = "Overdue by two days";
const EXPLANATION = "If ignored: the holding deposit is forfeited.";
const CLOCK: TaskCivilClock = { timezone: "UTC", workDate: "2026-09-13" };

/*
  Identifiers the Pulse projection carries and this card must never print. The
  card is given none of them; these strings exist so the assertion is about what
  a real projection would supply, not about a field this component happens to
  lack today.
*/
const PULSE_ID = "pls_cccccccc33333333";
const ITEM_REF = "tsk_bbbbbbbb22222222";
const BASIS_REF = "cap_dddddddd44444444";

/**
 * The canonical Task, which the card only ever learns about at the moment it
 * writes. Nothing in the card's props resembles it.
 */
const CANONICAL: TaskDetail = {
  task_id: TASK_ID,
  title: TITLE,
  lifecycle_state: "in_progress",
  priority: "p1",
  due_at: "2026-09-11T12:00:00Z",
  scheduled_at: null,
  deferred_until: null,
  archived_at: null,
  created_at: "2026-08-20T12:00:00Z",
  updated_at: "2026-09-11T12:00:00Z",
  description: null,
  evidence_state: "accepted",
  origin_kind: "evidence",
  origin_evidence_ref: BASIS_REF,
  closure_evidence_ref: null,
  accepted_by_review_decision_id: null,
  acceptance_kind: null,
  closure_history_id: null,
  version: 7,
  commitment_id: null,
  role: null,
  project_id: null,
  situation_id: null,
  opened_at: "2026-08-20T12:00:00Z",
  closed_at: null,
};

function ok(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

/*
  jsdom does not implement one browser behaviour these tests turn on: focus
  leaves an element at the moment it is disabled. Without it a test can only
  reach states a browser never produces, and a green test resting on such a
  state reports a mechanism as working when in a browser it does nothing at all.

  Taken verbatim from `web/src/components/work/task-list-row.test.tsx`.
*/
function emulateDisableBlur(): () => void {
  const original = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function patched(name: string, value: string) {
    if (name === "disabled" && document.activeElement === this) {
      (this as HTMLElement).blur();
    }
    return original.call(this, name, value);
  };
  return () => {
    Element.prototype.setAttribute = original;
  };
}

interface Recorded {
  readonly method: string;
  readonly path: string;
  readonly body: Record<string, unknown>;
}

function stubFetch(
  handlers: {
    detail?: () => Response | Promise<Response>;
    patch?: (body: Record<string, unknown>) => Response | Promise<Response>;
    transition?: (body: Record<string, unknown>) => Response | Promise<Response>;
  } = {},
): { fetcher: ReturnType<typeof vi.fn<typeof fetch>>; calls: Recorded[] } {
  const calls: Recorded[] = [];
  const base = `/api/tasks/${TASK_ID}`;
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    calls.push({ method, path, body });
    if (path === base && method === "GET") {
      return handlers.detail ? handlers.detail() : ok({ task: CANONICAL });
    }
    if (path === base && method === "PATCH") {
      return handlers.patch
        ? handlers.patch(body)
        : ok({
            task: { ...CANONICAL, version: 8, due_at: (body.dueAt as string | undefined) ?? null },
          });
    }
    if (path === `${base}/transition` && method === "POST") {
      return handlers.transition
        ? handlers.transition(body)
        : ok({ task: { ...CANONICAL, version: 8, lifecycle_state: body.toState } });
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return { fetcher, calls };
}

function detailReads(calls: readonly Recorded[]): Recorded[] {
  return calls.filter((call) => call.method === "GET" && call.path === `/api/tasks/${TASK_ID}`);
}

function renderCard(props: Partial<TodayTaskCardProps> = {}): {
  onMutationConfirmed: ReturnType<typeof vi.fn<NonNullable<TodayTaskCardProps["onMutationConfirmed"]>>>;
} {
  const onMutationConfirmed =
    vi.fn<NonNullable<TodayTaskCardProps["onMutationConfirmed"]>>();
  render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      <TodayTaskCard
        taskId={TASK_ID}
        title={TITLE}
        reason={REASON}
        explanation={EXPLANATION}
        clock={CLOCK}
        onMutationConfirmed={onMutationConfirmed}
        {...props}
      />
    </TaskRuntimeProvider>,
  );
  return { onMutationConfirmed };
}

function card(): HTMLElement {
  return screen.getByTestId("today-task-card");
}

function rescheduleTrigger(): HTMLElement {
  return screen.getByRole("button", { name: `Reschedule ${TITLE}` });
}

/** Open the Due popover and choose Tomorrow. */
async function reschedule(): Promise<void> {
  await userEvent.click(rescheduleTrigger());
  await userEvent.click(await screen.findByRole("button", { name: "Tomorrow" }));
}

describe("TodayTaskCard", () => {
  it("renders title, reason and the two actions, in that reading order", async () => {
    stubFetch();
    renderCard();

    const title = screen.getByTestId("today-task-card-title");
    const reason = screen.getByTestId("today-task-card-reason");
    const explanation = screen.getByTestId("today-task-card-explanation");
    expect(title.textContent).toBe(TITLE);
    expect(reason.textContent).toBe(REASON);

    const trigger = rescheduleTrigger();
    const close = screen.getByTestId("task-close-trigger");
    expect(within(card()).getByRole("group", { name: `Close ${TITLE}` })).toBeTruthy();

    /*
      Reading order is the claim, not merely presence: what it is, why now, what
      to do, and only then why it matters.
    */
    const order = [title, reason, trigger, close, explanation];
    for (let index = 0; index + 1 < order.length; index += 1) {
      const relation = order[index].compareDocumentPosition(order[index + 1]);
      expect(relation & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it("reads no Task detail at render, and exactly one at the first write", async () => {
    /*
      One Pulse card per item, and the user may touch none of them. Hydrating on
      mount would be a detail read per card — the fan-out this surface exists to
      avoid. The canonical read happens at the write, and only then.
    */
    const { calls } = stubFetch();
    renderCard();

    // Operable without having read anything.
    await waitFor(() => expect(rescheduleTrigger()).toHaveProperty("disabled", false));
    expect(detailReads(calls)).toHaveLength(0);

    await reschedule();

    await waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(detailReads(calls)).toHaveLength(1);
  });

  it("sends the canonical expectedVersion from that read, never a projection value", async () => {
    const expectedVersions: unknown[] = [];
    stubFetch({
      detail: async () => ok({ task: { ...CANONICAL, version: 11 } }),
      patch: async (body) => {
        expectedVersions.push(body.expectedVersion);
        return ok({ task: { ...CANONICAL, version: 12, due_at: (body.dueAt as string) ?? null } });
      },
    });
    renderCard();

    await reschedule();

    await waitFor(() => expect(expectedVersions).toHaveLength(1));
    expect(expectedVersions).toEqual([11]);
    // The card never held a version of its own; the projection's is not a thing.
    expect(expectedVersions).not.toContain(CANONICAL.version);
  });

  it("sends exactly the Due write contract — no planning fields", async () => {
    const bodies: Record<string, unknown>[] = [];
    stubFetch({
      patch: async (body) => {
        bodies.push(body);
        return ok({ task: { ...CANONICAL, version: 8, due_at: (body.dueAt as string) ?? null } });
      },
    });
    renderCard();

    await reschedule();

    await waitFor(() => expect(bodies).toHaveLength(1));
    const keys = Object.keys(bodies[0]).sort();
    expect(keys).toEqual(["dueAt", "expectedVersion", "idempotencyKey"]);
    expect(keys).not.toContain("scheduledAt");
    expect(keys).not.toContain("deferredUntil");
  });

  it("closes the Task in exactly two activations, and never asks for text", async () => {
    const { calls } = stubFetch();
    renderCard();

    expect(screen.queryByRole("textbox")).toBeNull();

    await userEvent.click(screen.getByTestId("task-close-trigger"));
    // The confirmation asks for a decision, not for authored text.
    expect(screen.queryByRole("textbox")).toBeNull();
    // No lifecycle selector anywhere on this card.
    expect(screen.queryByRole("combobox")).toBeNull();

    await userEvent.click(screen.getByTestId("task-close-confirm"));

    await waitFor(() =>
      expect(calls.some((call) => call.path.endsWith("/transition"))).toBe(true),
    );
    const transition = calls.find((call) => call.path.endsWith("/transition"));
    expect(transition?.body.toState).toBe("completed");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("shows no raw identifiers", async () => {
    stubFetch();
    renderCard();
    await waitFor(() => expect(rescheduleTrigger()).toHaveProperty("disabled", false));

    const text = card().textContent ?? "";
    const html = card().innerHTML;
    for (const identifier of [PULSE_ID, ITEM_REF, BASIS_REF, TASK_ID]) {
      expect(text).not.toContain(identifier);
      expect(html).not.toContain(identifier);
    }
    expect(text).not.toMatch(/\bRank\b|\bBasis\b/);
    expect(text).not.toMatch(/in_progress|completed|cancelled|lifecycle/i);
  });

  it("never states a Due or Status value it has not read", async () => {
    /*
      The central constraint. A Pulse item carries no `due_at` and no
      `lifecycle_state`, so the binder's unseeded fallbacks are `null` and
      `"open"`. Rendering either would announce "Due, No due date" for a Task
      that surfaced precisely because it is overdue, and "Open" for a Task
      nobody read. The card therefore presents Reschedule as an action and
      offers no Status at all.
    */
    stubFetch();
    renderCard();
    await waitFor(() => expect(rescheduleTrigger()).toHaveProperty("disabled", false));

    const text = card().textContent ?? "";
    expect(text).not.toContain(NO_DUE_DATE_LABEL);
    expect(screen.queryByRole("button", { name: new RegExp(`^Due, `) })).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("group", { name: `Change status for ${TITLE}` })).toBeNull();
    // And the accessible name is the action, carrying this Task's context.
    expect(rescheduleTrigger().getAttribute("aria-label")).toBe(`Reschedule ${TITLE}`);
  });

  /*
    TUX07-AC-018. Confirming Close makes the Task terminal, and this card's
    terminal affordance then withholds itself — so the control the user was
    holding and its `role="group"` both leave. The card is not a link and has no
    anchor for the shared engine's chain to land on, so before this the user was
    dropped on `document.body`, at the top of the document. The card declares its
    root focusable by script and the engine places them there.
  */
  it("returns focus to the card itself when Close removes the control the user was on", async () => {
    const restore = emulateDisableBlur();
    try {
      let release!: () => void;
      const held = new Promise<void>((resolve) => {
        release = resolve;
      });
      stubFetch({
        transition: async (body) => {
          await held;
          return ok({ task: { ...CANONICAL, version: 8, lifecycle_state: body.toState } });
        },
      });
      renderCard();

      const trigger = screen.getByTestId("task-close-trigger");
      trigger.focus();
      await userEvent.click(trigger);
      const confirm = screen.getByTestId("task-close-confirm");
      confirm.focus();
      expect(document.activeElement).toBe(confirm);
      await userEvent.click(confirm);

      // The browser lets go of the control the moment the write disables it.
      await waitFor(() => expect(confirm.hasAttribute("disabled")).toBe(true));
      expect(document.activeElement).toBe(document.body);
      release();

      // The Task is terminal: the whole Close affordance has withdrawn.
      await waitFor(() => expect(screen.queryByTestId("task-close-trigger")).toBeNull());
      await waitFor(() => expect(document.activeElement).toBe(card()));
      expect(document.activeElement).not.toBe(document.body);
    } finally {
      restore();
    }
  });

  /*
    Focusable by script, and nothing more. A `0` here would put every Pulse card
    in the tab order ahead of its own controls, making the list longer to walk
    for every keyboard user in order to serve one moment after a write.
  */
  it("keeps the focusable card root out of the tab order, and names it", async () => {
    stubFetch();
    renderCard();

    expect(card().getAttribute("tabindex")).toBe("-1");
    const labelledBy = card().getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    expect(document.getElementById(String(labelledBy))).toBe(
      screen.getByTestId("today-task-card-title"),
    );
  });

  it("names the Task it is about on its root, so the list can tell its cards apart", async () => {
    stubFetch();
    renderCard();

    /*
      The surface that owns Today's list restores focus when its authoritative
      re-read removes a card the user was standing in, and to do that it has to
      know which card left and which one now stands in its place. The test id
      names the kind of thing; this names the thing itself.
    */
    expect(card().getAttribute("data-today-task")).toBe(TASK_ID);
  });

  it("offers a way out of a version conflict rather than locking forever", async () => {
    const restore = emulateDisableBlur();
    try {
      stubFetch({
        patch: () =>
          new Response(
            JSON.stringify({
              error: { message: "version conflict", code: "conflict" },
              current: { ...CANONICAL, version: 9 },
            }),
            { status: 409, headers: { "content-type": "application/json" } },
          ),
      });
      renderCard();

      rescheduleTrigger().focus();
      await reschedule();

      const panel = await screen.findByTestId("today-card-conflict");
      expect(panel).toBeTruthy();

      // The question is put where the user can answer it.
      await act(async () => {
        await new Promise<void>((resolve) => {
          requestAnimationFrame(() => resolve());
        });
      });
      expect(document.activeElement).toBe(screen.getByTestId("today-card-conflict-reapply"));

      // And standing it down leaves the card working, not locked.
      await userEvent.click(screen.getByTestId("today-card-conflict-dismiss"));
      await waitFor(() => expect(screen.queryByTestId("today-card-conflict")).toBeNull());
      expect(rescheduleTrigger()).toHaveProperty("disabled", false);
      expect(screen.getByTestId("task-close-trigger")).toHaveProperty("disabled", false);
    } finally {
      restore();
    }
  });

  it("reports a confirmed mutation to its caller", async () => {
    stubFetch();
    const { onMutationConfirmed } = renderCard();

    await reschedule();

    await waitFor(() => expect(onMutationConfirmed).toHaveBeenCalledTimes(1));
    expect(onMutationConfirmed).toHaveBeenCalledWith({ taskId: TASK_ID, kind: "due" });
  });
});
