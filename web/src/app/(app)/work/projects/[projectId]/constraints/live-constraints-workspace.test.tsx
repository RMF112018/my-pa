import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PrincipalSession } from "@/contracts/identity";

const store = vi.hoisted(() => {
  let params = new URLSearchParams();
  let path = "/work/projects/prj_syn_0001/constraints";
  const listeners = new Set<() => void>();
  return {
    snapshot: () => params,
    path: () => path,
    go(href: string) {
      const [nextPath, query] = href.split("?");
      path = nextPath;
      params = new URLSearchParams(query ?? "");
      for (const listener of listeners) listener();
    },
    reset(query = "") {
      path = "/work/projects/prj_syn_0001/constraints";
      params = new URLSearchParams(query);
    },
    subscribe(listener: () => void) { listeners.add(listener); return () => listeners.delete(listener); },
  };
});

vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  const router = { push: store.go, replace: store.go, refresh: () => undefined };
  return {
    usePathname: store.path,
    useRouter: () => router,
    useSearchParams: () => useSyncExternalStore(store.subscribe, store.snapshot, store.snapshot),
  };
});

const reads = vi.hoisted(() => ({
  projects: vi.fn(), overview: vi.fn(), categories: vi.fn(), register: vi.fn(), detail: vi.fn(), history: vi.fn(),
}));

vi.mock("./constraint-live", () => ({
  readProjects: reads.projects,
  readOverview: reads.overview,
  readCategories: reads.categories,
  readRegister: reads.register,
  readDetail: reads.detail,
  readHistory: reads.history,
}));

import { AppShell } from "@/components/shell/app-shell";
import { syntheticConstraintWorkspace } from "@/lib/fixtures/constraints";
import type { ConstraintWorkspaceFixture } from "@/lib/fixtures/constraints";
import { DEFAULT_CONSTRAINT_URL_STATE } from "./constraint-url-state";
import { LiveConstraintsWorkspace } from "./live-constraints-workspace";

const PRINCIPAL: PrincipalSession = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "subject",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

let fixture: ConstraintWorkspaceFixture;
const complete = { scope: "constraints", coverage: "complete", freshnessAt: "2026-09-08T12:00:00Z", authority: "accepted", limitations: [], truncated: false } as const;
const ok = <T,>(value: T) => ({ ok: true as const, value, disclosure: complete });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => { resolve = accept; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
  fixture = syntheticConstraintWorkspace("prj_syn_0001") as ConstraintWorkspaceFixture;
  store.reset();
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined })));
  reads.projects.mockResolvedValue(ok([{ projectId: "prj_syn_0001", name: "Live Project", state: "active", description: null, participants: [], openedAt: "2026-01-01T00:00:00Z", closedAt: null }]));
  reads.overview.mockResolvedValue(ok(fixture.overview));
  reads.categories.mockResolvedValue(ok(fixture.categories));
  reads.register.mockResolvedValue(ok({ entries: fixture.entries.slice(0, 2), isTruncated: false, nextCursor: null, totalCount: null }));
  reads.detail.mockImplementation(async (_project: string, id: string) => ok(fixture.details[id]));
  reads.history.mockImplementation(async (_project: string, id: string) => ok({ entries: fixture.history[id] ?? [], nextCursor: null }));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function content(projectId = "prj_syn_0001") {
  return <AppShell principal={PRINCIPAL}><LiveConstraintsWorkspace projectId={projectId} initialState={DEFAULT_CONSTRAINT_URL_STATE} /></AppShell>;
}

function mount(query = "", projectId = "prj_syn_0001") {
  store.reset(query);
  return render(content(projectId));
}

