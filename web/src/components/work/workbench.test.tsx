import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Workbench } from "@/components/work/workbench";
import { parseWorkUrlState } from "@/lib/api/work-url";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); history.replaceState(null, "", "/"); });
function renderFromUrl() { return render(<Workbench initialState={parseWorkUrlState(Object.fromEntries(new URLSearchParams(location.search)))} />); }

describe("Work surface", () => {
  it("reserves the shell capture clearance below scrollable Work content", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } })));
    history.replaceState(null, "", "/work?view=today");
    renderFromUrl();
    await screen.findByText("No today tasks");
    expect(screen.getByRole("region", { name: "Work" }).className).toContain("pb-24");
  });

  it("keeps the approved view order and asks the server for exact Today semantics", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } })); vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=today");
    renderFromUrl();
    const navigation = screen.getByRole("navigation", { name: "Work views" });
    expect(Array.from(navigation.querySelectorAll("button"), (button) => button.textContent)).toEqual([
      "Overdue", "Today", "Upcoming", "Unscheduled", "Waiting", "Blocked", "Recently updated", "All open", "Completed", "Commitments",
    ]);
    expect(await screen.findByText("No today tasks")).toBeTruthy();
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
    expect(await screen.findByRole("region", { name: "Task lifecycle board" })).toBeTruthy();
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
    const detail = { ...task, description: null, evidence_state: "proposed", origin_evidence_ref: "cap_origin0001origin0001", closure_evidence_ref: null, closure_history_id: null, commitment_id: null, role: null, opened_at: task.created_at, closed_at: null };
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
    await userEvent.click(screen.getByRole("button", { name: "Waiting" }));
    expect((await screen.findByRole("link", { name: /Synthetic follow up/ })).getAttribute("href")).toBe("/work/tasks/tsk_aaaaaaaa11111111");
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/tasks?pageSize=50&workView=waiting&archived=exclude", expect.objectContaining({ cache: "no-store" })));
  });

  it("distinguishes terminal completion from terminal cancellation", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ tasks: [
      { task_id: "tsk_aaaaaaaa11111111", title: "Finished", lifecycle_state: "completed", priority: null, due_at: null, archived_at: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z" },
      { task_id: "tsk_bbbbbbbb22222222", title: "Withdrawn", lifecycle_state: "cancelled", priority: null, due_at: null, archived_at: null, created_at: "2026-08-21T12:00:00Z", updated_at: "2026-08-21T12:00:00Z" },
    ] }), { status: 200, headers: { "content-type": "application/json" } })));
    history.replaceState(null, "", "/work?view=completed"); renderFromUrl();
    expect(await screen.findByText(/terminal completion/)).toBeTruthy();
    expect(screen.getByText(/terminal cancellation/)).toBeTruthy();
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
    await userEvent.click(screen.getByRole("button", { name: "Preview change" }));
    expect(await screen.findByText(/Persisted preview: 1 affected/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Confirm exact preview" }));
    expect(await screen.findByText(/Persisted confirmation: 1 affected/)).toBeTruthy();
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
    await screen.findByText(/Persisted preview/);
    await userEvent.click(screen.getByRole("button", { name: "Confirm exact preview" }));
    await screen.findByText(/Work plane is unavailable/);
    expect(screen.getByText(/Preview bulk_aaaaaaaa11111111/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Confirm exact preview" }));
    expect(await screen.findByText(/Replayed confirmation/)).toBeTruthy();
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
    await userEvent.click(screen.getByRole("button", { name: "Today" }));
    expect(await screen.findByRole("option", { name: "Revised schedule" })).toBeTruthy();
    expect(screen.queryByLabelText(/Commitment ID/i)).toBeNull();
  });

  it("hydrates exact URL state and honors a validated timezone", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher); history.replaceState(null, "", "/work?view=upcoming&q=plan&tz=America%2FNew_York&archived=only"); renderFromUrl();
    await screen.findByText("No matching upcoming tasks");
    const path = String(fetcher.mock.calls[0]?.[0]); expect(path).toContain("workView=upcoming"); expect(path).toContain("q=plan"); expect(path).toContain("archived=only"); expect(path).toContain("timezone=America%2FNew_York");
  });
});
