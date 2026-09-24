"use client";

/**
 * `ConstraintAuthoring` — the live Create/Edit surface.
 *
 * **One atomic create intent, not two.** Publishing a brand-new Constraint
 * calls `constraints.create_published` directly (`createPublished`) — there is
 * no local "create the Draft, then publish it" sequence pretending to be one
 * operation (`PC-CM-UX-AC-003`). Save Draft is the explicit secondary action
 * and calls `constraints.create` (`createDraft`) instead; the two buttons
 * dispatch two different capabilities, never the same one with a flag.
 *
 * **Nothing is shown as saved until the mutation confirms.** There is no
 * optimistic Draft, no locally invented Code, no locally advanced version —
 * `PC-CM-UX-AC-005` and `PC-CM-FE-AC-045` both mean the same thing here: a
 * failed create leaves this dialog open on the author's own input, unsaved,
 * with nothing published anywhere.
 *
 * **Draft vs. saved Draft are two different claims.** What is on screen before
 * a Save Draft confirms is unsaved input; only a confirmed `constraints.create`
 * answer is a saved Draft, and only then does the dialog show the Draft's
 * `constraintId`/`version` (never a Code — `DRAFT_CODE_LABEL`,
 * `PC-CM-FE-AC-041`/`042`).
 *
 * **Only the server's Code is ever shown for a publish.** No Code is predicted,
 * reserved or displayed before the `constraints.create_published` /
 * `constraints.publish` answer carries one (`PC-CM-FE-AC-044`).
 *
 * **Only active Categories are offered for a Publish.** An inactive Category
 * is disabled in the picker; editing a Draft that already carries a
 * deactivated Category shows a remediation notice instead of silently letting
 * the Draft publish with it (`PC-CM-FE-AC-048`/`049`/`084`/`085`).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  ConstraintCategory,
  ConstraintListEntry,
} from "@/contracts/constraints";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useMutationFeedback } from "@/components/ui/mutation-feedback";
import { useConstraintRuntime } from "@/components/project-controls/constraint-runtime-provider";
import { constraintLockKey, mintCreateIntentLockKey } from "@/lib/constraint/mutation-coordinator";
import {
  codeLabel,
  DRAFT_CODE_LABEL,
} from "./presentation";
import { multilineCommitHandler } from "./constraint-lifecycle";
import {
  createDraft,
  createPublished,
  mintIdempotencyKey,
  publishConstraint,
  readDetail,
  updateConstraint,
  type LiveConstraintView,
  type LiveMutationFailure,
} from "./constraint-live";
import { ConstraintPartySelector, type RequestPartyRef } from "./constraint-party-selector";

export type ConstraintAuthoringMode = "create" | "edit";

export interface ConstraintAuthoringProps {
  readonly mode: ConstraintAuthoringMode;
  readonly open: boolean;
  readonly projectId: string;
  readonly categories: readonly ConstraintCategory[];
  /** The list-level row, for `edit` mode's initial values. */
  readonly entry?: ConstraintListEntry | null;
  /** The canonical detail, when the Inspector has already read it. */
  readonly detail?: LiveConstraintView | null;
  readonly onClose: () => void;
  /** Called once a create (Draft or Published) confirms, with the new id. */
  readonly onCreated: (constraintId: string) => void;
  /** Called once an edit confirms. */
  readonly onUpdated: () => void;
}

function toRequestParties(parties: readonly { readonly kind: string; readonly partyRefId: string | null; readonly displayLabel: string; readonly entityId?: string | null }[]): readonly RequestPartyRef[] {
  return parties.map((party) => {
    if (party.kind === "PRINCIPAL") return { kind: "principal" as const };
    if (party.kind === "ENTITY") {
      return { kind: "entity" as const, entityId: party.entityId ?? party.partyRefId ?? undefined, label: party.displayLabel };
    }
    return { kind: "unresolved" as const, label: party.displayLabel };
  });
}

