/**
 * Board and Calendar operations (WP-TUX-06).
 *
 * These guards are about the two things the perspectives could get wrong in ways
 * no other test would notice: what the Board is *for* (four active columns, no
 * terminal archive), and that operating a card or a marker goes through the one
 * shared mutation path with canonical authority — never the projection's stale
 * version, and never widening a Due change into a reschedule.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useCallback, useState } from "react";

import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import { WorkPerspectives, type WorkPerspectivesProps } from "@/components/work/work-perspectives";
import type { TaskDetail, TaskRow } from "@/contracts/work";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TASK_ID = "tsk_aaaaaaaa11111111";
const TITLE = "Prepare the permit set";

/** Relative instants, so no guard depends on the day the suite happens to run. */
const DAY_MS = 86_400_000;
const iso = (days: number) => new Date(Date.now() + days * DAY_MS).toISOString();

/** A Work projection: display seed only, carrying a deliberately stale version. */
function rowOf(overrides: Partial<TaskRow> = {}): TaskRow {
  return {
    task_id: TASK_ID,
    title: TITLE,
    lifecycle_state: "open",
    priority: "p1",
    due_at: iso(4),
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    created_at: "2026-08-20T12:00:00Z",
    updated_at: "2026-08-22T12:00:00Z",
    version: 3,
    ...overrides,
  };
}

function detailOf(row: TaskRow, overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    ...row,
    description: null,
    evidence_state: "accepted",
    origin_kind: "evidence",
    origin_evidence_ref: "cap_origin0001origin0001",
    closure_evidence_ref: null,
    accepted_by_review_decision_id: null,
    acceptance_kind: null,
    closure_history_id: null,
    // Canonical, and deliberately not the projection's version.
    version: 9,
    commitment_id: null,
    role: null,
    project_id: null,
    situation_id: null,
    opened_at: "2026-08-20T12:00:00Z",
    closed_at: null,
    ...overrides,
  };
}

