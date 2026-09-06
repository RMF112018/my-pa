/**
 * The Constraint workspace, rendered inside the real `AppShell`.
 *
 * **The shell is not stubbed, and that is the point of rendering it.** The one
 * claim `CM-FE-AC-090` makes is that Constraint detail appears in the shell's
 * existing Inspector rather than in a drawer of the feature's own. A test that
 * mounted the workspace alone could not tell the difference. So the whole shell
 * is mounted, the Inspector body is found *inside* the shell's Utility region,
 * and the number of regions on the page is asserted to be one.
 *
 * The URL is real too. `next/navigation` is replaced with a small store that
 * behaves like the router: a push or a replace changes the query, and every
 * component reading `useSearchParams` re-renders. Deep links, Back-shaped
 * assertions and "closing detail preserves the filters" are therefore claims
 * about the address bar rather than about component state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PrincipalSession } from "@/contracts/identity";

const urlStore = vi.hoisted(() => {
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
    reset() {
      path = "/work/projects/prj_syn_0001/constraints";
      params = new URLSearchParams();
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
});

vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  // One router object for the life of the module, as the real hook returns.
  const router = {
    push: (href: string) => urlStore.go(href),
    replace: (href: string) => urlStore.go(href),
    refresh: () => undefined,
    prefetch: () => undefined,
  };
  return {
    usePathname: () => urlStore.path(),
    useRouter: () => router,
    useSearchParams: () =>
      useSyncExternalStore(urlStore.subscribe, urlStore.snapshot, urlStore.snapshot),
  };
});

import { AppShell } from "@/components/shell/app-shell";
import { ConstraintsWorkspace } from "./constraints-workspace";
import { DEFAULT_CONSTRAINT_URL_STATE } from "./constraint-url-state";
import {
  SYNTHETIC_CONSTRAINT_PROJECT_ID,
  syntheticConstraintProjects,
  syntheticConstraintWorkspace,
  type ConstraintWorkspaceFixture,
} from "@/lib/fixtures/constraints";

const PRINCIPAL: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

let workspace: ConstraintWorkspaceFixture;

beforeEach(() => {
  vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
  urlStore.reset();
  workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID) as ConstraintWorkspaceFixture;
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mount(query = "") {
  if (query) urlStore.go(`/work/projects/prj_syn_0001/constraints?${query}`);
  return render(
    <AppShell principal={PRINCIPAL}>
      <ConstraintsWorkspace
        workspace={workspace}
        projects={syntheticConstraintProjects()}
        initialState={DEFAULT_CONSTRAINT_URL_STATE}
      />
    </AppShell>,
  );
}

/** Widen the viewport question the feature asks, for the responsive cases. */
function stubViewport(kind: "mobile" | "tablet" | "desktop") {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches:
        (kind === "mobile" && query.includes("max-width: 767px")) ||
        (kind === "tablet" && query.includes("min-width: 768px")),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })),
  );
}

describe("information architecture", () => {
  it("keeps the current Project identity visible throughout", () => {
    mount();
    const context = screen.getByTestId("project-context");
    expect(within(context).getByText("SYN-RW-2026")).toBeInTheDocument();
    expect(within(context).getByText(/prj_syn_0001/)).toBeInTheDocument();
  });

  it("offers Overview and Register as the only workspace tabs", () => {
    mount();
    const tablist = screen.getByRole("tablist", { name: "Constraint workspace" });
    expect(within(tablist).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Overview",
      "Register",
    ]);
  });

  it("adds no top-level destination for Constraints", () => {
    mount();
    expect(screen.queryByRole("link", { name: "Constraints" })).toBeNull();
    // Work is still the destination Constraints lives under.
    expect(screen.getAllByRole("link", { name: "Work" }).length).toBeGreaterThanOrEqual(1);
  });

  it("resolves a deep link to the Register with a filter, without prior navigation", () => {
    mount("view=register&scope=open&overdue=1");
    expect(screen.getAllByTestId("register-table").length).toBeGreaterThan(0);
    expect(screen.getByTestId("register-quick-overdue")).toHaveAttribute("aria-pressed", "true");
  });

  it("switches Project by route, dropping that Project's filter identities", async () => {
    const user = userEvent.setup();
    mount("view=register&category=cat_syn_0001&constraint=cst_syn_0001&group=status");
    await user.selectOptions(screen.getByTestId("project-selector"), "prj_syn_0002");
    expect(urlStore.path()).toBe("/work/projects/prj_syn_0002/constraints");
    const params = urlStore.snapshot();
    expect(params.has("category")).toBe(false);
    expect(params.has("constraint")).toBe(false);
    // A Project-neutral preference survives the switch.
    expect(params.get("group")).toBe("status");
  });
});

