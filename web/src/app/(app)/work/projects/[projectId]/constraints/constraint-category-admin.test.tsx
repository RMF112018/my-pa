/**
 * `ConstraintCategoryAdmin` — the prefix is visibly locked once immutable
 * (`PC-CM-FE-AC-082`), there is no routine hard delete (`-086`), and
 * keyboard Move Up/Down reorder waits for the saved order before it is
 * shown as final (`-089`, following the frozen §9/SP4 sequence).
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
  readCategories: vi.fn(),
  reorderCategories: vi.fn(),
  deactivateCategory: vi.fn(),
  createCategory: vi.fn(),
  updateCategory: vi.fn(),
}));

vi.mock("./constraint-live", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./constraint-live")>();
  return { ...actual, ...writes };
});

import { ConstraintCategoryAdmin } from "./constraint-category-admin";

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

const PROJECT_ID = "prj_aaaaaaaa11111111";

const CATEGORY_A: ConstraintCategory = {
  categoryId: "ccat_aaaaaaaa11111111",
  projectId: PROJECT_ID,
  prefix: "1",
  title: "Design",
  description: null,
  displayOrder: 0,
  state: "ACTIVE",
  nextSequence: 3,
  issuedCount: 2,
  version: 1,
  prefixLocked: true,
};

const CATEGORY_B: ConstraintCategory = {
  ...CATEGORY_A,
  categoryId: "ccat_bbbbbbbb22222222",
  prefix: "2",
  title: "Procurement",
  displayOrder: 1,
  issuedCount: 0,
  prefixLocked: false,
};

const ok = (value: readonly ConstraintCategory[]) => ({ ok: true as const, value, disclosure: { scope: "constraint-categories", coverage: "complete", freshnessAt: "2026-01-01T00:00:00Z", authority: "accepted", limitations: [], truncated: false } });

function reorderAnswer(categories: readonly ConstraintCategory[]) {
  return {
    shape: "backend",
    disposition: "applied",
    categories: categories.map((category, index) => ({
      categoryId: category.categoryId,
      projectId: PROJECT_ID,
      prefix: category.prefix,
      title: category.title,
      state: "active",
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-02T00:00:00Z",
      description: null,
      displayOrder: index,
      prefixLockedAt: category.prefixLocked ? "2026-01-01T00:00:00Z" : null,
    })),
    receipts: categories.map((category) => ({
      historyId: `cchst_${category.categoryId}`,
      projectId: PROJECT_ID,
      categoryId: category.categoryId,
      operation: "update",
      actor: "PRINCIPAL",
      outcome: "APPLIED",
      beforeVersion: category.version,
      afterVersion: category.version + 1,
      occurredAt: "2026-01-02T00:00:00Z",
      safeFailureReason: null,
    })),
    disclosure: { scope: "constraint-category-reorder", coverage: "complete", freshnessAt: "2026-01-02T00:00:00Z", authority: "accepted", limitations: [], truncated: false },
  };
}

describe("ConstraintCategoryAdmin", () => {
  it("shows the prefix as visibly locked only when the backend says so", async () => {
    render(
      <Harness>
        <ConstraintCategoryAdmin open projectId={PROJECT_ID} categories={[CATEGORY_A, CATEGORY_B]} onClose={() => undefined} onChanged={() => undefined} />
      </Harness>,
    );
    expect(screen.getByTestId(`category-prefix-locked-${CATEGORY_A.categoryId}`)).toBeInTheDocument();
    expect(screen.queryByTestId(`category-prefix-locked-${CATEGORY_B.categoryId}`)).toBeNull();
  });

  it("offers Deactivate and never a Delete control", () => {
    render(
      <Harness>
        <ConstraintCategoryAdmin open projectId={PROJECT_ID} categories={[CATEGORY_A]} onClose={() => undefined} onChanged={() => undefined} />
      </Harness>,
    );
    expect(screen.getByTestId(`category-deactivate-${CATEGORY_A.categoryId}`)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
    expect(screen.getByTestId("category-no-hard-delete")).toBeInTheDocument();
  });

  it("reorders with keyboard Move Up/Down, freezing the complete list and versions fresh before dispatch", async () => {
    const user = userEvent.setup();
    writes.readCategories.mockResolvedValue(ok([CATEGORY_A, CATEGORY_B]));
    writes.reorderCategories.mockResolvedValue(reorderAnswer([CATEGORY_B, CATEGORY_A]));
    render(
      <Harness>
        <ConstraintCategoryAdmin open projectId={PROJECT_ID} categories={[CATEGORY_A, CATEGORY_B]} onClose={() => undefined} onChanged={() => undefined} />
      </Harness>,
    );
    const moveDown = screen.getByTestId(`category-move-down-${CATEGORY_A.categoryId}`);
    await user.click(moveDown);
    await waitFor(() => expect(writes.reorderCategories).toHaveBeenCalledTimes(1));
    const [, body] = writes.reorderCategories.mock.calls[0];
    expect(body).toMatchObject({
      orderedCategoryIds: [CATEGORY_B.categoryId, CATEGORY_A.categoryId],
      expectedVersions: [CATEGORY_B.version, CATEGORY_A.version],
    });
    // SP4 step 1: the complete list was refetched fresh immediately before
    // dispatch, not read from what this component already held.
    expect(writes.readCategories).toHaveBeenCalled();
    await waitFor(() => expect(moveDown).toBeEnabled());
  });

  it("on a reorder conflict, keeps the proposed order separate and requires a deliberate reapply", async () => {
    const user = userEvent.setup();
    writes.readCategories.mockResolvedValue(ok([CATEGORY_A, CATEGORY_B]));
    writes.reorderCategories.mockRejectedValueOnce({ status: 409, code: "version_conflict", message: "conflict" });
    writes.reorderCategories.mockResolvedValueOnce(reorderAnswer([CATEGORY_B, CATEGORY_A]));
    render(
      <Harness>
        <ConstraintCategoryAdmin open projectId={PROJECT_ID} categories={[CATEGORY_A, CATEGORY_B]} onClose={() => undefined} onChanged={() => undefined} />
      </Harness>,
    );
    await user.click(screen.getByTestId(`category-move-down-${CATEGORY_A.categoryId}`));
    const conflict = await screen.findByTestId("category-reorder-conflict");
    expect(conflict).toHaveAttribute("data-state", "degraded");
    await user.click(screen.getByTestId("category-reorder-reapply"));
    await waitFor(() => expect(writes.reorderCategories).toHaveBeenCalledTimes(2));
    // A fresh idempotency key each attempt, never the same key blindly retried.
    const firstKey = writes.reorderCategories.mock.calls[0][1].idempotencyKey;
    const secondKey = writes.reorderCategories.mock.calls[1][1].idempotencyKey;
    expect(secondKey).not.toBe(firstKey);
  });
});
