/**
 * `ConstraintDirectActions` — never optimistic (`PC-CM-FE-AC-066`/`074`),
 * Void requires date and reason (`PC-CM-FE-AC-073`), Reopen requires a
 * terminal source (`PC-CM-FE-AC-075`).
 */
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ConstraintListEntry } from "@/contracts/constraints";
import { ConstraintRuntimeProvider } from "@/components/project-controls/constraint-runtime-provider";
import { ProjectScopeProvider } from "@/components/shell/project-scope-provider";
import { MutationFeedbackProvider } from "@/components/ui/mutation-feedback";
import type { ResolvedProjectScope } from "@/lib/project-scope/resolver";

const writes = vi.hoisted(() => ({
  closeConstraint: vi.fn(),
  voidConstraint: vi.fn(),
  reopenConstraint: vi.fn(),
  transitionConstraint: vi.fn(),
  closeFollowUpConstraint: vi.fn(),
}));

vi.mock("./constraint-live", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./constraint-live")>();
  return { ...actual, ...writes };
});

import { ConstraintDirectActions } from "./constraint-direct-actions";

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

const OPEN_ENTRY: ConstraintListEntry = {
  constraintId: "cst_aaaaaaaa11111111",
  projectId: "prj_aaaaaaaa11111111",
  constraintCode: "1.01",
  description: "Confirm the schedule",
  category: null,
  status: "IN_PROGRESS",
  dateIdentified: "2026-01-01",
  dueDate: "2026-02-01",
  bic: [],
  responsible: [],
  reference: null,
  daysElapsed: 10,
  version: 3,
  updatedAt: "2026-01-05T00:00:00Z",
  isOverdue: false,
  isDueSoon: false,
  inMyCourt: false,
  recordQuality: "NORMAL",
  needsAttention: false,
  syncState: "NEVER_SYNCED",
  groupKeys: [],
};

const CLOSED_ENTRY: ConstraintListEntry = { ...OPEN_ENTRY, status: "CLOSED" };

function answer(constraintId: string, lifecycleState: string) {
  return {
    shape: "backend",
    disposition: "applied",
    constraint: {
      constraintId,
      lifecycleState,
      origin: "product",
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-06T00:00:00Z",
      version: 4,
      projectId: "prj_aaaaaaaa11111111",
      categoryId: null,
      constraintCode: "1.01",
      description: "Confirm the schedule",
      dateIdentified: "2026-01-01",
      dueDate: "2026-02-01",
      reference: null,
      currentUpdate: null,
      bic: [],
      responsible: [],
      completionDate: null,
      closureCommentary: null,
      voidedDate: null,
      voidReason: null,
      recordQuality: "NORMAL",
      publishedAt: "2026-01-01T00:00:00Z",
    },
    receipt: {
      historyId: "chst_00000002",
      constraintId,
      operation: "CLOSE",
      actor: "PRINCIPAL",
      outcome: "APPLIED",
      beforeVersion: 3,
      afterVersion: 4,
      occurredAt: "2026-01-06T00:00:00Z",
      projectId: "prj_aaaaaaaa11111111",
      revisionId: null,
      safeFailureReason: null,
    },
    disclosure: { scope: "constraint-close", coverage: "complete", freshnessAt: "2026-01-06T00:00:00Z", authority: "accepted", limitations: [], truncated: false },
  };
}

