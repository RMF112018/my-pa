import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { useTaskRowOperations } from "@/components/tasks/use-task-row-operations";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import type { TaskDetail, TaskRow } from "@/contracts/work";
import type { TaskCivilClock } from "@/lib/tasks/presentation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CLOCK: TaskCivilClock = { timezone: "UTC", workDate: "2026-09-12" };

function listRow(id: string): TaskRow {
  return {
    task_id: id,
    title: `Task ${id}`,
    lifecycle_state: "in_progress",
    priority: "p1",
    due_at: "2026-09-13T12:00:00Z",
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    created_at: "2026-08-20T12:00:00Z",
    updated_at: "2026-08-22T12:00:00Z",
    // Deliberately present and deliberately stale: a projection may carry a
    // version, and it is still never write authority.
    version: 3,
  };
}

function canonical(id: string): TaskDetail {
  return {
    ...listRow(id),
    description: null,
    evidence_state: "accepted",
    origin_kind: "evidence",
    origin_evidence_ref: "cap_origin0001origin0001",
    closure_evidence_ref: null,
    accepted_by_review_decision_id: null,
    acceptance_kind: null,
    closure_history_id: null,
    version: 4,
    commitment_id: null,
    role: null,
    project_id: null,
    situation_id: null,
    opened_at: "2026-08-20T12:00:00Z",
    closed_at: null,
  };
}

