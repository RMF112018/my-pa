"use client";

/**
 * Quick Constraint — the fourth Capture type (R02-WP10 Phase 7).
 *
 * Reuses the existing Capture chooser/session infrastructure — this session's
 * one shared Project context (`PC-CM-CAPTURE-AC-004`/`-005`, `capture/session.ts`)
 * — and the existing shared Constraint runtime Impl-3 landed
 * (`ConstraintMutationCoordinator`, `ConstraintReadCoordinator`,
 * `FocusReturnRegistry`, all from `useConstraintRuntime()`) and the
 * already-mounted `MutationFeedbackProvider` (`useMutationFeedback()`). It
 * mounts none of those a second time, and it is a **distinct branch**
 * (`PC-CM-CAPTURE-AC-003`): unlike Quick note and Conversation log, a
 * Constraint capture never freezes a `FrozenCaptureIntent` and never calls the
 * generic `/api/capture` route or the offline queue. It calls the one
 * authoring endpoint a Constraint Register already creates published records
 * through, `POST /api/project-controls/projects/{projectId}/constraints`
 * (`constraints.create_published`), through `ConstraintMutationCoordinator`.
 *
 * **One lock per mounted form instance.** The create-intent lock key
 * (`mintCreateIntentLockKey("capture-constraint-create")`) is minted exactly
 * once, in a ref initializer, when this component first mounts — never per
 * keystroke, never per submit attempt. Combined with the idempotency key
 * being reused verbatim across a retry of the same attempt, this is
 * `PC-CM-CAPTURE-AC-018` (one stable intent identity) and `-023` (no blind
 * retry/fuzzy dedupe): the coordinator itself already guarantees both, and
 * this component's only job is to never mint a second key for the same
 * mounted instance.
 *
 * **Every field a settled attempt froze stays frozen until it resolves.**
 * While a create is in flight (`saving`) or ambiguous (`unavailable` — the
 * request may already have applied server-side), every field is disabled and
 * the authored values are untouched, so "Retry" resends exactly what an
 * ambiguous attempt already tried (`ConstraintMutationCoordinator.retry`
 * resends the attempt's own frozen request, not a fresh read of these
 * fields) and a validation refusal or any other terminal failure leaves every
 * authored value exactly where the person left it (`PC-CM-CAPTURE-AC-022`).
 *
 * **Server-side defaults, never invented here.** Date Identified and Due are
 * sent only when the person opens Details and overrides them
 * (`PC-CM-CAPTURE-AC-012`/`-013` — the backend defaults them to the Project's
 * own `projectToday` and +10 business days); Status is sent only when
 * overridden away from the backend's own Identified default
 * (`PC-CM-CAPTURE-AC-011`). Details starts collapsed and offers only the
 * fields eligible here — Status, Date Identified, Due, Comments and BIC
 * (`PC-CM-CAPTURE-AC-015`).
 *
 * **BIC is the canonical `PartyRef` identity, never a guess**
 * (`PC-CM-CAPTURE-AC-010`, joint with Impl-4's `constraint-party-selector.tsx`
 * for the fuller Register authoring surface — this Quick form's own half is
 * exactly this file's use of that identity). It offers exactly the two kinds a
 * quick capture can name without a search widget: `"principal"` (the
 * signed-in Principal themself — the closed identity every `PRINCIPAL` party
 * shares, carrying no label) and `"unresolved"` (free text, explicitly
 * unresolved to any entity — never a fabricated `entityId`, never a guess at
 * matching one). A person who needs to search Entities uses the Register's own
 * authoring surface instead; nothing here approximates that.
 */
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type Dispatch,
} from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { TextField } from "@/components/ui/field";
import { WhenDiagnostics } from "@/components/diagnostics/diagnostics-provider";
import { CaptureProjectSelector } from "@/components/capture/capture-project-selector";
import { apiGet, apiPost } from "@/lib/api/client";
import { useConstraintRuntime } from "@/components/project-controls/constraint-runtime-provider";
import { useMutationFeedback } from "@/components/ui/mutation-feedback";
import {
  mintCreateIntentLockKey,
  type ConstraintMutateOutcome,
} from "@/lib/constraint/mutation-coordinator";
import { buildConstraintQueryKey } from "@/lib/constraint/query-key";
import type { CaptureSessionEvent, CaptureSessionState } from "@/lib/capture/session";

