/**
 * `ConstraintAuthoring` — Draft vs. Publish are two different capabilities,
 * dispatched from two different buttons (`PC-CM-UX-AC-003`/`004`), and
 * nothing is shown as saved until the mutation confirms
 * (`PC-CM-FE-AC-045`, `PC-CM-UX-AC-005`).
 */
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ConstraintCategory } from "@/contracts/constraints";
import { ConstraintRuntimeProvider } from "@/components/project-controls/constraint-runtime-provider";
import { ProjectScopeProvider } from "@/components/shell/project-scope-provider";
import { MutationFeedbackProvider } from "@/components/ui/mutation-feedback";
import type { ResolvedProjectScope } from "@/lib/project-scope/resolver";

const writes = vi.hoisted(() => ({
  createDraft: vi.fn(),
  createPublished: vi.fn(),
}));

vi.mock("./constraint-live", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./constraint-live")>();
  return { ...actual, createDraft: writes.createDraft, createPublished: writes.createPublished };
});

import { ConstraintAuthoring } from "./constraint-authoring";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const ALL_PROJECTS_RESOLUTION: ResolvedProjectScope = {
  scope: { kind: "ALL_PROJECTS" },
  source: "default",
  project: null,
  normalized: false,
};

function Harness({ children }: { readonly children: ReactNode }) {
  return (
    <ProjectScopeProvider principalId="prn_aaaaaaaa11111111" sessionEpoch="session:a" initialResolution={ALL_PROJECTS_RESOLUTION}>
      <MutationFeedbackProvider>
        <ConstraintRuntimeProvider principalId="prn_aaaaaaaa11111111" sessionEpoch="session:a">
          {children}
        </ConstraintRuntimeProvider>
      </MutationFeedbackProvider>
    </ProjectScopeProvider>
  );
}

const ACTIVE_CATEGORY: ConstraintCategory = {
  categoryId: "ccat_aaaaaaaa11111111",
  projectId: "prj_aaaaaaaa11111111",
  prefix: "1",
  title: "Design",
  description: null,
  displayOrder: 0,
  state: "ACTIVE",
  nextSequence: 1,
  issuedCount: 0,
  version: 1,
  prefixLocked: false,
};

const INACTIVE_CATEGORY: ConstraintCategory = { ...ACTIVE_CATEGORY, categoryId: "ccat_bbbbbbbb22222222", title: "Retired", state: "INACTIVE" };

function draftAnswer(overrides: Record<string, unknown> = {}) {
  return {
    shape: "backend",
    disposition: "applied",
    constraint: {
      constraintId: "cst_aaaaaaaa11111111",
      lifecycleState: "draft",
      origin: "product",
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-01T00:00:00Z",
      version: 1,
      projectId: "prj_aaaaaaaa11111111",
      categoryId: null,
      constraintCode: null,
      description: "A new Draft",
      dateIdentified: null,
      dueDate: null,
      reference: null,
      currentUpdate: null,
      bic: [],
      responsible: [],
      completionDate: null,
      closureCommentary: null,
      voidedDate: null,
      voidReason: null,
      recordQuality: "NORMAL",
      publishedAt: null,
    },
    receipt: {
      historyId: "chst_00000001",
      constraintId: "cst_aaaaaaaa11111111",
      operation: "CREATE",
      actor: "PRINCIPAL",
      outcome: "APPLIED",
      beforeVersion: 0,
      afterVersion: 1,
      occurredAt: "2026-01-01T00:00:00Z",
      projectId: "prj_aaaaaaaa11111111",
      revisionId: null,
      safeFailureReason: null,
    },
    disclosure: { scope: "constraint-create", coverage: "complete", freshnessAt: "2026-01-01T00:00:00Z", authority: "accepted", limitations: [], truncated: false },
    ...overrides,
  };
}

describe("ConstraintAuthoring — create", () => {
  it("shows the Draft wording, never a Code, before anything is saved", async () => {
    render(
      <Harness>
        <ConstraintAuthoring
          mode="create"
          open
          projectId="prj_aaaaaaaa11111111"
          categories={[ACTIVE_CATEGORY]}
          onClose={() => undefined}
          onCreated={() => undefined}
          onUpdated={() => undefined}
        />
      </Harness>,
    );
    expect(screen.getByTestId("authoring-code")).toHaveTextContent("Draft — no Constraint number yet");
  });

  it("Save Draft dispatches constraints.create, not create_published", async () => {
    const user = userEvent.setup();
    writes.createDraft.mockResolvedValue(draftAnswer());
    const onCreated = vi.fn();
    render(
      <Harness>
        <ConstraintAuthoring
          mode="create"
          open
          projectId="prj_aaaaaaaa11111111"
          categories={[ACTIVE_CATEGORY]}
          onClose={() => undefined}
          onCreated={onCreated}
          onUpdated={() => undefined}
        />
      </Harness>,
    );
    await user.type(screen.getByTestId("authoring-description"), "A new Draft");
    await user.click(screen.getByTestId("authoring-save-draft"));
    await waitFor(() => expect(writes.createDraft).toHaveBeenCalled());
    expect(writes.createPublished).not.toHaveBeenCalled();
    expect(writes.createDraft.mock.calls[0][0]).toBe("prj_aaaaaaaa11111111");
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("cst_aaaaaaaa11111111"));
  });

  it("Publish requires a Category, and only an active one", async () => {
    const user = userEvent.setup();
    render(
      <Harness>
        <ConstraintAuthoring
          mode="create"
          open
          projectId="prj_aaaaaaaa11111111"
          categories={[ACTIVE_CATEGORY, INACTIVE_CATEGORY]}
          onClose={() => undefined}
          onCreated={() => undefined}
          onUpdated={() => undefined}
        />
      </Harness>,
    );
    await user.click(screen.getByTestId("authoring-publish"));
    expect(await screen.findByTestId("authoring-error")).toHaveTextContent("Choose a Category before publishing.");
    expect(writes.createPublished).not.toHaveBeenCalled();
    // The inactive Category is offered but disabled — never a silently
    // eligible option for a new Publish.
    expect(screen.getByRole("option", { name: /Retired/ })).toBeDisabled();
  });

  it("leaves nothing saved when the write fails", async () => {
    const user = userEvent.setup();
    writes.createDraft.mockRejectedValue({ status: 500, code: "backend_error", message: "The write failed." });
    const onCreated = vi.fn();
    render(
      <Harness>
        <ConstraintAuthoring
          mode="create"
          open
          projectId="prj_aaaaaaaa11111111"
          categories={[ACTIVE_CATEGORY]}
          onClose={() => undefined}
          onCreated={onCreated}
          onUpdated={() => undefined}
        />
      </Harness>,
    );
    await user.type(screen.getByTestId("authoring-description"), "Will not save");
    await user.click(screen.getByTestId("authoring-save-draft"));
    expect(await screen.findByTestId("authoring-error")).toHaveTextContent("The write failed.");
    expect(onCreated).not.toHaveBeenCalled();
    // The dialog stays open on the author's own input.
    expect(screen.getByTestId("authoring-description")).toHaveValue("Will not save");
  });
});