describe("the Overview", () => {
  it("renders the backend's own figures under the canonical names", () => {
    mount();
    expect(screen.getByTestId("kpi-overdue")).toHaveTextContent(String(workspace.overview.overdue));
    expect(screen.getByTestId("kpi-dueSoon")).toHaveTextContent(String(workspace.overview.dueSoon));
    expect(screen.getByTestId("kpi-dueSoon")).toHaveTextContent(workspace.overview.dueSoonThrough);
    expect(screen.getByTestId("kpi-inMyCourt")).toHaveTextContent(String(workspace.overview.inMyCourt));
    expect(screen.getByTestId("kpi-totalOpen")).toHaveTextContent(String(workspace.overview.totalOpen));
    expect(screen.getByTestId("kpi-onHold")).toHaveTextContent(String(workspace.overview.onHold));
    expect(screen.getByTestId("kpi-draft")).toHaveTextContent(String(workspace.overview.draft));
    expect(screen.getByTestId("kpi-needsAttention")).toHaveTextContent(
      String(workspace.overview.needsAttention),
    );
    expect(screen.getByTestId("kpi-averageOpenAgeBusinessDays")).toHaveTextContent(
      String(workspace.overview.averageOpenAgeBusinessDays),
    );
    expect(screen.getByTestId("overview-sync-health")).toHaveTextContent("Sync conflict");
  });

  it("does not reconstruct a metric from the rows it holds", () => {
    mount();
    const tallied = workspace.entries.filter((entry) => entry.isOverdue).length;
    expect(screen.getByTestId("kpi-overdue")).toHaveTextContent(String(workspace.overview.overdue));
    expect(workspace.overview.overdue).not.toBe(tallied);
  });

  it("does not offer navigation for a metric with no matching backend filter", () => {
    mount();
    for (const testId of ["kpi-recentlyChanged", "kpi-recentlyClosed"]) {
      const card = screen.getByTestId(testId);
      expect(card.tagName).not.toBe("BUTTON");
      expect(card).toHaveTextContent(/does not navigate/i);
    }
  });

  it("navigates Overdue to the backend-supported overdue Register state and moves focus", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(screen.getByTestId("kpi-overdue"));
    expect(urlStore.snapshot().get("view")).toBe("register");
    expect(urlStore.snapshot().get("overdue")).toBe("1");
    await waitFor(() => expect(screen.getByTestId("register-heading")).toHaveFocus());
  });

  it("navigates an Open-by-Category bar by canonical categoryId", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(screen.getByTestId("overview-category-cat_syn_0003"));
    expect(urlStore.snapshot().get("category")).toBe("cat_syn_0003");
    expect(urlStore.snapshot().get("view")).toBe("register");
  });
});

