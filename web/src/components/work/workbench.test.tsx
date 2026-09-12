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

  it("catches focus when a second row's write confirms after the first", async () => {
    /*
      Two rows triaged in quick succession, both writes in flight at once.

      An earlier design armed a single focus handoff when a write was dispatched
      and opened it on the next confirmed mutation in the session. Neither signal
      carried a Task identity — a list change cannot — so the first row's
      confirmation opened the gate for the handoff belonging to the second, and
      the list update that removed the first row spent it while the second row
      was still there. When the second row really did go, nothing was left to
      catch focus and it fell to `document.body`: the keyboard user is dropped at
      the top of the document with no sign their action succeeded.

      Restoring on focus actually being lost cannot make that mistake. There is
      nothing to arm and nothing to spend early — the first row leaving costs the
      user no focus, and the second row leaving is caught because it does.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const alpha = rowOf("tsk_aaaaaaaa11111111", "Confirms first");
    const bravo = rowOf("tsk_bbbbbbbb22222222", "Confirms second");
    const charlie = rowOf("tsk_cccccccc33333333", "Takes the place");
    let listed = [alpha, bravo, charlie];
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    // Each close is held open so both are in flight together, and released in order.
    const release: Record<string, () => void> = {};
    const inFlight = (taskId: string) =>
      new Promise<void>((resolve) => {
        release[taskId] = resolve;
      });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.includes("/transition") && method === "POST") {
        const subject = [alpha, bravo, charlie].find((row) => path.includes(row.task_id))!;
        await inFlight(subject.task_id);
        // The server decides membership: a closed Task is gone from an open view.
        listed = listed.filter((row) => row.task_id !== subject.task_id);
        return body({ task: { ...subject, version: 3, lifecycle_state: "completed" } });
      }
      for (const row of [alpha, bravo, charlie]) {
        if (path === `/api/tasks/${row.task_id}`) return body({ task: row });
      }
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Confirms first");

    const user = userEvent.setup();
    const rows = screen.getAllByTestId("task-list-row");

    // Close the first row; its write is held open.
    await user.click(within(rows[0]).getByTestId("task-close-trigger"));
    await user.click(within(rows[0]).getByTestId("task-close-confirm"));
    await waitFor(() => expect(release[alpha.task_id]).toEqual(expect.any(Function)));

    // Move to the second row and close it too, while the first is still in flight.
    await user.click(within(rows[1]).getByTestId("task-close-trigger"));
    await user.click(within(rows[1]).getByTestId("task-close-confirm"));
    await waitFor(() => expect(release[bravo.task_id]).toEqual(expect.any(Function)));

    // The first write lands and its row leaves, while the user's row is still here.
    await act(async () => {
      release[alpha.task_id]();
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText("Confirms first")).toBeNull());

    // Now the row the user was actually in goes.
    await act(async () => {
      release[bravo.task_id]();
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText("Confirms second")).toBeNull());

    await waitFor(() => {
      expect(document.activeElement).not.toBe(document.body);
      expect(document.activeElement?.textContent).toContain("Takes the place");
    });
  });

  it("returns focus to the Task the user was in, not to whatever holds its old place", async () => {
    /*
      The remembered position is where the row sat when focus arrived, and rows
      above it can leave in the meantime. If restoration went by position alone
      it would hand focus to a different Task than the one the user was reading,
      which is worse than the body: it looks deliberate and it is wrong.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const above = rowOf("tsk_aaaaaaaa11111111", "Leaves from above");
    const reading = rowOf("tsk_bbbbbbbb22222222", "Where the user was");
    const below = rowOf("tsk_cccccccc33333333", "Not where the user was");
    let listed = [above, reading, below];
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      for (const row of [above, reading, below]) {
        if (path === `/api/tasks/${row.task_id}`) return body({ task: row });
      }
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Where the user was");

    /*
      Focus a control inside the middle row and then lose it the way an
      unmounting control does — the element leaves the document and takes focus
      with it, while the row it belonged to is still there.
    */
    const user = userEvent.setup();
    const rows = screen.getAllByTestId("task-list-row");
    await user.click(within(rows[1]).getByTestId("task-close-trigger"));
    const confirm = within(rows[1]).getByTestId("task-close-confirm");
    confirm.focus();
    expect(document.activeElement).toBe(confirm);
    confirm.remove();
    expect(document.activeElement).toBe(document.body);

    // The row above leaves, so the user's row is no longer at the remembered index.
    listed = [reading, below];
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText("Leaves from above")).toBeNull());
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement?.textContent).toContain("Where the user was");
  });

  it("catches focus in the Board perspective too, not only in the List", async () => {
    /*
      Board lays its Tasks out as cards rather than rows, and Calendar again
      differently. Resolving rows by one perspective's own container label found
      nothing in the others, so every branch that places focus was dead there and
      restoration always fell through to the page heading — throwing a keyboard
      user to the top of the document instead of to the Task beside the one that
      left.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const leaving = rowOf("tsk_aaaaaaaa11111111", "Leaves the board");
    const staying = rowOf("tsk_bbbbbbbb22222222", "Stays on the board");
    let listed = [leaving, staying];
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      for (const row of [leaving, staying]) {
        if (path === `/api/tasks/${row.task_id}`) return body({ task: row });
      }
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open&perspective=board");
    renderFromUrl();
    await screen.findByText("Leaves the board");
    expect(screen.getByRole("region", { name: "Task lifecycle board" })).toBeTruthy();

    // The user is on a card; its Task then leaves the filter on a refresh.
    const card = screen.getByRole("link", { name: /Leaves the board/ });
    card.focus();
    expect(document.activeElement).toBe(card);

    listed = [staying];
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText("Leaves the board")).toBeNull());
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // Focus lands on the Task beside it, not on the page heading.
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement?.tagName).not.toBe("H1");
    expect(document.activeElement?.textContent).toContain("Stays on the board");
  });

  it("does not pull focus back when the user put it down themselves", async () => {
    /*
      Focus on the document body is not always focus that was taken. A user who
      clicks the page background has deliberately put it down, and a refresh that
      arrives afterwards — a plain freshness poll, with no mutation anywhere and
      nothing leaving the list — must not haul them back into the list and scroll
      them there, over and over on every poll after.

      What separates the two is whether the control they were in is still in the
      document: if it is, nothing was taken from them.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const first = rowOf("tsk_aaaaaaaa11111111", "Row one");
    const second = rowOf("tsk_bbbbbbbb22222222", "Row two");
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      for (const row of [first, second]) {
        if (path === `/api/tasks/${row.task_id}`) return body({ task: row });
      }
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: [first, second] });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Row one");

    // The user visits a row and then puts focus down on the page background.
    const rows = screen.getAllByTestId("task-list-row");
    const link = within(rows[0]).getByRole("link");
    link.focus();
    link.blur();
    expect(document.activeElement).toBe(document.body);

    // A refresh arrives. Membership has not changed and nothing was mutated.
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // Focus is where the user left it, and the row they visited is still there.
    expect(document.activeElement).toBe(document.body);
    expect(screen.getByText("Row one")).toBeTruthy();
  });

  it("returns focus to the surface when the sheet closes on a Task that has left", async () => {
    /*
      Detail restores focus to the row it was opened from. If that Task leaves
      the filter while the sheet is open, the row is gone and the remembered
      trigger is a detached node — focusing it does nothing whatever, silently,
      and when the list has nothing left to fall back to the user closes the
      sheet onto the document body, with no sign it closed and nowhere to arrow
      from.
    */
    const only = {
      task_id: "tsk_aaaaaaaa11111111", title: "Open in the sheet", lifecycle_state: "open",
      priority: null, due_at: null, scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    };
    let listed = [only];
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === `/api/tasks/${only.task_id}`) return body({ task: only });
      if (path.includes("/comments")) return body({ comments: [] });
      if (path.includes("/history")) return body({ history: [] });
      if (path.startsWith("/api/commitments")) return body({ commitments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Open in the sheet");

    const user = userEvent.setup();
    await user.click(screen.getByRole("link", { name: /Open in the sheet/ }));
    await screen.findByRole("dialog");

    // While the sheet is open the Task leaves the filter, and nothing replaces it.
    listed = [];
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // The user is returned to the Work surface, not stranded on the document body.
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Work", level: 1 }));
  });

  it("waits a frame before deciding focus was lost", async () => {
    /*
      The decision is "has focus fallen to nothing", and it cannot be taken in
      the same commit that removed the row: at that instant focus is on the body
      by definition, and anything about to claim it deliberately — a sheet
      opening, a dialog, the detail surface — has not had its turn yet. Deciding
      then would read every such handover as a loss and take focus from whatever
      was on its way to it. The answer is only true after a frame.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const leaving = rowOf("tsk_aaaaaaaa11111111", "Leaves the filter");
    const staying = rowOf("tsk_bbbbbbbb22222222", "Takes its place");
    let listed = [leaving, staying];
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      for (const row of [leaving, staying]) {
        if (path === `/api/tasks/${row.task_id}`) return body({ task: row });
      }
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Leaves the filter");

    const rows = screen.getAllByTestId("task-list-row");
    const link = within(rows[0]).getByRole("link");
    link.focus();

    // Hold the frame, so the commit and the decision can be told apart.
    const frames: FrameRequestCallback[] = [];
    const realFrame = globalThis.requestAnimationFrame;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      frames.push(callback);
      return frames.length;
    });
    vi.stubGlobal("cancelAnimationFrame", () => undefined);

    try {
      listed = [staying];
      await act(async () => {
        fireEvent(window, new Event("focus"));
        await Promise.resolve();
      });
      await waitFor(() => expect(screen.queryByText("Leaves the filter")).toBeNull());

      // The row is gone and the frame has not run: nothing has been decided yet.
      expect(frames.length).toBeGreaterThan(0);
      expect(document.activeElement).toBe(document.body);

      // Now the frame runs, and only now is focus placed.
      await act(async () => {
        for (const frame of frames.splice(0)) frame(0);
      });
      expect(document.activeElement?.textContent).toContain("Takes its place");
    } finally {
      vi.stubGlobal("requestAnimationFrame", realFrame);
    }
  });

  it("forgets a row that left while the user was working elsewhere", async () => {
    /*
      The record of where focus was is maintained, not merely spent. A user who
      leaves the list deliberately — into search, say — and whose old row then
      leaves the filter is owed nothing: that row is finished. Kept, the record
      would be read on some later change as "focus was taken from this row", and
      a plain freshness poll would pull the user out of wherever they had got to
      and back into the list.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const visited = rowOf("tsk_aaaaaaaa11111111", "Row the user visited");
    const stays = rowOf("tsk_bbbbbbbb22222222", "Row that stays");
    let listed = [visited, stays];
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      for (const row of [visited, stays]) {
        if (path === `/api/tasks/${row.task_id}`) return body({ task: row });
      }
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Row the user visited");

    // The user visits a row, then deliberately leaves the list for the search box.
    const rows = screen.getAllByTestId("task-list-row");
    within(rows[0]).getByRole("link").focus();
    const search = screen.getByLabelText("Search tasks");
    search.focus();
    expect(document.activeElement).toBe(search);

    // The row they had visited leaves the filter while they are typing.
    listed = [stays];
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText("Row the user visited")).toBeNull());
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });
    expect(document.activeElement).toBe(search);

    // Later the user puts focus down, and an ordinary poll arrives.
    search.blur();
    expect(document.activeElement).toBe(document.body);
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // Nothing was owed, so nothing was taken.
    expect(document.activeElement).toBe(document.body);
  });

  it("follows the row as the list changes around it", async () => {
    /*
      Where a row sits is remembered when focus arrives, and the list moves
      underneath it: rows leave from above, others arrive, and none of it fires a
      focus event to correct the remembered position. By the time the user's own
      row goes, a stale position names somebody else's row — and because it names
      a row that really is there, nothing downstream can notice it is wrong.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const above = [rowOf("tsk_aaaaaaaa11111111", "Above one"), rowOf("tsk_bbbbbbbb22222222", "Above two")];
    const kept = [rowOf("tsk_cccccccc33333333", "Kept one"), rowOf("tsk_dddddddd44444444", "Kept two")];
    const standing = rowOf("tsk_eeeeeeee55555555", "Where the user is");
    const arrived = [rowOf("tsk_ffffffff66666666", "Arrived one"), rowOf("tsk_99999999aaaaaaaa", "Arrived two")];
    const everything = [...above, ...kept, standing, ...arrived];
    let listed = [...above, ...kept, standing];
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      for (const row of everything) {
        if (path === `/api/tasks/${row.task_id}`) return body({ task: row });
      }
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Where the user is");

    // The user is in the last row of five, at position 4.
    const rows = screen.getAllByTestId("task-list-row");
    const held = within(rows[4]).getByRole("link");
    held.focus();

    // The two rows above leave and two more arrive below. The user touches
    // nothing and keeps focus; their row is now at position 2, not 4.
    listed = [...kept, standing, ...arrived];
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText("Above one")).toBeNull());
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });
    expect(document.activeElement).toBe(held);

    // Now their own row goes. The list is long enough that a stale position
    // still names a real row, so only a refreshed one gives the right answer.
    listed = [...kept, ...arrived];
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText("Where the user is")).toBeNull());
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // Focus lands on what took their place, not on a row two positions further on.
    expect(document.activeElement?.textContent).toContain("Arrived one");
  });

  it("catches focus in the Calendar perspective too", async () => {
    /*
      Calendar lays its Tasks out as dated markers. They carried no row identity
      at all, so focus was never recorded there: a keyboard user on a marker
      whose Task left the filter was dropped on the document body with nothing to
      catch them — and a record left over from the List survived the switch and
      was spent on the first Calendar refresh.
    */
    const rowOf = (id: string, title: string, dueAt: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: dueAt,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const leaving = rowOf("tsk_aaaaaaaa11111111", "Dated and leaving", "2026-09-13T12:00:00Z");
    const staying = rowOf("tsk_bbbbbbbb22222222", "Dated and staying", "2026-09-14T12:00:00Z");
    let listed = [leaving, staying];
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      for (const row of [leaving, staying]) {
        if (path === `/api/tasks/${row.task_id}`) return body({ task: row });
      }
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open&perspective=calendar");
    renderFromUrl();
    await screen.findByText("Dated and leaving");

    const marker = screen.getByRole("link", { name: /Dated and leaving/ });
    marker.focus();
    expect(document.activeElement).toBe(marker);

    listed = [staying];
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText("Dated and leaving")).toBeNull());
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement?.tagName).not.toBe("H1");
    expect(document.activeElement?.textContent).toContain("Dated and staying");
  });

  it("keeps the record through a refresh that lands while a write is running", async () => {
    /*
      The mainline success path, interrupted. A row disables the control the user
      operated while its write runs, and a browser answers that by dropping focus
      to the document body. If an ordinary refresh lands in that window — the
      freshness poll, another row's write, pagination — and is read as "the user
      put focus down", the record is thrown away; then the write confirms, the
      row leaves, and there is nothing left to catch focus.
    */
    const rowOf = (id: string, title: string) => ({
      task_id: id, title, lifecycle_state: "open", priority: null, due_at: null,
      scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
    });
    const working = rowOf("tsk_aaaaaaaa11111111", "Being worked on");
    const neighbour = rowOf("tsk_bbbbbbbb22222222", "The neighbour");
    let listed = [working, neighbour];
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      for (const row of [working, neighbour]) {
        if (path === `/api/tasks/${row.task_id}`) return body({ task: row });
      }
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open");
    renderFromUrl();
    await screen.findByText("Being worked on");

    // The user is on a control in the first row; it is then disabled under them.
    const rows = screen.getAllByTestId("task-list-row");
    const control = within(rows[0]).getByRole("combobox") as HTMLSelectElement;
    control.focus();
    expect(document.activeElement).toBe(control);
    // jsdom will not blur a disabled element, so produce the browser's end
    // state directly: focus on the body, the control it let go of disabled.
    control.blur();
    control.disabled = true;
    expect(document.activeElement).toBe(document.body);

    // A refresh lands while the write is still running. Membership is unchanged.
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // The write now confirms and the Task leaves the filter.
    listed = [neighbour];
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText("Being worked on")).toBeNull());
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // Focus was caught, not dropped by the refresh that came through first.
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement?.textContent).toContain("The neighbour");
  });

  it("records the Calendar marker the user is on, not the Task's first marker", async () => {
    /*
      One Task holds several places in the Calendar at once — a marker for its
      deadline, one for planned work, one for when it becomes available — and all
      of them carry the same Task identity. Looking the position up by identity
      answers with the first, so a user standing at the foot of the calendar was
      recorded as standing near the top, and sent there when their marker left.
    */
    const taskOf = (id: string, title: string, dates: Partial<Record<"due_at" | "scheduled_at" | "deferred_until", string>>) => ({
      task_id: id, title, lifecycle_state: "open", priority: null,
      due_at: null, scheduled_at: null, deferred_until: null, archived_at: null,
      created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z", version: 2,
      ...dates,
    });
    // The multi-dated Task brackets the others: earliest marker and latest marker.
    const spread = taskOf("tsk_aaaaaaaa11111111", "Spread across the calendar", {
      due_at: "2026-09-10T12:00:00Z",
      scheduled_at: "2026-09-13T12:00:00Z",
      deferred_until: "2026-09-15T12:00:00Z",
    });
    const early = taskOf("tsk_bbbbbbbb22222222", "Early neighbour", { due_at: "2026-09-11T12:00:00Z" });
    const late = taskOf("tsk_cccccccc33333333", "Late neighbour", { due_at: "2026-09-16T12:00:00Z" });
    let listed = [spread, early, late];
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });

    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      for (const row of [spread, early, late]) {
        if (path === `/api/tasks/${row.task_id}`) return body({ task: row });
      }
      if (path.includes("/comments")) return body({ comments: [] });
      return body({ tasks: listed });
    }));

    history.replaceState(null, "", "/work?view=all-open&perspective=calendar");
    renderFromUrl();
    await screen.findByText("Late neighbour");

    // The user is on the Task's LAST marker, near the foot of the calendar.
    const markers = screen.getAllByRole("link", { name: /Spread across the calendar/ });
    expect(markers.length).toBeGreaterThan(1);
    const standing = markers[markers.length - 1];
    standing.focus();

    // That Task leaves, taking every one of its markers with it.
    listed = [early, late];
    await act(async () => {
      fireEvent(window, new Event("focus"));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByText("Spread across the calendar")).toBeNull());
    await act(async () => {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => resolve());
      });
    });

    // Focus lands where the user actually was, not at the Task's first marker.
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement?.textContent).toContain("Late neighbour");
    expect(document.activeElement?.textContent).not.toContain("Early neighbour");
  });

  it("does not move focus on a later refresh after a mutation that kept the Task", async () => {
    /*
      A Status change usually leaves the Task right where it was, so no focus
      move is owed. `rows` then keeps changing for reasons of its own — the
      freshness poll, another Task's mutation — and none of those changes cost
      the user the focus they are holding. Focus is only placed when it has
      actually fallen to nothing, so the user keeps working where they are.
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

    // Focus was not stolen by a list change that had nothing to do with it.
    expect(document.activeElement).toBe(parked);
  });

  it("does not move focus when the user pages away before a mutation settles", async () => {
    /*
      Independent review reproduced this. Paging changes the whole visible set,
      so the Task the user was in is trivially absent from the new
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
      still empties the rows. Reading that empty list as "the Task is gone"
      would pull focus to the heading, away from the Commitments
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

  it("leaves focus alone when a mutation fails and the Task later leaves anyway", async () => {
    /*
      A failed mutation moved nothing and cost the user no focus, so it is owed
      no focus placement — not then, and not when the Task later leaves the
      filter for reasons of its own. Focus that is somewhere real is never taken
      from the user to be placed somewhere they did not ask to be.
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

