import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SearchPage } from "./search-page";
import { TaskRuntimeProvider } from "@/components/work/task-runtime-provider";
import { presentFederatedHits, type FederatedHit } from "@/lib/search/presentation";
import { collectLevel1Copy } from "@/lib/ui/user-copy";

const routerPush = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/search",
  useRouter: () => ({ push: routerPush, refresh: vi.fn() }),
}));

afterEach(() => {
  cleanup();
  routerPush.mockReset();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const TASK_HIT = {
  domain: "tasks",
  item: {
    task_id: "tsk_aaaaaaaa11111111",
    title: "Morning task",
    lifecycle_state: "open",
    priority: null,
    due_at: null,
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    version: 1,
  },
};

describe("Search page", () => {
  it("is Search-only, focuses the query field, and is not a destination launcher", () => {
    render(<SearchPage initialQuery="" />);
    const field = screen.getByTestId("search-command-input");
    expect(field).toHaveFocus();
    expect(screen.getByRole("heading", { name: "Search", level: 1 })).toBeTruthy();
    expect(screen.getByTestId("search-command-list")).toHaveTextContent("Start typing to search.");
    expect(screen.queryByRole("link", { name: "Today" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Work" })).toBeNull();
    expect(screen.queryByRole("link", { name: "People" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Review" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Quick Capture" })).toBeNull();
  });

  it("summarizes coverage with omitted domains still omitted", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          shape: "backend",
          query: "morning",
          hits: [TASK_HIT],
          coverage: [
            { domain: "tasks", state: "searched", hitCount: 1 },
            { domain: "goodnotes", state: "searched", hitCount: 0 },
            { domain: "knowledge", state: "knowledge_not_enrolled", hitCount: 0 },
            { domain: "meetings", state: "omitted", hitCount: 0, reason: "no_search_capability" },
          ],
          disclosure: {
            scope: "search",
            coverage: "partial",
            freshnessAt: null,
            authority: "derived",
            limitations: ["knowledge is not enrolled"],
            truncated: false,
          },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    render(<SearchPage initialQuery="" />);
    await user.type(screen.getByTestId("search-command-input"), "morning");

    expect(await screen.findByTestId("search-group-tasks")).toHaveTextContent("Morning task");
    const coverage = screen.getByTestId("search-coverage");
    expect(coverage).toHaveTextContent("goodnotes: searched");
    expect(coverage).not.toHaveTextContent("goodnotes: omitted");
    expect(coverage).toHaveTextContent("meetings: omitted (no_search_capability)");
    expect(coverage).toHaveTextContent("knowledge_not_enrolled");
    expect(screen.getByRole("button", { name: "Quick Capture" })).toBeTruthy();
    expect(collectLevel1Copy(document.body)).not.toMatch(/coverage token/i);
  });

  it("does not treat all-unavailable zero hits as empty", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          shape: "backend",
          query: "morning",
          hits: [],
          coverage: [
            { domain: "tasks", state: "unavailable", hitCount: 0 },
            { domain: "meetings", state: "omitted", hitCount: 0, reason: "no_search_capability" },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    render(<SearchPage initialQuery="morning" />);
    expect(await screen.findByTestId("search-unavailable")).toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByTestId("search-empty")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("search-coverage")).toHaveTextContent("meetings: omitted"));
  });
});


/* ---------------------------------------------------------------------------
 * Task activation (WP-TUX-06 Worker B)
 * ------------------------------------------------------------------------ */

const TASK_FIELDS = {
  priority: null,
  due_at: null,
  scheduled_at: null,
  deferred_until: null,
  archived_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  version: 4,
} as const;

function taskHit(taskId: string, title: string, lifecycleState = "open") {
  return { domain: "tasks", item: { task_id: taskId, title, lifecycle_state: lifecycleState, ...TASK_FIELDS } };
}

function commitmentHit(commitmentId: string, title: string) {
  return {
    domain: "commitments",
    item: {
      commitment_id: commitmentId,
      title,
      state: "open",
      direction: "owed_by_me",
      counterparty: null,
      due_at: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  };
}

function searchBody(query: string, hits: readonly unknown[]) {
  const domains = new Set(hits.map((hit) => (hit as { domain: string }).domain));
  return {
    shape: "backend",
    query,
    hits,
    coverage: [...domains].map((domain) => ({
      domain,
      state: "searched",
      hitCount: hits.filter((hit) => (hit as { domain: string }).domain === domain).length,
    })),
    disclosure: {
      scope: "search",
      coverage: "full",
      freshnessAt: null,
      authority: "derived",
      limitations: [],
      truncated: false,
    },
  };
}

function canonicalTask(taskId: string) {
  return {
    task_id: taskId,
    title: "Canonical title",
    description: null,
    lifecycle_state: "open",
    evidence_state: "accepted",
    origin_kind: "direct_principal" as const,
    origin_evidence_ref: null,
    closure_evidence_ref: null,
    accepted_by_review_decision_id: null,
    acceptance_kind: null,
    closure_history_id: null,
    version: 9,
    priority: null,
    due_at: null,
    scheduled_at: null,
    deferred_until: null,
    archived_at: null,
    commitment_id: null,
    role: null,
    project_id: null,
    situation_id: null,
    opened_at: "2026-01-01T00:00:00Z",
    closed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

/**
 * One fetch surface for the whole Search + Task-sheet path, with a mutable hit
 * set so a test can refresh the result list while the sheet is open.
 */
function installFetch(
  initialHits: readonly unknown[],
  canonical?: (taskId: string) => Response,
) {
  const state = { hits: initialHits };
  const paths: string[] = [];
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const raw =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : (input as Request).url;
    const parsed = new URL(raw, "http://localhost");
    const path = parsed.pathname;
    paths.push(`${parsed.pathname}${parsed.search}`);
    if (path === "/api/search") {
      return Response.json(searchBody(parsed.searchParams.get("q") ?? "", state.hits));
    }
    if (/^\/api\/tasks\/[^/]+\/comments$/.test(path)) return Response.json({ comments: [] });
    if (/^\/api\/tasks\/[^/]+\/history$/.test(path)) return Response.json({ history: [] });
    if (path === "/api/commitments") return Response.json({ commitments: [] });
    const detail = /^\/api\/tasks\/([^/]+)$/.exec(path);
    if (detail) {
      return canonical ? canonical(detail[1]) : Response.json({ task: canonicalTask(detail[1]) });
    }
    throw new Error(`unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return { state, paths };
}

/** Exact canonical Task reads — never the comments, history or search calls. */
function canonicalTaskReads(paths: readonly string[]): readonly string[] {
  return paths.filter((path) => /^\/api\/tasks\/[^/?]+$/.test(path));
}

function renderSearch(initialQuery = "") {
  return render(
    <TaskRuntimeProvider principalId="prin_test" sessionEpoch="epoch-test">
      <SearchPage initialQuery={initialQuery} />
    </TaskRuntimeProvider>,
  );
}

function resultRows(): readonly HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[data-search-result="true"]'));
}

/** Waits for the result list itself to settle — the open sheet also shows a title. */
async function waitForResultKeys(keys: readonly string[]) {
  await waitFor(() =>
    expect(resultRows().map((row) => row.getAttribute("data-result-key"))).toEqual([...keys]),
  );
}

async function search(query: string) {
  const user = userEvent.setup();
  renderSearch();
  await user.type(screen.getByTestId("search-command-input"), query);
  return user;
}

describe("Search Task activation", () => {
  it("carries no version into the UI layer, so the projection cannot be write authority", () => {
    const hit = taskHit("tsk_aaaaaaaa11111111", "Morning task") as unknown as FederatedHit;
    const [group] = presentFederatedHits([hit]);
    const activation = group.hits[0].task;
    expect(activation?.taskId).toBe("tsk_aaaaaaaa11111111");
    expect(activation?.seed.title).toBe("Morning task");
    expect(Object.keys(activation?.seed ?? {})).not.toContain("version");
    expect("version" in (activation?.seed ?? {})).toBe(false);
  });


  it("opens the canonical Task sheet in place instead of navigating away", async () => {
    installFetch([taskHit("tsk_aaaaaaaa11111111", "Morning task")]);
    const user = await search("morning");

    const row = await screen.findByRole("link", { name: /Morning task/ });
    // The e2e contract pins this: a Task hit stays a link named by its title.
    expect(row.tagName).toBe("A");
    expect(row.getAttribute("href")).toBe("/work/tasks/tsk_aaaaaaaa11111111");

    await user.click(row);

    expect(await screen.findByTestId("task-compact-sheet")).toBeTruthy();
    expect(routerPush).not.toHaveBeenCalled();
  });

  it("still navigates for a non-Task hit", async () => {
    installFetch([commitmentHit("cmt_bbbbbbbb22222222", "Send the draft")]);
    const user = await search("draft");

    const row = await screen.findByRole("link", { name: /Send the draft/ });
    await user.click(row);

    await waitFor(() =>
      expect(routerPush).toHaveBeenCalledWith("/work/commitments/cmt_bbbbbbbb22222222"),
    );
    expect(screen.queryByTestId("task-compact-sheet")).toBeNull();
  });

  it("reads no canonical Task until one is activated, then reads exactly that one", async () => {
    const { paths } = installFetch([
      taskHit("tsk_aaaaaaaa11111111", "Morning task"),
      taskHit("tsk_bbbbbbbb22222222", "Afternoon task"),
      taskHit("tsk_cccccccc33333333", "Evening task"),
    ]);
    const user = await search("task");

    await screen.findByRole("link", { name: /Morning task/ });
    await screen.findByRole("link", { name: /Evening task/ });
    // Rendering a result list is not a reason to read three Tasks.
    expect(canonicalTaskReads(paths)).toEqual([]);

    await user.click(screen.getByRole("link", { name: /Afternoon task/ }));
    await screen.findByTestId("task-compact-sheet");

    await waitFor(() =>
      expect(canonicalTaskReads(paths)).toEqual(["/api/tasks/tsk_bbbbbbbb22222222"]),
    );
  });

  it("never renders a raw lifecycle token in a Search result", async () => {
    installFetch([taskHit("tsk_aaaaaaaa11111111", "Morning task", "in_progress")]);
    await search("morning");

    const group = await screen.findByTestId("search-group-tasks");
    expect(group).toHaveTextContent("In progress");
    expect(group.textContent ?? "").not.toMatch(/in_progress/);
    expect(collectLevel1Copy(document.body)).not.toMatch(/in_progress/);
  });

  it("returns focus to the result that opened the sheet", async () => {
    installFetch([
      taskHit("tsk_aaaaaaaa11111111", "Morning task"),
      taskHit("tsk_bbbbbbbb22222222", "Afternoon task"),
    ]);
    const user = await search("task");
    await screen.findByRole("link", { name: /Morning task/ });

    // Activate from the query field, so nothing but the focus contract can put
    // focus on the result row afterwards.
    await user.keyboard("{Enter}");
    await screen.findByTestId("task-compact-sheet");

    await user.click(screen.getByRole("button", { name: "Close panel" }));

    await waitFor(() => expect(resultRows()[0]).toHaveFocus());
  });

  it("falls back to the result standing in that position when a refresh removed the original", async () => {
    const handle = installFetch([
      taskHit("tsk_aaaaaaaa11111111", "Morning task"),
      taskHit("tsk_bbbbbbbb22222222", "Afternoon task"),
    ]);
    const user = await search("task");

    await user.click(await screen.findByRole("link", { name: /Morning task/ }));
    await screen.findByTestId("task-compact-sheet");

    // The result list refreshes underneath the open sheet and the originating
    // row is gone.
    handle.state.hits = [
      taskHit("tsk_dddddddd44444444", "Replacement task"),
      taskHit("tsk_eeeeeeee55555555", "Later task"),
    ];
    fireEvent.change(screen.getByTestId("search-command-input"), { target: { value: "refreshed" } });
    await waitForResultKeys(["tsk_dddddddd44444444", "tsk_eeeeeeee55555555"]);

    await user.click(screen.getByRole("button", { name: "Close panel" }));

    await waitFor(() => {
      const rows = resultRows();
      expect(rows).toHaveLength(2);
      expect(rows[0]).toHaveFocus();
      expect(within(rows[0]).getByText("Replacement task")).toBeTruthy();
    });
  });

  it("falls back to the previous result, and then to the query field, rather than the body", async () => {
    const handle = installFetch([
      taskHit("tsk_aaaaaaaa11111111", "Morning task"),
      taskHit("tsk_bbbbbbbb22222222", "Afternoon task"),
    ]);
    const user = await search("task");

    await user.click(await screen.findByRole("link", { name: /Afternoon task/ }));
    await screen.findByTestId("task-compact-sheet");

    handle.state.hits = [taskHit("tsk_dddddddd44444444", "Only task")];
    fireEvent.change(screen.getByTestId("search-command-input"), { target: { value: "refreshed" } });
    await waitForResultKeys(["tsk_dddddddd44444444"]);

    await user.click(screen.getByRole("button", { name: "Close panel" }));

    await waitFor(() => expect(resultRows()[0]).toHaveFocus());
    expect(document.activeElement).not.toBe(document.body);

    // Now the same close with no result left at all.
    await user.click(screen.getByRole("link", { name: /Only task/ }));
    await screen.findByTestId("task-compact-sheet");
    handle.state.hits = [];
    fireEvent.change(screen.getByTestId("search-command-input"), { target: { value: "nothing at all" } });
    await waitForResultKeys([]);

    await user.click(screen.getByRole("button", { name: "Close panel" }));

    await waitFor(() => expect(screen.getByTestId("search-command-input")).toHaveFocus());
    expect(document.activeElement).not.toBe(document.body);
  });

  it("exposes no mutation control when the canonical Task could not be read", async () => {
    installFetch(
      [taskHit("tsk_aaaaaaaa11111111", "Morning task")],
      () =>
        new Response(JSON.stringify({ error: { message: "upstream is down", code: "unavailable" } }), {
          status: 503,
          headers: { "content-type": "application/json" },
        }),
    );
    const user = await search("morning");

    await user.click(await screen.findByRole("link", { name: /Morning task/ }));
    const sheet = await screen.findByTestId("task-compact-sheet");

    await waitFor(() => expect(within(sheet).getByRole("button", { name: /Retry Task read/ })).toBeTruthy());
    expect(screen.queryByTestId("task-status-control")).toBeNull();
    expect(screen.queryByTestId("task-due-control")).toBeNull();
    expect(screen.queryByTestId("task-close-control")).toBeNull();

    // Positive control for the three queries above: with a canonical read that
    // succeeds, the same lookups do find controls. The absence asserted above is
    // therefore a fact about the unavailable Task, not about the query.
    cleanup();
    installFetch([taskHit("tsk_aaaaaaaa11111111", "Morning task")]);
    const second = await search("morning");
    await second.click(await screen.findByRole("link", { name: /Morning task/ }));
    expect(await screen.findByTestId("task-status-control")).toBeTruthy();
    expect(screen.getByTestId("task-close-control")).toBeTruthy();
    expect(screen.getByTestId("task-due-control")).toBeTruthy();
  });
});