describe("the Register", () => {
  it("opens on the default state", () => {
    mount("view=register");
    expect(screen.getByTestId("register-scope-open")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("register-group")).toHaveValue("category");
    expect(screen.getByTestId("register-sort")).toHaveValue("code");
    expect(screen.getByTestId("register-direction")).toHaveTextContent("Ascending");
  });

  it("uses a semantic table with a sortable, aria-sorted Code header", () => {
    mount("view=register");
    const table = screen.getAllByTestId("register-table")[0];
    const codeHeader = within(table).getAllByRole("columnheader", { name: /Code/ })[0];
    expect(codeHeader).toHaveAttribute("aria-sort", "ascending");
    expect(within(table).getAllByRole("columnheader").length).toBeGreaterThan(4);
    // Not a custom ARIA grid.
    expect(screen.queryByRole("grid")).toBeNull();
  });

  it("names Ball in Court and Responsible party distinctly", () => {
    mount("view=register&group=none");
    const table = screen.getByTestId("register-table");
    expect(within(table).getByRole("columnheader", { name: "Ball in Court" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Responsible party" })).toBeInTheDocument();
  });

  it("omits the Category column when already grouped by Category, and shows it otherwise", () => {
    const grouped = mount("view=register&group=category");
    expect(
      within(screen.getAllByTestId("register-table")[0]).queryByRole("columnheader", {
        name: "Category",
      }),
    ).toBeNull();
    grouped.unmount();
    mount("view=register&group=none");
    expect(
      within(screen.getByTestId("register-table")).getByRole("columnheader", { name: "Category" }),
    ).toBeInTheDocument();
  });

  it("honours the backend's isOverdue on a record whose due date is long past", () => {
    mount("view=register&group=none&scope=all&q=Historic due date");
    const row = screen.getByTestId("register-row-cst_syn_0043");
    expect(row).toHaveTextContent("2021-03-31");
    expect(within(row).queryByText("Overdue")).toBeNull();
  });

  it("shows Closed and Void distinctly under the Closed scope", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none");
    await user.click(screen.getByTestId("register-scope-closed"));
    expect(screen.getByTestId("register-table")).toHaveTextContent("Closed");
    expect(screen.getByTestId("register-table")).toHaveTextContent("Void");
  });

  it("renders a legacy record explicitly and never as IDENTIFIED when its lifecycle is absent", () => {
    mount("view=register&group=none&scope=all&q=no stored lifecycle");
    const row = screen.getByTestId("register-row-cst_syn_0054");
    expect(row).toHaveTextContent("Status unavailable — legacy record");
    expect(row).toHaveTextContent("Legacy");
    expect(row).not.toHaveTextContent("Identified");
  });

  it("shows a Draft with no Code and never a predicted one", () => {
    mount("view=register&group=none&scope=draft");
    const table = screen.getByTestId("register-table");
    expect(table).toHaveTextContent("Draft — no Constraint number yet");
    expect(table).not.toHaveTextContent(/TBD-/);
  });

  it("serializes quick filters to the URL and shows an active-filter summary", async () => {
    const user = userEvent.setup();
    mount("view=register");
    await user.click(screen.getByTestId("register-quick-inMyCourt"));
    expect(urlStore.snapshot().get("inMyCourt")).toBe("1");
    expect(screen.getByTestId("register-active-filters")).toHaveTextContent("My Court");
  });

  it("distinguishes no matching rows from an unavailable read", async () => {
    const user = userEvent.setup();
    mount("view=register");
    await user.type(screen.getByTestId("register-search"), "zzz-nothing-matches-zzz");
    await waitFor(() => expect(screen.getByTestId("register-empty-filtered")).toBeInTheDocument());
    const state = screen.getByTestId("register-empty-filtered");
    expect(state).toHaveAttribute("data-state", "empty");
    expect(state).toHaveAttribute("role", "status");
  });

  it("continues to a second bounded page without duplicating a row", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none&scope=all");
    const first = screen.getAllByRole("row").length;
    await user.click(screen.getByTestId("register-load-more"));
    const rows = screen
      .getAllByRole("row")
      .map((row) => row.getAttribute("data-testid"))
      .filter((id): id is string => id !== null);
    expect(rows.length).toBeGreaterThan(first - 1);
    expect(new Set(rows).size).toBe(rows.length);
  });

  it("offers no unresolved party as an individually selectable filter option", async () => {
    const user = userEvent.setup();
    mount("view=register");
    await user.click(screen.getByTestId("register-filters"));
    const select = await screen.findByTestId("register-filter-bic");
    const options = within(select).getAllByRole("option").map((option) => option.textContent);
    expect(options).not.toContain("structural eng. (per log)");
    expect(options).toContain("Unresolved (all)");
  });
});

describe("the shared Inspector", () => {
  it("renders Constraint detail in the shell's one Utility region, not a second drawer", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none");
    await user.click(within(screen.getByTestId("register-row-cst_syn_0001")).getByRole("button"));
    const region = await screen.findByRole("complementary", { name: "Utility region" });
    await waitFor(() =>
      expect(within(region).getByTestId("constraint-inspector")).toBeInTheDocument(),
    );
    expect(screen.getAllByRole("complementary", { name: "Utility region" })).toHaveLength(1);
    expect(within(region).getByRole("heading", { name: /Constraint 1\.01/ })).toBeInTheDocument();
  });

  it("puts the selected Constraint in the URL and takes it out again on close", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none&overdue=1");
    await user.click(within(screen.getByTestId("register-row-cst_syn_0001")).getByRole("button"));
    expect(urlStore.snapshot().get("constraint")).toBe("cst_syn_0001");
    await user.click(await screen.findByTestId("inspector-close-panel"));
    expect(urlStore.snapshot().has("constraint")).toBe(false);
    // Everything else about the view survives.
    expect(urlStore.snapshot().get("overdue")).toBe("1");
    expect(urlStore.snapshot().get("group")).toBe("none");
  });

  it("returns focus to the row that opened it", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none");
    const trigger = within(screen.getByTestId("register-row-cst_syn_0001")).getByRole("button");
    await user.click(trigger);
    await user.click(await screen.findByTestId("inspector-close-panel"));
    await waitFor(() =>
      expect(document.getElementById("constraint-row-trigger-cst_syn_0001")).toHaveFocus(),
    );
  });

  it("states that a detail read failed while leaving the Register intact", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none&scope=all&q=Historic due date");
    await user.click(within(screen.getByTestId("register-row-cst_syn_0043")).getByRole("button"));
    const unavailable = await screen.findByTestId("inspector-detail-unavailable");
    expect(unavailable).toHaveAttribute("data-state", "unavailable");
    expect(unavailable).toHaveAttribute("role", "alert");
    // The Register still holds its row.
    expect(screen.getByTestId("register-row-cst_syn_0043")).toBeInTheDocument();
  });

  it("shows the legacy callout and only the backend's own missing fields", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none&scope=all&q=drainage invert");
    await user.click(within(screen.getByTestId("register-row-cst_syn_0052")).getByRole("button"));
    expect(await screen.findByTestId("inspector-legacy-callout")).toHaveTextContent(
      "Legacy record — needs review",
    );
    const missing = await screen.findByTestId("inspector-missing-fields");
    const listed = within(missing).getAllByRole("listitem").map((item) => item.textContent);
    const backendFields = workspace.details["cst_syn_0052"].missingFields;
    expect(listed).toHaveLength(backendFields.length);
  });

  it("navigates a Close + Follow-up relationship by backend relationship identity", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none&scope=all&constraint=cst_syn_0049");
    const link = await screen.findByTestId("inspector-relationship-rel_syn_0001");
    await user.click(link);
    expect(urlStore.snapshot().get("constraint")).toBe("cst_syn_0064");
  });

  it("renders history as operation, actor, timestamp and version, with provenance only when given", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none&scope=all&q=drainage invert");
    await user.click(within(screen.getByTestId("register-row-cst_syn_0052")).getByRole("button"));
    const history = await screen.findByTestId("inspector-history");
    expect(history).toHaveTextContent("Created");
    expect(history).toHaveTextContent("Version 0 → 1");
    expect(history).toHaveTextContent("Imported from the legacy Constraints Log workbook.");
    expect(history).not.toHaveTextContent("request_digest");
  });

  it("links validated evidence and leaves unvalidated reference text unlinked", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none&constraint=cst_syn_0001");
    const evidence = await screen.findByTestId("inspector-evidence");
    expect(within(evidence).getByRole("link", { name: /synthetic.example\/rfi/ })).toBeInTheDocument();
    expect(screen.getByTestId("inspector-evidence-text-evl_syn_0002")).toBeInTheDocument();
    expect(within(evidence).queryByRole("link", { name: /Constraints Log 2026-Q2/ })).toBeNull();
  });
});