export function ConstraintAuthoring({
  mode,
  open,
  projectId,
  categories,
  entry = null,
  detail = null,
  onClose,
  onCreated,
  onUpdated,
}: ConstraintAuthoringProps) {
  const runtime = useConstraintRuntime();
  const feedback = useMutationFeedback();
  // Lazy `useState` initializers, not `useRef(...).current` read at render
  // time: minted exactly once per mount either way, but a ref may not be
  // read during render.
  const [surfaceId] = useState(() => `constraint-authoring:${crypto.randomUUID()}`);
  const [createIntentKey] = useState(() => mintCreateIntentLockKey("constraint-create"));

  const initialDescription = detail?.description ?? entry?.description ?? "";
  const initialCategoryId = detail?.category?.categoryId ?? entry?.category?.categoryId ?? "";
  const initialDueDate = detail?.dueDate ?? entry?.dueDate ?? "";
  const initialDateIdentified = detail?.dateIdentified ?? entry?.dateIdentified ?? "";
  const initialReference = detail?.reference ?? entry?.reference ?? "";
  const initialCurrentUpdate = detail?.currentUpdate ?? "";
  const initialBic = useMemo(
    () => toRequestParties(detail?.bic ?? entry?.bic ?? []),
    [detail, entry],
  );
  const initialResponsible = useMemo(
    () => toRequestParties(detail?.responsible ?? entry?.responsible ?? []),
    [detail, entry],
  );

  const [description, setDescription] = useState(initialDescription);
  const [categoryId, setCategoryId] = useState(initialCategoryId);
  const [dueDate, setDueDate] = useState(initialDueDate);
  const [dateIdentified, setDateIdentified] = useState(initialDateIdentified);
  const [reference, setReference] = useState(initialReference);
  const [currentUpdate, setCurrentUpdate] = useState(initialCurrentUpdate);
  const [bic, setBic] = useState<readonly RequestPartyRef[]>(initialBic);
  const [responsible, setResponsible] = useState<readonly RequestPartyRef[]>(initialResponsible);
  const [toState, setToState] = useState<"identified" | "pending" | "in_progress" | "on_hold">("identified");
  const [pending, setPending] = useState<"draft" | "publish" | "publishDraft" | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A node inside `<Dialog>`'s own native `<dialog>` subtree (the top layer
  // `.showModal()` opens), passed as the BIC/Responsible popovers' portal
  // container so their content renders inside the dialog's own top layer
  // instead of escaping to `document.body` — see `popover.tsx`'s doc
  // comment. Held in state (not read from a ref during render, which
  // `react-hooks/refs` now forbids) via a callback ref, the same pattern
  // `live-constraints-workspace.tsx`'s `attachRegisterHeading`/
  // `attachProjectSelector` already use.
  const [contentNode, setContentNode] = useState<HTMLDivElement | null>(null);
  const attachContent = useCallback((node: HTMLDivElement | null) => {
    setContentNode(node);
  }, []);

  const currentCategory = categories.find((category) => category.categoryId === categoryId) ?? null;
  const categoryInactive = currentCategory !== null && currentCategory.state !== "ACTIVE";
  // The Register's list-row `entry` only ever carries the "open" scope (the
  // four active states — Draft is its own separate scope), so a Draft this
  // dialog itself just saved never appears there: `entry` stays `null` even
  // though `detail` (the Inspector's own already-loaded canonical read) is at
  // that same moment showing the Draft correctly. Fall back to `detail`'s own
  // status whenever the Register row isn't loaded, rather than treating a
  // missing `entry` as "not a Draft".
  const effectiveStatus = entry?.status ?? detail?.status ?? null;
  const isDraftEdit = mode === "edit" && effectiveStatus === "DRAFT";
  const isLegacyDraftCategoryIssue = isDraftEdit && categoryInactive;
  // Same fallback, for the same reason, extended to this record's own
  // identity: `isDraftEdit` becoming reachable with `entry === null` (a
  // just-saved Draft outside the Register's loaded "open" scope) means every
  // other `entry`-only read in this component's own `submit()` — the lock
  // key, the dispatch URL, the post-confirm re-read — must fall back to
  // `detail`'s own `constraintId` too, or Publish/Save now render and are
  // clickable in exactly the state that makes them throw (`entry!.constraintId`
  // on a `null` entry) instead of dispatching.
  const effectiveId = entry?.constraintId ?? detail?.constraintId ?? null;

  function markDirty(dirty: boolean) {
    if (dirty) runtime.mutationCoordinator.reportDirtyState(surfaceId, true);
    else runtime.mutationCoordinator.clearDirtyState(surfaceId);
  }

  useEffect(() => {
    const coordinator = runtime.mutationCoordinator;
    return () => coordinator.clearDirtyState(surfaceId);
    // Unmount-only cleanup: clears this surface's dirty flag however the
    // dialog goes away, so a forced unmount can never leave a stale dirty
    // surface behind for `hasDirtyAuthoredState()` to keep reporting.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onFieldChange<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value);
      markDirty(true);
    };
  }

  function close() {
    markDirty(false);
    onClose();
  }

  const buildRequest = useCallback(
    (includeToState: boolean) => {
      const request: Record<string, unknown> = {
        description: description.trim().length > 0 ? description : undefined,
        categoryId: categoryId || undefined,
        dateIdentified: dateIdentified || undefined,
        dueDate: dueDate || undefined,
        reference: reference.trim().length > 0 ? reference : undefined,
        currentUpdate: currentUpdate.trim().length > 0 ? currentUpdate : undefined,
        bic,
        responsible,
      };
      if (includeToState) request.toState = toState;
      return request;
    },
    [description, categoryId, dateIdentified, dueDate, reference, currentUpdate, bic, responsible, toState],
  );

  async function submit(action: "draft" | "publish" | "publishDraft") {
    if (pending) return;
    if (mode === "edit" && effectiveId === null) {
      // Defensive: edit mode always implies some loaded identity (entry or
      // detail) by construction of how this dialog is opened. If neither is
      // present, fail loudly and safely here rather than dispatching a
      // request with no target id — before any pending/focus-capture side
      // effect, so nothing is left dangling on this early return.
      setError("This record could not be identified. Close and reopen it before trying again.");
      return;
    }
    const willPublish = action === "publish" || action === "publishDraft";
    if (willPublish) {
      if (categoryId === "") {
        setError("Choose a Category before publishing.");
        return;
      }
      if (categoryInactive) {
        setError("Choose an active Category before publishing.");
        return;
      }
    }
    setPending(action);
    setError(null);
    const invoker = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusToken = runtime.focusReturn.capture({ origin: invoker });
    const idempotencyKey = mintIdempotencyKey();
    // `constraints.publish` (CONSTRAINT_PUBLISH_FIELDS) takes only Category,
    // dates, parties and the target state — never Description/Reference/
    // Current Update. Publishing an existing Draft therefore sends exactly
    // that narrower set; anything else changed on this form must be saved
    // first (the "Save" button), which is why the notice below this form
    // says so explicitly rather than silently dropping those edits.
    const request =
      action === "publishDraft"
        ? {
            toState,
            categoryId: categoryId || undefined,
            dateIdentified: dateIdentified || undefined,
            dueDate: dueDate || undefined,
            bic,
            responsible,
          }
        : buildRequest(mode === "create" && action === "publish");

    const outcome = await runtime.mutationCoordinator.mutate({
      kind: action === "publishDraft" ? "constraintPublish" : mode === "edit" ? "constraintUpdate" : "constraintCreate",
      lockRequest:
        mode === "edit" && effectiveId !== null
          ? { kind: "constraint-record", key: constraintLockKey(effectiveId) }
          : { kind: "create-intent", key: createIntentKey },
      idempotencyKey,
      expectedVersion: mode === "edit" ? (detail?.version ?? entry?.version) : undefined,
      request,
      epoch: runtime.scopeEpoch,
      isCurrentEpoch: runtime.isCurrentEpoch,
      baseSnapshot: mode === "edit" ? (detail ?? entry ?? undefined) : undefined,
      dispatch: async ({ request: dispatchRequest, idempotencyKey: key, expectedVersion }) => {
        const body: Record<string, unknown> = { ...(dispatchRequest as Record<string, unknown>), idempotencyKey: key };
        if (mode === "edit") {
          if (expectedVersion !== undefined) body.expectedVersion = expectedVersion;
          // `effectiveId` was already required non-null by the guard at the
          // top of `submit()` for `mode === "edit"`.
          return action === "publishDraft"
            ? publishConstraint(projectId, effectiveId as string, body)
            : updateConstraint(projectId, effectiveId as string, body);
        }
        return action === "draft" ? createDraft(projectId, body) : createPublished(projectId, body);
      },
      hooks: {
        feedback: async (result, phase) => {
          if (phase === "confirmed") {
            feedback.publish({
              eventId: `constraint-authoring-${idempotencyKey}`,
              kind: "success",
              message:
                action === "publishDraft"
                  ? "The Draft was published."
                  : mode === "edit"
                    ? "The Constraint was updated."
                    : action === "draft"
                      ? "The Draft was saved."
                      : "The Constraint was published.",
            });
          } else if (phase === "failed") {
            feedback.publish({
              eventId: `constraint-authoring-${idempotencyKey}-failed`,
              kind: "error",
              message: "The write did not complete. Nothing was saved.",
            });
          } else if (phase === "conflict") {
            feedback.publish({
              eventId: `constraint-authoring-${idempotencyKey}-conflict`,
              kind: "conflict",
              message: "This record changed since it was read. Re-read it before trying again.",
            });
          } else if (phase === "ambiguous") {
            feedback.publish({
              eventId: `constraint-authoring-${idempotencyKey}-ambiguous`,
              kind: "error",
              message: "The write's outcome could not be confirmed. Re-read the record before retrying.",
            });
          }
        },
        resolveFocus: () => {
          runtime.focusReturn.resolve(focusToken.tokenId);
        },
        fetchCurrent:
          mode === "edit" && effectiveId !== null
            ? async () => {
                const controller = new AbortController();
                const result = await readDetail(projectId, effectiveId, controller.signal);
                return result.ok ? result.value : undefined;
              }
            : undefined,
      },
    });

    setPending(null);
    if (outcome.refused) {
      setError("This record is already being written to. Wait for that write to finish.");
      return;
    }
    if (outcome.state.phase === "confirmed") {
      markDirty(false);
      const answer = outcome.result as { constraint: { constraintId: string } };
      if (mode === "edit") onUpdated();
      else onCreated(answer.constraint.constraintId);
      onClose();
      return;
    }
    if (outcome.state.phase === "conflict") {
      setError("This record changed since it was read. Close and reopen it to see the current state.");
      return;
    }
    if (outcome.state.phase === "ambiguous") {
      setError("The write's outcome could not be confirmed. Check the record before retrying.");
      return;
    }
    const failure = outcome.state.error as LiveMutationFailure | undefined;
    setError(failure?.message ?? "The write failed. Nothing was saved.");
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={mode === "create" ? "New Constraint" : `Edit ${codeLabel(entry?.constraintCode ?? null)}`}
    >
      <div className="grid gap-3" ref={attachContent}>
        <p className="text-sm text-muted" data-testid="authoring-code">
          Constraint Code:{" "}
          {mode === "create"
            ? DRAFT_CODE_LABEL
            : effectiveStatus === "DRAFT"
              ? DRAFT_CODE_LABEL
              : codeLabel(entry?.constraintCode ?? null)}
        </p>
        {mode === "edit" && effectiveStatus === "DRAFT" ? (
          <p className="text-xs text-muted" data-testid="authoring-draft-identity">
            This Draft is identified by its id and version, never a Code, until it is published.
          </p>
        ) : null}
        {isLegacyDraftCategoryIssue ? (
          <p role="status" className="text-sm text-moss-coral-strong" data-testid="authoring-category-remediation">
            This Draft&rsquo;s Category is no longer active. Choose an active Category before this Draft can be
            published.
          </p>
        ) : null}
        <label className="grid gap-1 text-sm">
          Description
          <Textarea
            value={description}
            data-testid="authoring-description"
            onChange={(event) => onFieldChange(setDescription)(event.target.value)}
            onKeyDown={multilineCommitHandler(() => void submit("draft"))}
          />
        </label>
        <label className="grid gap-1 text-sm">
          Category
          <Select
            value={categoryId}
            data-testid="authoring-category"
            onChange={(event) => onFieldChange(setCategoryId)(event.target.value)}
          >
            <option value="">Choose a Category</option>
            {categories.map((category) => (
              <option
                key={category.categoryId}
                value={category.categoryId}
                disabled={category.state !== "ACTIVE" && category.categoryId !== initialCategoryId}
              >
                {category.title}
                {category.state === "ACTIVE" ? "" : " (inactive — not available for Publish)"}
              </option>
            ))}
          </Select>
        </label>
        <label className="grid gap-1 text-sm">
          Date Identified
          <Input
            type="date"
            value={dateIdentified}
            data-testid="authoring-date-identified"
            onChange={(event) => onFieldChange(setDateIdentified)(event.target.value)}
          />
        </label>
        <label className="grid gap-1 text-sm">
          Due Date
          <Input
            type="date"
            value={dueDate}
            data-testid="authoring-due-date"
            onChange={(event) => onFieldChange(setDueDate)(event.target.value)}
          />
        </label>
        <label className="grid gap-1 text-sm">
          Reference
          <Input
            type="text"
            value={reference}
            data-testid="authoring-reference"
            onChange={(event) => onFieldChange(setReference)(event.target.value)}
          />
        </label>
        <label className="grid gap-1 text-sm">
          Current Update
          <Textarea
            value={currentUpdate}
            data-testid="authoring-current-update"
            onChange={(event) => onFieldChange(setCurrentUpdate)(event.target.value)}
          />
        </label>
        <ConstraintPartySelector
          label="Ball in Court"
          value={bic}
          onChange={(next) => onFieldChange(setBic)(next)}
          testIdPrefix="authoring-bic"
          portalContainer={contentNode}
        />
        <ConstraintPartySelector
          label="Responsible party"
          value={responsible}
          onChange={(next) => onFieldChange(setResponsible)(next)}
          testIdPrefix="authoring-responsible"
          portalContainer={contentNode}
        />
        {mode === "create" || isDraftEdit ? (
          <label className="grid gap-1 text-sm">
            First status on Publish
            <Select
              value={toState}
              data-testid="authoring-to-state"
              onChange={(event) => onFieldChange(setToState)(event.target.value as typeof toState)}
            >
              {(["identified", "pending", "in_progress", "on_hold"] as const).map((state) => (
                <option key={state} value={state}>
                  {state.replace(/_/g, " ")}
                </option>
              ))}
            </Select>
          </label>
        ) : null}
        {isDraftEdit ? (
          <p className="text-xs text-muted" data-testid="authoring-publish-scope-note">
            Publish saves Category, dates, Ball in Court and Responsible party as shown here. Save
            first if you also changed Description, Reference or Current Update.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-moss-coral-strong" data-testid="authoring-error">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Badge tone="green">Live write</Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant={mode === "create" || isDraftEdit ? "secondary" : "primary"}
            disabled={pending !== null}
            data-testid="authoring-save-draft"
            onClick={() => void submit("draft")}
          >
            {pending === "draft" ? "Saving…" : mode === "create" ? "Save Draft" : "Save"}
          </Button>
          {mode === "create" || isDraftEdit ? (
            <Button
              size="sm"
              disabled={pending !== null || (mode === "edit" && isLegacyDraftCategoryIssue)}
              data-testid="authoring-publish"
              onClick={() => void submit(mode === "create" ? "publish" : "publishDraft")}
            >
              {pending === "publish" || pending === "publishDraft" ? "Publishing…" : "Publish"}
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={close} data-testid="authoring-cancel">
            Cancel
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