function ok(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function gate(): { wait: Promise<void>; release: () => void } {
  let release!: () => void;
  const wait = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { wait, release };
}

interface Recorded {
  readonly method: string;
  readonly path: string;
  readonly body: Record<string, unknown>;
}

/** Every Task route answered from a canonical Task; nothing else is expected. */
function stubFetch(handlers: {
  detail?: (taskId: string) => Response | Promise<Response>;
  transition?: (body: Record<string, unknown>, taskId: string) => Response | Promise<Response>;
  patch?: (body: Record<string, unknown>, taskId: string) => Response | Promise<Response>;
} = {}) {
  const calls: Recorded[] = [];
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    calls.push({ method, path, body });
    const detailMatch = /^\/api\/tasks\/([^/?]+)$/.exec(path);
    const transitionMatch = /^\/api\/tasks\/([^/?]+)\/transition$/.exec(path);
    if (detailMatch && method === "GET") {
      const id = decodeURIComponent(detailMatch[1]!);
      return handlers.detail ? handlers.detail(id) : ok({ task: detailOf(rowOf({ task_id: id })) });
    }
    if (detailMatch && method === "PATCH") {
      const id = decodeURIComponent(detailMatch[1]!);
      return handlers.patch
        ? handlers.patch(body, id)
        : ok({
            task: detailOf(rowOf({ task_id: id }), {
              version: 10,
              due_at: (body.dueAt as string | undefined) ?? null,
            }),
          });
    }
    if (transitionMatch && method === "POST") {
      const id = decodeURIComponent(transitionMatch[1]!);
      return handlers.transition
        ? handlers.transition(body, id)
        : ok({
            task: detailOf(rowOf({ task_id: id }), {
              version: 10,
              lifecycle_state: body.toState as TaskRow["lifecycle_state"],
            }),
          });
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return {
    calls,
    detailGets: (taskId = TASK_ID) =>
      calls.filter((call) => call.method === "GET" && call.path === `/api/tasks/${taskId}`),
    of: (method: string, suffix: string) =>
      calls.filter((call) => call.method === method && call.path.endsWith(suffix)),
  };
}

interface Handles {
  readonly onSelectTask: ReturnType<typeof vi.fn<WorkPerspectivesProps["onSelectTask"]>>;
  readonly onOpen: ReturnType<typeof vi.fn<WorkPerspectivesProps["onOpen"]>>;
  readonly onTaskMutationConfirmed: ReturnType<
    typeof vi.fn<NonNullable<WorkPerspectivesProps["onTaskMutationConfirmed"]>>
  >;
}

function renderPerspective(
  perspective: WorkPerspectivesProps["perspective"],
  rows: readonly TaskRow[],
  props: Partial<WorkPerspectivesProps> = {},
): Handles {
  const handles: Handles = {
    onSelectTask: vi.fn<WorkPerspectivesProps["onSelectTask"]>(),
    onOpen: vi.fn<WorkPerspectivesProps["onOpen"]>(),
    onTaskMutationConfirmed:
      vi.fn<NonNullable<WorkPerspectivesProps["onTaskMutationConfirmed"]>>(),
  };
  render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      <WorkPerspectives
        perspective={perspective}
        rows={rows}
        commitments={false}
        selectedTaskIds={[]}
        onSelectTask={handles.onSelectTask}
        onOpen={handles.onOpen}
        onTaskMutationConfirmed={handles.onTaskMutationConfirmed}
        {...props}
      />
    </TaskRuntimeProvider>,
  );
  return handles;
}

function board(): HTMLElement {
  return screen.getByRole("region", { name: "Task lifecycle board" });
}

function columnNames(): string[] {
  return within(board())
    .getAllByRole("heading", { level: 2 })
    .map((heading) => (heading.textContent ?? "").replace(/\s*\(\d+\)\s*$/, "").trim());
}

function cardFor(title: string): HTMLElement {
  const card = screen
    .getAllByTestId("task-board-card")
    .find((candidate) => candidate.textContent?.includes(title));
  if (!card) throw new Error(`no board card for ${title}`);
  return card;
}

describe("WorkPerspectives — Board", () => {
  it("stands exactly four permanent active columns and gives terminal Tasks none of them", async () => {
    /*
      A board is a picture of work in hand. Permanent Completed and Cancelled
      columns turned it into an archive the Principal had to read past on every
      visit, and the Completed Work view already answers that question — so
      terminal Tasks leave the board rather than piling up at the end of it.
    */
    stubFetch();
    renderPerspective("board", [
      rowOf({ task_id: "tsk_aaaaaaaa11111111", title: "Still open", lifecycle_state: "open" }),
      rowOf({ task_id: "tsk_bbbbbbbb22222222", title: "Under way", lifecycle_state: "in_progress" }),
      rowOf({ task_id: "tsk_cccccccc33333333", title: "Held up", lifecycle_state: "waiting" }),
      rowOf({ task_id: "tsk_dddddddd44444444", title: "Stuck fast", lifecycle_state: "blocked" }),
      rowOf({ task_id: "tsk_eeeeeeee55555555", title: "Finished work", lifecycle_state: "completed" }),
      rowOf({ task_id: "tsk_ffffffff66666666", title: "Withdrawn work", lifecycle_state: "cancelled" }),
    ]);

    expect(columnNames()).toEqual(["Open", "In progress", "Waiting", "Blocked"]);
    expect(screen.getAllByTestId("task-board-card")).toHaveLength(4);
    expect(board().textContent).not.toContain("Finished work");
    expect(board().textContent).not.toContain("Withdrawn work");
    // No "done" column was invented to hold them either.
    expect(columnNames()).not.toContain("Closed");
    expect(columnNames()).not.toContain("Cancelled");
  });

  it("keeps one link and a working selection checkbox on every card", async () => {
    stubFetch();
    const handles = renderPerspective("board", [rowOf()]);

    const card = cardFor(TITLE);
    // Singular by contract: Work resolves the card by its one link.
    expect(card.querySelectorAll("a[href]")).toHaveLength(1);
    expect(card.getAttribute("data-work-item")).toBe(TASK_ID);

    await userEvent.click(within(card).getByRole("checkbox", { name: `Select ${TITLE}` }));
    expect(handles.onSelectTask).toHaveBeenCalledWith(TASK_ID);
    // Operating a control is neither selection nor open.
    expect(handles.onOpen).not.toHaveBeenCalled();
  });

  it("speaks product language only — no lifecycle tokens, priority codes or Task IDs", async () => {
    stubFetch();
    renderPerspective("board", [rowOf({ lifecycle_state: "in_progress", priority: "p1" })]);

    const text = board().textContent ?? "";
    expect(text).not.toMatch(/in_progress|lifecycle|\bp[1-4]\b/i);
    expect(text).not.toContain(TASK_ID);
    expect(columnNames()).toContain("In progress");
    expect(cardFor(TITLE).textContent).toContain("Critical");
  });

  it("reaches the canonical version before a Status write and never sends the projection's", async () => {
    /*
      The board projection carries a `version`, and it is not write authority: it
      is a read of some earlier moment. The card must therefore reach the
      canonical read before it writes and send that version — while staying
      operable before it, because hydrating every card on mount would cost one
      detail read per card for a board the user may never touch.
    */
    const stub = stubFetch();
    renderPerspective("board", [rowOf()]);

    const status = within(cardFor(TITLE)).getByRole("combobox");
    expect(status).toHaveProperty("disabled", false);
    // Nothing has been read for this Task yet.
    expect(stub.detailGets()).toHaveLength(0);

    await userEvent.selectOptions(status, "waiting");
    await waitFor(() => expect(stub.of("POST", "/transition")).toHaveLength(1));

    expect(stub.detailGets()).toHaveLength(1);
    const sent = stub.of("POST", "/transition")[0]!.body;
    expect(sent.expectedVersion).toBe(9);
    expect(sent.expectedVersion).not.toBe(rowOf().version);
  });

  it("shows the Status move optimistically and rolls it back when the write is definitively refused", async () => {
    const held = gate();
    stubFetch({
      transition: async () => {
        await held.wait;
        return new Response(JSON.stringify({ error: { message: "no", code: "invalid" } }), {
          status: 422,
          headers: { "content-type": "application/json" },
        });
      },
    });
    renderPerspective("board", [rowOf({ lifecycle_state: "open" })]);

    const status = within(cardFor(TITLE)).getByRole("combobox");
    await userEvent.selectOptions(status, "blocked");

    // The move is shown before the server has answered.
    await waitFor(() => expect(status).toHaveProperty("value", "blocked"));
    expect(cardFor(TITLE).getAttribute("aria-busy")).toBe("true");

    await act(async () => {
      held.release();
      await Promise.resolve();
    });

    // Refused definitively: the card goes back to what is true, and stays put.
    await waitFor(() => expect(status).toHaveProperty("value", "open"));
    expect(cardFor(TITLE)).toBeTruthy();
    expect(cardFor(TITLE).getAttribute("aria-busy")).toBeNull();
  });

  it("puts a version conflict on the card it belongs to, with a way out", async () => {
    const titles: Record<string, string> = {
      tsk_aaaaaaaa11111111: "The one written to",
      tsk_bbbbbbbb22222222: "The untouched neighbour",
    };
    stubFetch({
      detail: (id) => ok({ task: detailOf(rowOf({ task_id: id, title: titles[id] })) }),
      transition: () =>
        new Response(
          JSON.stringify({
            error: { message: "version conflict", code: "conflict" },
            current: {
              ...detailOf(rowOf({ task_id: "tsk_aaaaaaaa11111111", title: "The one written to" })),
              version: 11,
              lifecycle_state: "waiting",
            },
          }),
          { status: 409, headers: { "content-type": "application/json" } },
        ),
    });
    renderPerspective("board", [
      rowOf({ task_id: "tsk_aaaaaaaa11111111", title: "The one written to" }),
      rowOf({ task_id: "tsk_bbbbbbbb22222222", title: "The untouched neighbour" }),
    ]);

    const subject = cardFor("The one written to");
    await userEvent.selectOptions(within(subject).getByRole("combobox"), "blocked");

    const panel = await screen.findByTestId("task-board-card-conflict");
    // On this card, not loose on the board and not on its neighbour.
    expect(cardFor("The one written to").contains(panel)).toBe(true);
    expect(cardFor("The untouched neighbour").contains(panel)).toBe(false);
    expect(screen.getAllByTestId("task-board-card-conflict")).toHaveLength(1);
    expect(screen.getByTestId("task-board-card-conflict-reapply")).toBeTruthy();
    expect(screen.getByTestId("task-board-card-conflict-dismiss")).toBeTruthy();
  });

  it("issues no detail read at all when a board of many cards mounts", async () => {
    /*
      One canonical read per card at mount is a read storm the Principal pays for
      on a board they may only be glancing at. The binder hydrates on demand, and
      this is the guard that keeps it that way.
    */
    const stub = stubFetch();
    const many = Array.from({ length: 24 }, (_, index) =>
      rowOf({
        task_id: `tsk_${String(index).padStart(8, "0")}11111111`,
        title: `Card number ${index}`,
        lifecycle_state: (["open", "in_progress", "waiting", "blocked"] as const)[index % 4],
      }),
    );
    renderPerspective("board", many);

    expect(screen.getAllByTestId("task-board-card")).toHaveLength(24);
    await act(async () => {
      await Promise.resolve();
    });
    expect(stub.calls.filter((call) => call.method === "GET")).toHaveLength(0);
  });
});

/** A board whose page is re-read the way Work re-reads it: on a confirmed mutation. */
function ServerBackedBoard({ initial, onConfirm }: {
  readonly initial: readonly TaskRow[];
  readonly onConfirm: (rows: readonly TaskRow[], input: { taskId: string; kind: string }) => readonly TaskRow[];
}) {
  const [rows, setRows] = useState<readonly TaskRow[]>(initial);
  const confirmed = useCallback(
    (input: { taskId: string; kind: string }) => {
      setRows((current) => onConfirm(current, input));
    },
    [onConfirm],
  );
  return (
    <WorkPerspectives
      perspective="board"
      rows={rows}
      commitments={false}
      selectedTaskIds={[]}
      onSelectTask={() => undefined}
      onOpen={() => undefined}
      onTaskMutationConfirmed={confirmed}
    />
  );
}

describe("WorkPerspectives — Board closure", () => {
  it("removes the card only once the terminal mutation is confirmed", async () => {
    const held = gate();
    stubFetch({
      transition: async (body) => {
        await held.wait;
        return ok({
          task: detailOf(rowOf(), { version: 10, lifecycle_state: body.toState as TaskRow["lifecycle_state"] }),
        });
      },
    });
    render(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        <ServerBackedBoard
          initial={[rowOf()]}
          /* Terminal Tasks are not on the board, so a confirmed close drops it. */
          onConfirm={(rows, input) =>
            input.kind === "close" ? rows.filter((row) => row.task_id !== input.taskId) : rows
          }
        />
      </TaskRuntimeProvider>,
    );

    await userEvent.click(within(cardFor(TITLE)).getByRole("button", { name: "Close Task" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm Closed" }));

    // Dispatched, unanswered: the card is still there. Nothing is hidden on hope.
    expect(cardFor(TITLE)).toBeTruthy();

    await act(async () => {
      held.release();
      await Promise.resolve();
    });

    await waitFor(() => expect(screen.queryAllByTestId("task-board-card")).toHaveLength(0));
  });
});

describe("WorkPerspectives — Calendar", () => {
  const DATED = rowOf({ due_at: iso(3), scheduled_at: iso(5), deferred_until: iso(7) });

  function markers(): HTMLElement[] {
    return Array.from(document.querySelectorAll<HTMLElement>("li[data-work-item]"));
  }

  it("names each dated field in the language of the field, and keeps one marker per date", async () => {
    stubFetch();
    renderPerspective("calendar", [DATED]);

    const list = markers();
    expect(list).toHaveLength(3);
    // Chronological, one per date, each still carrying its Task identity.
    expect(list.map((item) => item.querySelector("time")?.getAttribute("datetime"))).toEqual([
      DATED.due_at,
      DATED.scheduled_at,
      DATED.deferred_until,
    ]);
    expect(list.every((item) => item.getAttribute("data-work-item") === TASK_ID)).toBe(true);
    expect(list.every((item) => item.querySelectorAll("a[href]").length === 1)).toBe(true);

    const text = screen.getByLabelText("Work calendar", { selector: "section" }).textContent ?? "";
    expect(text).toContain("Planned for");
    expect(text).toContain("Snoozed until");
    // The old vocabulary is gone from all three.
    expect(text).not.toContain("Deadline");
    expect(text).not.toContain("Planned work");
    expect(text).not.toContain("Available after");
    expect(text).not.toContain(TASK_ID);
    expect(text).not.toMatch(/\bp[1-4]\b|open|in_progress/);
  });

  it("offers Due editing on the Due marker alone", async () => {
    stubFetch();
    renderPerspective("calendar", [DATED]);

    const editable = markers().filter(
      (item) => within(item).queryByRole("group", { name: `Change due date for ${TITLE}` }) !== null,
    );
    expect(editable).toHaveLength(1);
    expect(editable[0]!.querySelector("time")?.getAttribute("datetime")).toBe(DATED.due_at);
    // Planned-for and Snoozed-until answer other questions and stay read-only.
    expect(markers()[1]!.querySelectorAll("button")).toHaveLength(0);
    expect(markers()[2]!.querySelectorAll("button")).toHaveLength(0);
  });

  it("sends due fields alone, leaving planned work and the snooze untouched", async () => {
    /*
      Due, Planned for and Snoozed until are three separate answers. Moving a
      deadline from the calendar must never quietly reschedule the work or re-arm
      the snooze — so the request that carries it names only due fields.
    */
    const stub = stubFetch();
    renderPerspective("calendar", [DATED]);

    await userEvent.click(screen.getByRole("button", { name: /^Due, / }));
    await userEvent.click(screen.getByRole("button", { name: "Today" }));

    await waitFor(() => expect(stub.of("PATCH", TASK_ID)).toHaveLength(1));
    const sent = stub.of("PATCH", TASK_ID)[0]!.body;
    expect(Object.keys(sent).toSorted()).toEqual(
      ["dueAt", "expectedVersion", "idempotencyKey"].toSorted(),
    );
    expect(sent).not.toHaveProperty("scheduledAt");
    expect(sent).not.toHaveProperty("deferredUntil");
    expect(sent.expectedVersion).toBe(9);

    // Still exactly one Due marker, and the other two are where they were.
    await waitFor(() => {
      const list = markers();
      expect(list).toHaveLength(3);
      expect(list[1]!.querySelector("time")?.getAttribute("datetime")).toBe(DATED.scheduled_at);
      expect(list[2]!.querySelector("time")?.getAttribute("datetime")).toBe(DATED.deferred_until);
    });
    expect(
      markers().filter(
        (item) => within(item).queryByRole("group", { name: `Change due date for ${TITLE}` }) !== null,
      ),
    ).toHaveLength(1);
  });

  it("issues no detail read when a calendar of many markers mounts", async () => {
    const stub = stubFetch();
    renderPerspective(
      "calendar",
      Array.from({ length: 20 }, (_, index) =>
        rowOf({
          task_id: `tsk_${String(index).padStart(8, "0")}11111111`,
          title: `Dated item ${index}`,
          due_at: iso(index + 1),
        }),
      ),
    );

    expect(markers()).toHaveLength(20);
    await act(async () => {
      await Promise.resolve();
    });
    expect(stub.calls.filter((call) => call.method === "GET")).toHaveLength(0);
  });
});