describe("the live read-only workspace", () => {
  it("renders authoritative Overview figures and category navigation without invented counts", async () => {
    mount();
    await screen.findByTestId("kpi-totalOpen");
    const categories = screen.getByTestId("overview-by-category");
    expect(categories).toHaveTextContent("Category totals are not part of this read contract");
    expect(categories).toHaveTextContent("View in Register");
    expect(screen.queryByTestId("overview-oldest-open")).toBeNull();
  });

  it("immediately hides prior Project Overview, category and disclosure state", async () => {
    reads.overview.mockResolvedValue({
      ok: true,
      value: fixture.overview,
      disclosure: { ...complete, coverage: "partial", limitations: ["Synthetic limitation"] },
    });
    const view = mount();
    expect(await screen.findByTestId("overview-by-category")).toBeVisible();
    expect(screen.getByTestId("degraded-banner")).toBeVisible();

    reads.overview.mockImplementation(() => new Promise(() => undefined));
    reads.categories.mockImplementation(() => new Promise(() => undefined));
    view.rerender(content("prj_syn_0002"));

    expect(screen.queryByTestId("overview-by-category")).toBeNull();
    expect(screen.queryByTestId("degraded-banner")).toBeNull();
    expect(screen.getByTestId("overview-loading")).toBeVisible();
  });

  it("immediately hides prior Project summary errors", async () => {
    reads.overview.mockResolvedValue({
      ok: false,
      error: { status: 503, code: "transport_unavailable", message: "Old overview error" },
    });
    reads.categories.mockResolvedValue({
      ok: false,
      error: { status: 503, code: "transport_unavailable", message: "Old category error" },
    });
    const view = mount();
    expect(await screen.findByTestId("overview-unavailable")).toHaveTextContent(
      "Old overview error",
    );
    expect(await screen.findByText(/Old category error/)).toBeVisible();

    reads.overview.mockImplementation(() => new Promise(() => undefined));
    reads.categories.mockImplementation(() => new Promise(() => undefined));
    view.rerender(content("prj_syn_0002"));

    expect(screen.queryByTestId("overview-unavailable")).toBeNull();
    expect(screen.queryByText(/Old category error/)).toBeNull();
    expect(screen.getByTestId("overview-loading")).toBeVisible();
  });

  it("renders server rows without mutation controls and loads selected detail independently", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none");
    const table = await screen.findByTestId("register-table");
    expect(within(table).getAllByRole("row").length).toBeGreaterThan(1);
    expect(screen.queryByTestId("register-new-constraint")).toBeNull();
    await user.click(screen.getByRole("button", { name: fixture.entries[0].constraintCode ?? "Draft (Code not issued)" }));
    await waitFor(() => expect(reads.detail).toHaveBeenCalled());
    expect(await screen.findByTestId("constraint-inspector")).toBeInTheDocument();
    expect(screen.queryByTestId("inspector-edit")).toBeNull();
  });

  it("preserves an initial deep-linked selection", async () => {
    const id = fixture.entries[0].constraintId;
    mount(`view=register&group=none&constraint=${id}`);

    await waitFor(() => expect(reads.detail).toHaveBeenCalledWith(
      "prj_syn_0001",
      id,
      expect.any(AbortSignal),
    ));
    expect(store.snapshot().get("constraint")).toBe(id);
    expect(await screen.findByTestId("constraint-inspector")).toBeVisible();
  });

  it("clears selection and aborts stale Inspector reads when the Register query changes", async () => {
    const user = userEvent.setup();
    const id = fixture.entries[0].constraintId;
    const pendingDetail = deferred<ReturnType<typeof ok<typeof fixture.details[string]>>>();
    const pendingHistory = deferred<ReturnType<typeof ok<{ entries: typeof fixture.history[string]; nextCursor: null }>>>();
    reads.detail.mockReturnValue(pendingDetail.promise);
    reads.history.mockReturnValue(pendingHistory.promise);
    mount(`view=register&group=none&constraint=${id}`);

    await waitFor(() => expect(reads.history).toHaveBeenCalled());
    const detailSignal = reads.detail.mock.calls[0][2] as AbortSignal;
    const historySignal = reads.history.mock.calls[0][3] as AbortSignal;
    await user.type(screen.getByTestId("register-search"), "steel");

    expect(store.snapshot().has("constraint")).toBe(false);
    expect(detailSignal.aborted).toBe(true);
    expect(historySignal.aborted).toBe(true);
    await act(async () => {
      pendingDetail.resolve(ok(fixture.details[id]));
      pendingHistory.resolve(ok({ entries: fixture.history[id], nextCursor: null }));
    });
    expect(screen.queryByTestId("constraint-inspector")).toBeNull();
    expect(screen.queryByTestId("inspector-history-unavailable")).toBeNull();
  });

  it("focuses the mounted Register heading after KPI navigation", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByTestId("kpi-overdue"));

    expect(store.snapshot().get("view")).toBe("register");
    await waitFor(() => expect(screen.getByTestId("register-heading")).toHaveFocus());
  });

  it("restores focus to the Project selector after the routed Project mounts", async () => {
    const user = userEvent.setup();
    const secondProject = {
      projectId: "prj_syn_0002",
      name: "Second Live Project",
      state: "active",
      description: null,
      participants: [],
      openedAt: "2026-01-02T00:00:00Z",
      closedAt: null,
    };
    reads.projects.mockResolvedValue(ok([
      { projectId: "prj_syn_0001", name: "Live Project", state: "active", description: null, participants: [], openedAt: "2026-01-01T00:00:00Z", closedAt: null },
      secondProject,
    ]));
    const view = mount("view=register&group=none");
    const selector = await screen.findByTestId("project-selector");
    await user.selectOptions(selector, secondProject.projectId);
    view.rerender(content(secondProject.projectId));

    expect(store.path()).toBe("/work/projects/prj_syn_0002/constraints");
    await waitFor(() => expect(screen.getByTestId("project-selector")).toHaveFocus());
  });

  it("returns focus to the live row trigger after the Inspector closes", async () => {
    const user = userEvent.setup();
    const id = fixture.entries[0].constraintId;
    mount("view=register&group=none");
    const trigger = await screen.findByRole("button", {
      name: fixture.entries[0].constraintCode ?? "Draft (Code not issued)",
    });
    await user.click(trigger);
    await user.click(await screen.findByTestId("inspector-close-panel"));

    await waitFor(() => expect(document.getElementById(`constraint-row-trigger-${id}`)).toHaveFocus());
  });

  it("focuses the Register heading when a deep-linked selection is off the loaded page", async () => {
    const user = userEvent.setup();
    const offPageId = fixture.entries[2].constraintId;
    mount(`view=register&group=none&constraint=${offPageId}`);

    expect(await screen.findByTestId("constraint-inspector")).toBeVisible();
    expect(screen.queryByTestId(`register-row-${offPageId}`)).toBeNull();
    await user.click(screen.getByTestId("inspector-close-panel"));

    await waitFor(() => expect(screen.getByTestId("register-heading")).toHaveFocus());
    expect(store.snapshot().has("constraint")).toBe(false);
  });

  it("focuses the Register heading after closing an off-page relationship selection", async () => {
    const user = userEvent.setup();
    const sourceId = fixture.entries[0].constraintId;
    const relatedId = fixture.entries[2].constraintId;
    const relationshipId = "rel_live_off_page";
    reads.detail.mockImplementation(async (_project: string, id: string) =>
      ok(
        id === sourceId
          ? {
              ...fixture.details[sourceId],
              relationships: [
                {
                  relationshipId,
                  relationshipType: "RELATED_TO",
                  direction: "OUTGOING",
                  relatedConstraintId: relatedId,
                  relatedConstraintCode: fixture.entries[2].constraintCode,
                  relatedStatus: fixture.entries[2].status,
                },
              ],
            }
          : fixture.details[id],
      ),
    );
    mount("view=register&group=none");
    await user.click(
      await screen.findByRole("button", {
        name: fixture.entries[0].constraintCode ?? "Draft (Code not issued)",
      }),
    );
    await user.click(await screen.findByTestId(`inspector-relationship-${relationshipId}`));
    await waitFor(() => expect(store.snapshot().get("constraint")).toBe(relatedId));
    expect(screen.queryByTestId(`register-row-${relatedId}`)).toBeNull();

    await user.click(await screen.findByTestId("inspector-close-panel"));

    await waitFor(() => expect(screen.getByTestId("register-heading")).toHaveFocus());
    expect(store.snapshot().has("constraint")).toBe(false);
  });

  it("canonicalizes a deep-linked search before issuing the narrower read", async () => {
    mount("view=register&q=steel&overdue=1&group=status");
    await waitFor(() => expect(store.snapshot().get("q")).toBe("steel"));
    expect(store.snapshot().has("overdue")).toBe(false);
    expect(store.snapshot().get("group")).toBe("none");
  });

  it("shows only a reading state while the Register answer is pending", async () => {
    reads.register.mockImplementation(() => new Promise(() => undefined));
    mount("view=register&group=none");

    expect(await screen.findByTestId("register-loading")).toHaveTextContent(
      "Reading the Constraint Register",
    );
    expect(screen.queryByTestId("register-live")).toBeNull();
    expect(screen.queryByTestId("register-count")).toBeNull();
    expect(screen.queryByTestId("register-empty-project")).toBeNull();
    expect(screen.queryByTestId("register-empty-filtered")).toBeNull();
  });

  it("announces a terminal null-total page as loaded without inventing a total", async () => {
    mount("view=register&group=none");

    const announcement = await screen.findByTestId("register-live");
    expect(announcement).toHaveTextContent("2 Constraints loaded.");
    expect(announcement).not.toHaveTextContent("Showing");
    expect(announcement).not.toHaveTextContent("more available");
  });

  it("announces more available only when a null-total continuation proves it", async () => {
    reads.register.mockResolvedValue(
      ok({
        entries: fixture.entries.slice(0, 2),
        isTruncated: true,
        nextCursor: "next-page",
        totalCount: null,
      }),
    );
    mount("view=register&group=none");

    const announcement = await screen.findByTestId("register-live");
    expect(announcement).toHaveTextContent("2 Constraints loaded; more available.");
    expect(announcement).not.toHaveTextContent("Showing");
  });

  it("uses Showing N of T only when the backend supplies an authoritative total", async () => {
    reads.register.mockResolvedValue(
      ok({
        entries: fixture.entries.slice(0, 2),
        isTruncated: true,
        nextCursor: "next-page",
        totalCount: 17,
      }),
    );
    mount("view=register&group=none");

    expect(await screen.findByTestId("register-live")).toHaveTextContent(
      "Showing 2 of 17 Constraints.",
    );
  });

  it("immediately hides prior rows and disclosure when the Register query changes", async () => {
    const user = userEvent.setup();
    const id = fixture.entries[0].constraintId;
    reads.register.mockResolvedValue({
      ok: true,
      value: {
        entries: fixture.entries.slice(0, 2),
        isTruncated: false,
        nextCursor: null,
        totalCount: null,
      },
      disclosure: { ...complete, coverage: "partial", limitations: ["Old query limitation"] },
    });
    mount("view=register&group=none");
    expect(await screen.findByTestId(`register-row-${id}`)).toBeVisible();
    expect(screen.getByTestId("degraded-banner")).toBeVisible();

    reads.register.mockImplementation(() => new Promise(() => undefined));
    await user.type(screen.getByTestId("register-search"), "x");

    expect(screen.queryByTestId(`register-row-${id}`)).toBeNull();
    expect(screen.queryByTestId("degraded-banner")).toBeNull();
    expect(screen.getByTestId("register-loading")).toBeVisible();
    expect(screen.queryByTestId("register-empty-filtered")).toBeNull();
  });

  it.each([
    ["unavailable", "transport_unavailable", "The read plane could not be reached."],
    ["malformed", "upstream_contract_invalid", "The Constraint answer was malformed."],
    ["capability unavailable", "unsupported", "The capability is unavailable."],
  ])("shows only an unavailable state for a %s Register answer", async (_case, code, message) => {
    reads.register.mockResolvedValue({ ok: false, error: { status: 503, code, message } });
    mount("view=register&group=none");

    const unavailable = await screen.findByTestId("register-unavailable");
    expect(unavailable).toHaveAttribute("data-state", "unavailable");
    expect(unavailable).toHaveTextContent(message);
    expect(screen.queryByTestId("register-live")).toBeNull();
    expect(screen.queryByTestId("register-count")).toBeNull();
    expect(screen.queryByTestId("register-empty-project")).toBeNull();
    expect(screen.queryByTestId("register-empty-filtered")).toBeNull();
  });

  it("keeps a successful empty Register distinct from unavailable", async () => {
    reads.register.mockResolvedValue(
      ok({ entries: [], isTruncated: false, nextCursor: null, totalCount: 0 }),
    );
    mount("view=register&group=none");

    const empty = await screen.findByTestId("register-empty-project");
    expect(empty).toHaveAttribute("data-state", "empty");
    expect(empty).toHaveTextContent("The read succeeded");
    expect(screen.queryByTestId("register-unavailable")).toBeNull();
  });

  it("keeps ordinary history continuation bounded and deduplicated", async () => {
    const user = userEvent.setup();
    const id = fixture.entries[0].constraintId;
    const first = fixture.history[id][0];
    const second = { ...fixture.history[id][1], historyId: "hst_page_two" };
    reads.history.mockImplementation(async (_project: string, selected: string, cursor: string | null) =>
      cursor === null
        ? ok({ entries: [first], nextCursor: "history-page-2" })
        : ok({ entries: [first, second], nextCursor: null }),
    );
    mount("view=register&group=none");
    await user.click(await screen.findByRole("button", { name: fixture.entries[0].constraintCode ?? "Draft (Code not issued)" }));
    await user.click(await screen.findByTestId("inspector-history-more"));

    await waitFor(() => expect(screen.getByTestId("inspector-history").querySelectorAll("li")).toHaveLength(2));
    expect(reads.history).toHaveBeenLastCalledWith(
      "prj_syn_0001",
      id,
      "history-page-2",
      expect.any(AbortSignal),
    );
  });

  it("clears a continuation failure while retrying and appends the successful retry once", async () => {
    const user = userEvent.setup();
    const id = fixture.entries[0].constraintId;
    const first = { ...fixture.history[id][0], historyId: "hst_retry_first" };
    const second = { ...fixture.history[id][1], historyId: "hst_retry_second" };
    const retry = deferred<
      ReturnType<typeof ok<{ entries: typeof fixture.history[string]; nextCursor: null }>>
    >();
    let continuation = 0;
    reads.history.mockImplementation(
      async (_project: string, selected: string, cursor: string | null) => {
        if (selected === id && cursor === null) {
          return ok({ entries: [first], nextCursor: "retry-cursor" });
        }
        continuation += 1;
        if (continuation === 1) {
          return {
            ok: false as const,
            error: {
              status: 503,
              code: "transport_unavailable",
              message: "History continuation failed.",
            },
          };
        }
        return retry.promise;
      },
    );
    mount("view=register&group=none");
    await user.click(
      await screen.findByRole("button", {
        name: fixture.entries[0].constraintCode ?? "Draft (Code not issued)",
      }),
    );
    await user.click(await screen.findByTestId("inspector-history-more"));
    expect(await screen.findByTestId("inspector-history-unavailable")).toHaveTextContent(
      "History continuation failed.",
    );

    await user.click(screen.getByTestId("inspector-history-more"));
    expect(screen.queryByTestId("inspector-history-unavailable")).toBeNull();
    await act(async () => retry.resolve(ok({ entries: [first, second], nextCursor: null })));

    await waitFor(() =>
      expect(screen.getByTestId("inspector-history").querySelectorAll("li")).toHaveLength(2),
    );
    expect(screen.queryByTestId("inspector-history-unavailable")).toBeNull();
    expect(screen.getByTestId("inspector-history-hst_retry_second")).toBeVisible();
  });

  it("hides prior Project rows and Inspector state before replacement reads settle", async () => {
    const id = fixture.entries[0].constraintId;
    const view = mount(`view=register&group=none&constraint=${id}`);
    expect(await screen.findByTestId(`register-row-${id}`)).toBeVisible();
    expect(await screen.findByTestId("constraint-inspector")).toBeVisible();
    expect(
      await screen.findByTestId(`inspector-history-${fixture.history[id][0].historyId}`),
    ).toBeVisible();

    reads.overview.mockImplementation(() => new Promise(() => undefined));
    reads.categories.mockImplementation(() => new Promise(() => undefined));
    reads.register.mockImplementation(() => new Promise(() => undefined));
    reads.detail.mockImplementation(() => new Promise(() => undefined));
    reads.history.mockImplementation(() => new Promise(() => undefined));
    view.rerender(content("prj_syn_0002"));

    expect(screen.queryByTestId(`register-row-${id}`)).toBeNull();
    expect(screen.queryByTestId("constraint-inspector")).toBeNull();
    expect(
      screen.queryByTestId(`inspector-history-${fixture.history[id][0].historyId}`),
    ).toBeNull();
    expect(screen.getByTestId("register-loading")).toBeVisible();
  });

  it("aborts and rejects delayed reads from the previous Project", async () => {
    const id = fixture.entries[0].constraintId;
    const oldOverview = deferred<ReturnType<typeof ok<typeof fixture.overview>>>();
    const oldCategories = deferred<ReturnType<typeof ok<typeof fixture.categories>>>();
    const oldRegister = deferred<
      ReturnType<
        typeof ok<{
          entries: typeof fixture.entries;
          isTruncated: false;
          nextCursor: null;
          totalCount: null;
        }>
      >
    >();
    const oldDetail = deferred<ReturnType<typeof ok<typeof fixture.details[string]>>>();
    const oldHistory = deferred<
      ReturnType<typeof ok<{ entries: typeof fixture.history[string]; nextCursor: null }>>
    >();
    reads.overview.mockImplementation((project: string) =>
      project === "prj_syn_0001" ? oldOverview.promise : new Promise(() => undefined),
    );
    reads.categories.mockImplementation((project: string) =>
      project === "prj_syn_0001" ? oldCategories.promise : new Promise(() => undefined),
    );
    reads.register.mockImplementation((project: string) =>
      project === "prj_syn_0001" ? oldRegister.promise : new Promise(() => undefined),
    );
    reads.detail.mockImplementation((project: string) =>
      project === "prj_syn_0001" ? oldDetail.promise : new Promise(() => undefined),
    );
    reads.history.mockImplementation((project: string) =>
      project === "prj_syn_0001" ? oldHistory.promise : new Promise(() => undefined),
    );
    const view = mount(`view=register&group=none&constraint=${id}`);
    await waitFor(() => expect(reads.history).toHaveBeenCalled());
    const signals = [
      reads.overview.mock.calls[0][1],
      reads.categories.mock.calls[0][1],
      reads.register.mock.calls[0][3],
      reads.detail.mock.calls[0][2],
      reads.history.mock.calls[0][3],
    ] as AbortSignal[];

    view.rerender(content("prj_syn_0002"));
    expect(signals.every((signal) => signal.aborted)).toBe(true);
    await act(async () => {
      oldOverview.resolve(ok(fixture.overview));
      oldCategories.resolve(ok(fixture.categories));
      oldRegister.resolve(
        ok({
          entries: fixture.entries,
          isTruncated: false,
          nextCursor: null,
          totalCount: null,
        }),
      );
      oldDetail.resolve(ok(fixture.details[id]));
      oldHistory.resolve(ok({ entries: fixture.history[id], nextCursor: null }));
    });

    expect(screen.queryByTestId(`register-row-${id}`)).toBeNull();
    expect(screen.queryByTestId("constraint-inspector")).toBeNull();
    expect(screen.getByTestId("register-loading")).toBeVisible();
  });

  it("ignores a late continuation after selection changes", async () => {
    const user = userEvent.setup();
    const firstId = fixture.entries[0].constraintId;
    const secondId = fixture.entries[1].constraintId;
    const late = deferred<ReturnType<typeof ok<{ entries: typeof fixture.history[string]; nextCursor: null }>>>();
    const current = deferred<ReturnType<typeof ok<{ entries: typeof fixture.history[string]; nextCursor: null }>>>();
    const firstEntry = { ...fixture.history[firstId][0], historyId: "hst_first_initial" };
    const lateEntry = { ...fixture.history[firstId][1], historyId: "hst_stale_continuation" };
    const currentEntry = { ...fixture.history[secondId][0], historyId: "hst_current_selection" };
    reads.history.mockImplementation(
      async (_project: string, selected: string, cursor: string | null) => {
        if (selected === firstId && cursor === null) {
          return ok({ entries: [firstEntry], nextCursor: "old-selection-cursor" });
        }
        if (selected === firstId) return late.promise;
        return current.promise;
      },
    );
    mount("view=register&group=none");
    await user.click(await screen.findByRole("button", { name: fixture.entries[0].constraintCode ?? "Draft (Code not issued)" }));
    await user.click(await screen.findByTestId("inspector-history-more"));
    await user.click(screen.getByRole("button", { name: fixture.entries[1].constraintCode ?? "Draft (Code not issued)" }));

    await act(async () => current.resolve(ok({ entries: [currentEntry], nextCursor: null })));
    expect(await screen.findByTestId("inspector-history-hst_current_selection")).toBeVisible();
    await act(async () => late.resolve(ok({ entries: [lateEntry], nextCursor: null })));

    await waitFor(() => expect(screen.queryByTestId("inspector-history-hst_stale_continuation")).toBeNull());
    expect(screen.getByTestId("inspector-history-hst_current_selection")).toBeVisible();
  });
});
