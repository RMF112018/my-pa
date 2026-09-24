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
import type { LiveConstraintView } from "./constraint-live";
import { ConstraintRuntimeProvider } from "@/components/project-controls/constraint-runtime-provider";
import { ProjectScopeProvider } from "@/components/shell/project-scope-provider";
import { MutationFeedbackProvider } from "@/components/ui/mutation-feedback";
import type { ResolvedProjectScope } from "@/lib/project-scope/resolver";

const writes = vi.hoisted(() => ({
  createDraft: vi.fn(),
  createPublished: vi.fn(),
  publishConstraint: vi.fn(),
}));

vi.mock("./constraint-live", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./constraint-live")>();
  return {
    ...actual,
    createDraft: writes.createDraft,
    createPublished: writes.createPublished,
    publishConstraint: writes.publishConstraint,
  };
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

const DRAFT_DETAIL: LiveConstraintView = {
  constraintId: "cst_aaaaaaaa11111111",
  projectId: "prj_aaaaaaaa11111111",
  constraintCode: null,
  description: "A just-saved Draft",
  category: null,
  status: "DRAFT",
  dateIdentified: null,
  dueDate: null,
  bic: [],
  responsible: [],
  reference: null,
  daysElapsed: null,
  version: 1,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  isOverdue: false,
  isDueSoon: false,
  inMyCourt: false,
  recordQuality: "NORMAL",
  needsAttention: false,
  needsAttentionReasons: [],
  missingFields: [],
  isPublished: false,
  publishedAt: null,
  currentUpdate: null,
  completion: null,
  void: null,
  sync: { state: "NEVER_SYNCED", lastVerifiedAt: null, conflictCount: 0 },
  relationships: [],
  evidenceLinks: [],
};

describe("ConstraintAuthoring — edit, isDraftEdit falls back to detail (finding 4)", () => {
  it("offers Publish for a just-saved Draft even when the Register row (entry) isn't loaded", () => {
    // The Register's default scope is "open" — Draft is a separate scope —
    // so a Draft this dialog itself just saved is never in the currently
    // loaded rows: `entry` is `null` here, exactly as it would be live.
    // `detail` (the Inspector's own already-loaded canonical read) is what
    // must be consulted instead.
    render(
      <Harness>
        <ConstraintAuthoring
          mode="edit"
          open
          projectId="prj_aaaaaaaa11111111"
          categories={[ACTIVE_CATEGORY]}
          entry={null}
          detail={DRAFT_DETAIL}
          onClose={() => undefined}
          onCreated={() => undefined}
          onUpdated={() => undefined}
        />
      </Harness>,
    );
    expect(screen.getByTestId("authoring-code")).toHaveTextContent("Draft — no Constraint number yet");
    expect(screen.getByTestId("authoring-draft-identity")).toBeInTheDocument();
    expect(screen.getByTestId("authoring-publish")).toBeInTheDocument();
  });

  it("actually dispatches Publish (not just renders the button) for a just-saved Draft with entry === null, using detail's own constraintId", async () => {
    // The Publish button rendering (above) is necessary but not sufficient:
    // `submit()`'s own dispatch previously read `entry!.constraintId`
    // unconditionally in edit mode — a `TypeError` on a `null` entry,
    // classified by the mutation coordinator as a "network" failure and
    // surfaced as an ambiguous, unconfirmed outcome (confirmed live: no
    // network request was ever sent). This proves the actual write reaches
    // `publishConstraint` with `detail`'s own id, and confirms.
    const user = userEvent.setup();
    writes.publishConstraint.mockResolvedValue({
      shape: "backend",
      disposition: "applied",
      constraint: {
        constraintId: DRAFT_DETAIL.constraintId,
        lifecycleState: "identified",
        origin: "product",
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: "2026-01-02T00:00:00Z",
        version: 2,
        projectId: "prj_aaaaaaaa11111111",
        categoryId: ACTIVE_CATEGORY.categoryId,
        constraintCode: "1.01",
        description: DRAFT_DETAIL.description,
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
        publishedAt: "2026-01-02T00:00:00Z",
      },
      receipt: {
        historyId: "chst_00000002",
        constraintId: DRAFT_DETAIL.constraintId,
        operation: "PUBLISH",
        actor: "PRINCIPAL",
        outcome: "APPLIED",
        beforeVersion: 1,
        afterVersion: 2,
        occurredAt: "2026-01-02T00:00:00Z",
        projectId: "prj_aaaaaaaa11111111",
        revisionId: null,
        safeFailureReason: null,
      },
      disclosure: { scope: "constraint-publish", coverage: "complete", freshnessAt: "2026-01-02T00:00:00Z", authority: "accepted", limitations: [], truncated: false },
    });
    const onUpdated = vi.fn();
    render(
      <Harness>
        <ConstraintAuthoring
          mode="edit"
          open
          projectId="prj_aaaaaaaa11111111"
          categories={[ACTIVE_CATEGORY]}
          entry={null}
          detail={DRAFT_DETAIL}
          onClose={() => undefined}
          onCreated={() => undefined}
          onUpdated={onUpdated}
        />
      </Harness>,
    );
    await user.selectOptions(screen.getByTestId("authoring-category"), ACTIVE_CATEGORY.categoryId);
    await user.click(screen.getByTestId("authoring-publish"));
    await waitFor(() => expect(writes.publishConstraint).toHaveBeenCalled());
    expect(writes.publishConstraint.mock.calls[0][0]).toBe("prj_aaaaaaaa11111111");
    expect(writes.publishConstraint.mock.calls[0][1]).toBe(DRAFT_DETAIL.constraintId);
    await waitFor(() => expect(onUpdated).toHaveBeenCalled());
    expect(screen.queryByTestId("authoring-error")).toBeNull();
  });

  it("shows the Code, not Draft wording, and no Publish button for a published entry with no detail loaded yet", () => {
    // The inverse case: `entry` present (published), `detail` not yet loaded.
    // Confirms the `detail` fallback added for finding 4 doesn't invert this.
    render(
      <Harness>
        <ConstraintAuthoring
          mode="edit"
          open
          projectId="prj_aaaaaaaa11111111"
          categories={[ACTIVE_CATEGORY]}
          entry={{
            constraintId: "cst_bbbbbbbb22222222",
            projectId: "prj_aaaaaaaa11111111",
            constraintCode: "1.01",
            description: "Published",
            category: null,
            status: "IDENTIFIED",
            dateIdentified: null,
            dueDate: null,
            bic: [],
            responsible: [],
            reference: null,
            daysElapsed: null,
            version: 1,
            updatedAt: "2026-01-01T00:00:00Z",
            isOverdue: false,
            isDueSoon: false,
            inMyCourt: false,
            recordQuality: "NORMAL",
            needsAttention: false,
            syncState: "NEVER_SYNCED",
            groupKeys: [],
          }}
          detail={null}
          onClose={() => undefined}
          onCreated={() => undefined}
          onUpdated={() => undefined}
        />
      </Harness>,
    );
    expect(screen.getByTestId("authoring-code")).toHaveTextContent("1.01");
    expect(screen.queryByTestId("authoring-draft-identity")).toBeNull();
    expect(screen.queryByTestId("authoring-publish")).toBeNull();
  });
});

describe("ConstraintAuthoring — BIC/Responsible popover stays inside the dialog's own top layer (finding 5)", () => {
  it("renders the Add-party popover content inside the authoring <dialog>'s own DOM subtree", async () => {
    const user = userEvent.setup();
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
    await user.click(screen.getByTestId("authoring-bic-add"));
    const popoverContent = await screen.findByTestId("authoring-bic-add-me");
    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    // Never portaled out to `document.body` — the default Radix behavior —
    // once `constraint-authoring.tsx` supplies its own subtree as the
    // popover's `container`.
    expect(dialog?.contains(popoverContent)).toBe(true);
  });
});
