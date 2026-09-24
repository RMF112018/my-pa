"use client";

/**
 * `ConstraintCategoryAdmin` — Category administration, including reorder.
 *
 * **No routine hard delete (`PC-CM-FE-AC-086`).** The only way a Category
 * leaves the active set is Deactivate; there is no Delete control anywhere in
 * this file. A deactivated Category stays visible here, stays readable on any
 * existing Constraint that carries it, and is simply unavailable for a new
 * Publish (`constraint-authoring.tsx` enforces that half).
 *
 * **The prefix is visibly locked once it is immutable (`PC-CM-FE-AC-082`).**
 * `category.prefixLocked` is a backend-published flag, never inferred here
 * from whether a Register row happens to exist.
 *
 * **Reorder follows the frozen §9/SP4 sequence exactly:** immediately before
 * every dispatch this refetches the Project's complete all-state Category
 * list (never trusts whatever this component already had in memory),
 * freezes `orderedCategoryIds` as a permutation of that fresh list and
 * `expectedVersions` positionally from each Category's fresh version, sends
 * one idempotency key, and on success refetches the complete list again. On a
 * `409` it refetches the complete list, keeps the reader's proposed order
 * separately as a conflict banner, and requires a deliberate "Reapply this
 * order" action — minting a brand-new idempotency key — rather than silently
 * retrying the same request (`PC-CM-FE-AC-089`).
 *
 * **Keyboard reorder, and it waits.** Move Up/Down are ordinary `<button>`s —
 * no drag interaction is required to reorder. Both are disabled on every row
 * while a reorder is in flight, so a second Move cannot race the first; the
 * visible order only becomes the new order once the dispatch confirms.
 */
import { useCallback, useState } from "react";
import type { ConstraintCategory } from "@/contracts/constraints";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SurfaceState } from "@/components/ui/surface-state";
import { useMutationFeedback } from "@/components/ui/mutation-feedback";
import { useConstraintRuntime } from "@/components/project-controls/constraint-runtime-provider";
import { categoryCollectionLockKey, categoryLockKey } from "@/lib/constraint/mutation-coordinator";
import {
  createCategory,
  deactivateCategory,
  mintIdempotencyKey,
  readCategories,
  reorderCategories,
  updateCategory,
  type LiveMutationFailure,
} from "./constraint-live";

export interface ConstraintCategoryAdminProps {
  readonly open: boolean;
  readonly projectId: string;
  readonly categories: readonly ConstraintCategory[];
  readonly onClose: () => void;
  /** Called after any confirmed Category write, so the caller can refresh its own list. */
  readonly onChanged: () => void;
}

interface ReorderConflict {
  readonly proposedOrder: readonly string[];
  readonly message: string;
}

function byDisplayOrder(list: readonly ConstraintCategory[]): readonly ConstraintCategory[] {
  return [...list].sort((a, b) => a.displayOrder - b.displayOrder);
}