describe("the fixture-only lifecycle surfaces", () => {
  it("says that nothing was published and no Code was issued", async () => {
    const user = userEvent.setup();
    mount("view=register");
    await user.click(screen.getByTestId("register-new-constraint"));
    expect(screen.getByTestId("synthetic-notice-form")).toHaveTextContent("Fixture only");
    expect(screen.getByTestId("form-code")).toHaveTextContent("Draft — no Constraint number yet");
    await user.click(screen.getByTestId("form-publish"));
    const live = await screen.findByTestId("workspace-live");
    expect(live).toHaveTextContent(/no Constraint Code was issued/i);
    expect(live).toHaveAttribute("role", "alert");
  });

  it("says that a close incremented no version and issued no receipt", async () => {
    const user = userEvent.setup();
    mount("view=register&group=none&constraint=cst_syn_0001");
    await user.click(await screen.findByTestId("inspector-close"));
    await user.click(screen.getByTestId("lifecycle-confirm"));
    expect(await screen.findByTestId("workspace-live")).toHaveTextContent(
      /no version was incremented, no receipt was issued/i,
    );
  });

  it("commits a multiline field on Ctrl+Enter and takes a newline on Shift+Enter", async () => {
    const user = userEvent.setup();
    mount("view=register");
    await user.click(screen.getByTestId("register-new-constraint"));
    const description = screen.getByTestId("form-description");
    await user.click(description);
    await user.keyboard("one{Shift>}{Enter}{/Shift}two");
    expect(description).toHaveValue("one\ntwo");
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(await screen.findByTestId("workspace-live")).toHaveTextContent(/Not saved as a Draft/i);
  });

  it("offers no Category reorder, and says why", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(screen.getByTestId("open-categories"));
    expect(screen.getByTestId("category-reorder-unavailable")).toHaveTextContent(
      /atomic backend reorder operation/i,
    );
    expect(screen.queryByRole("button", { name: /Move up/i })).toBeNull();
    expect(screen.getByTestId("category-prefix-locked-cat_syn_0001")).toHaveTextContent(/locked/i);
  });
});

