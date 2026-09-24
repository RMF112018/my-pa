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
import { ConstraintRuntimeProvider, useConstraintRuntime } from "@/components/project-controls/constraint-runtime-provider";
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

/**
 * Exercises the same `useConstraintRuntime().canSwitchScope()` barrier
 * `ProjectPicker` calls for the real §5a scope-switch guard (see
 * `constraint-runtime-provider.tsx`): with no dirty surface it resolves
 * `true` synchronously (no dialog); with a dirty surface it opens the same
 * "Discard unsaved changes?" `Sheet` the provider itself owns
 * (`constraint-scope-discard-confirm`/`-cancel`). This is a black-box probe
 * of whatever the mounted dialogs have reported via
 * `reportDirtyState`/`clearDirtyState` — it asserts nothing about their
 * internals, only what the runtime barrier itself would do.
 */
function DirtyProbe() {
  const runtime = useConstraintRuntime();
  return (
    <button type="button" data-testid="dirty-probe" onClick={() => void runtime.canSwitchScope()}>
      probe scope switch
    </button>
  );
}

function Harness({ children }: { readonly children: ReactNode }) {
  return (
    <ProjectScopeProvider principalId="prn_aaaaaaaa11111111" sessionEpoch="session:a" initialResolution={ALL_PROJECTS_RESOLUTION}>
      <MutationFeedbackProvider>
        <ConstraintRuntimeProvider principalId="prn_aaaaaaaa11111111" sessionEpoch="session:a">
          <DirtyProbe />
          {children}
        </ConstraintRuntimeProvider>
      </MutationFeedbackProvider>
    </ProjectScopeProvider>
  );
}