export function ConstraintCategoryAdmin({
  open,
  projectId,
  categories: initialCategories,
  onClose,
  onChanged,
}: ConstraintCategoryAdminProps) {
  const runtime = useConstraintRuntime();
  const feedback = useMutationFeedback();

  const [categories, setCategories] = useState<readonly ConstraintCategory[]>(byDisplayOrder(initialCategories));
  const [savingOrder, setSavingOrder] = useState(false);
  const [conflict, setConflict] = useState<ReorderConflict | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ConstraintCategory | null>(null);

  // Adopt a fresher `initialCategories` prop whenever it changes while open
  // (a caller-driven refresh), without a `useEffect` setState-on-mount
  // cascade: comparing against a tracked prior value, during render, is the
  // same "derive state from props" pattern `register-table.tsx`'s
  // `RegisterRow` uses.
  const [trackedCategories, setTrackedCategories] = useState(initialCategories);
  if (open && trackedCategories !== initialCategories) {
    setTrackedCategories(initialCategories);
    setCategories(byDisplayOrder(initialCategories));
  }

  const refresh = useCallback(async () => {
    const controller = new AbortController();
    const result = await readCategories(projectId, controller.signal);
    if (result.ok) {
      const own = result.value.filter((category) => category.projectId === projectId);
      setCategories(byDisplayOrder(own));
    }
    return result;
  }, [projectId]);

  async function commitReorder(proposedIds: readonly string[]) {
    setSavingOrder(true);
    setConflict(null);
    setError(null);

    // SP4 step 1: the complete, all-state list, fetched fresh immediately
    // before this dispatch — never the list already held in memory.
    const fresh = await refresh();
    if (!fresh.ok) {
      setSavingOrder(false);
      setError("The current Category order could not be read, so this reorder was not sent.");
      return;
    }
    const freshList = fresh.value.filter((category) => category.projectId === projectId);
    const freshIds = new Set(freshList.map((category) => category.categoryId));
    const proposedSet = new Set(proposedIds);
    const isPermutation = proposedSet.size === freshIds.size && [...proposedSet].every((id) => freshIds.has(id));
    if (!isPermutation) {
      setSavingOrder(false);
      setConflict({
        proposedOrder: proposedIds,
        message: "The Category set changed since this order was proposed. Review the current list before reapplying.",
      });
      return;
    }
    const byId = new Map(freshList.map((category) => [category.categoryId, category]));
    const expectedVersions = proposedIds.map((id) => byId.get(id)!.version);
    const idempotencyKey = mintIdempotencyKey();

    const outcome = await runtime.mutationCoordinator.mutate({
      kind: "categoryReorder",
      lockRequest: {
        kind: "category-collection",
        key: categoryCollectionLockKey(projectId),
        projectId,
        checkProjectRecordLocks: true,
      },
      idempotencyKey,
      expectedVersions,
      request: { orderedCategoryIds: proposedIds },
      epoch: runtime.scopeEpoch,
      isCurrentEpoch: runtime.isCurrentEpoch,
      dispatch: async ({ request, idempotencyKey: key, expectedVersions: versions }) =>
        reorderCategories(projectId, {
          orderedCategoryIds: (request as { orderedCategoryIds: readonly string[] }).orderedCategoryIds,
          expectedVersions: versions,
          idempotencyKey: key,
        }),
      hooks: {
        feedback: async (_result, phase) => {
          if (phase === "confirmed") {
            feedback.publish({ eventId: `category-reorder-${idempotencyKey}`, kind: "success", message: "The Category order was saved." });
          } else if (phase === "conflict") {
            feedback.publish({ eventId: `category-reorder-${idempotencyKey}-conflict`, kind: "conflict", message: "The Category order could not be saved: at least one Category changed." });
          } else if (phase === "failed" || phase === "ambiguous") {
            feedback.publish({ eventId: `category-reorder-${idempotencyKey}-failed`, kind: "error", message: "The Category order was not saved." });
          }
        },
      },
    });

    setSavingOrder(false);
    if (outcome.refused) {
      setError("Another Category write is in progress for this Project. Wait for it to finish.");
      return;
    }
    if (outcome.state.phase === "confirmed") {
      // SP4 step 5: refetch the complete list; the confirmed order is the
      // refetched order, never the locally proposed one.
      await refresh();
      onChanged();
      return;
    }
    if (outcome.state.phase === "conflict") {
      // SP4 step 6: refetch, keep the proposed order separately, require a
      // deliberate reapply.
      await refresh();
      setConflict({
        proposedOrder: proposedIds,
        message: "The order could not be saved: at least one Category changed since it was read.",
      });
      return;
    }
    const failure = outcome.state.error as LiveMutationFailure | undefined;
    setError(failure?.message ?? "The Category order was not saved.");
  }

  function move(categoryId: string, direction: -1 | 1) {
    if (savingOrder) return;
    const index = categories.findIndex((category) => category.categoryId === categoryId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= categories.length) return;
    const next = [...categories];
    [next[index], next[target]] = [next[target], next[index]];
    setCategories(next);
    void commitReorder(next.map((category) => category.categoryId));
  }

  function reapplyConflict() {
    if (!conflict) return;
    void commitReorder(conflict.proposedOrder);
  }

  return (
    <Dialog open={open} onClose={onClose} title="Constraint Categories">
      <div className="grid gap-3">
        <Badge tone="green">Live write</Badge>
        {conflict ? (
          <SurfaceState kind="degraded" title="Reorder not saved" detail={conflict.message} testId="category-reorder-conflict">
            <Button size="sm" onClick={reapplyConflict} data-testid="category-reorder-reapply">
              Reapply this order
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConflict(null)} data-testid="category-reorder-dismiss">
              Dismiss
            </Button>
          </SurfaceState>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-moss-coral-strong" data-testid="category-admin-error">
            {error}
          </p>
        ) : null}
        <table className="w-full text-left text-sm" data-testid="category-table">
          <caption className="sr-only">Constraint Categories in display order</caption>
          <thead>
            <tr>
              <th scope="col" className="px-2 py-1">Order</th>
              <th scope="col" className="px-2 py-1">Prefix</th>
              <th scope="col" className="px-2 py-1">Title</th>
              <th scope="col" className="px-2 py-1">State</th>
              <th scope="col" className="px-2 py-1">Actions</th>
            </tr>
          </thead>
          <tbody>
            {categories.map((category, index) => (
              <tr key={category.categoryId} data-testid={`category-row-${category.categoryId}`}>
                <td className="px-2 py-1">
                  <div className="flex items-center gap-1">
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      aria-label={`Move ${category.title} up`}
                      disabled={savingOrder || index === 0}
                      data-testid={`category-move-up-${category.categoryId}`}
                      onClick={() => move(category.categoryId, -1)}
                    >
                      ↑
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      aria-label={`Move ${category.title} down`}
                      disabled={savingOrder || index === categories.length - 1}
                      data-testid={`category-move-down-${category.categoryId}`}
                      onClick={() => move(category.categoryId, 1)}
                    >
                      ↓
                    </Button>
                    <span>{category.displayOrder}</span>
                  </div>
                </td>
                <td className="px-2 py-1">
                  {category.prefix}
                  {category.prefixLocked ? (
                    <span className="ml-1 text-xs text-muted" data-testid={`category-prefix-locked-${category.categoryId}`}>
                      (locked — {category.issuedCount} Codes issued)
                    </span>
                  ) : null}
                </td>
                <td className="px-2 py-1">{category.title}</td>
                <td className="px-2 py-1">
                  <Badge tone={category.state === "ACTIVE" ? "neutral" : "gold"}>
                    {category.state === "ACTIVE" ? "Active" : category.state === "INACTIVE" ? "Inactive" : "Archived"}
                  </Badge>
                </td>
                <td className="px-2 py-1">
                  <div className="flex gap-1">
                    <Button size="sm" variant="secondary" data-testid={`category-edit-${category.categoryId}`} onClick={() => setEditing(category)}>
                      Edit
                    </Button>
                    {category.state === "ACTIVE" ? (
                      <CategoryDeactivateButton
                        projectId={projectId}
                        category={category}
                        onDone={async () => {
                          await refresh();
                          onChanged();
                        }}
                      />
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-sm text-muted" data-testid="category-no-hard-delete">
          There is no routine hard delete. Deactivating retires a Category from new filings; it stays
          readable on existing Constraints.
        </p>
        <div className="flex gap-2">
          <Button size="sm" data-testid="category-create" onClick={() => setCreateOpen(true)}>
            New Category
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose} data-testid="category-close">
            Close
          </Button>
        </div>
      </div>
      <CategoryCreateDialog
        open={createOpen}
        projectId={projectId}
        nextDisplayOrder={categories.length}
        onClose={() => setCreateOpen(false)}
        onCreated={async () => {
          setCreateOpen(false);
          await refresh();
          onChanged();
        }}
      />
      <CategoryEditDialog
        category={editing}
        projectId={projectId}
        onClose={() => setEditing(null)}
        onUpdated={async () => {
          setEditing(null);
          await refresh();
          onChanged();
        }}
      />
    </Dialog>
  );
}

function CategoryDeactivateButton({
  projectId,
  category,
  onDone,
}: {
  readonly projectId: string;
  readonly category: ConstraintCategory;
  readonly onDone: () => void | Promise<void>;
}) {
  const runtime = useConstraintRuntime();
  const feedback = useMutationFeedback();
  const [pending, setPending] = useState(false);

  async function deactivate() {
    if (pending) return;
    setPending(true);
    const idempotencyKey = mintIdempotencyKey();
    const outcome = await runtime.mutationCoordinator.mutate({
      kind: "categoryDeactivate",
      lockRequest: { kind: "category-record", key: categoryLockKey(category.categoryId), projectId },
      idempotencyKey,
      expectedVersion: category.version,
      request: {},
      epoch: runtime.scopeEpoch,
      isCurrentEpoch: runtime.isCurrentEpoch,
      dispatch: async ({ idempotencyKey: key, expectedVersion }) =>
        deactivateCategory(projectId, category.categoryId, { idempotencyKey: key, expectedVersion }),
      hooks: {
        feedback: async (_result, phase) => {
          if (phase === "confirmed") {
            feedback.publish({ eventId: `category-deactivate-${idempotencyKey}`, kind: "success", message: `${category.title} was deactivated.` });
          } else {
            feedback.publish({ eventId: `category-deactivate-${idempotencyKey}-${phase}`, kind: phase === "conflict" ? "conflict" : "error", message: `${category.title} was not deactivated.` });
          }
        },
      },
    });
    setPending(false);
    if (!outcome.refused && outcome.state.phase === "confirmed") await onDone();
  }

  return (
    <Button size="sm" variant="danger" disabled={pending} data-testid={`category-deactivate-${category.categoryId}`} onClick={() => void deactivate()}>
      {pending ? "Working…" : "Deactivate"}
    </Button>
  );
}

function CategoryCreateDialog({
  open,
  projectId,
  nextDisplayOrder,
  onClose,
  onCreated,
}: {
  readonly open: boolean;
  readonly projectId: string;
  readonly nextDisplayOrder: number;
  readonly onClose: () => void;
  readonly onCreated: () => void | Promise<void>;
}) {
  const runtime = useConstraintRuntime();
  const feedback = useMutationFeedback();
  const [prefix, setPrefix] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (pending || prefix.trim().length === 0 || title.trim().length === 0) return;
    setPending(true);
    setError(null);
    const idempotencyKey = mintIdempotencyKey();
    const outcome = await runtime.mutationCoordinator.mutate({
      kind: "categoryCreate",
      // Same collection-level lock a reorder for this Project takes, so a
      // create and an in-flight reorder for the same Project cannot race.
      lockRequest: { kind: "category-collection", key: categoryCollectionLockKey(projectId), projectId },
      idempotencyKey,
      request: {
        prefix: prefix.trim(),
        title: title.trim(),
        description: description.trim().length > 0 ? description.trim() : undefined,
        displayOrder: nextDisplayOrder,
        state: "active" as const,
      },
      epoch: runtime.scopeEpoch,
      isCurrentEpoch: runtime.isCurrentEpoch,
      dispatch: async ({ request, idempotencyKey: key }) =>
        createCategory(projectId, { ...(request as Record<string, unknown>), idempotencyKey: key }),
      hooks: {
        feedback: async (_result, phase) => {
          if (phase === "confirmed") {
            feedback.publish({ eventId: `category-create-${idempotencyKey}`, kind: "success", message: "The Category was created." });
          } else {
            feedback.publish({ eventId: `category-create-${idempotencyKey}-${phase}`, kind: "error", message: "The Category was not created." });
          }
        },
      },
    });
    setPending(false);
    if (outcome.refused) {
      setError("Another Category write is in progress. Try again shortly.");
      return;
    }
    if (outcome.state.phase === "confirmed") {
      setPrefix("");
      setTitle("");
      setDescription("");
      await onCreated();
      return;
    }
    const failure = outcome.state.error as LiveMutationFailure | undefined;
    setError(failure?.message ?? "The Category was not created.");
  }

  return (
    <Dialog open={open} onClose={onClose} title="New Category">
      <div className="grid gap-3">
        <label className="grid gap-1 text-sm">
          Prefix
          <Input value={prefix} data-testid="category-form-prefix" onChange={(event) => setPrefix(event.target.value)} />
        </label>
        <label className="grid gap-1 text-sm">
          Title
          <Input value={title} data-testid="category-form-title" onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label className="grid gap-1 text-sm">
          Description
          <Textarea value={description} data-testid="category-form-description" onChange={(event) => setDescription(event.target.value)} />
        </label>
        {error ? (
          <p role="alert" className="text-sm text-moss-coral-strong" data-testid="category-form-error">
            {error}
          </p>
        ) : null}
        <div className="flex gap-2">
          <Button size="sm" disabled={pending} data-testid="category-form-submit" onClick={() => void submit()}>
            {pending ? "Creating…" : "Create"}
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose} data-testid="category-form-cancel">
            Cancel
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function CategoryEditDialog({
  category,
  projectId,
  onClose,
  onUpdated,
}: {
  readonly category: ConstraintCategory | null;
  readonly projectId: string;
  readonly onClose: () => void;
  readonly onUpdated: () => void | Promise<void>;
}) {
  const runtime = useConstraintRuntime();
  const feedback = useMutationFeedback();
  const [title, setTitle] = useState(category?.title ?? "");
  const [description, setDescription] = useState(category?.description ?? "");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A fresh `category` (a different row's Edit was clicked) resets the form,
  // derived during render rather than a `useEffect` setState cascade.
  const [trackedCategory, setTrackedCategory] = useState(category);
  if (trackedCategory !== category) {
    setTrackedCategory(category);
    setTitle(category?.title ?? "");
    setDescription(category?.description ?? "");
    setError(null);
  }

  if (category === null) return null;

  async function submit() {
    if (pending || title.trim().length === 0 || category === null) return;
    setPending(true);
    setError(null);
    const idempotencyKey = mintIdempotencyKey();
    const outcome = await runtime.mutationCoordinator.mutate({
      kind: "categoryUpdate",
      lockRequest: { kind: "category-record", key: categoryLockKey(category.categoryId), projectId },
      idempotencyKey,
      expectedVersion: category.version,
      request: {
        title: title.trim(),
        description: description.trim().length > 0 ? description.trim() : undefined,
      },
      epoch: runtime.scopeEpoch,
      isCurrentEpoch: runtime.isCurrentEpoch,
      dispatch: async ({ request, idempotencyKey: key, expectedVersion }) =>
        updateCategory(projectId, category.categoryId, {
          ...(request as Record<string, unknown>),
          idempotencyKey: key,
          expectedVersion,
        }),
      hooks: {
        feedback: async (_result, phase) => {
          if (phase === "confirmed") {
            feedback.publish({ eventId: `category-update-${idempotencyKey}`, kind: "success", message: "The Category was updated." });
          } else {
            feedback.publish({ eventId: `category-update-${idempotencyKey}-${phase}`, kind: phase === "conflict" ? "conflict" : "error", message: "The Category was not updated." });
          }
        },
      },
    });
    setPending(false);
    if (outcome.refused) {
      setError("This Category is already being written to.");
      return;
    }
    if (outcome.state.phase === "confirmed") {
      await onUpdated();
      return;
    }
    const failure = outcome.state.error as LiveMutationFailure | undefined;
    setError(failure?.message ?? "The Category was not updated.");
  }

  return (
    <Dialog open onClose={onClose} title={`Edit ${category.title}`}>
      <div className="grid gap-3">
        <p className="text-sm text-muted" data-testid="category-edit-prefix">
          Prefix: {category.prefix}
          {category.prefixLocked ? " (locked)" : ""}
        </p>
        <label className="grid gap-1 text-sm">
          Title
          <Input value={title} data-testid="category-edit-title" onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label className="grid gap-1 text-sm">
          Description
          <Textarea value={description} data-testid="category-edit-description" onChange={(event) => setDescription(event.target.value)} />
        </label>
        {error ? (
          <p role="alert" className="text-sm text-moss-coral-strong" data-testid="category-edit-error">
            {error}
          </p>
        ) : null}
        <div className="flex gap-2">
          <Button size="sm" disabled={pending} data-testid="category-edit-submit" onClick={() => void submit()}>
            {pending ? "Saving…" : "Save"}
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose} data-testid="category-edit-cancel">
            Cancel
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