/** The fixed confirmation for discarding an unsent, dirty Quick Constraint. */
export const CAPTURE_CONSTRAINT_DISCARD_PROMPT =
  "Discard this unsent Constraint? Nothing has been filed yet.";

/** `PC-CM-CAPTURE-AC-011`: the backend's own default when `toState` is omitted. */
const DEFAULT_STATUS = "identified" as const;

/**
 * The four active states `constraints.create_published`'s `toState` admits —
 * transcribed locally rather than imported from
 * `app/api/project-controls/constraint-requests.ts` (a Next.js route module
 * that imports `next/server`, unsafe for a client component's runtime bundle
 * even though the compiled reference would be type-only) or from
 * `contracts/constraints.ts`'s `ConstraintLifecycle` (a different, uppercase
 * *read*-plane vocabulary — `"IDENTIFIED"` — never the lowercase wire shape a
 * mutation body sends).
 */
const STATUS_CHOICES = [
  { value: "identified", label: "Identified" },
  { value: "pending", label: "Pending" },
  { value: "in_progress", label: "In Progress" },
  { value: "on_hold", label: "On Hold" },
] as const;

type ConstraintActiveState = (typeof STATUS_CHOICES)[number]["value"];

/** The two `PartyRef` kinds a Quick Constraint's BIC control can name. */
type BicChoice = "none" | "me" | "other";

/** The wire shape one BIC entry sends — `PartyRef.__post_init__`'s pairing rules. */
type BrowserPartyRef =
  | { readonly kind: "principal"; readonly entityId: null; readonly label: null }
  | { readonly kind: "unresolved"; readonly entityId: null; readonly label: string };

interface CategoryOption {
  readonly categoryId: string;
  readonly prefix: string;
  readonly title: string;
}

/** Shape-checked rows only; a row this tier cannot recognise is not offered. */
function readActiveCategories(body: unknown): readonly CategoryOption[] {
  if (!body || typeof body !== "object" || !Array.isArray((body as { categories?: unknown }).categories)) {
    return [];
  }
  const options: CategoryOption[] = [];
  for (const row of (body as { categories: readonly unknown[] }).categories) {
    if (
      row &&
      typeof row === "object" &&
      typeof (row as { categoryId?: unknown }).categoryId === "string" &&
      typeof (row as { title?: unknown }).title === "string" &&
      typeof (row as { prefix?: unknown }).prefix === "string" &&
      (row as { state?: unknown }).state === "active"
    ) {
      const r = row as { categoryId: string; title: string; prefix: string };
      options.push({ categoryId: r.categoryId, title: r.title, prefix: r.prefix });
    }
  }
  return options;
}

/** The authoritative fields the create response's record carries, projected. */
interface ConfirmedConstraintSummary {
  readonly constraintId: string;
  readonly constraintCode: string | null;
  readonly description: string | null;
  readonly lifecycleState: string | null;
  readonly dateIdentified: string | null;
  readonly dueDate: string | null;
}

function readConfirmedSummary(result: unknown): ConfirmedConstraintSummary | null {
  if (!result || typeof result !== "object") return null;
  const record = (result as { constraint?: unknown }).constraint;
  if (!record || typeof record !== "object") return null;
  const r = record as Record<string, unknown>;
  if (typeof r.constraintId !== "string") return null;
  return {
    constraintId: r.constraintId,
    constraintCode: typeof r.constraintCode === "string" ? r.constraintCode : null,
    description: typeof r.description === "string" ? r.description : null,
    lifecycleState: typeof r.lifecycleState === "string" ? r.lifecycleState : null,
    dateIdentified: typeof r.dateIdentified === "string" ? r.dateIdentified : null,
    dueDate: typeof r.dueDate === "string" ? r.dueDate : null,
  };
}

