"use client";

/**
 * The create, edit and lifecycle surfaces — and the boundary they stop at.
 *
 * **Nothing here saves anything, and every one of them says so before you
 * submit and after.** There is no Constraint mutation endpoint at this head. A
 * form that pretended otherwise would be the worst possible outcome of a
 * fixture build: a reader would close a Constraint, see a confirmation, and
 * have closed nothing. So each dialog carries a standing synthetic notice, and
 * submitting produces one sentence naming exactly what did not happen.
 *
 * **No Code, no version, no receipt is invented.** Publishing does not show a
 * number the allocator would have issued; closing does not show a receipt id or
 * an incremented version. Those are backend authority and a fabricated one is
 * indistinguishable from a real one at a glance, which is precisely why
 * `CM-FE-AC-032` forbids the frontend predicting or reserving a Code and the
 * accepted contract forbids synthesising a Receipt.
 *
 * **Keyboard behaviour is the accepted one.** The native `<dialog>` primitive
 * traps focus and restores it to the opener; Escape cancels; multiline fields
 * commit on Ctrl/Cmd+Enter and take a newline on Shift+Enter
 * (`CM-FE-AC-136`/`137`/`139`).
 */
import { useState, type KeyboardEvent } from "react";
import type { ConstraintCategory, ConstraintListEntry } from "@/contracts/constraints";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { codeLabel, DRAFT_CODE_LABEL, lifecycleLabel } from "./presentation";
import type { ConstraintLifecycleAction } from "./constraint-inspector";

/** The standing notice every one of these surfaces carries. */
export const SYNTHETIC_MUTATION_NOTICE =
  "Fixture only. This build has no Constraint mutation endpoint, so nothing here is sent, " +
  "saved, or issued a Constraint Code, version or receipt.";

function SyntheticNotice({ surface }: { readonly surface: string }) {
  return (
    <p className="mb-3 flex items-center gap-2 text-sm text-muted" data-testid={`synthetic-notice-${surface}`}>
      <Badge tone="synthetic">Fixture</Badge>
      {SYNTHETIC_MUTATION_NOTICE}
    </p>
  );
}

/**
 * Commit on Ctrl/Cmd+Enter; leave Shift+Enter to insert a newline.
 *
 * Returned rather than inlined so the same rule governs every multiline field.
 */
export function multilineCommitHandler(commit: () => void) {
  return (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      commit();
    }
  };
}

export interface ConstraintFormDialogProps {
  readonly open: boolean;
  readonly mode: "create" | "edit";
  readonly entry: ConstraintListEntry | null;
  readonly categories: readonly ConstraintCategory[];
  readonly onClose: () => void;
  readonly onSyntheticOutcome: (message: string) => void;
}