function ok(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function stubFetch() {
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    const detail = /^\/api\/tasks\/(tsk_[0-9a-f]+)$/.exec(path);
    if (detail && method === "GET") return ok({ task: canonical(detail[1]) });
    const transition = /^\/api\/tasks\/(tsk_[0-9a-f]+)\/transition$/.exec(path);
    if (transition && method === "POST") {
      return ok({ task: { ...canonical(transition[1]), version: 5, lifecycle_state: body.toState } });
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

function detailGets(fetcher: ReturnType<typeof stubFetch>): string[] {
  return fetcher.mock.calls
    .filter(([, init]) => (init?.method ?? "GET").toUpperCase() === "GET")
    .map(([input]) => String(input))
    .filter((path) => /^\/api\/tasks\/tsk_[0-9a-f]+$/.test(path));
}

interface ProbeProps {
  readonly task: TaskRow;
  readonly onMutationConfirmed?: (input: { taskId: string; kind: string }) => void;
}

/** The smallest possible consumer: a card that is not the List row. */
function Probe({ task, onMutationConfirmed }: ProbeProps): React.JSX.Element {
  const operations = useTaskRowOperations<HTMLDivElement>({
    taskId: task.task_id,
    task,
    clock: CLOCK,
    onMutationConfirmed,
  });
  const { rowRef, handleStatus } = operations;
  return (
    <div ref={rowRef} data-testid={`probe-${task.task_id}`}>
      <button type="button" onClick={() => handleStatus("blocked")}>
        {`Block ${task.title}`}
      </button>
    </div>
  );
}

function renderProbes(ids: readonly string[], onMutationConfirmed?: ProbeProps["onMutationConfirmed"]): void {
  render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      {ids.map((id) => (
        <Probe key={id} task={listRow(id)} onMutationConfirmed={onMutationConfirmed} />
      ))}
    </TaskRuntimeProvider>,
  );
}

describe("useTaskRowOperations", () => {
  /*
    The no-N+1 contract, guarded where it is now decided.

    The hydrate mode used to be spelled out inside the List row; it is now one
    shared line serving every card surface, so a single edit there would fan a
    collection out into one detail read per card. This is the test that stops it.
  */
  it("reads no Task detail when cards mount", async () => {
    const fetcher = stubFetch();
    renderProbes(["tsk_aaaaaaaa11111111", "tsk_bbbbbbbb22222222", "tsk_cccccccc33333333"]);

    expect(screen.getByTestId("probe-tsk_cccccccc33333333")).toBeTruthy();
    await waitFor(() => expect(detailGets(fetcher)).toEqual([]));
  });

  it("hydrates canonically at the first write, then reports the confirmation", async () => {
    const fetcher = stubFetch();
    const onMutationConfirmed = vi.fn<(input: { taskId: string; kind: string }) => void>();
    renderProbes(["tsk_aaaaaaaa11111111", "tsk_bbbbbbbb22222222"], onMutationConfirmed);

    await userEvent.click(screen.getByRole("button", { name: "Block Task tsk_aaaaaaaa11111111" }));

    await waitFor(() =>
      expect(onMutationConfirmed).toHaveBeenCalledWith({ taskId: "tsk_aaaaaaaa11111111", kind: "status" }),
    );
    // Only the card that was written to paid a detail read.
    expect(detailGets(fetcher)).toEqual(["/api/tasks/tsk_aaaaaaaa11111111"]);
    const sent = fetcher.mock.calls.find(
      ([input, init]) =>
        String(input) === "/api/tasks/tsk_aaaaaaaa11111111/transition" && init?.method === "POST",
    );
    const body = JSON.parse(String(sent?.[1]?.body)) as Record<string, unknown>;
    // The canonical version, never the projection's stale 3.
    expect(body.expectedVersion).toBe(4);
  });
});

/* ------------------------------------------------------------------ *
 * Focus return on a card-shaped surface
 * ------------------------------------------------------------------ */

/**
 * A browser blurs a focused element the instant `disabled` is applied to it.
 * jsdom does not, and a focus-return test that passes only because of that
 * difference is evidence of nothing — the whole engine reads `document.body` as
 * its signal. Copied from `work/task-list-row.test.tsx`, where the same
 * necessity was found.
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

interface CardProbeProps {
  readonly task: TaskRow;
  /** Whether the card root declares itself focusable by script (`tabIndex={-1}`). */
  readonly focusableRoot: boolean;
  /** Whether the card carries a title link, as the Work row and Board card do. */
  readonly anchor: boolean;
}

/**
 * A card whose Close affordance withdraws itself once the Task is terminal —
 * exactly the shape of `TodayTaskCard`, and the shape the old fallback chain had
 * no answer for. The held control and its `role="group"` leave together.
 */
function CardProbe({ task, focusableRoot, anchor }: CardProbeProps): React.JSX.Element {
  const operations = useTaskRowOperations<HTMLElement>({
    taskId: task.task_id,
    task,
    clock: CLOCK,
  });
  const { rowRef, handleClose, locked, terminal } = operations;
  return (
    <article ref={rowRef} data-testid="card" tabIndex={focusableRoot ? -1 : undefined}>
      <h3>{task.title}</h3>
      {anchor ? <a href={`/work/${task.task_id}`}>{task.title}</a> : null}
      {terminal ? null : (
        <div role="group" aria-label={`Close ${task.title}`}>
          <button type="button" disabled={locked} onClick={handleClose}>
            Confirm Closed
          </button>
        </div>
      )}
    </article>
  );
}

/** A transition held open, so the locked window can be observed rather than raced. */
function gatedStubFetch(): { release: () => void } {
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    const detail = /^\/api\/tasks\/(tsk_[0-9a-f]+)$/.exec(path);
    if (detail && method === "GET") return ok({ task: canonical(detail[1]) });
    const transition = /^\/api\/tasks\/(tsk_[0-9a-f]+)\/transition$/.exec(path);
    if (transition && method === "POST") {
      await held;
      return ok({ task: { ...canonical(transition[1]), version: 5, lifecycle_state: body.toState } });
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return { release };
}

interface ClosedCard {
  readonly card: HTMLElement;
  /**
   * Calls to `focus()` on the card root.
   *
   * The outcome alone cannot speak for the focusability guard: calling `focus()`
   * on an element that cannot take focus does nothing — in jsdom and in a
   * browser alike — so `document.activeElement` reads the same whether the
   * engine declined to aim at the root or aimed at it and was ignored. The
   * difference is precisely what the guard is for, and it is only visible here.
   */
  readonly rootFocus: ReturnType<typeof vi.fn<() => void>>;
}

async function closeFromKeyboard(props: Omit<CardProbeProps, "task">): Promise<ClosedCard> {
  const { release } = gatedStubFetch();
  render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      <CardProbe task={listRow("tsk_dddddddd44444444")} {...props} />
    </TaskRuntimeProvider>,
  );
  const card = screen.getByTestId("card");
  const rootFocus = vi.fn<() => void>();
  const nativeFocus = card.focus.bind(card);
  card.focus = () => {
    rootFocus();
    nativeFocus();
  };
  const confirm = within(card).getByRole("button", { name: "Confirm Closed" });
  confirm.focus();
  expect(document.activeElement).toBe(confirm);
  await userEvent.click(confirm);
  // The browser has let go of the control, exactly as it does. Observed while
  // the write is still held open, so this is the real starting point of the
  // return and not a state the assertion raced past.
  await waitFor(() => expect(confirm.hasAttribute("disabled")).toBe(true));
  expect(document.activeElement).toBe(document.body);
  release();
  // The Task is terminal, so the whole affordance — control and group — is gone.
  await waitFor(() =>
    expect(within(card).queryByRole("button", { name: "Confirm Closed" })).toBeNull(),
  );
  return { card, rootFocus };
}

/**
 * Acceptance traceability: TASK-AC-034 — where focus lands when the control a user held is
 * removed by the write they just made.
 */
describe("useTaskRowOperations focus return", () => {
  /*
    The defect this closes. A card that is not a link has no `a[href]` for the
    chain to land on, so every earlier step having failed used to mean nothing
    was focused at all and the keyboard user was left on the body, at the top of
    the document.
  */
  it("lands on the card root when the held control, its group and any anchor are all absent", async () => {
    const restore = emulateDisableBlur();
    try {
      const { card, rootFocus } = await closeFromKeyboard({ focusableRoot: true, anchor: false });
      await waitFor(() => expect(document.activeElement).toBe(card));
      expect(rootFocus).toHaveBeenCalled();
      expect(document.activeElement).not.toBe(document.body);
    } finally {
      restore();
    }
  });

  /*
    The Work surfaces, unchanged. The root is a last resort and nothing more: a
    row that has its own title link still returns the user to that link, so this
    step can never quietly take precedence over a better destination.
  */
  it("still prefers the row's own anchor over the root when one is present", async () => {
    const restore = emulateDisableBlur();
    try {
      const { card, rootFocus } = await closeFromKeyboard({ focusableRoot: true, anchor: true });
      const link = within(card).getByRole("link");
      await waitFor(() => expect(document.activeElement).toBe(link));
      expect(document.activeElement).not.toBe(card);
      expect(rootFocus).not.toHaveBeenCalled();
    } finally {
      restore();
    }
  });

  /*
    The opt-in is load-bearing. Focusing a root that cannot take focus does
    nothing at all, silently, so handing it focus would report a return that
    never happened — a surface that has not declared itself focusable is left
    alone instead.
  */
  it("does not hand focus to a root that cannot take it", async () => {
    const restore = emulateDisableBlur();
    try {
      const { card, rootFocus } = await closeFromKeyboard({ focusableRoot: false, anchor: false });
      await new Promise((resolve) => setTimeout(resolve, 0));
      /*
        Not merely "focus did not land there" — `focus()` on an element that
        cannot take it is a silent no-op, so that would read the same either way.
        The claim is that the engine never aimed at it.
      */
      expect(rootFocus).not.toHaveBeenCalled();
      expect(document.activeElement).not.toBe(card);
      expect(document.activeElement).toBe(document.body);
    } finally {
      restore();
    }
  });
});