/** Clicks the probe and reports whether the discard-confirm barrier opened. */
async function probeIsDirty(user: ReturnType<typeof userEvent.setup>): Promise<boolean> {
  await user.click(screen.getByTestId("dirty-probe"));
  const prompt = screen.queryByTestId("constraint-scope-discard-confirm");
  if (prompt) {
    // Resolve it without actually discarding anything, so the probe itself
    // never changes the state under test.
    await user.click(screen.getByTestId("constraint-scope-discard-cancel"));
    return true;
  }
  return false;
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

  it("reports the New Category form's unsaved state to the runtime's scope-switch barrier, and clears it on Cancel", async () => {
    const user = userEvent.setup();
    render(
      <Harness>
        <ConstraintCategoryAdmin open projectId={PROJECT_ID} categories={[CATEGORY_A]} onClose={() => undefined} onChanged={() => undefined} />
      </Harness>,
    );
    await user.click(screen.getByTestId("category-create"));
    // Untouched: not dirty yet.
    expect(await probeIsDirty(user)).toBe(false);

    await user.type(screen.getByTestId("category-form-title"), "Environmental");
    expect(await probeIsDirty(user)).toBe(true);

    await user.click(screen.getByTestId("category-form-cancel"));
    expect(await probeIsDirty(user)).toBe(false);
  });

  it("reports the New Category form's unsaved state to the runtime's scope-switch barrier, and clears it on a confirmed Create", async () => {
    const user = userEvent.setup();
    writes.createCategory.mockResolvedValue({
      shape: "backend",
      disposition: "applied",
      category: { ...CATEGORY_A, categoryId: "ccat_cccccccc33333333", prefix: "3", title: "Environmental" },
      receipt: { historyId: "cchst_new", projectId: PROJECT_ID, categoryId: "ccat_cccccccc33333333", operation: "create", actor: "PRINCIPAL", outcome: "APPLIED", beforeVersion: 0, afterVersion: 1, occurredAt: "2026-01-02T00:00:00Z", safeFailureReason: null },
      disclosure: { scope: "constraint-category-create", coverage: "complete", freshnessAt: "2026-01-02T00:00:00Z", authority: "accepted", limitations: [], truncated: false },
    });
    render(
      <Harness>
        <ConstraintCategoryAdmin open projectId={PROJECT_ID} categories={[CATEGORY_A]} onClose={() => undefined} onChanged={() => undefined} />
      </Harness>,
    );
    await user.click(screen.getByTestId("category-create"));
    await user.type(screen.getByTestId("category-form-prefix"), "3");
    await user.type(screen.getByTestId("category-form-title"), "Environmental");
    expect(await probeIsDirty(user)).toBe(true);

    writes.readCategories.mockResolvedValue(ok([CATEGORY_A]));
    await user.click(screen.getByTestId("category-form-submit"));
    await waitFor(() => expect(writes.createCategory).toHaveBeenCalledTimes(1));
    expect(await probeIsDirty(user)).toBe(false);
  });

  it("reports the Edit Category form's unsaved state to the runtime's scope-switch barrier, and clears it on Cancel", async () => {
    const user = userEvent.setup();
    render(
      <Harness>
        <ConstraintCategoryAdmin open projectId={PROJECT_ID} categories={[CATEGORY_A]} onClose={() => undefined} onChanged={() => undefined} />
      </Harness>,
    );
    await user.click(screen.getByTestId(`category-edit-${CATEGORY_A.categoryId}`));
    // Pre-filled from the stored Category, so not dirty until actually changed.
    expect(await probeIsDirty(user)).toBe(false);

    await user.clear(screen.getByTestId("category-edit-title"));
    await user.type(screen.getByTestId("category-edit-title"), "Design (revised)");
    expect(await probeIsDirty(user)).toBe(true);

    await user.click(screen.getByTestId("category-edit-cancel"));
    expect(await probeIsDirty(user)).toBe(false);
  });

  describe("the outer admin dialog is never closed by a nested dialog's own lifecycle (finding 8)", () => {
    it("renders New Category's own <dialog> as a DOM sibling, never a descendant, of the admin's own <dialog>", async () => {
      const user = userEvent.setup();
      render(
        <Harness>
          <ConstraintCategoryAdmin open projectId={PROJECT_ID} categories={[CATEGORY_A]} onClose={() => undefined} onChanged={() => undefined} />
        </Harness>,
      );
      await user.click(screen.getByTestId("category-create"));
      const adminDialog = document.querySelector('dialog[aria-label="Constraint Categories"]');
      const createDialog = document.querySelector('dialog[aria-label="New Category"]');
      expect(adminDialog).not.toBeNull();
      expect(createDialog).not.toBeNull();
      // The real, live-confirmed browser behavior this fix avoids only fires
      // for a *nested* modal `<dialog>` — closing an inner one nested inside
      // an outer one also closed the outer one, with no React-state cause of
      // its own (see `constraint-category-admin.tsx`'s own doc comment).
      // jsdom implements neither `showModal()`'s real top-layer semantics nor
      // that specific browser behavior, so it cannot reproduce the bug
      // itself (that is what `project-controls-run02.spec.ts`'s
      // `[PC-CM-FE-AC-089]`/`[...AC-049][...AC-085]` E2E tests are for) —
      // but it can, and does, prove the structural precondition the fix
      // actually changed: the two dialogs are siblings, not nested.
      expect(adminDialog?.contains(createDialog)).toBe(false);
    });

    it("keeps the admin dialog open (never calls its own onClose) through a confirmed Category create", async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      writes.createCategory.mockResolvedValue({
        shape: "backend",
        disposition: "applied",
        category: { ...CATEGORY_A, categoryId: "ccat_cccccccc33333333", prefix: "3", title: "Environmental" },
        receipt: {
          historyId: "cchst_new2",
          projectId: PROJECT_ID,
          categoryId: "ccat_cccccccc33333333",
          operation: "create",
          actor: "PRINCIPAL",
          outcome: "APPLIED",
          beforeVersion: 0,
          afterVersion: 1,
          occurredAt: "2026-01-02T00:00:00Z",
          safeFailureReason: null,
        },
        disclosure: { scope: "constraint-category-create", coverage: "complete", freshnessAt: "2026-01-02T00:00:00Z", authority: "accepted", limitations: [], truncated: false },
      });
      writes.readCategories.mockResolvedValue(ok([CATEGORY_A]));
      render(
        <Harness>
          <ConstraintCategoryAdmin open projectId={PROJECT_ID} categories={[CATEGORY_A]} onClose={onClose} onChanged={() => undefined} />
        </Harness>,
      );
      await user.click(screen.getByTestId("category-create"));
      await user.type(screen.getByTestId("category-form-prefix"), "3");
      await user.type(screen.getByTestId("category-form-title"), "Environmental");
      await user.click(screen.getByTestId("category-form-submit"));
      await waitFor(() => expect(writes.createCategory).toHaveBeenCalledTimes(1));
      // The sub-dialog closes (its own onClose/onCreated path)...
      await waitFor(() => expect(screen.getByTestId("category-form-prefix")).not.toBeVisible());
      // ...but the admin's own onClose was never called, and its own dialog
      // is still present and open.
      expect(onClose).not.toHaveBeenCalled();
      expect(screen.getByRole("dialog", { name: "Constraint Categories" })).toBeInTheDocument();
    });
  });
});
