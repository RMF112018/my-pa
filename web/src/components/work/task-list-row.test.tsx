import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaskListRow, type TaskListRowProps } from "@/components/work/task-list-row";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import type { TaskDetail, TaskRow } from "@/contracts/work";
import { formatTaskPriority, type TaskCivilClock } from "@/lib/tasks/presentation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TASK_ID = "tsk_aaaaaaaa11111111";
const TITLE = "Coordinate the quarterly review";
const CLOCK: TaskCivilClock = { timezone: "UTC", workDate: "2026-09-12" };

/** A Work list projection: display seed only, deliberately carrying no version. */
const LIST_ROW: TaskRow = {
  task_id: TASK_ID,
  title: TITLE,
  lifecycle_state: "in_progress",
  priority: "p1",
  due_at: "2026-09-13T12:00:00Z",
  scheduled_at: "2026-09-14T12:00:00Z",
  deferred_until: "2026-09-15T12:00:00Z",
  archived_at: null,
  created_at: "2026-08-20T12:00:00Z",
  updated_at: "2026-08-22T12:00:00Z",
  // Deliberately present and deliberately stale: a list projection may carry a
  // version, and the row must still not treat it as write authority.
  version: 3,
};

const CANONICAL: TaskDetail = {
  ...LIST_ROW,
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

function ok(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

/*
  jsdom does not implement one browser behaviour these tests turn on: focus
  leaves an element at the moment it is disabled. Without it, a test can only
  reach states a browser never produces — and a green test that depends on such
  a state is worse than no test, because it reports a mechanism as working when
  in a browser it does nothing at all.

  React applies `disabled` through `setAttribute` while committing, so that is
  where the blur belongs. The element is blurred just before it is disabled,
  which leaves exactly the state a browser leaves: focus on the body, and the
  control it let go of disabled.
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

function gate(): { wait: Promise<void>; release: () => void } {
  let release!: () => void;
  const wait = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { wait, release };
}

/** Every Task route answered from the canonical Task; nothing else is expected. */
function stubFetch(handlers: {
  detail?: () => Response | Promise<Response>;
  transition?: (body: Record<string, unknown>) => Response | Promise<Response>;
  patch?: (body: Record<string, unknown>) => Response | Promise<Response>;
} = {}) {
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    const base = `/api/tasks/${TASK_ID}`;
    if (path === base && method === "GET") {
      return handlers.detail ? handlers.detail() : ok({ task: CANONICAL });
    }
    if (path === base && method === "PATCH") {
      return handlers.patch
        ? handlers.patch(body)
        : ok({ task: { ...CANONICAL, version: 5, due_at: (body.dueAt as string) ?? null } });
    }
    if (path === `${base}/transition` && method === "POST") {
      return handlers.transition
        ? handlers.transition(body)
        : ok({ task: { ...CANONICAL, version: 5, lifecycle_state: body.toState } });
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

interface Handles {
  readonly onSelect: ReturnType<typeof vi.fn<TaskListRowProps["onSelect"]>>;
  readonly onOpen: ReturnType<typeof vi.fn<TaskListRowProps["onOpen"]>>;
  readonly onOpenActivity: ReturnType<typeof vi.fn<NonNullable<TaskListRowProps["onOpenActivity"]>>>;
  readonly onMutationConfirmed: ReturnType<
    typeof vi.fn<NonNullable<TaskListRowProps["onMutationConfirmed"]>>
  >;
}

function renderRow(props: Partial<TaskListRowProps> = {}): Handles {
  const handles: Handles = {
    onSelect: vi.fn<TaskListRowProps["onSelect"]>(),
    onOpen: vi.fn<TaskListRowProps["onOpen"]>(),
    onOpenActivity: vi.fn<NonNullable<TaskListRowProps["onOpenActivity"]>>(),
    onMutationConfirmed: vi.fn<NonNullable<TaskListRowProps["onMutationConfirmed"]>>(),
  };
  render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      <TaskListRow
        task={LIST_ROW}
        selected={false}
        clock={CLOCK}
        onSelect={handles.onSelect}
        onOpen={handles.onOpen}
        onOpenActivity={handles.onOpenActivity}
        onMutationConfirmed={handles.onMutationConfirmed}
        {...props}
      />
    </TaskRuntimeProvider>,
  );
  return handles;
}

function row(): HTMLElement {
  return screen.getByTestId("task-list-row");
}

/** The row hydrates canonically before any versioned control unlocks. */
async function hydrated(): Promise<HTMLElement> {
  await waitFor(() => {
    expect(screen.getByTestId("task-close-trigger")).not.toHaveProperty("disabled", true);
  });
  return row();
}

describe("TaskListRow", () => {
  it("speaks human Status only — no lifecycle tokens, no raw priority enums", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    const text = row().textContent ?? "";
    expect(text).not.toMatch(/in_progress|completed|cancelled|lifecycle|\bp[1-4]\b/i);
    expect(within(row()).getByRole("combobox")).toHaveProperty("value", "in_progress");
    expect(text).toContain("In progress");
    expect(text).toContain("Critical");
  });

  it("states Due in human words and shows no planning or bookkeeping timestamps", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    const text = row().textContent ?? "";
    expect(screen.getByRole("button", { name: "Due, Tomorrow" })).toBeTruthy();
    expect(text).not.toContain("Updated");
    expect(text).not.toContain("Planned work");
    expect(text).not.toContain("Available after");
    expect(text).not.toContain("2026-09-14");
  });

  it("never renders the Task ID as visible text", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    expect(row().textContent ?? "").not.toContain(TASK_ID);
    expect(screen.queryByText(TASK_ID)).toBeNull();
  });

  it("offers a Comment affordance that opens the Activity surface", async () => {
    stubFetch();
    const handles = renderRow();
    await hydrated();

    const comment = screen.getByRole("button", { name: `Add comment to ${TITLE}` });
    await userEvent.click(comment);

    expect(handles.onOpenActivity).toHaveBeenCalledTimes(1);
    expect(handles.onOpenActivity).toHaveBeenCalledWith(TASK_ID, TITLE, comment);
    expect(handles.onOpen).not.toHaveBeenCalled();
  });

  it("closes through a confirmation that asks for no authored text", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    await userEvent.click(screen.getByRole("button", { name: "Close Task" }));
    const confirmation = screen.getByTestId("task-close-confirmation");
    expect(confirmation.getAttribute("role")).toBe("alertdialog");
    expect(within(confirmation).queryByRole("textbox")).toBeNull();
    expect(confirmation.querySelectorAll("input, textarea").length).toBe(0);
    expect(within(confirmation).getByRole("button", { name: "Confirm Closed" })).toBeTruthy();
  });

  it("keeps Cancel under More, at lower prominence than Close", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    expect(screen.queryByTestId("task-cancel-trigger")).toBeNull();

    const more = screen.getByRole("button", { name: `More actions for ${TITLE}` });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(more);

    const cancel = screen.getByTestId("task-cancel-trigger");
    const close = screen.getByTestId("task-close-trigger");
    expect(more.getAttribute("aria-expanded")).toBe("true");
    expect(cancel.textContent).toContain("Cancel Task");
    expect(close.getAttribute("data-prominence")).toBe("primary");
    expect(cancel.getAttribute("data-prominence")).toBe("secondary");
  });

  it("selects from the checkbox without opening detail", async () => {
    stubFetch();
    const handles = renderRow();
    await hydrated();

    await userEvent.click(screen.getByLabelText(`Select ${TITLE}`));
    expect(handles.onSelect).toHaveBeenCalledWith(TASK_ID);
    expect(handles.onOpen).not.toHaveBeenCalled();
    expect(handles.onOpenActivity).not.toHaveBeenCalled();
  });

  it("keeps Status, Due, Comment and Close out of selection and detail", async () => {
    stubFetch();
    const handles = renderRow();
    await hydrated();

    await userEvent.selectOptions(within(row()).getByRole("combobox"), "blocked");
    await userEvent.click(screen.getByRole("button", { name: "Due, Tomorrow" }));
    await userEvent.click(screen.getByRole("button", { name: `Add comment to ${TITLE}` }));
    await userEvent.click(screen.getByRole("button", { name: "Close Task" }));

    expect(handles.onOpen).not.toHaveBeenCalled();
    expect(handles.onSelect).not.toHaveBeenCalled();
  });

  it("opens detail from the title and hands over its own element as the trigger", async () => {
    stubFetch();
    const handles = renderRow();
    await hydrated();

    const title = screen.getByTestId("task-list-row-title");
    await userEvent.click(title);

    expect(handles.onOpen).toHaveBeenCalledTimes(1);
    expect(handles.onOpen).toHaveBeenCalledWith("task", TASK_ID, TITLE, title);
    expect(handles.onSelect).not.toHaveBeenCalled();
  });

  it("canonical-hydrates at the first write instead of trusting the row's own version", async () => {
    /*
      The list projection carries a `version`, and it is not write authority: it
      is a read of some earlier moment, so between the list load and this click
      the Task may have moved. The row must therefore reach the canonical read
      before it writes, and send that version — while still leaving the control
      operable, because locking every row until it hydrated would mean one detail
      read per row for a list the user may never touch.
    */
    const expectedVersions: unknown[] = [];
    stubFetch({
      detail: async () => ok({ task: { ...CANONICAL, version: 9 } }),
      transition: async (body) => {
        expectedVersions.push((body as { expectedVersion?: unknown }).expectedVersion);
        return ok({ task: { ...CANONICAL, version: 10, lifecycle_state: "waiting" } });
      },
    });
    renderRow();

    // Operable before any hydration has happened.
    const status = within(row()).getByRole("combobox");
    expect(status).toHaveProperty("disabled", false);

    await userEvent.selectOptions(status, "waiting");

    await waitFor(() => expect(expectedVersions.length).toBe(1));
    // The canonical version, never the projection's stale one.
    expect(expectedVersions).toEqual([9]);
    expect(expectedVersions).not.toContain(LIST_ROW.version);
  });

  it("names every control in the context of this Task", async () => {
    stubFetch();
    renderRow();
    await hydrated();

    expect(screen.getByLabelText(`Select ${TITLE}`)).toBeTruthy();
    expect(screen.getByRole("group", { name: `Change status for ${TITLE}` })).toBeTruthy();
    expect(screen.getByRole("group", { name: `Change due date for ${TITLE}` })).toBeTruthy();
    expect(screen.getByRole("button", { name: `Add comment to ${TITLE}` })).toBeTruthy();
    expect(screen.getByRole("group", { name: `Close ${TITLE}` })).toBeTruthy();
    expect(screen.getByRole("button", { name: `More actions for ${TITLE}` })).toBeTruthy();
  });

  it("marks the row busy while a write is in flight", async () => {
    const transition = gate();
    stubFetch({
      transition: async (body) => {
        await transition.wait;
        return ok({ task: { ...CANONICAL, version: 5, lifecycle_state: body.toState } });
      },
    });
    renderRow();
    await hydrated();

    await userEvent.selectOptions(within(row()).getByRole("combobox"), "blocked");
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBe("true"));

    transition.release();
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());
  });

  it("locks the row from the activation, not from the write", async () => {
    /*
      A list row reaches the canonical Task on demand, so an activation can spend
      a real round trip before anything is sent. While that read was in flight the
      controls stayed live, so a second activation got through — and the
      coordinator refused it without a word, leaving the user pressing a control
      twice and told nothing either time.
    */
    const detail = gate();
    stubFetch({
      detail: async () => {
        await detail.wait;
        return ok({ task: CANONICAL });
      },
    });
    renderRow();
    // Close is offered immediately; hydration happens at the first write.
    await userEvent.click(await screen.findByTestId("task-close-trigger"));
    await userEvent.click(await screen.findByTestId("task-close-confirm"));

    // The canonical read has not answered yet, and the row is already busy.
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBe("true"));

    detail.release();
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());
  });

  it("unlocks the row when the canonical read it needs cannot be had", async () => {
    /*
      The row locks from the activation, before the canonical Task it needs has
      been read. If that read fails there is no write to settle and nothing else
      will clear the lock — so the unlock on that path is the only thing standing
      between a refused read and a row whose every control is disabled for good,
      with no way back short of a reload.
    */
    stubFetch({
      detail: () =>
        new Response(JSON.stringify({ error: { message: "unavailable", code: "unavailable" } }), {
          status: 503,
          headers: { "content-type": "application/json" },
        }),
    });
    renderRow();

    await userEvent.click(await screen.findByTestId("task-close-trigger"));
    await userEvent.click(await screen.findByTestId("task-close-confirm"));

    // The read is refused, and the row comes back under the user's hand.
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());
    await waitFor(() =>
      expect(screen.getByTestId("task-close-trigger")).not.toHaveProperty("disabled", true),
    );
  });

  it("gives focus back to the control when a write is refused", async () => {
    /*
      A keyboard user changes Status. The control is disabled while the write
      runs, and a browser lets go of a focused element the instant that happens.
      If the write is then refused the Task does not move, the list does not
      change, and nothing else will put the user back — they are left on the
      document body with the control they were operating right in front of them.
    */
    const restore = emulateDisableBlur();
    try {
      const refusal = gate();
      stubFetch({
        transition: async () => {
          await refusal.wait;
          return new Response(JSON.stringify({ error: { message: "nope", code: "invalid" } }), {
            status: 400,
            headers: { "content-type": "application/json" },
          });
        },
      });
      renderRow();
      await hydrated();

      const status = within(row()).getByRole("combobox");
      status.focus();
      await userEvent.selectOptions(status, "blocked");

      // The browser has let go of the control, exactly as it does.
      await waitFor(() => expect(row().getAttribute("aria-busy")).toBe("true"));
      expect(document.activeElement).toBe(document.body);

      refusal.release();
      await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());
      await act(async () => {
        await new Promise<void>((resolve) => {
          requestAnimationFrame(() => resolve());
        });
      });

      // The refusal left the Task where it was, and the user where they were.
      expect(document.activeElement).toBe(status);
    } finally {
      restore();
    }
  });

  it("gives focus back to the control when a conflict is stood down", async () => {
    /*
      Standing a conflict down unmounts the panel the user is standing in, so
      the act of answering the question costs them their place a second time.
      They are returned to the control the conflict was about.
    */
    const restore = emulateDisableBlur();
    try {
      stubFetch({
        transition: () =>
          new Response(
            JSON.stringify({
              error: { message: "version conflict", code: "conflict" },
              current: { ...CANONICAL, version: 9, lifecycle_state: "blocked" },
            }),
            { status: 409, headers: { "content-type": "application/json" } },
          ),
      });
      renderRow();
      await hydrated();

      const status = within(row()).getByRole("combobox");
      status.focus();
      await userEvent.selectOptions(status, "blocked");

      const dismiss = await screen.findByTestId("task-list-row-conflict-dismiss");
      await userEvent.click(dismiss);
      await waitFor(() => expect(screen.queryByTestId("task-list-row-conflict")).toBeNull());
      await act(async () => {
        await new Promise<void>((resolve) => {
          requestAnimationFrame(() => resolve());
        });
      });

      expect(document.activeElement).not.toBe(document.body);
      expect(document.activeElement).toBe(within(row()).getByRole("combobox"));
    } finally {
      restore();
    }
  });

  it("gives focus back to the control when a conflict is recovered", async () => {
    /*
      The same on the other answer: a successful reapply unmounts the panel, and
      when the Task stays in this filter there is no list change to catch the
      user. They are returned to the control they operated.
    */
    const restore = emulateDisableBlur();
    try {
      let attempts = 0;
      stubFetch({
        transition: (body) => {
          attempts += 1;
          if (attempts === 1) {
            return new Response(
              JSON.stringify({
                error: { message: "version conflict", code: "conflict" },
                current: { ...CANONICAL, version: 9, lifecycle_state: "in_progress" },
              }),
              { status: 409, headers: { "content-type": "application/json" } },
            );
          }
          return ok({ task: { ...CANONICAL, version: 10, lifecycle_state: body.toState } });
        },
      });
      renderRow();
      await hydrated();

      const status = within(row()).getByRole("combobox");
      status.focus();
      await userEvent.selectOptions(status, "blocked");

      await userEvent.click(await screen.findByTestId("task-list-row-conflict-reapply"));
      await waitFor(() => expect(attempts).toBe(2));
      await waitFor(() => expect(screen.queryByTestId("task-list-row-conflict")).toBeNull());
      await act(async () => {
        await new Promise<void>((resolve) => {
          requestAnimationFrame(() => resolve());
        });
      });

      expect(document.activeElement).not.toBe(document.body);
      expect(row().contains(document.activeElement)).toBe(true);
    } finally {
      restore();
    }
  });

  it("gives focus back after a Due change, whose own control closes under the user", async () => {
    /*
      Due is chosen from a popover, and choosing dismisses it — so the button the
      user pressed is gone before the write has even settled. Returning focus to
      it returns them nothing: `focus()` on a node that has left the document
      does nothing at all, silently, and leaves them on the body at the top of
      the page. This is the common case, not an edge: it happens on the success
      path, every time Due is changed from the list.
    */
    const restore = emulateDisableBlur();
    try {
      stubFetch();
      renderRow();
      await hydrated();

      const trigger = screen.getByRole("button", { name: "Due, Tomorrow" });
      trigger.focus();
      await userEvent.click(trigger);
      const choice = await screen.findByRole("button", { name: "Today" });
      choice.focus();
      await userEvent.click(choice);

      // The chosen button is gone with its popover, and the write has settled.
      expect(choice.isConnected).toBe(false);
      await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());

      // The user is back on the Due affordance itself, not stranded.
      expect(document.activeElement).not.toBe(document.body);
      expect(row().contains(document.activeElement)).toBe(true);
      expect(document.activeElement?.getAttribute("aria-label")).toContain("Due");
    } finally {
      restore();
    }
  });

  it("gives focus back after a Due change that is refused", async () => {
    /*
      The same, with nothing to reconcile afterwards: a refused Due write moves
      no Task and changes no list, so if the return does not place focus, nothing
      else will.
    */
    const restore = emulateDisableBlur();
    try {
      stubFetch({
        patch: () =>
          new Response(JSON.stringify({ error: { message: "nope", code: "invalid" } }), {
            status: 400,
            headers: { "content-type": "application/json" },
          }),
      });
      renderRow();
      await hydrated();

      const trigger = screen.getByRole("button", { name: "Due, Tomorrow" });
      trigger.focus();
      await userEvent.click(trigger);
      const choice = await screen.findByRole("button", { name: "Today" });
      choice.focus();
      await userEvent.click(choice);

      await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());

      expect(document.activeElement).not.toBe(document.body);
      expect(row().contains(document.activeElement)).toBe(true);
    } finally {
      restore();
    }
  });

  it("does not pull a user back into the row if they moved on while it ran", async () => {
    /*
      The row holds the control the user operated so it can give it back. It
      must only do so if focus is still lying on the body: a user who
      moved on to something else during the write chose where they are, and
      yanking them back into a row they have finished with is worse than never
      having held the element at all.
    */
    const refusal = gate();
    stubFetch({
      transition: async () => {
        await refusal.wait;
        return new Response(JSON.stringify({ error: { message: "nope", code: "invalid" } }), {
          status: 400,
          headers: { "content-type": "application/json" },
        });
      },
    });
    renderRow();
    await hydrated();

    const status = within(row()).getByRole("combobox");
    status.focus();
    await userEvent.selectOptions(status, "blocked");
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBe("true"));

    // The user moves on somewhere else entirely while the write runs.
    const elsewhere = document.createElement("button");
    elsewhere.textContent = "Somewhere else";
    document.body.append(elsewhere);
    elsewhere.focus();
    expect(document.activeElement).toBe(elsewhere);

    refusal.release();
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());
    /*
      The return is deferred a frame, so the frame has to run before this can be
      believed. Asserting sooner cannot observe the steal it rules out, which is
      what made an earlier version of this test pass with its guard deleted.
    */
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // They are left where they chose to be.
    expect(document.activeElement).toBe(elsewhere);
    elsewhere.remove();
  });

  it("puts the user on the conflict question when a write is refused for version", async () => {
    /*
      A conflict is a question put to the user, and the write that raised it has
      already cost them their place: disabling the control they operated drops
      focus to the document body. The control stays disabled while the conflict
      stands, so handing focus back to it would hand them nothing. Without this
      they are left at the top of the document, tabbing down to a panel that
      appeared without them.
    */
    const restore = emulateDisableBlur();
    try {
    stubFetch({
      transition: () =>
        new Response(
          JSON.stringify({
            error: { message: "version conflict", code: "conflict" },
            current: { ...CANONICAL, version: 9, lifecycle_state: "blocked" },
          }),
          { status: 409, headers: { "content-type": "application/json" } },
        ),
    });
    renderRow();
    await hydrated();

    const status = within(row()).getByRole("combobox");
    status.focus();
    await userEvent.selectOptions(status, "blocked");
    // The browser has let go of the control, which is how the user lost focus.
    expect(document.activeElement).toBe(document.body);

    await screen.findByTestId("task-list-row-conflict");
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(screen.getByTestId("task-list-row-conflict-reapply"));
    } finally {
      restore();
    }
  });

  it("reconciles the list when a conflict is recovered, not only when it is avoided", async () => {
    /*
      A conflict is not a settled attempt: the intent is still the user's, and
      the reapply they are offered is that same attempt continued. If the awaited
      intent is dropped when the conflict arrives, the retry confirms and nobody
      is told — so Work never re-reads, and a Task the user has just moved out of
      this filter sits there looking as though the change never happened.
    */
    let attempts = 0;
    stubFetch({
      transition: (body) => {
        attempts += 1;
        if (attempts === 1) {
          return new Response(
            JSON.stringify({
              error: { message: "version conflict", code: "conflict" },
              current: { ...CANONICAL, version: 9, lifecycle_state: "in_progress" },
            }),
            { status: 409, headers: { "content-type": "application/json" } },
          );
        }
        return ok({ task: { ...CANONICAL, version: 10, lifecycle_state: body.toState } });
      },
    });
    const handles = renderRow();
    await hydrated();

    await userEvent.selectOptions(within(row()).getByRole("combobox"), "blocked");
    await screen.findByTestId("task-list-row-conflict");
    expect(handles.onMutationConfirmed).not.toHaveBeenCalled();

    await userEvent.click(screen.getByTestId("task-list-row-conflict-reapply"));
    await waitFor(() => expect(attempts).toBe(2));

    // The recovered write is reported, so Work can re-read the filter.
    await waitFor(() => expect(handles.onMutationConfirmed).toHaveBeenCalled());
    expect(handles.onMutationConfirmed.mock.calls[0][0]).toMatchObject({ taskId: TASK_ID, kind: "status" });
  });

  it("does not take a user to the conflict question if they moved on", async () => {
    /*
      The conflict is worth answering, but not worth interrupting for. A user who
      moved on to something else while the write ran chose where they are, and
      the panel waits in the row for them rather than pulling them to it.
    */
    const restore = emulateDisableBlur();
    try {
      const refusal = gate();
      stubFetch({
        transition: async () => {
          await refusal.wait;
          return new Response(
            JSON.stringify({
              error: { message: "version conflict", code: "conflict" },
              current: { ...CANONICAL, version: 9, lifecycle_state: "blocked" },
            }),
            { status: 409, headers: { "content-type": "application/json" } },
          );
        },
      });
      renderRow();
      await hydrated();

      const status = within(row()).getByRole("combobox");
      status.focus();
      await userEvent.selectOptions(status, "blocked");
      await waitFor(() => expect(row().getAttribute("aria-busy")).toBe("true"));

      // The user goes elsewhere while the write is still running.
      const elsewhere = document.createElement("button");
      elsewhere.textContent = "Somewhere else";
      document.body.append(elsewhere);
      elsewhere.focus();

      refusal.release();
      await screen.findByTestId("task-list-row-conflict");
      await act(async () => {
        await new Promise<void>((resolve) => {
          requestAnimationFrame(() => resolve());
        });
      });

      // The question is there to answer; they were not dragged to it.
      expect(document.activeElement).toBe(elsewhere);
      elsewhere.remove();
    } finally {
      restore();
    }
  });

  it("offers no Close or Cancel on a Task that is already closed", async () => {
    /*
      A closed Task cannot be closed again. The row was offering a live Close —
      and, under More, Cancel — on every row of the Completed view, with a
      confirmation behind it that dispatched a second transition against a Task
      that had already had one. Task detail has always drawn this line.
    */
    const closed = { ...LIST_ROW, lifecycle_state: "completed" as const };
    stubFetch({ detail: () => ok({ task: { ...CANONICAL, lifecycle_state: "completed" } }) });
    renderRow({ task: closed });

    // The outcome is stated; the action is not offered.
    expect(await screen.findByTestId("task-list-row")).toBeTruthy();
    expect(row().textContent).toContain("Closed");
    expect(screen.queryByTestId("task-close-trigger")).toBeNull();

    /*
      Nor Cancel, nor the More that reveals it: leaving More behind meant a live
      disclosure announcing itself as expanded over an empty labelled group.
    */
    expect(screen.queryByTestId("task-list-row-more")).toBeNull();
    expect(screen.queryByRole("button", { name: /cancel task/i })).toBeNull();
    expect(screen.queryByRole("group", { name: `Close ${TITLE}` })).toBeNull();
  });

  it("gives focus back to the row when a confirmed Close empties the control", async () => {
    /*
      A Close that succeeds withdraws the very affordance it was made from: the
      Task becomes terminal, so the row stops offering to close it. The button
      the user confirmed with is gone, and so is everything else in that group —
      in a view that still lists the Task, nothing moves and no other surface is
      going to catch them. They are returned to the row itself.
    */
    const restore = emulateDisableBlur();
    try {
      stubFetch({
        transition: (body) => ok({ task: { ...CANONICAL, version: 5, lifecycle_state: body.toState } }),
        detail: () => ok({ task: CANONICAL }),
      });
      renderRow();
      await hydrated();

      const trigger = screen.getByTestId("task-close-trigger");
      trigger.focus();
      await userEvent.click(trigger);
      const confirm = screen.getByTestId("task-close-confirm");
      confirm.focus();
      await userEvent.click(confirm);

      // The Task is closed, so the row no longer offers to close it.
      await waitFor(() => expect(screen.queryByTestId("task-close-trigger")).toBeNull());
      await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());

      expect(document.activeElement).not.toBe(document.body);
      expect(row().contains(document.activeElement)).toBe(true);
    } finally {
      restore();
    }
  });

  it("follows the list it lives in when the Task changes elsewhere", async () => {
    /*
      A row is keyed by Task and never remounts while it stays listed, so a
      refreshed projection arrives as a new prop on a mounted row. Preferring the
      snapshot it first held froze it there: the Task could be closed from its own
      detail sheet, from a second tab, or by anyone else, and the row went on
      showing it as open — and, worse, went on offering to close it, because the
      gate that withholds that action reads the same frozen value.

      The projection drives what is shown. It still authorises nothing: the
      canonical read remains the only source of write authority.
    */
    stubFetch();
    const view = render(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        <TaskListRow task={LIST_ROW} selected={false} clock={CLOCK} onSelect={vi.fn()} onOpen={vi.fn()} />
      </TaskRuntimeProvider>,
    );
    await hydrated();
    expect(row().textContent).toContain("In progress");
    expect(row().textContent).toContain(TITLE);
    expect(screen.getByTestId("task-close-trigger")).toBeTruthy();

    // The same Task, closed somewhere else, comes back on the next list read.
    view.rerender(
      <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
        <TaskListRow
          task={{
            ...LIST_ROW,
            title: "Renamed somewhere else",
            priority: "p3",
            lifecycle_state: "completed",
            version: 7,
            updated_at: "2026-09-12T12:00:00Z",
          }}
          selected={false}
          clock={CLOCK}
          onSelect={vi.fn()}
          onOpen={vi.fn()}
        />
      </TaskRuntimeProvider>,
    );

    // The row says what is true now, and no longer offers to close it again.
    await waitFor(() => expect(row().textContent).toContain("Closed"));
    expect(screen.queryByTestId("task-close-trigger")).toBeNull();
    /*
      Including its name — which is not decoration: it is the row's link text and
      the accessible name of every control on it, so a stale one tells a screen
      reader the wrong Task.
    */
    expect(row().textContent).toContain("Renamed somewhere else");
    expect(row().textContent).not.toContain(TITLE);
    expect(screen.getByRole("link", { name: /Renamed somewhere else/ })).toBeTruthy();
    // Priority comes from the same base, and froze in the same way.
    expect(row().textContent).toContain(formatTaskPriority("p3"));
  });

  it("never shows a Task as closed on a response that carried no Task", async () => {
    /*
      Close and Cancel are pessimistic: the operation matrix requires a server
      Task before either terminal state may be shown. A response carrying no Task
      is not that — the write may have landed or may not, and saying "Closed" on
      the strength of a status code would be telling the user something nobody
      confirmed.

      The Task has to hydrate first, or the write is never dispatched at all and
      this proves nothing: an earlier version of this test starved the canonical
      read outright, which failed before the transition and quietly duplicated
      the hydration test next door. So the row hydrates, and only then is the
      confirming re-read starved — a transient failure there is enough.
    */
    let hydrations = 0;
    let transitions = 0;
    stubFetch({
      // Accepted, with no Task in the body.
      transition: () => {
        transitions += 1;
        return ok({});
      },
      // Hydrates once; the confirming re-read then comes back with nothing.
      detail: () => {
        hydrations += 1;
        return hydrations === 1 ? ok({ task: CANONICAL }) : ok({});
      },
    });
    const handles = renderRow();
    await hydrated();

    await userEvent.click(screen.getByTestId("task-close-trigger"));
    await userEvent.click(screen.getByTestId("task-close-confirm"));
    await waitFor(() => expect(row().getAttribute("aria-busy")).toBeNull());

    // The write really was sent — otherwise this says nothing about its answer.
    expect(transitions).toBe(1);

    // Not claimed as closed, and still offered — because nothing says it is.
    const status = within(row()).getByRole("combobox") as HTMLSelectElement;
    expect(status.value).toBe("in_progress");
    expect(screen.getByTestId("task-close-trigger")).toBeTruthy();
    /*
      And nothing downstream is told the Task moved. Reporting a confirmation
      here would send Work off to re-read a filter on the strength of a status
      code, and would speak success copy for a write nobody confirmed.
    */
    expect(handles.onMutationConfirmed).not.toHaveBeenCalled();
  });

  it("reports a confirmed mutation so Work can move the row", async () => {
    stubFetch();
    const handles = renderRow();
    await hydrated();

    await userEvent.selectOptions(within(row()).getByRole("combobox"), "blocked");

    await waitFor(() => {
      expect(handles.onMutationConfirmed).toHaveBeenCalledWith({ taskId: TASK_ID, kind: "status" });
    });
  });
});