type Outcome =
  | { readonly kind: "idle" }
  | { readonly kind: "saving" }
  | { readonly kind: "success"; readonly record: ConfirmedConstraintSummary }
  | { readonly kind: "refused"; readonly reason: string }
  | { readonly kind: "unavailable"; readonly reason: string; readonly attemptId: string };

interface FieldErrors {
  project?: string;
  category?: string;
  description?: string;
}

function statusLabel(value: string | null): string {
  return STATUS_CHOICES.find((choice) => choice.value === value)?.label ?? "Identified";
}

export function CaptureConstraintForm({
  principalId,
  session,
  dispatch,
  onClose,
  onBack,
}: {
  readonly principalId: string;
  readonly session: CaptureSessionState;
  readonly dispatch: Dispatch<CaptureSessionEvent>;
  /** The whole Capture surface closes. Used by Cancel and by the success screen's Close. */
  readonly onClose: () => void;
  /** Back to the chooser — mirrors the note branch's own Back. */
  readonly onBack: () => void;
}) {
  const runtime = useConstraintRuntime();
  const feedback = useMutationFeedback();
  const router = useRouter();

  const baseId = useId();
  const projectFieldId = `${baseId}-project`;
  const categoryFieldId = `${baseId}-category`;
  const descriptionFieldId = `${baseId}-description`;
  const bicFieldId = `${baseId}-bic`;
  const bicOtherFieldId = `${baseId}-bic-other`;
  const statusFieldId = `${baseId}-status`;
  const dateIdentifiedFieldId = `${baseId}-date-identified`;
  const dueDateFieldId = `${baseId}-due-date`;
  const commentsFieldId = `${baseId}-comments`;

  const descriptionRef = useRef<HTMLTextAreaElement>(null);
  const categoryRef = useRef<HTMLSelectElement>(null);
  const saveButtonRef = useRef<HTMLButtonElement>(null);

  // One lock per mounted form instance — minted once, in this lazy
  // initializer, never re-minted. A `useState` lazy initializer (not a ref
  // read during render) is this codebase's own pattern for "compute once at
  // first render" — see `capture-project-selector.tsx`'s `renderedSession`.
  const [surfaceId] = useState(() => mintCreateIntentLockKey("capture-constraint-create"));

  // Reused across a retry of the same attempt; re-minted only once a terminal
  // outcome (success, definitive refusal, or an abandoned ambiguous attempt)
  // makes the next Save a new attempt.
  const idempotencyKeyRef = useRef<string | null>(null);
  const savingRef = useRef(false);
  const attemptIdRef = useRef<string | null>(null);
  const focusTokenRef = useRef<string | null>(null);

  const projectId = session.projectId;

  const [categories, setCategories] = useState<readonly CategoryOption[]>([]);
  const [categoriesUnavailable, setCategoriesUnavailable] = useState(false);
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [bicChoice, setBicChoice] = useState<BicChoice>("none");
  const [bicOtherLabel, setBicOtherLabel] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [status, setStatus] = useState<ConstraintActiveState>(DEFAULT_STATUS);
  const [dateIdentified, setDateIdentified] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [comments, setComments] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  const frozen = outcome.kind === "saving" || outcome.kind === "unavailable";

  // `PC-CM-CAPTURE-AC-016`: a Project change clears Category and the Details
  // overrides Category selection implies (Status/dates are Project-calendar
  // defaults, not portable across Projects). The BIC "me" choice is
  // Principal-scoped, not Project-scoped, and is deliberately left alone; a
  // typed "someone else" label is cleared with the rest, since it was offered
  // alongside a now-superseded Category/options set.
  //
  // Adjusted during render (React's own sanctioned "reset state when a prop
  // changes" pattern — `capture-project-selector.tsx`'s `renderedSession` is
  // this same shape) rather than in an effect: an effect-triggered `setState`
  // here would still show the stale Category for one paint before resetting.
  const [trackedProjectId, setTrackedProjectId] = useState(projectId);
  if (trackedProjectId !== projectId) {
    setTrackedProjectId(projectId);
    setCategoryId(null);
    setStatus(DEFAULT_STATUS);
    setDateIdentified("");
    setDueDate("");
    setBicOtherLabel("");
    if (bicChoice === "other") setBicChoice("none");
    setFieldErrors((current) => ({ ...current, category: undefined }));
    // The prior Project's loaded page never survives a switch — cleared here
    // (render time) rather than in the fetch effect below, so no stale
    // Category from Project A is ever offered, even for one paint, once B is
    // chosen; the effect's own job is only to fetch B's page.
    setCategories([]);
    setCategoriesUnavailable(false);
  }

  // Load the exact Project's active Categories. A revoked/unreadable read
  // leaves the picker empty and says so; it never offers a stale list. Every
  // `setState` here runs inside the async body, never synchronously in the
  // effect's own top-level (`react-hooks/set-state-in-effect`).
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    void (async () => {
      setCategoriesLoading(true);
      setCategoriesUnavailable(false);
      let result: Awaited<ReturnType<typeof apiGet>>;
      try {
        result = await apiGet(
          { hasSession: true },
          `/api/project-controls/projects/${encodeURIComponent(projectId)}/constraint-categories`,
        );
      } catch {
        if (!cancelled) {
          setCategoriesUnavailable(true);
          setCategoriesLoading(false);
        }
        return;
      }
      if (cancelled) return;
      setCategoriesLoading(false);
      if (!result.ok || !result.data) {
        setCategoriesUnavailable(true);
        return;
      }
      setCategories(readActiveCategories(result.data));
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Report/clear this surface's dirty (unsaved authored) state with the
  // shared coordinator — the §5a Project-scope switch barrier
  // (`useCanSwitchProjectScope`) reads this, exactly as documented.
  const dirty =
    categoryId !== null ||
    description.trim() !== "" ||
    bicChoice !== "none" ||
    comments.trim() !== "" ||
    dateIdentified !== "" ||
    dueDate !== "" ||
    status !== DEFAULT_STATUS;
  useEffect(() => {
    runtime.mutationCoordinator.reportDirtyState(surfaceId, dirty && outcome.kind !== "success");
  }, [runtime.mutationCoordinator, surfaceId, dirty, outcome.kind]);
  useEffect(() => {
    return () => runtime.mutationCoordinator.clearDirtyState(surfaceId);
    // Unmount only: the lock key (and so the dirty-state entry it keys) is
    // this instance's own for its whole lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    return () => {
      // A token this instance never resolved (unmounted mid-attempt) must not
      // be left pending forever.
      if (focusTokenRef.current) runtime.focusReturn.abandon(focusTokenRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Take focus into the form once, on mount — the generic dialog-level focus
  // move in `capture-dialog.tsx` targets the note field, which this branch
  // never renders.
  useEffect(() => {
    document.getElementById(projectFieldId)?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount only
  }, []);

  function buildRequestBody(): Record<string, unknown> {
    const body: Record<string, unknown> = {
      categoryId,
      description: description.trim(),
    };
    if (dateIdentified) body.dateIdentified = dateIdentified;
    if (dueDate) body.dueDate = dueDate;
    if (comments.trim()) body.currentUpdate = comments.trim();
    const bic: BrowserPartyRef[] = [];
    if (bicChoice === "me") bic.push({ kind: "principal", entityId: null, label: null });
    else if (bicChoice === "other" && bicOtherLabel.trim()) {
      bic.push({ kind: "unresolved", entityId: null, label: bicOtherLabel.trim() });
    }
    if (bic.length > 0) body.bic = bic;
    if (status !== DEFAULT_STATUS) body.toState = status;
    return body;
  }

  const postConstraint = useCallback(
    async (
      forProjectId: string,
      request: Record<string, unknown>,
      idempotencyKey: string,
    ): Promise<unknown> => {
      const result = await apiPost(
        { hasSession: true },
        `/api/project-controls/projects/${encodeURIComponent(forProjectId)}/constraints`,
        { ...request, idempotencyKey },
      );
      if (result.ok && result.data) return result.data;
      const error = new Error(result.error ?? "the request did not complete") as Error & {
        status?: number;
        code?: string;
      };
      error.status = result.status;
      if (result.code) error.code = result.code;
      throw error;
    },
    [],
  );

  /** Best-effort: never let a reconcile failure be mistaken for a create failure. */
  const reconcile = useCallback(
    (forProjectId: string) => {
      try {
        const overviewKey = buildConstraintQueryKey({
          mode: "overview",
          scope: { kind: "PROJECT", projectId: forProjectId },
          sessionKey: runtime.sessionKey,
          scopeEpoch: runtime.scopeEpoch,
        });
        runtime.readCoordinator.markStale(overviewKey);
        const portfolioKey = buildConstraintQueryKey({
          mode: "portfolio",
          scope: { kind: "ALL_PROJECTS" },
          sessionKey: runtime.sessionKey,
          scopeEpoch: runtime.scopeEpoch,
        });
        runtime.readCoordinator.markStale(portfolioKey);
      } catch {
        // Best-effort reconciliation only; the create itself already succeeded.
      }
    },
    [runtime.readCoordinator, runtime.sessionKey, runtime.scopeEpoch],
  );

  function publishFeedback(kind: "success" | "error", message: string, correlationId: string) {
    feedback.publish({
      eventId: `constraint:capture:${kind}:${correlationId}`,
      kind,
      message,
    });
  }

  async function settle(outcomeResult: ConstraintMutateOutcome) {
    attemptIdRef.current = outcomeResult.attemptId;
    if (outcomeResult.refused) {
      setOutcome({ kind: "refused", reason: outcomeResult.reason ?? "This Constraint was not filed." });
      return;
    }
    const state = outcomeResult.state;
    if (state.phase === "confirmed") {
      const summary = readConfirmedSummary(outcomeResult.result);
      // The coordinator has already fully settled this attempt as confirmed
      // (lock released, `retry()` no longer applies to it) — an answer this
      // tier cannot verify as the authoritative record is never shown as a
      // success (`PC-CM-CAPTURE-AC-019`), so this is a definitive refusal, not
      // a retry-eligible one.
      idempotencyKeyRef.current = null;
      runtime.mutationCoordinator.acknowledge(outcomeResult.attemptId);
      if (!summary) {
        setOutcome({ kind: "refused", reason: "The response could not be verified." });
        return;
      }
      setOutcome({ kind: "success", record: summary });
      return;
    }
    if (state.phase === "ambiguous") {
      setOutcome({
        kind: "unavailable",
        reason:
          state.error?.message ??
          "This may still have been filed. Retry with the same attempt, or discard it.",
        attemptId: outcomeResult.attemptId,
      });
      return;
    }
    if (state.phase === "stale_epoch") {
      // The Project scope moved under this attempt; no feedback, no focus
      // move (the coordinator already skipped both), and nothing to show as
      // an outcome of what the person authored here.
      setOutcome({ kind: "idle" });
      return;
    }
    // failed / conflict.
    setOutcome({
      kind: "refused",
      reason: state.error?.message ?? "This Constraint was not filed.",
    });
    idempotencyKeyRef.current = null;
    runtime.mutationCoordinator.acknowledge(outcomeResult.attemptId);
  }

  async function save() {
    if (savingRef.current) return;
    const errors: FieldErrors = {};
    if (!projectId) errors.project = "Select a Project to file this Constraint against.";
    if (!categoryId) errors.category = "Select a Category.";
    if (!description.trim()) errors.description = "Enter a description.";
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      if (errors.project) {
        document.getElementById(projectFieldId)?.focus();
      } else if (errors.category) {
        categoryRef.current?.focus();
      } else {
        descriptionRef.current?.focus();
      }
      return;
    }
    setFieldErrors({});
    savingRef.current = true;
    if (!idempotencyKeyRef.current) {
      idempotencyKeyRef.current = `cst-cap-${crypto.randomUUID()}`;
    }
    const forProjectId = projectId!;
    const correlationId = idempotencyKeyRef.current;
    const origin = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const token = runtime.focusReturn.capture({ origin, fallback: () => saveButtonRef.current });
    focusTokenRef.current = token.tokenId;
    setOutcome({ kind: "saving" });
    const request = buildRequestBody();
    try {
      const result = await runtime.mutationCoordinator.mutate({
        kind: "captureConstraintCreate",
        lockRequest: { kind: "create-intent", key: surfaceId },
        idempotencyKey: correlationId,
        epoch: runtime.scopeEpoch,
        isCurrentEpoch: runtime.isCurrentEpoch,
        request,
        dispatch: ({ request: frozenRequest, idempotencyKey }) =>
          postConstraint(forProjectId, frozenRequest as Record<string, unknown>, idempotencyKey),
        hooks: {
          reconcile: async () => reconcile(forProjectId),
          feedback: async (result, phase) => {
            if (phase === "confirmed") {
              const summary = readConfirmedSummary(result);
              publishFeedback(
                "success",
                summary?.constraintCode
                  ? `Constraint ${summary.constraintCode} filed.`
                  : "Constraint filed.",
                correlationId,
              );
              return;
            }
            if (phase === "failed" || phase === "conflict") {
              publishFeedback("error", "This Constraint was not filed.", correlationId);
            }
          },
          resolveFocus: (_result, phase) => {
            // The confirmed success screen offers its own deterministic
            // "Open Constraint" / "Close" choice, each of which resolves the
            // token itself once acted on. Every other settle has no such
            // choice, so it resolves immediately.
            if (phase !== "confirmed" && focusTokenRef.current) {
              runtime.focusReturn.resolve(focusTokenRef.current);
              focusTokenRef.current = null;
            }
          },
        },
      });
      await settle(result);
    } finally {
      savingRef.current = false;
    }
  }

  async function retry() {
    if (savingRef.current || !attemptIdRef.current) return;
    savingRef.current = true;
    setOutcome({ kind: "saving" });
    try {
      const result = await runtime.mutationCoordinator.retry(
        attemptIdRef.current,
        runtime.scopeEpoch,
        runtime.isCurrentEpoch,
      );
      await settle(result);
    } finally {
      savingRef.current = false;
    }
  }

  function discardAttempt() {
    if (!attemptIdRef.current) return;
    runtime.mutationCoordinator.abandon(attemptIdRef.current);
    if (focusTokenRef.current) {
      runtime.focusReturn.abandon(focusTokenRef.current);
      focusTokenRef.current = null;
    }
    attemptIdRef.current = null;
    idempotencyKeyRef.current = null;
    setOutcome({ kind: "idle" });
  }

  function confirmDiscardUnsent(): boolean {
    return window.confirm(CAPTURE_CONSTRAINT_DISCARD_PROMPT);
  }

  function cancel() {
    if (frozen) return; // an in-flight/ambiguous attempt is not a draft to discard
    if (dirty && !confirmDiscardUnsent()) return;
    dispatch({ type: "discard_unsent" });
    onClose();
  }

  function resolveAndClose() {
    if (focusTokenRef.current) {
      runtime.focusReturn.resolve(focusTokenRef.current);
      focusTokenRef.current = null;
    }
    onClose();
  }

  /** `PC-CM-CAPTURE-AC-021`'s "Open Constraint" choice: navigate, then close Capture. */
  function openConstraint(constraintId: string) {
    if (focusTokenRef.current) {
      runtime.focusReturn.resolve(focusTokenRef.current);
      focusTokenRef.current = null;
    }
    onClose();
    router.push(
      `/work/projects/${encodeURIComponent(projectId ?? "")}/constraints?view=register&constraint=${encodeURIComponent(constraintId)}`,
    );
  }

  if (outcome.kind === "success") {
    return (
      <div className="flex flex-col gap-3" data-testid="capture-constraint-success">
        <p role="status" className="text-sm text-success">
          {outcome.record.constraintCode
            ? `Filed as ${outcome.record.constraintCode}.`
            : "Filed."}
        </p>
        <dl className="flex flex-col gap-1 text-sm text-text-primary">
          <div className="flex justify-between gap-2">
            <dt className="text-muted">Description</dt>
            <dd className="text-right">{outcome.record.description ?? "—"}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-muted">Status</dt>
            <dd>{statusLabel(outcome.record.lifecycleState)}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-muted">Date identified</dt>
            <dd>{outcome.record.dateIdentified ?? "—"}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-muted">Due</dt>
            <dd>{outcome.record.dueDate ?? "—"}</dd>
          </div>
        </dl>
        <WhenDiagnostics>
          <p className="font-mono text-xs text-muted">{outcome.record.constraintId}</p>
        </WhenDiagnostics>
        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            data-testid="capture-constraint-close"
            onClick={resolveAndClose}
          >
            Close
          </Button>
          <Button
            data-testid="capture-constraint-open"
            onClick={() => openConstraint(outcome.record.constraintId)}
          >
            Open Constraint
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <CaptureProjectSelector
        id={projectFieldId}
        value={projectId}
        disabled={frozen}
        onChange={(next) => dispatch({ type: "select_project", projectId: next })}
        principalId={principalId}
        sessionEpoch={session.sessionEpoch}
        required
        placeholderLabel="Select a Project"
      />
      {fieldErrors.project ? (
        <p role="alert" data-testid="capture-constraint-project-error" className="text-xs text-destructive">
          {fieldErrors.project}
        </p>
      ) : null}

      <div className="flex flex-col gap-1">
        <label htmlFor={categoryFieldId} className="text-sm font-medium text-text-primary">
          Category<span className="font-normal text-muted"> (required)</span>
        </label>
        <Select
          ref={categoryRef}
          id={categoryFieldId}
          value={categoryId ?? ""}
          disabled={frozen || !projectId || categoriesLoading}
          aria-required="true"
          aria-invalid={fieldErrors.category ? true : undefined}
          onChange={(event) => setCategoryId(event.target.value === "" ? null : event.target.value)}
          data-testid="capture-constraint-category"
          className="min-h-11 text-text-primary disabled:opacity-60"
        >
          <option value="">
            {!projectId
              ? "Select a Project first"
              : categoriesLoading
                ? "Loading Categories…"
                : "Select a Category"}
          </option>
          {categories.map((category) => (
            <option key={category.categoryId} value={category.categoryId}>
              {category.prefix} · {category.title}
            </option>
          ))}
        </Select>
        {categoriesUnavailable ? (
          <p data-testid="capture-constraint-categories-unavailable" className="text-xs text-muted">
            Categories unavailable — try again, or open the Register directly.
          </p>
        ) : null}
        {fieldErrors.category ? (
          <p role="alert" data-testid="capture-constraint-category-error" className="text-xs text-destructive">
            {fieldErrors.category}
          </p>
        ) : null}
      </div>

      <TextField
        ref={descriptionRef}
        id={descriptionFieldId}
        label="Description"
        required
        disabled={frozen}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        error={fieldErrors.description}
        data-testid="capture-constraint-description"
      />

      <Button
        type="button"
        variant="ghost"
        className="w-fit"
        disabled={frozen}
        aria-expanded={detailsOpen}
        onClick={() => setDetailsOpen((open) => !open)}
        data-testid="capture-constraint-details-toggle"
      >
        {detailsOpen ? "Hide details" : "Details"}
      </Button>

      {detailsOpen ? (
        <div className="flex flex-col gap-3 border-l-2 border-border-subtle pl-3" data-testid="capture-constraint-details">
          <div className="flex flex-col gap-1">
            <label htmlFor={bicFieldId} className="text-sm font-medium text-text-primary">
              BIC
            </label>
            <Select
              id={bicFieldId}
              value={bicChoice}
              disabled={frozen}
              onChange={(event) => setBicChoice(event.target.value as BicChoice)}
              data-testid="capture-constraint-bic"
              className="min-h-11 text-text-primary disabled:opacity-60"
            >
              <option value="none">Not assigned</option>
              <option value="me">Me</option>
              <option value="other">Someone else</option>
            </Select>
            {bicChoice === "other" ? (
              <>
                <label htmlFor={bicOtherFieldId} className="sr-only">
                  BIC name
                </label>
                <Input
                  id={bicOtherFieldId}
                  value={bicOtherLabel}
                  disabled={frozen}
                  placeholder="Name"
                  onChange={(event) => setBicOtherLabel(event.target.value)}
                  data-testid="capture-constraint-bic-other"
                />
              </>
            ) : null}
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor={statusFieldId} className="text-sm font-medium text-text-primary">
              Status
            </label>
            <Select
              id={statusFieldId}
              value={status}
              disabled={frozen}
              onChange={(event) => setStatus(event.target.value as ConstraintActiveState)}
              data-testid="capture-constraint-status"
              className="min-h-11 text-text-primary disabled:opacity-60"
            >
              {STATUS_CHOICES.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {choice.label}
                </option>
              ))}
            </Select>
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor={dateIdentifiedFieldId} className="text-sm font-medium text-text-primary">
              Date identified
            </label>
            <Input
              id={dateIdentifiedFieldId}
              type="date"
              disabled={frozen}
              value={dateIdentified}
              onChange={(event) => setDateIdentified(event.target.value)}
              data-testid="capture-constraint-date-identified"
            />
            <p className="text-xs text-muted">Left blank, defaults to today on the Project&apos;s calendar.</p>
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor={dueDateFieldId} className="text-sm font-medium text-text-primary">
              Due
            </label>
            <Input
              id={dueDateFieldId}
              type="date"
              disabled={frozen}
              value={dueDate}
              onChange={(event) => setDueDate(event.target.value)}
              data-testid="capture-constraint-due-date"
            />
            <p className="text-xs text-muted">Left blank, defaults to 10 business days out.</p>
          </div>

          <TextField
            id={commentsFieldId}
            label="Comments"
            disabled={frozen}
            value={comments}
            onChange={(event) => setComments(event.target.value)}
            data-testid="capture-constraint-comments"
          />
        </div>
      ) : null}

      {outcome.kind === "refused" ? (
        <p role="alert" data-testid="capture-constraint-refused" className="text-sm text-destructive">
          This Constraint was not filed. Every value above is still here.
          <WhenDiagnostics>
            <span className="ml-1">{outcome.reason}</span>
          </WhenDiagnostics>
        </p>
      ) : null}
      {outcome.kind === "unavailable" ? (
        <div role="alert" data-testid="capture-constraint-unavailable" className="flex flex-col gap-2 text-sm text-destructive">
          <p>
            This may still have been filed. Retry resends the exact same attempt — it cannot file
            it twice.
            <WhenDiagnostics>
              <span className="ml-1">{outcome.reason}</span>
            </WhenDiagnostics>
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="secondary"
              data-testid="capture-constraint-retry"
              onClick={() => void retry()}
            >
              Retry
            </Button>
            <Button
              type="button"
              variant="ghost"
              data-testid="capture-constraint-discard-attempt"
              onClick={discardAttempt}
            >
              Discard attempt
            </Button>
          </div>
        </div>
      ) : null}

      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          disabled={frozen}
          data-testid="capture-entry-back"
          onClick={onBack}
        >
          Back
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={frozen}
          data-testid="capture-constraint-cancel"
          onClick={cancel}
        >
          Cancel
        </Button>
        <Button
          ref={saveButtonRef}
          type="button"
          disabled={frozen}
          aria-busy={outcome.kind === "saving" || undefined}
          data-testid="capture-constraint-save"
          onClick={() => void save()}
        >
          {outcome.kind === "saving" ? "Filing…" : "File"}
        </Button>
      </div>
    </div>
  );
}
