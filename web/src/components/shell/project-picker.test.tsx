/**
 * The Project Picker (Phase 3).
 *
 * Three things carry the weight here: `All Projects` is always a real,
 * selectable choice; the collapsed value is always exactly the committed
 * scope's name, never an optimistic guess that could conflict with it
 * mid-reconciliation; and the Phase 4 scope-change barrier seam is honored
 * before any request is ever sent.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  PROJECT_PICKER_ALL_LABEL,
  PROJECT_PICKER_BLOCKED,
  PROJECT_PICKER_LABEL,
  ProjectPicker,
} from "@/components/shell/project-picker";
import { ProjectScopeProvider } from "@/components/shell/project-scope-provider";
import { ProjectRouteScopeBinding } from "@/app/(app)/work/projects/[projectId]/project-scope-binding";
import type { ResolvedProjectScope } from "@/lib/project-scope/resolver";

const { push, apiGet, apiPost } = vi.hoisted(() => ({
  push: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api/client", () => ({ apiGet, apiPost }));

const LINKED_ID = "prj_aaaaaaaa11111111";
const SAVED_ID = "prj_bbbbbbbb22222222";

const ALL_PROJECTS_RESOLUTION: ResolvedProjectScope = {
  scope: { kind: "ALL_PROJECTS" },
  source: "default",
  project: null,
  normalized: false,
};

const LINKED_PROJECT_RESOLUTION: ResolvedProjectScope = {
  scope: { kind: "PROJECT", projectId: LINKED_ID },
  source: "deep_link",
  project: { project_id: LINKED_ID, name: "Bridge Rollout", state: "active", version: 3 },
  normalized: false,
};

const SAVED_PROJECT_RESOLUTION: ResolvedProjectScope = {
  scope: { kind: "PROJECT", projectId: SAVED_ID },
  source: "preference",
  project: { project_id: SAVED_ID, name: "Harbor Migration", state: "on_hold", version: 6 },
  normalized: false,
};

function emptyPage() {
  return { ok: true, status: 200, data: { projects: [], nextCursor: null }, error: null, errorClass: null, code: null };
}

beforeEach(() => {
  push.mockReset();
  apiGet.mockReset();
  apiPost.mockReset();
  apiGet.mockResolvedValue(emptyPage());
});

afterEach(cleanup);

function renderPicker(
  props: Partial<React.ComponentProps<typeof ProjectPicker>> = {},
  initialResolution: ResolvedProjectScope = ALL_PROJECTS_RESOLUTION,
) {
  return render(
    <ProjectScopeProvider
      principalId="prn_aaaaaaaa11111111"
      sessionEpoch="session:a"
      initialResolution={initialResolution}
    >
      <ProjectPicker {...props} />
    </ProjectScopeProvider>,
  );
}

function select(): HTMLSelectElement {
  return screen.getByRole("combobox", { name: PROJECT_PICKER_LABEL }) as HTMLSelectElement;
}

describe("All Projects", () => {
  it("is always present and selectable, never degraded-state-only", async () => {
    renderPicker();
    const control = select();
    expect(within(control).getByText(PROJECT_PICKER_ALL_LABEL)).toBeInTheDocument();
    expect(control).toHaveValue("ALL_PROJECTS");
  });

  it("remains selectable even while the Project listing has not yet answered", () => {
    apiGet.mockReturnValue(new Promise(() => {})); // never resolves
    renderPicker();
    expect(within(select()).getByText(PROJECT_PICKER_ALL_LABEL)).toBeInTheDocument();
  });
});

describe("the collapsed value", () => {
  it("shows the exact current scope's canonical name and the fixed accessible name", () => {
    renderPicker({}, LINKED_PROJECT_RESOLUTION);
    const control = select();
    expect(control).toHaveAccessibleName(PROJECT_PICKER_LABEL);
    expect(control).toHaveValue(LINKED_ID);
    expect(within(control).getByText("Bridge Rollout")).toBeInTheDocument();
  });

  it("never shows a conflicting name mid-reconciliation while a switch is in flight", async () => {
    const user = userEvent.setup();
    let resolveWrite!: (value: unknown) => void;
    apiPost.mockReturnValue(
      new Promise((resolve) => {
        resolveWrite = resolve;
      }),
    );
    apiGet.mockResolvedValue({
      ok: true,
      status: 200,
      data: { projects: [{ projectId: LINKED_ID, name: "Bridge Rollout" }], nextCursor: null },
      error: null,
      errorClass: null,
      code: null,
    });
    renderPicker({}, ALL_PROJECTS_RESOLUTION);
    const control = select();
    await waitFor(() => expect(within(control).getByText("Bridge Rollout")).toBeInTheDocument());

    await user.selectOptions(control, LINKED_ID);
    // The write has not resolved yet: the committed scope is still All
    // Projects, so the collapsed value must still say so — never the new
    // Project's name ahead of it actually being applied.
    expect(control).toHaveValue("ALL_PROJECTS");

    resolveWrite({
      ok: true,
      status: 200,
      data: { scope: "PROJECT", project: { id: LINKED_ID, name: "Bridge Rollout", state: "active", version: 3 } },
      error: null,
      errorClass: null,
      code: null,
    });
    await waitFor(() => expect(control).toHaveValue(LINKED_ID));
    expect(push).toHaveBeenCalledWith(`/work/projects/${LINKED_ID}/constraints`);
  });
});

describe("the injected scope-change barrier", () => {
  it("refuses the switch, sends no request, and leaves the applied scope unchanged when it returns false", async () => {
    const user = userEvent.setup();
    apiGet.mockResolvedValue({
      ok: true,
      status: 200,
      data: { projects: [{ projectId: LINKED_ID, name: "Bridge Rollout" }], nextCursor: null },
      error: null,
      errorClass: null,
      code: null,
    });
    const canSwitchScope = vi.fn(() => false);
    renderPicker({ canSwitchScope }, ALL_PROJECTS_RESOLUTION);
    const control = select();
    await waitFor(() => expect(within(control).getByText("Bridge Rollout")).toBeInTheDocument());

    await user.selectOptions(control, LINKED_ID);
    expect(canSwitchScope).toHaveBeenCalledOnce();
    expect(apiPost).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent(PROJECT_PICKER_BLOCKED);
  });

  it("defaults to always-allowed when no check is injected", async () => {
    const user = userEvent.setup();
    apiGet.mockResolvedValue({
      ok: true,
      status: 200,
      data: { projects: [{ projectId: LINKED_ID, name: "Bridge Rollout" }], nextCursor: null },
      error: null,
      errorClass: null,
      code: null,
    });
    apiPost.mockResolvedValue({
      ok: true,
      status: 200,
      data: { scope: "PROJECT", project: { id: LINKED_ID, name: "Bridge Rollout", state: "active", version: 3 } },
      error: null,
      errorClass: null,
      code: null,
    });
    renderPicker({}, ALL_PROJECTS_RESOLUTION);
    const control = select();
    await waitFor(() => expect(within(control).getByText("Bridge Rollout")).toBeInTheDocument());
    await user.selectOptions(control, LINKED_ID);
    await waitFor(() => expect(apiPost).toHaveBeenCalledOnce());
    expect(apiPost).toHaveBeenCalledWith({ hasSession: true }, "/api/project-scope", {
      scope: "PROJECT",
      projectId: LINKED_ID,
    });
  });
});

describe("selecting All Projects", () => {
  it("writes ALL_PROJECTS and navigates to the canonical Project-neutral route", async () => {
    const user = userEvent.setup();
    apiPost.mockResolvedValue({
      ok: true,
      status: 200,
      data: { scope: "ALL_PROJECTS" },
      error: null,
      errorClass: null,
      code: null,
    });
    renderPicker({}, LINKED_PROJECT_RESOLUTION);
    const control = select();
    await user.selectOptions(control, "ALL_PROJECTS");
    expect(apiPost).toHaveBeenCalledWith({ hasSession: true }, "/api/project-scope", {
      scope: "ALL_PROJECTS",
    });
    await waitFor(() => expect(control).toHaveValue("ALL_PROJECTS"));
    expect(push).toHaveBeenCalledWith("/work");
  });
});

describe("deep-link route authority winning over a stored preference", () => {
  it("reflects the deep-linked Project's name, not the remembered preference's, through the combined provider + binding", async () => {
    apiPost.mockResolvedValue({ ok: true, status: 200, data: { scope: "PROJECT" }, error: null, errorClass: null, code: null });
    render(
      <ProjectScopeProvider
        principalId="prn_aaaaaaaa11111111"
        sessionEpoch="session:a"
        initialResolution={SAVED_PROJECT_RESOLUTION}
      >
        <ProjectRouteScopeBinding
          resolution={LINKED_PROJECT_RESOLUTION}
          fallbackResolution={SAVED_PROJECT_RESOLUTION}
        >
          <ProjectPicker />
        </ProjectRouteScopeBinding>
      </ProjectScopeProvider>,
    );
    const control = select();
    expect(control).toHaveValue(LINKED_ID);
    expect(within(control).getByText("Bridge Rollout")).toBeInTheDocument();
    expect(screen.queryByText("Harbor Migration")).not.toBeInTheDocument();
    // The accepted deep link is persisted as the new remembered preference.
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith({ hasSession: true }, "/api/project-scope", {
        scope: "PROJECT",
        projectId: LINKED_ID,
      }),
    );
  });
});