describe("ConstraintDirectActions", () => {
  it("dispatches Close only on explicit confirm, never while the dialog is merely open", async () => {
    const user = userEvent.setup();
    writes.closeConstraint.mockResolvedValue(answer(OPEN_ENTRY.constraintId, "closed"));
    const onCompleted = vi.fn();
    render(
      <Harness>
        <ConstraintDirectActions action="close" projectId="prj_aaaaaaaa11111111" entry={OPEN_ENTRY} onClose={() => undefined} onCompleted={onCompleted} />
      </Harness>,
    );
    expect(screen.getByTestId("direct-action-confirm")).toBeInTheDocument();
    expect(writes.closeConstraint).not.toHaveBeenCalled();
    await user.click(screen.getByTestId("direct-action-confirm"));
    await waitFor(() => expect(writes.closeConstraint).toHaveBeenCalledTimes(1));
    expect(writes.closeConstraint.mock.calls[0][1]).toBe(OPEN_ENTRY.constraintId);
    expect(writes.closeConstraint.mock.calls[0][2]).toMatchObject({ expectedVersion: OPEN_ENTRY.version });
    await waitFor(() => expect(onCompleted).toHaveBeenCalledWith({ successorId: undefined }));
  });

  it("requires both a date and a reason before Void can be confirmed", async () => {
    const user = userEvent.setup();
    render(
      <Harness>
        <ConstraintDirectActions action="void" projectId="prj_aaaaaaaa11111111" entry={OPEN_ENTRY} onClose={() => undefined} onCompleted={() => undefined} />
      </Harness>,
    );
    const confirm = screen.getByTestId("direct-action-confirm");
    expect(confirm).toBeDisabled();
    await user.type(screen.getByTestId("direct-action-void-reason"), "Superseded by 1.03");
    expect(confirm).toBeDisabled();
    await user.type(screen.getByTestId("direct-action-void-date"), "2026-01-06");
    expect(confirm).toBeEnabled();
    writes.voidConstraint.mockResolvedValue(answer(OPEN_ENTRY.constraintId, "void"));
    await user.click(confirm);
    await waitFor(() => expect(writes.voidConstraint).toHaveBeenCalled());
    expect(writes.voidConstraint.mock.calls[0][2]).toMatchObject({ voidReason: "Superseded by 1.03", voidedDate: "2026-01-06" });
  });

  it("does not offer Reopen for a non-terminal record", () => {
    render(
      <Harness>
        <ConstraintDirectActions action="reopen" projectId="prj_aaaaaaaa11111111" entry={OPEN_ENTRY} onClose={() => undefined} onCompleted={() => undefined} />
      </Harness>,
    );
    expect(screen.getByTestId("direct-action-reopen-ineligible")).toBeInTheDocument();
    expect(screen.getByTestId("direct-action-confirm")).toBeDisabled();
  });

  it("allows Reopen for a terminal record once a target state and reason are given", async () => {
    const user = userEvent.setup();
    writes.reopenConstraint.mockResolvedValue(answer(CLOSED_ENTRY.constraintId, "identified"));
    render(
      <Harness>
        <ConstraintDirectActions action="reopen" projectId="prj_aaaaaaaa11111111" entry={CLOSED_ENTRY} onClose={() => undefined} onCompleted={() => undefined} />
      </Harness>,
    );
    expect(screen.queryByTestId("direct-action-reopen-ineligible")).toBeNull();
    const confirm = screen.getByTestId("direct-action-confirm");
    expect(confirm).toBeDisabled();
    await user.type(screen.getByTestId("direct-action-reopen-reason"), "Client reopened the item");
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() => expect(writes.reopenConstraint).toHaveBeenCalled());
  });

  it("reports a conflict as requiring a fresh review, not a blind retry", async () => {
    const user = userEvent.setup();
    writes.closeConstraint.mockRejectedValue({ status: 409, code: "version_conflict", message: "conflict" });
    render(
      <Harness>
        <ConstraintDirectActions action="close" projectId="prj_aaaaaaaa11111111" entry={OPEN_ENTRY} onClose={() => undefined} onCompleted={() => undefined} />
      </Harness>,
    );
    await user.click(screen.getByTestId("direct-action-confirm"));
    expect(await screen.findByTestId("direct-action-error")).toHaveTextContent("fresh review");
    // No retry control — closing and reopening against the current record is
    // the only path forward.
    expect(screen.queryByTestId("direct-action-retry")).toBeNull();
  });
});