describe("responsive presentation", () => {
  it("uses the dense semantic table on desktop", () => {
    stubViewport("desktop");
    mount("view=register&group=none");
    expect(screen.getByTestId("register-table")).toBeInTheDocument();
    expect(screen.queryByTestId("register-card-list")).toBeNull();
  });

  it("keeps Code, Description, Status, BIC and Due on tablet and moves the rest", () => {
    stubViewport("tablet");
    mount("view=register&group=none");
    const headers = within(screen.getByTestId("register-table"))
      .getAllByRole("columnheader")
      .map((header) => header.textContent?.replace(/[▲▼↕]/g, "").trim());
    expect(headers).toEqual(["Code", "Description", "Status", "Ball in Court", "Due"]);
  });

  it("uses a list of cards on mobile rather than a spreadsheet clone", () => {
    stubViewport("mobile");
    mount("view=register&group=none");
    expect(screen.getByTestId("register-card-list")).toBeInTheDocument();
    expect(screen.queryByTestId("register-table")).toBeNull();
  });

  it("keeps the record workflows reachable on mobile", async () => {
    stubViewport("mobile");
    const user = userEvent.setup();
    mount("view=register&group=none");
    await user.click(
      within(screen.getByTestId("register-card-cst_syn_0001")).getAllByRole("button")[0],
    );
    expect(urlStore.snapshot().get("constraint")).toBe("cst_syn_0001");
    expect(await screen.findByTestId("constraint-inspector")).toBeInTheDocument();
  });
});

describe("state is carried by words, not by colour", () => {
  it("gives every urgency, attention, legacy and sync state a visible label", () => {
    mount("view=register&group=none&scope=all&q=order for precast");
    const row = screen.getByTestId("register-row-cst_syn_0013");
    expect(row).toHaveTextContent("Overdue");
    expect(row).toHaveTextContent("Needs attention");
    expect(row).toHaveTextContent("Sync conflict");
    expect(row).toHaveTextContent("In progress");
  });
});