export function ConstraintFormDialog({
  open,
  mode,
  entry,
  categories,
  onClose,
  onSyntheticOutcome,
}: ConstraintFormDialogProps) {
  const [description, setDescription] = useState(entry?.description ?? "");
  const [categoryId, setCategoryId] = useState(entry?.category?.categoryId ?? "");
  const [dueDate, setDueDate] = useState(entry?.dueDate ?? "");

  function commit(published: boolean) {
    onSyntheticOutcome(
      published
        ? "Not published. This build has no mutation endpoint, so no Constraint Code was issued and nothing was saved."
        : "Not saved as a Draft. This build has no mutation endpoint, so nothing was written and no version changed.",
    );
    onClose();
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={mode === "create" ? "New Constraint" : `Edit ${codeLabel(entry?.constraintCode ?? null)}`}
    >
      <SyntheticNotice surface="form" />
      <div className="grid gap-3">
        <p className="text-sm text-muted" data-testid="form-code">
          Constraint Code: {mode === "create" ? DRAFT_CODE_LABEL : codeLabel(entry?.constraintCode ?? null)}
        </p>
        <label className="grid gap-1 text-sm">
          Description
          <Textarea
            value={description}
            data-testid="form-description"
            onChange={(event) => setDescription(event.target.value)}
            onKeyDown={multilineCommitHandler(() => commit(false))}
          />
          <span className="text-xs text-muted">
            Ctrl/Cmd+Enter saves the Draft. Shift+Enter starts a new line.
          </span>
        </label>
        <label className="grid gap-1 text-sm">
          Category
          <Select
            value={categoryId}
            data-testid="form-category"
            onChange={(event) => setCategoryId(event.target.value)}
          >
            <option value="">Choose a Category</option>
            {categories.map((category) => (
              <option
                key={category.categoryId}
                value={category.categoryId}
                // An inactive Category is unavailable for a new Publish, and a
                // Draft already using one is not migrated anywhere.
                disabled={category.state !== "ACTIVE" && category.categoryId !== entry?.category?.categoryId}
              >
                {category.title}
                {category.state === "ACTIVE" ? "" : " (inactive — not available for Publish)"}
              </option>
            ))}
          </Select>
        </label>
        <label className="grid gap-1 text-sm">
          Due Date
          <Input
            type="date"
            value={dueDate}
            data-testid="form-due-date"
            onChange={(event) => setDueDate(event.target.value)}
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" data-testid="form-save-draft" onClick={() => commit(false)}>
            Save Draft
          </Button>
          <Button size="sm" data-testid="form-publish" onClick={() => commit(true)}>
            Publish
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose} data-testid="form-cancel">
            Cancel
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

const ACTION_TITLES: Record<ConstraintLifecycleAction, string> = {
  publish: "Publish Constraint",
  edit: "Edit Constraint",
  transition: "Change status",
  close: "Close Constraint",
  closeWithFollowUp: "Close with a follow-up Constraint",
  void: "Void Constraint",
  reopen: "Reopen Constraint",
};

export interface LifecycleDialogProps {
  readonly action: ConstraintLifecycleAction | null;
  readonly entry: ConstraintListEntry | null;
  readonly onClose: () => void;
  readonly onSyntheticOutcome: (message: string) => void;
}

export function LifecycleDialog({ action, entry, onClose, onSyntheticOutcome }: LifecycleDialogProps) {
  const [commentary, setCommentary] = useState("");
  const [nextStatus, setNextStatus] = useState("IN_PROGRESS");
  if (action === null || action === "edit") return null;

  function commit() {
    const label = action === null ? "" : ACTION_TITLES[action];
    onSyntheticOutcome(
      `${label} was not carried out. This build has no Constraint mutation endpoint: no version ` +
        "was incremented, no receipt was issued, and the record is unchanged.",
    );
    onClose();
  }

  return (
    <Dialog open onClose={onClose} title={ACTION_TITLES[action]}>
      <SyntheticNotice surface="lifecycle" />
      <div className="grid gap-3">
        <p className="text-sm text-moss-slate" data-testid="lifecycle-subject">
          {codeLabel(entry?.constraintCode ?? null)} — {lifecycleLabel(entry?.status ?? null)}
        </p>
        {action === "transition" ? (
          <label className="grid gap-1 text-sm">
            New status
            <Select
              value={nextStatus}
              data-testid="lifecycle-next-status"
              onChange={(event) => setNextStatus(event.target.value)}
            >
              {(["IDENTIFIED", "PENDING", "IN_PROGRESS", "ON_HOLD"] as const).map((status) => (
                <option key={status} value={status}>
                  {lifecycleLabel(status)}
                </option>
              ))}
            </Select>
          </label>
        ) : null}
        {action === "close" || action === "closeWithFollowUp" || action === "void" ? (
          <label className="grid gap-1 text-sm">
            {action === "void" ? "Void reason" : "Closure commentary"}
            <Textarea
              value={commentary}
              data-testid="lifecycle-commentary"
              onChange={(event) => setCommentary(event.target.value)}
              onKeyDown={multilineCommitHandler(commit)}
            />
            <span className="text-xs text-muted">
              Ctrl/Cmd+Enter confirms. Shift+Enter starts a new line.
            </span>
          </label>
        ) : null}
        {action === "closeWithFollowUp" ? (
          <p className="text-sm text-muted" data-testid="lifecycle-follow-up-note">
            A live Close + Follow-up returns the closed predecessor, the published successor and
            the relationship between them, all issued by the backend. None of those is invented
            here.
          </p>
        ) : null}
        {action === "publish" ? (
          <p className="text-sm text-muted" data-testid="lifecycle-publish-note">
            A Constraint Code is issued by the backend allocator on Publish. This build does not
            predict, reserve or display one.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" data-testid="lifecycle-confirm" onClick={commit}>
            {ACTION_TITLES[action]}
          </Button>
          <Button size="sm" variant="ghost" data-testid="lifecycle-cancel" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

export interface CategoryPanelProps {
  readonly open: boolean;
  readonly categories: readonly ConstraintCategory[];
  readonly onClose: () => void;
  readonly onSyntheticOutcome: (message: string) => void;
}

/**
 * Category management, with reorder deliberately unavailable.
 *
 * The accepted package makes live reorder conditional on one atomic backend
 * reorder operation existing (`CM-FE-AC-087`/`088`). None does at this head, so
 * this offers no drag handle and no Move Up/Down that would have to be issued
 * as a sequence of independent updates pretending to be a transaction. The
 * ordering is shown, and the reason it cannot be changed is stated.
 */
export function CategoryPanel({ open, categories, onClose, onSyntheticOutcome }: CategoryPanelProps) {
  return (
    <Dialog open={open} onClose={onClose} title="Constraint Categories">
      <SyntheticNotice surface="category" />
      <table className="w-full text-left text-sm" data-testid="category-table">
        <caption className="sr-only">Constraint Categories in display order</caption>
        <thead>
          <tr>
            <th scope="col" className="px-2 py-1">Order</th>
            <th scope="col" className="px-2 py-1">Prefix</th>
            <th scope="col" className="px-2 py-1">Title</th>
            <th scope="col" className="px-2 py-1">State</th>
          </tr>
        </thead>
        <tbody>
          {categories.map((category) => (
            <tr key={category.categoryId} data-testid={`category-row-${category.categoryId}`}>
              <td className="px-2 py-1">{category.displayOrder}</td>
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
                  {category.state === "ACTIVE" ? "Active" : "Inactive"}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-sm text-muted" data-testid="category-reorder-unavailable">
        Reordering is not offered. It requires one atomic backend reorder operation, and issuing a
        sequence of independent updates as a pretend transaction could leave the ordering half
        applied.
      </p>
      <p className="mt-2 text-sm text-muted">
        Inactive Categories stay readable on existing Constraints and are unavailable for a new
        Publish. There is no routine hard delete.
      </p>
      <div className="mt-3 flex gap-2">
        <Button
          size="sm"
          variant="secondary"
          data-testid="category-create"
          onClick={() => {
            onSyntheticOutcome(
              "No Category was created. This build has no Category mutation endpoint.",
            );
            onClose();
          }}
        >
          New Category
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose} data-testid="category-close">
          Close
        </Button>
      </div>
    </Dialog>
  );
}
