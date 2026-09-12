import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Workbench } from "@/components/work/workbench";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import { parseWorkUrlState } from "@/lib/api/work-url";
import { TASK_FRESHNESS_INTERVAL_MS } from "@/components/work/use-task-freshness";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  history.replaceState(null, "", "/");
});

function renderFromUrl() {
  return render(
    <TaskRuntimeProvider principalId="00000000-0000-4000-8000-000000000001" sessionEpoch="test">
      <Workbench initialState={parseWorkUrlState(Object.fromEntries(new URLSearchParams(location.search)))} />
    </TaskRuntimeProvider>,
  );
}

async function chooseWorkView(label: string) {
  await userEvent.click(screen.getByRole("button", { name: "Work views" }));
  await userEvent.click(await screen.findByRole("menuitem", { name: label }));
}

function listTaskGets(fetcher: ReturnType<typeof vi.fn<typeof fetch>>) {
  return fetcher.mock.calls.filter(([path, init]) => {
    const url = String(path);
    const method = (init?.method ?? "GET").toUpperCase();
    return method === "GET" && url.startsWith("/api/tasks?");
  });
}

describe("Work surface", () => {
  it("reserves the shell capture clearance below scrollable Work content", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } })));
    history.replaceState(null, "", "/work?view=today");
    renderFromUrl();
    await screen.findByText("No today tasks");
    expect(screen.getByRole("region", { name: "Work" }).className).toContain("pb-24");
    expect(screen.getByText("Tasks and commitments you are tracking.")).toBeTruthy();
    expect(screen.queryByText("Select Tasks for admitted bulk actions")).toBeNull();
    expect(screen.queryByText("Create task")).toBeNull();
    expect(screen.getByRole("button", { name: "New task" })).toBeTruthy();
    expect(screen.getByText("Filters")).toBeTruthy();
    expect(screen.getByLabelText("Archive")).toBeTruthy();
  });

  it("shows short loading copy while Work is reading", async () => {
    let resolveRead!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((next) => { resolveRead = next; })));
    history.replaceState(null, "", "/work?view=today");
    renderFromUrl();
    expect(screen.getByText("Loading work…")).toBeTruthy();
    await waitFor(() => expect(resolveRead).toEqual(expect.any(Function)));
    await act(async () => resolveRead(new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } })));
    await screen.findByText("No today tasks");
  });

  it("keeps compact selectors without a horizontal work-views carousel", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } })); vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=today");
    renderFromUrl();
    expect(await screen.findByText("No today tasks")).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "Work views" })).toBeNull();
    expect(screen.getByRole("region", { name: "Work" }).innerHTML).not.toMatch(/overflow-x-auto/);
    expect(screen.getByRole("button", { name: "Tasks" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Commitments" })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: "Work views" }));
    expect(Array.from(screen.getAllByRole("menuitem"), (item) => item.textContent)).toEqual([
      "Overdue", "Today", "Upcoming", "Unscheduled", "Waiting", "Blocked", "Recently updated", "All open", "Completed",
    ]);
    const path = String(fetcher.mock.calls[0]?.[0]);
    expect(path).toContain("/api/tasks?pageSize=50&workView=today&archived=exclude");
    expect(path).toMatch(/workDate=\d{4}-\d{2}-\d{2}/);
    expect(path).toContain("timezone=");
  });

  it("switches list, lifecycle board, and calendar without losing selection or URL filters", async () => {
    const task = {
      task_id: "tsk_aaaaaaaa11111111", title: "Prepare permit set", lifecycle_state: "in_progress", priority: "p1",
      due_at: "2026-08-24T16:00:00Z", scheduled_at: "2026-08-23T13:00:00Z", deferred_until: "2026-08-22T12:00:00Z",
      archived_at: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-22T12:00:00Z", version: 4,
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ tasks: [task] }), { status: 200, headers: { "content-type": "application/json" } })));
    history.replaceState(null, "", "/work?view=all-open&q=permit&archived=exclude"); renderFromUrl();
    const checkbox = await screen.findByRole("checkbox", { name: "Select Prepare permit set" });
    await userEvent.click(checkbox);
    await userEvent.click(screen.getByRole("button", { name: "Board" }));
    const board = await screen.findByRole("region", { name: "Task lifecycle board" });
    expect(board.className).not.toMatch(/overflow-x-auto|snap-x/);
    expect(screen.queryByLabelText(/Move .* lifecycle/)).toBeNull();
    expect(screen.getByRole("checkbox", { name: "Select Prepare permit set" })).toBeChecked();
    expect(location.search).toContain("q=permit"); expect(location.search).toContain("perspective=board");
    await userEvent.click(screen.getByRole("button", { name: "Calendar" }));
    expect(await screen.findByText("Deadline")).toBeTruthy();
    expect(screen.getByText("Planned work")).toBeTruthy();
    expect(screen.getByText("Available after")).toBeTruthy();
    expect(location.search).toContain("perspective=calendar");
  });

  it("opens canonical detail in the foundation Sheet and restores URL and trigger focus", async () => {
    const task = {
      task_id: "tsk_aaaaaaaa11111111", title: "Inspect me", lifecycle_state: "open", priority: null,
      due_at: null, scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-22T12:00:00Z", version: 2,
    };
    const detail = { ...task, description: null, evidence_state: "proposed", origin_kind: "evidence", origin_evidence_ref: "cap_origin0001origin0001", closure_evidence_ref: null, closure_history_id: null, commitment_id: null, role: null, opened_at: task.created_at, closed_at: null };
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === "/api/tasks/tsk_aaaaaaaa11111111") return new Response(JSON.stringify({ task: detail }), { status: 200, headers: { "content-type": "application/json" } });
      if (path.includes("/history")) return new Response(JSON.stringify({ history: [] }), { status: 200, headers: { "content-type": "application/json" } });
      if (path.startsWith("/api/commitments")) return new Response(JSON.stringify({ commitments: [] }), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify({ tasks: [task] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=all-open&q=inspect"); renderFromUrl();
    const trigger = await screen.findByRole("link", { name: /Inspect me/ });
    await userEvent.click(trigger);
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(location.search).toContain("task=tsk_aaaaaaaa11111111");
    await userEvent.click(screen.getByRole("button", { name: "Close panel" }));
    await waitFor(() => expect(location.search).not.toContain("task="));
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(location.search).toContain("q=inspect");
  });

  it("opens a Task through the compact Task Sheet, seeding from the list row without reading diagnostics", async () => {
    const task = {
      task_id: "tsk_bbbbbbbb22222222", title: "Seeded from the list", lifecycle_state: "in_progress",
      priority: "p1", due_at: null, scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-22T12:00:00Z", version: 2,
    };
    const detail = { ...task, description: null, evidence_state: "accepted", origin_kind: "direct_principal", origin_evidence_ref: null, closure_evidence_ref: null, accepted_by_review_decision_id: null, acceptance_kind: null, closure_history_id: null, commitment_id: null, role: null, project_id: null, situation_id: null, opened_at: task.created_at, closed_at: null };
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      const body = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });
      if (path === `/api/tasks/${task.task_id}`) return body({ task: detail });
      if (path.includes("/comments")) return body({ comments: [] });
      if (path.includes("/history")) return body({ history: [] });
      if (path.startsWith("/api/commitments")) return body({ commitments: [] });
      return body({ tasks: [task] });
    });
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=all-open"); renderFromUrl();

    await userEvent.click(await screen.findByRole("link", { name: /Seeded from the list/ }));

    const sheet = await screen.findByTestId("task-compact-sheet");
    expect(location.search).toContain(`task=${task.task_id}`);

    // Product language only, and no raw identifier or backend token in the compact view.
    await waitFor(() => expect(sheet.textContent).toContain("In progress"));
    expect(sheet.textContent).toContain("Critical");
    expect(sheet.textContent).not.toMatch(/in_progress|\bp1\b/);
    expect(sheet.textContent).not.toContain(task.task_id);

    // Opening a Task does not eagerly read technical history.
    expect(fetcher.mock.calls.some(([path]) => String(path).includes("/history"))).toBe(false);
  });

  it("passes Commitment due focus and civil-date timezone to the server", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ commitments: [] }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=commitments&commitment=due&tz=America%2FNew_York"); renderFromUrl();
    await screen.findByText("No matching commitments");
    const path = String(fetcher.mock.calls[0]?.[0]);
    expect(path).toContain("workView=due"); expect(path).toMatch(/workDate=\d{4}-\d{2}-\d{2}/); expect(path).toContain("timezone=America%2FNew_York");
  });

  it("loads an executable lifecycle view without deriving it in the browser", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ tasks: [{ task_id: "tsk_aaaaaaaa11111111", title: "Synthetic follow up", lifecycle_state: "waiting", priority: "p2", due_at: null, archived_at: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z" }] }), { status: 200, headers: { "content-type": "application/json" } })));
    history.replaceState(null, "", "/work?view=today"); renderFromUrl();
    await chooseWorkView("Waiting");
    expect((await screen.findByRole("link", { name: /Synthetic follow up/ })).getAttribute("href")).toBe("/work/tasks/tsk_aaaaaaaa11111111");
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/tasks?pageSize=50&workView=waiting&archived=exclude", expect.objectContaining({ cache: "no-store" })));
  });

  it("distinguishes terminal completion from terminal cancellation", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ tasks: [
      { task_id: "tsk_aaaaaaaa11111111", title: "Finished", lifecycle_state: "completed", priority: null, due_at: null, archived_at: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z" },
      { task_id: "tsk_bbbbbbbb22222222", title: "Withdrawn", lifecycle_state: "cancelled", priority: null, due_at: null, archived_at: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z" },
    ] }), { status: 200, headers: { "content-type": "application/json" } })));
    history.replaceState(null, "", "/work?view=completed"); renderFromUrl();
    /*
      Same guarantee, said in product language. The operational row states the
      terminal outcome as Closed or Cancelled rather than as "terminal
      completion" / "terminal cancellation", and the two remain distinguishable —
      which is what this test has always been for. The row deliberately shows no
      raw lifecycle token, so the backend words are asserted absent too.
    */
    const rows = await screen.findAllByTestId("task-list-row");
    expect(rows).toHaveLength(2);
    const finished = rows.find((row) => row.textContent?.includes("Finished"));
    const withdrawn = rows.find((row) => row.textContent?.includes("Withdrawn"));
    expect(finished?.textContent).toContain("Closed");
    expect(withdrawn?.textContent).toContain("Cancelled");
    expect(finished?.textContent).not.toContain("completed");
    expect(withdrawn?.textContent).not.toContain("cancelled");
  });

  it("moves focus to the Task that takes the place of one that left the filter", async () => {
    /*
      The package's primary acceptance gate. Closing a Task from an open view
      removes the row the user was standing on, and with it the control that had
      focus. Focus must land on whatever now occupies that place — never on
      `document.body`, where a keyboard user would be stranded at the top of the
      document with no idea the action succeeded.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const first = rowOf("tsk_aaaaaaaa11111111", "Leaves the filter");
    const second = rowOf("tsk_bbbbbbbb22222222", "Takes its place");
    let closed = false;
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.includes("/transition") && method === "POST") {
        closed = true;
        return body({ task: { ...first, version: 3, lifecycle_state: "completed" } });
      }
      if (path === `/api/tasks/${first.task_id}`) return body({ task: first });
      if (path === `/api/tasks/${second.task_id}`) return body({ task: second });
      if (path.includes("/comments")) return body({ comments: [] });
      // The server decides membership: once closed, the Task is gone from an open view.
      return body({ tasks: closed ? [second] : [first, second] });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Leaves the filter");

    const user = userEvent.setup();
    const rows = screen.getAllByTestId("task-list-row");
    await user.click(within(rows[0]).getByTestId("task-close-trigger"));
    await user.click(within(rows[0]).getByTestId("task-close-confirm"));

    // The row that remains now holds focus at the place the closed one left.
    await waitFor(() => expect(screen.queryByText("Leaves the filter")).toBeNull());
    await waitFor(() => {
      expect(document.activeElement).not.toBe(document.body);
      expect(document.activeElement?.textContent).toContain("Takes its place");
    });
  });

  it("does not move focus on a later refresh after a mutation that kept the Task", async () => {
    /*
      The dangling-handoff case. A Status change usually leaves the Task right
      where it was, so no focus move is owed. But `rows` keeps changing for
      reasons of its own — the freshness poll, another Task's mutation — and if
      the handoff armed at dispatch were still sitting there, one of those later
      refreshes would be read as "this mutation removed the Task" and pull focus
      somewhere the user was not working.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const kept = rowOf("tsk_aaaaaaaa11111111", "Stays put");
    const other = rowOf("tsk_bbbbbbbb22222222", "Someone else");
    let listed = [kept, other];
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.includes("/transition") && method === "POST") {
        return body({ task: { ...kept, version: 3, lifecycle_state: "waiting" } });
      }
      if (path === `/api/tasks/${kept.task_id}`) return body({ task: kept });
      if (path === `/api/tasks/${other.task_id}`) return body({ task: other });
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Stays put");

    const user = userEvent.setup();
    const rows = screen.getAllByTestId("task-list-row");
    // Status change that does not remove the Task from this view.
    await user.selectOptions(within(rows[0]).getByRole("combobox"), "waiting");
    await waitFor(() =>
      expect(screen.getByTestId("mutation-feedback-region").textContent).toContain("Status changed to"),
    );

    // Park focus somewhere deliberate, then let the freshness poll bring back a
    // list this Task is no longer in — an ordinary background refresh, nothing
    // to do with the Status change that already settled.
    const parked = screen.getByRole("heading", { name: "Work", level: 1 });
    parked.focus();
    expect(document.activeElement).toBe(parked);

    const listReads = () =>
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.filter(
        ([input, init]) =>
          String(input).startsWith("/api/tasks?") && (init?.method ?? "GET").toUpperCase() === "GET",
      ).length;
    const before = listReads();

    // A plain background refresh, with no mutation in front of it: the window
    // regains focus and the active query re-reads. By then the Task has moved
    // elsewhere for reasons of its own.
    listed = [other];
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });

    await waitFor(() => expect(listReads()).toBeGreaterThan(before));
    await waitFor(() => expect(screen.queryByText("Stays put")).toBeNull());

    // Focus placement runs inside a frame, so give it one before judging.
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // Focus was not stolen by a handoff that no longer had anything to do.
    expect(document.activeElement).toBe(parked);
  });

  it("does not move focus when the user pages away before a mutation settles", async () => {
    /*
      Independent review reproduced this. Paging changes the whole visible set,
      so the Task a pending handoff is tracking is trivially absent from the new
      page — and without a clear, that reads as "the mutation removed it" and
      pulls focus onto whatever now sits at that index. The user is on page two
      looking at different work entirely.

      The clear is keyed on the query identity, which already covers the cursor,
      rather than on a list of call sites. The first attempt enumerated call
      sites by matching `setCursor("")` and missed pagination, which calls
      `setCursor(nextCursor)`.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const pageOne = rowOf("tsk_aaaaaaaa11111111", "Page one task");
    const pageTwo = rowOf("tsk_bbbbbbbb22222222", "Page two task");
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });
    const withCursor = (tasks: unknown[]) =>
      body({
        tasks,
        disclosure: {
          scope: "tasks", coverage: "partial", freshnessAt: "2026-08-21T12:00:00Z",
          authority: "accepted", limitations: ["bounded page"], truncated: true,
          nextCursor: "cursor-page-two",
        },
      });

    let releaseTransition: () => void = () => undefined;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.includes("/transition") && method === "POST") {
        // Still in flight while the user pages away.
        await new Promise<void>((resolve) => {
          releaseTransition = () => resolve();
        });
        return body({ task: { ...pageOne, version: 3, lifecycle_state: "waiting" } });
      }
      if (path === `/api/tasks/${pageOne.task_id}`) return body({ task: pageOne });
      if (path === `/api/tasks/${pageTwo.task_id}`) return body({ task: pageTwo });
      if (path.includes("/comments")) return body({ comments: [] });
      return withCursor(path.includes("after=") ? [pageTwo] : [pageOne]);
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Page one task");

    const user = userEvent.setup();
    // Dispatch a Status change, then page away before it settles.
    void user.selectOptions(screen.getByRole("combobox", { name: /Status/i }), "waiting");
    await screen.findByRole("button", { name: /Next page/i });
    await user.click(screen.getByRole("button", { name: /Next page/i }));
    await screen.findByText("Page two task");

    const parked = screen.getByRole("heading", { name: "Work", level: 1 });
    parked.focus();
    releaseTransition();

    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // Focus stayed where the user put it, on the page they navigated to.
    expect(document.activeElement).toBe(parked);
  });

  it("does not move focus when the user switches to Commitments mid-mutation", async () => {
    /*
      Found by review, and a regression I introduced: switching between Tasks and
      Commitments pins the task view through `lastTaskView`, so the query
      identity can be byte-identical either side of the toggle — while the switch
      still empties the rows. A handoff left armed reads that empty list as "the
      Task is gone" and pulls focus to the heading, away from the Commitments
      control the user just pressed.

      The list load is resolved a frame late here on purpose. Resolving it in the
      same microtask hides the theft behind a lucky cancelAnimationFrame; any
      real round trip does not.
    */
    const task = {
      task_id: "tsk_aaaaaaaa11111111", title: "Mid-flight task", lifecycle_state: "open",
      priority: null, due_at: null, scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    };
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    let releaseTransition: () => void = () => undefined;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.includes("/transition") && method === "POST") {
        await new Promise<void>((resolve) => {
          releaseTransition = () => resolve();
        });
        return body({ task: { ...task, version: 3, lifecycle_state: "waiting" } });
      }
      if (path === `/api/tasks/${task.task_id}`) return body({ task });
      if (path.includes("/comments")) return body({ comments: [] });
      if (path.startsWith("/api/commitments")) {
        // Arrives a frame later, as a real round trip would.
        await new Promise<void>((resolve) => {
          requestAnimationFrame(() => resolve());
        });
        return body({ commitments: [] });
      }
      return body({ tasks: [task] });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Mid-flight task");

    const user = userEvent.setup();
    void user.selectOptions(screen.getByRole("combobox", { name: /Status/i }), "waiting");

    const commitments = await screen.findByRole("button", { name: "Commitments" });
    await user.click(commitments);
    commitments.focus();

    releaseTransition();
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // Focus stayed on the control the user pressed.
    expect(document.activeElement).toBe(commitments);
  });

  it("stands the focus handoff down when a mutation fails", async () => {
    /*
      A failed mutation moved nothing, so it is owed no focus placement. If its
      handoff were left armed it would be spent on whatever changed the list
      next — a poll, someone else's edit — and focus would jump for a reason the
      user could not connect to anything they did.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const task = rowOf("tsk_aaaaaaaa11111111", "Refuses to move");
    const other = rowOf("tsk_bbbbbbbb22222222", "Someone else");
    let listed = [task, other];
    const body = (data: unknown, status = 200) =>
      new Response(JSON.stringify(status >= 400 ? { error: { message: "nope", code: "invalid" } } : data), {
        status, headers: { "content-type": "application/json" },
      });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      // The write is definitively refused.
      if (path.includes("/transition") && method === "POST") return body(null, 400);
      if (path === `/api/tasks/${task.task_id}`) return body({ task });
      if (path === `/api/tasks/${other.task_id}`) return body({ task: other });
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Refuses to move");

    const user = userEvent.setup();
    const rows = screen.getAllByTestId("task-list-row");
    await user.selectOptions(within(rows[0]).getByRole("combobox"), "waiting");
    await waitFor(() =>
      expect(screen.getByTestId("mutation-feedback-region").textContent).toMatch(/could not|not be saved/i),
    );

    const parked = screen.getByRole("heading", { name: "Work", level: 1 });
    parked.focus();

    // Later, the Task leaves the filter for reasons of its own.
    listed = [other];
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText("Refuses to move")).toBeNull());
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // The failed attempt was owed nothing, so focus stayed put.
    expect(document.activeElement).toBe(parked);
  });

  it("falls back to the Work heading when nothing is left to focus", async () => {
    const only = {
      task_id: "tsk_aaaaaaaa11111111", title: "The last one", lifecycle_state: "open",
      priority: null, due_at: null, scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    };
    let closed = false;
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.includes("/transition") && method === "POST") {
        closed = true;
        return body({ task: { ...only, version: 3, lifecycle_state: "completed" } });
      }
      if (path === `/api/tasks/${only.task_id}`) return body({ task: only });
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: closed ? [] : [only] });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("The last one");

    const user = userEvent.setup();
    await user.click(screen.getByTestId("task-close-trigger"));
    await user.click(screen.getByTestId("task-close-confirm"));

    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Work", level: 1 }));
    });
  });

  it("previews and confirms the exact same bounded mutation list", async () => {
    const task = { task_id: "tsk_aaaaaaaa11111111", title: "Synthetic follow up", lifecycle_state: "waiting", priority: "p2", due_at: null, archived_at: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z" };
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path.includes("/bulk/preview")) return new Response(JSON.stringify({ bulk_operation_id: "bulk_aaaaaaaa11111111", expires_at: "2099-08-21T12:15:00Z", affected: 1, no_op: 0, rejected: 0, replayed: false }), { status: 200, headers: { "content-type": "application/json" } });
      if (path.includes("/bulk/confirm")) return new Response(JSON.stringify({ bulk_operation_id: "bulk_aaaaaaaa11111111", affected: 1, no_op: 0, rejected: 0, history_ids: ["tsh_aaaaaaaa11111111"], replayed: false }), { status: 200, headers: { "content-type": "application/json" } });
      if (path === "/api/tasks/tsk_aaaaaaaa11111111") return new Response(JSON.stringify({ task: { ...task, version: 4 } }), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify({ tasks: [task] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=waiting"); renderFromUrl();
    await userEvent.click(await screen.findByRole("checkbox", { name: "Select Synthetic follow up" }));
    const confirm = screen.getByRole("button", { name: "Confirm exact preview" });
    expect(confirm).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Preview change" }));
    expect(await screen.findByText("Preview ready")).toBeTruthy();
    expect(screen.getByText(/1 affected/)).toBeTruthy();
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    expect(await screen.findByText("Changes applied")).toBeTruthy();
    expect(screen.getByText(/1 affected/)).toBeTruthy();
    const previewCall = fetcher.mock.calls.find(([path]) => String(path).includes("/bulk/preview"));
    const confirmCall = fetcher.mock.calls.find(([path]) => String(path).includes("/bulk/confirm"));
    const previewBody = JSON.parse(String(previewCall?.[1]?.body));
    const confirmBody = JSON.parse(String(confirmCall?.[1]?.body));
    expect(confirmBody.mutations).toEqual(previewBody.mutations);
    expect(confirmBody.bulkOperationId).toBe("bulk_aaaaaaaa11111111");
  });

  it("replays an ambiguous bulk confirmation with the exact preview, mutations, and key", async () => {
    const task = { task_id: "tsk_aaaaaaaa11111111", title: "Synthetic follow up", lifecycle_state: "waiting", priority: "p2", due_at: null, archived_at: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z" };
    let confirmations = 0;
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path.includes("/bulk/preview")) return new Response(JSON.stringify({ bulk_operation_id: "bulk_aaaaaaaa11111111", expires_at: "2099-08-21T12:15:00Z", affected: 1, no_op: 0, rejected: 0, replayed: false }), { status: 200, headers: { "content-type": "application/json" } });
      if (path.includes("/bulk/confirm")) {
        confirmations += 1;
        if (confirmations === 1) return new Response(JSON.stringify({ error: { code: "unavailable", message: "upstream result unknown" } }), { status: 503, headers: { "content-type": "application/json" } });
        return new Response(JSON.stringify({ bulk_operation_id: "bulk_aaaaaaaa11111111", affected: 1, no_op: 0, rejected: 0, history_ids: ["tsh_aaaaaaaa11111111"], replayed: true }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (path === "/api/tasks/tsk_aaaaaaaa11111111") return new Response(JSON.stringify({ task: { ...task, version: 4 } }), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify({ tasks: [task] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=waiting"); renderFromUrl();
    await userEvent.click(await screen.findByRole("checkbox", { name: "Select Synthetic follow up" }));
    await userEvent.click(screen.getByRole("button", { name: "Preview change" }));
    await screen.findByText("Preview ready");
    await userEvent.click(screen.getByRole("button", { name: "Confirm exact preview" }));
    await screen.findByText(/Work is unavailable/);
    expect(screen.getByText(/Preview bulk_aaaaaaaa11111111/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Confirm exact preview" }));
    expect(await screen.findByText("Changes applied")).toBeTruthy();
    expect(screen.getByText(/Replayed confirmation/)).toBeTruthy();
    const bodies = fetcher.mock.calls.filter(([path]) => String(path).includes("/bulk/confirm")).map(([, init]) => JSON.parse(String(init?.body)));
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toEqual(bodies[0]);
  });

  it("retains the selected Task and action when preview conflicts", async () => {
    const task = { task_id: "tsk_aaaaaaaa11111111", title: "Synthetic follow up", lifecycle_state: "waiting", priority: "p2", due_at: null, archived_at: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z" };
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const path = String(input);
      if (path.includes("/bulk/preview")) return new Response(JSON.stringify({ error: { code: "conflict", message: "version changed" } }), { status: 409, headers: { "content-type": "application/json" } });
      if (path === "/api/tasks/tsk_aaaaaaaa11111111") return new Response(JSON.stringify({ task: { ...task, version: 4 } }), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify({ tasks: [task] }), { status: 200, headers: { "content-type": "application/json" } });
    }));
    history.replaceState(null, "", "/work?view=waiting"); renderFromUrl();
    const checkbox = await screen.findByRole("checkbox", { name: "Select Synthetic follow up" });
    await userEvent.click(checkbox); await userEvent.click(screen.getByRole("button", { name: "Preview change" }));
    expect(await screen.findByText(/Preview conflicted/)).toBeTruthy();
    expect(checkbox).toBeChecked();
    expect((screen.getByRole("combobox", { name: "Bulk value" }) as HTMLSelectElement).value).toBe("p1");
  });

  it("synchronizes Task search and continuation state with the URL", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ tasks: [{ task_id: "tsk_aaaaaaaa11111111", title: "Find this", lifecycle_state: "open", priority: null, due_at: null, archived_at: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z" }], disclosure: { scope: "tasks", coverage: "partial", freshnessAt: "2026-08-21T12:00:00Z", authority: "accepted", limitations: ["bounded page"], truncated: true, nextCursor: "tsk_aaaaaaaa11111111" } }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=all-open"); renderFromUrl();
    const search = screen.getByRole("textbox", { name: "Search tasks" }); await userEvent.type(search, "Find");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(location.search).toContain("q=Find"));
    expect(await screen.findByText("More Work is available")).toBeTruthy();
    const freshness = document.querySelector('time[data-visual-dynamic="freshness"]');
    expect(freshness?.getAttribute("datetime")).toBe("2026-08-21T12:00:00Z");
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(location.search).toContain("cursor=tsk_aaaaaaaa11111111");
    await waitFor(() => expect(fetcher.mock.calls.some(([path]) => String(path).includes("q=Find") && String(path).includes("after=tsk_aaaaaaaa11111111"))).toBe(true));
  });

  it("does not read canonical Work while a search query is only being drafted", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=all-open"); renderFromUrl();
    await screen.findByText("No all open tasks");
    fetcher.mockClear();
    await userEvent.type(screen.getByRole("textbox", { name: "Search tasks" }), "uncommitted");
    await Promise.resolve();
    expect(fetcher).not.toHaveBeenCalled();
    expect(location.search).not.toContain("q=");
  });

  it("commits a replacement search before reading and never sends its stale cursor", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=all-open&q=old&cursor=tsk_stale111111111"); renderFromUrl();
    await screen.findByText("No matching all open tasks");
    fetcher.mockClear();
    const search = screen.getByRole("textbox", { name: "Search tasks" });
    await userEvent.clear(search); await userEvent.type(search, "replacement");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const path = String(fetcher.mock.calls[0]?.[0]);
    expect(location.search).toContain("q=replacement");
    expect(location.search).not.toContain("cursor=");
    expect(path).toContain("q=replacement");
    expect(path).not.toContain("after=");
  });

  it("does not let an older overlapping read overwrite the current URL-derived answer", async () => {
    let resolveOld!: (response: Response) => void;
    let resolveCurrent!: (response: Response) => void;
    const oldResponse = new Promise<Response>((resolve) => { resolveOld = resolve; });
    const currentResponse = new Promise<Response>((resolve) => { resolveCurrent = resolve; });
    const fetcher = vi.fn<typeof fetch>((input) => String(input).includes("q=current") ? currentResponse : oldResponse);
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=all-open&q=old"); renderFromUrl();
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const search = screen.getByRole("textbox", { name: "Search tasks" });
    await userEvent.clear(search); await userEvent.type(search, "current");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    const row = (title: string, id: string) => ({ task_id: id, title, lifecycle_state: "open", priority: null, due_at: null, archived_at: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z" });
    await act(async () => resolveCurrent(new Response(JSON.stringify({ tasks: [row("Current answer", "tsk_current11111111")] }), { status: 200, headers: { "content-type": "application/json" } })));
    expect(await screen.findByText("Current answer")).toBeTruthy();
    await act(async () => resolveOld(new Response(JSON.stringify({ tasks: [row("Stale answer", "tsk_stale111111111")] }), { status: 200, headers: { "content-type": "application/json" } })));
    await Promise.resolve();
    expect(screen.getByText("Current answer")).toBeTruthy();
    expect(screen.queryByText("Stale answer")).toBeNull();
    expect(location.search).toContain("q=current");
  });

  it("uses the dedicated Waiting On endpoint and truthfully disables unsupported search", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ waiting_on: [{ commitment_id: "cmt_aaaaaaaa11111111", title: "Revised schedule", counterparty_person_id: "per_aaaaaaaa11111111", counterparty: { person_id: "per_aaaaaaaa11111111", display_name: "Sam Rivera" }, due_date: null, state: "open", follow_up_task_id: "tsk_aaaaaaaa11111111", follow_up_task_title: "Ask Sam", follow_up_task_state: "waiting" }] }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=commitments&commitment=waiting-on&q=Sam"); renderFromUrl();
    expect(await screen.findByText(/Sam Rivera · waiting on · open/)).toBeTruthy();
    expect(screen.getByText(/Follow-up: Ask Sam · waiting/)).toBeTruthy();
    expect(screen.queryByText(/per_aaaaaaaa|cmt_aaaaaaaa|tsk_aaaaaaaa/)).toBeNull();
    expect(screen.getByText("Search is unavailable for the dedicated Waiting On view.")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Search commitments" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();
    expect(String(fetcher.mock.calls[0]?.[0])).toBe("/api/commitments/waiting-on?pageSize=50");
  });

  it("offers only human-readable verified counterparty and Commitment choices", async () => {
    const commitment = { commitment_id: "cmt_aaaaaaaa11111111", title: "Revised schedule", direction: "owed_to_principal", state: "open", counterparty_person_id: "per_aaaaaaaa11111111", counterparty: { person_id: "per_aaaaaaaa11111111", display_name: "Sam Rivera" }, description: null, due_date: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 1 };
    const fetcher = vi.fn<typeof fetch>(async (input) => String(input).startsWith("/api/commitments")
      ? new Response(JSON.stringify({ commitments: [commitment], counterparty_options: [commitment.counterparty], counterparty_options_truncated: false }), { status: 200, headers: { "content-type": "application/json" } })
      : new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=commitments"); renderFromUrl();
    await screen.findByText("Revised schedule");
    await userEvent.click(screen.getByRole("button", { name: "New commitment" }));
    expect(await screen.findByRole("option", { name: "Sam Rivera" })).toBeTruthy();
    expect(screen.queryByLabelText(/person ID/i)).toBeNull();
    // Work create is the canonical sheet: Commitment and Role are runtime/server
    // decisions and have no field here, so no Commitment can be offered at all.
    await userEvent.click(screen.getByRole("button", { name: "Tasks" }));
    await userEvent.click(await screen.findByRole("button", { name: "New task" }));
    expect(await screen.findByTestId("task-create-sheet")).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Revised schedule" })).toBeNull();
    expect(screen.queryByLabelText(/^Commitment$/i)).toBeNull();
    expect(screen.queryByLabelText(/^Role$/i)).toBeNull();
    expect(screen.queryByLabelText(/Commitment ID/i)).toBeNull();
  });

  it("creates a Task through the canonical sheet without capture evidence, commitments or an origin note", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path === "/api/tasks" && init?.method === "POST") {
        return new Response(JSON.stringify({ task: { task_id: "tsk_aaaaaaaa11111111" }, history: {}, replayed: false }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (path.startsWith("/api/commitments")) return new Response(JSON.stringify({ commitments: [] }), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetcher);
    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("No all open tasks");
    await userEvent.click(screen.getByRole("button", { name: "New task" }));
    expect(await screen.findByTestId("task-create-sheet")).toBeTruthy();
    expect(screen.queryByLabelText("Origin note")).toBeNull();
    await userEvent.type(screen.getByLabelText("Title"), "Direct task");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => {
      expect(fetcher.mock.calls.some(([path, init]) => String(path) === "/api/tasks" && init?.method === "POST")).toBe(true);
    });
    const createCall = fetcher.mock.calls.find(([path, init]) => String(path) === "/api/tasks" && init?.method === "POST");
    expect(createCall).toBeTruthy();
    const body = JSON.parse(String(createCall?.[1]?.body));
    expect(body).toMatchObject({ title: "Direct task", idempotencyKey: expect.any(String) });
    expect(body).not.toHaveProperty("originEvidenceRef");
    expect(body).not.toHaveProperty("originKind");
    expect(body).not.toHaveProperty("commitmentId");
    expect(body).not.toHaveProperty("role");
    expect(fetcher.mock.calls.some(([path]) => String(path) === "/api/capture")).toBe(false);
    expect(fetcher.mock.calls.some(([path]) => String(path).startsWith("/api/commitments"))).toBe(false);
  });

  it("hydrates exact URL state and honors a validated timezone", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=upcoming&q=plan&tz=America%2FNew_York&archived=only"); renderFromUrl();
    await screen.findByText("No matching upcoming tasks");
    const path = String(fetcher.mock.calls[0]?.[0]); expect(path).toContain("workView=upcoming"); expect(path).toContain("q=plan"); expect(path).toContain("archived=only"); expect(path).toContain("timezone=America%2FNew_York");
    expect((screen.getByLabelText("Archive") as HTMLSelectElement).value).toBe("only");
  });

  it("updates the URL from compact mode, scope, and presentation selectors", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input) => {
      const path = String(input);
      const body = path.includes("waiting-on") ? { waiting_on: [] } : path.includes("/api/commitments") ? { commitments: [] } : { tasks: [] };
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }));
    history.replaceState(null, "", "/work?view=today");
    renderFromUrl();
    await screen.findByText("No today tasks");
    await chooseWorkView("Overdue");
    expect(location.search).toContain("view=overdue");
    await userEvent.click(screen.getByRole("button", { name: "Commitments" }));
    await screen.findByText("No commitments");
    expect(location.search).toContain("view=commitments");
    await userEvent.click(screen.getByRole("button", { name: "Commitment filter" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Waiting on" }));
    expect(location.search).toContain("commitment=waiting-on");
    await userEvent.click(screen.getByRole("button", { name: "Board" }));
    expect(location.search).toContain("perspective=board");
  });

  it("does not treat a failed Work read as an empty view", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "unavailable", message: "gateway down" } }), { status: 503, headers: { "content-type": "application/json" } })));
    history.replaceState(null, "", "/work?view=today");
    renderFromUrl();
    expect(await screen.findByText("This could not be read")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByTestId("surface-state-detail").textContent).toBe("This could not be read. Try again.");
    expect(screen.getByTestId("surface-state-diagnostic").textContent).toBe("gateway down");
    expect(screen.queryByText("No today tasks")).toBeNull();
  });

  it("double-submit create issues only one network POST", async () => {
    let resolveCreate!: (response: Response) => void;
    const createPromise = new Promise<Response>((resolve) => {
      resolveCreate = resolve;
    });
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path === "/api/tasks" && init?.method === "POST") return createPromise;
      if (path.startsWith("/api/commitments")) {
        return new Response(JSON.stringify({ commitments: [] }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetcher);
    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("No all open tasks");
    await userEvent.click(screen.getByRole("button", { name: "New task" }));
    await userEvent.type(await screen.findByLabelText("Title"), "Only once");
    // Same guarantee as the retired embedded Work form, now through the shared sheet.
    const form = screen.getByTestId("task-create-sheet");
    expect(form).toBeTruthy();
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => {
      expect(fetcher.mock.calls.filter(([path, init]) => String(path) === "/api/tasks" && init?.method === "POST")).toHaveLength(1);
    });
    await act(async () => {
      resolveCreate(
        new Response(JSON.stringify({ task: { task_id: "tsk_aaaaaaaa11111111" }, history: {}, replayed: false }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    });
    await waitFor(() => expect(screen.queryByTestId("task-create-sheet")).toBeNull());
  });

  it("retains confirmed rows when a background poll returns 503", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const task = {
      task_id: "tsk_aaaaaaaa11111111",
      title: "Keep me",
      lifecycle_state: "open",
      priority: null,
      due_at: null,
      archived_at: null,
      created_at: "2026-08-21T12:00:00Z",
      updated_at: "2026-08-21T12:00:00Z",
    };
    let listReads = 0;
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path.startsWith("/api/tasks?")) {
        listReads += 1;
        if (listReads === 1) {
          return new Response(JSON.stringify({ tasks: [task] }), { status: 200, headers: { "content-type": "application/json" } });
        }
        return new Response(JSON.stringify({ error: { code: "unavailable", message: "gateway down" } }), {
          status: 503,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetcher);
    history.replaceState(null, "", "/work?view=today");
    renderFromUrl();
    expect(await screen.findByText("Keep me")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TASK_FRESHNESS_INTERVAL_MS);
    });
    await waitFor(() => expect(listReads).toBeGreaterThanOrEqual(2));
    expect(screen.getByText("Keep me")).toBeTruthy();
    expect(screen.queryByText("No today tasks")).toBeNull();
    expect(screen.queryByText("This could not be read")).toBeNull();
    expect(await screen.findByTestId("mutation-feedback-region")).toBeTruthy();
    expect(screen.getByRole("status")).toHaveTextContent(/temporarily unavailable/i);
  });

  it("does not multiply freshness polls when switching perspective", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetcher = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetcher);
    history.replaceState(null, "", "/work?view=today");
    renderFromUrl();
    await screen.findByText("No today tasks");
    const beforePerspectives = listTaskGets(fetcher).length;
    await userEvent.click(screen.getByRole("button", { name: "Board" }));
    await userEvent.click(screen.getByRole("button", { name: "Calendar" }));
    await userEvent.click(screen.getByRole("button", { name: "List" }));
    expect(listTaskGets(fetcher).length).toBe(beforePerspectives);
    fetcher.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TASK_FRESHNESS_INTERVAL_MS);
    });
    expect(listTaskGets(fetcher).length).toBe(1);
    fetcher.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TASK_FRESHNESS_INTERVAL_MS);
    });
    expect(listTaskGets(fetcher).length).toBe(1);
  });

  it("retries an ambiguous create with the same idempotency key", async () => {
    let createPosts = 0;
    const keys: string[] = [];
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path === "/api/tasks" && init?.method === "POST") {
        createPosts += 1;
        const body = JSON.parse(String(init.body)) as { idempotencyKey: string; title: string };
        keys.push(body.idempotencyKey);
        if (createPosts === 1) {
          return new Response(JSON.stringify({ error: { code: "unavailable", message: "gateway timeout" } }), {
            status: 504,
            headers: { "content-type": "application/json" },
          });
        }
        return new Response(
          JSON.stringify({ task: { task_id: "tsk_aaaaaaaa11111111" }, history: {}, replayed: false }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      if (path.startsWith("/api/commitments")) {
        return new Response(JSON.stringify({ commitments: [] }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetcher);
    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("No all open tasks");
    await userEvent.click(screen.getByRole("button", { name: "New task" }));
    await userEvent.type(await screen.findByLabelText("Title"), "Ambiguous retry");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(
      await screen.findByText(/Create may still have succeeded\. Retry with the same intent/i),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry same create" })).toBeTruthy();
    expect(createPosts).toBe(1);
    await userEvent.click(screen.getByRole("button", { name: "Retry same create" }));
    await waitFor(() => expect(createPosts).toBe(2));
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
    expect(keys[0]).toMatch(/\S/);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Retry same create" })).toBeNull());
  });

  it("closes create form even when list reconcile never resolves", async () => {
    let resolveList!: (response: Response) => void;
    const listPromise = new Promise<Response>((resolve) => {
      resolveList = resolve;
    });
    let createPosts = 0;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path === "/api/tasks" && init?.method === "POST") {
        createPosts += 1;
        return new Response(
          JSON.stringify({ task: { task_id: "tsk_aaaaaaaa11111111" }, history: {}, replayed: false }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      if (path.startsWith("/api/tasks?")) return listPromise;
      if (path.startsWith("/api/commitments")) {
        return new Response(JSON.stringify({ commitments: [] }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetcher);
    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    // First paint waits on the hung list promise — resolve the initial mount read only.
    await act(async () => {
      resolveList(new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } }));
    });
    await screen.findByText("No all open tasks");
    // Subsequent list reads hang again.
    const listPromise2 = new Promise<Response>(() => undefined);
    fetcher.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/tasks" && init?.method === "POST") {
        createPosts += 1;
        return new Response(
          JSON.stringify({ task: { task_id: "tsk_aaaaaaaa11111111" }, history: {}, replayed: false }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      if (path.startsWith("/api/tasks?")) return listPromise2;
      if (path.startsWith("/api/commitments")) {
        return new Response(JSON.stringify({ commitments: [] }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    await userEvent.click(screen.getByRole("button", { name: "New task" }));
    await userEvent.type(await screen.findByLabelText("Title"), "Must close");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(createPosts).toBe(1));
    await waitFor(() => expect(screen.queryByTestId("task-create-sheet")).toBeNull());
  });

  it("opens the canonical Task create sheet from New task without reading commitments", async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetcher);
    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("No all open tasks");

    await userEvent.click(screen.getByRole("button", { name: "New task" }));

    expect(await screen.findByTestId("task-create-sheet")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Create task" })).toBeTruthy();
    // The retired embedded form fetched up to 100 commitments just to paint a field.
    expect(fetcher.mock.calls.filter(([path]) => String(path).startsWith("/api/commitments"))).toHaveLength(0);
    // Commitment and Role are not principal-authored on the canonical surface.
    expect(screen.queryByLabelText(/^Commitment$/i)).toBeNull();
    expect(screen.queryByLabelText(/^Role$/i)).toBeNull();
  });

  it("does not prefill create from the current Work view, filter or search", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path === "/api/tasks" && init?.method === "POST") {
        return new Response(JSON.stringify({ task: { task_id: "tsk_aaaaaaaa11111111" }, history: {}, replayed: false }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetcher);
    history.replaceState(null, "", "/work?view=upcoming&q=plan&archived=only&tz=America%2FNew_York");
    renderFromUrl();
    await screen.findByText("No matching upcoming tasks");

    await userEvent.click(screen.getByRole("button", { name: "New task" }));
    expect(await screen.findByTestId("task-create-sheet")).toBeTruthy();

    expect((screen.getByLabelText("Due") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Priority") as HTMLSelectElement).value).toBe("");
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe("");

    await userEvent.type(screen.getByLabelText("Title"), "No prefill");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => {
      expect(fetcher.mock.calls.some(([path, init]) => String(path) === "/api/tasks" && init?.method === "POST")).toBe(true);
    });
    const createCall = fetcher.mock.calls.find(([path, init]) => String(path) === "/api/tasks" && init?.method === "POST");
    const body = JSON.parse(String(createCall?.[1]?.body));
    expect(body).toMatchObject({ title: "No prefill" });
    for (const field of ["dueAt", "priority", "projectId", "situationId", "commitmentId", "role"]) {
      expect(body).not.toHaveProperty(field);
    }
  });

  it("restores focus to New task when create closes", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } }),
    ));
    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("No all open tasks");
    const trigger = screen.getByRole("button", { name: "New task" });

    await userEvent.click(trigger);
    expect(await screen.findByTestId("task-create-sheet")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Close panel" }));
    await waitFor(() => expect(screen.queryByTestId("task-create-sheet")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("revalidates the active Work query exactly once through the runtime seam on confirmed create", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path === "/api/tasks" && init?.method === "POST") {
        return new Response(JSON.stringify({ task: { task_id: "tsk_aaaaaaaa11111111" }, history: {}, replayed: false }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetcher);
    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("No all open tasks");
    const before = listTaskGets(fetcher).length;

    await userEvent.click(screen.getByRole("button", { name: "New task" }));
    await userEvent.type(await screen.findByLabelText("Title"), "Reconciled");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(listTaskGets(fetcher).length).toBe(before + 1));
    // No extra list read is invented: the one post-create read is the seam's.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(listTaskGets(fetcher).length).toBe(before + 1);
  });

  it("publishes create success into the mutation feedback live region", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path === "/api/tasks" && init?.method === "POST") {
        return new Response(JSON.stringify({ task: { task_id: "tsk_aaaaaaaa11111111" }, history: {}, replayed: false }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (path.startsWith("/api/commitments")) {
        return new Response(JSON.stringify({ commitments: [] }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetcher);
    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("No all open tasks");
    await userEvent.click(screen.getByRole("button", { name: "New task" }));
    await userEvent.type(await screen.findByLabelText("Title"), "Feedback task");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByTestId("mutation-feedback-region")).toBeTruthy();
    expect(screen.getByTestId(/^mutation-feedback-live-task:create:confirmed:/)).toHaveTextContent(
      /Task created/,
    );
  });
});

  it("REVIEW SCRATCH: does not strand focus when an unrelated poll interleaves before the mutation's own confirm", async () => {
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const first = rowOf("tsk_aaaaaaaa11111111", "Leaves the filter");
    const second = rowOf("tsk_bbbbbbbb22222222", "Takes its place");
    let closed = false;
    let releaseClose: () => void = () => undefined;
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.includes("/transition") && method === "POST") {
        await new Promise<void>((resolve) => { releaseClose = () => resolve(); });
        closed = true;
        return body({ task: { ...first, version: 3, lifecycle_state: "completed" } });
      }
      if (path === `/api/tasks/${first.task_id}`) return body({ task: first });
      if (path === `/api/tasks/${second.task_id}`) return body({ task: second });
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: closed ? [second] : [first, second] });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Leaves the filter");

    const user = userEvent.setup();
    const rows = screen.getAllByTestId("task-list-row");
    await user.click(within(rows[0]).getByTestId("task-close-trigger"));
    // Dispatch the close confirm; the POST stalls on releaseClose.
    void user.click(within(rows[0]).getByTestId("task-close-confirm"));

    // An unrelated background poll interleaves while the close is still in flight
    // and resolves first, showing the pre-close list (the server hasn't processed
    // the close yet).
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
      await Promise.resolve();
    });

    // Now let the close itself confirm.
    releaseClose();
    await waitFor(() => expect(screen.queryByText("Leaves the filter")).toBeNull());
    await act(async () => {
      await new Promise<void>((resolve) => { requestAnimationFrame(() => resolve()); });
      await new Promise<void>((resolve) => { requestAnimationFrame(() => resolve()); });
    });

    // eslint-disable-next-line no-console
    console.log("REVIEW SCRATCH activeElement:", document.activeElement?.tagName, document.activeElement?.textContent, document.activeElement === document.body);
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement?.textContent).toContain("Takes its place");
  });
