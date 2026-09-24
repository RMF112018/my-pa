/**
 * The local Capture experience: one Project context, one frozen intent (C03).
 *
 * **This is a local adapter, not a second global scope.** It is a pure reducer
 * with no React and no network. The single owning React state lives in
 * `AppShellBody`, under the already-mounted `ProjectScopeProvider` and Task
 * runtime. Global Project Scope is read **once**, to initialize a fresh
 * experience, and is never written: `applyResolution`, preference cookies,
 * `localStorage` and the router are all somebody else's and stay that way.
 *
 * **Three ideas that are easy to conflate, kept apart here.**
 *
 * * The *editing context* — drafts, the selected form, the local Project. A
 *   close resets this.
 * * The *frozen intent* — what was actually submitted, under which Principal and
 *   with which key. A close does **not** cancel it. Closing a dialog is not a
 *   cancellation of a request the server may already have committed, and the
 *   shell keeps holding it so an explicit reopen resumes it.
 * * The *authentication epoch* — an in-memory generation counter for discarding
 *   stale answers. It is not credential material, it is not persisted, and it is
 *   no part of the idempotency identity.
 *
 * **A late result cannot reach a new experience.** Every result carries the
 * experience and epoch it belongs to, and the reducer drops it if either moved
 * on. Without that, a reply to a request issued before an account switch could
 * clear the draft a different person is typing.
 *
 * **Nothing here decides a Project is unavailable and quietly substitutes No
 * Project.** An unresolved name is an unresolved name; the selection is retained
 * and said to be unavailable. An automatic fallback to null would file a note
 * against nothing while the screen said otherwise.
 */
import type { CaptureKind, CaptureProjectId, FrozenCaptureIntent } from "@/lib/capture/contract";

/**
 * Which Capture type is on screen.
 *
 * `"constraint"` (R02-WP10 Phase 7) is the fourth Capture type. It shares this
 * session's one Project context (`PC-CM-CAPTURE-AC-004`/`-005`) exactly as
 * `"quick_note"` and `"conversation_log"` already do, and switching to or from
 * it leaves `noteDraft`/`conversationDraft` untouched, the same isolation the
 * two note forms already have from each other (`PC-CM-CAPTURE-AC-024`). It
 * carries no draft field of its own here: unlike the two note kinds, a
 * Constraint capture is never frozen into a `FrozenCaptureIntent` and never
 * submitted through `/api/capture` (`PC-CM-CAPTURE-AC-003`) — its own fields,
 * dirty state and submission run entirely inside `CaptureConstraintForm`,
 * through `ConstraintMutationCoordinator`, so `activeDraft`/
 * `freezeCaptureIntent` below are never called for it.
 */
export type CaptureForm = "quick_note" | "conversation_log" | "constraint";

/** Which overlay currently owns the screen. There is never more than one. */
export type CaptureModalOwner = "capture" | "task" | "none";

/** What is true of the active intent. `editable` means nothing is in flight. */
export type CaptureOutcome =
  | "editable"
  | "submitting"
  | "ambiguous"
  | "refused"
  | "persisted"
  | "enqueued";

/** What is known about the selected Project's authorized display name. */
export type CaptureProjectName =
  | { readonly kind: "none" }
  | { readonly kind: "resolving" }
  | { readonly kind: "named"; readonly name: string }
  | { readonly kind: "unavailable" };

export interface CaptureSessionState {
  readonly experienceId: string;
  readonly principalId: string;
  readonly sessionEpoch: number;
  /** The local selection. Never written back to global scope. */
  readonly projectId: CaptureProjectId;
  /** Bumped whenever a name/options request in flight must be disregarded. */
  readonly nameEpoch: number;
  readonly projectName: CaptureProjectName;
  readonly noteDraft: string;
  readonly conversationDraft: string;
  readonly form: CaptureForm;
  /** The submitted intent, while it remains unresolved. */
  readonly intent: FrozenCaptureIntent | null;
  readonly outcome: CaptureOutcome;
  readonly modalOwner: CaptureModalOwner;
}

export type CaptureSessionEvent =
  /** A fresh open. The Project comes from global scope exactly once, here. */
  | {
      readonly type: "open";
      readonly experienceId: string;
      readonly principalId: string;
      readonly sessionEpoch: number;
      readonly projectId: CaptureProjectId;
    }
  /** Reopen an experience that still holds an unresolved intent. */
  | { readonly type: "reopen" }
  | { readonly type: "select_project"; readonly projectId: CaptureProjectId }
  | { readonly type: "project_name"; readonly nameEpoch: number; readonly name: CaptureProjectName }
  | { readonly type: "select_form"; readonly form: CaptureForm }
  | { readonly type: "edit_draft"; readonly form: CaptureForm; readonly text: string }
  /** Capture → Task. Nothing is captured and nothing is queued. */
  | { readonly type: "to_task" }
  /** Task → Back, carrying the Project Task actually holds. */
  | { readonly type: "task_back"; readonly projectId: CaptureProjectId }
  | { readonly type: "freeze"; readonly intent: FrozenCaptureIntent }
  | {
      readonly type: "result";
      readonly experienceId: string;
      readonly sessionEpoch: number;
      readonly outcome: Exclude<CaptureOutcome, "editable" | "submitting">;
    }
  /** Close the surface. An unresolved intent survives; the editing context does not. */
  | { readonly type: "close" }
  | { readonly type: "discard_unsent" }
  /** Global Project Scope moved. Deliberately inert here. */
  | { readonly type: "global_scope_changed"; readonly projectId: CaptureProjectId }
  | { readonly type: "principal_changed"; readonly principalId: string; readonly sessionEpoch: number };

/** A fresh experience, initialized from global scope once. */
export function beginCaptureExperience(input: {
  readonly experienceId: string;
  readonly principalId: string;
  readonly sessionEpoch: number;
  readonly projectId: CaptureProjectId;
}): CaptureSessionState {
  return {
    experienceId: input.experienceId,
    principalId: input.principalId,
    sessionEpoch: input.sessionEpoch,
    projectId: input.projectId,
    nameEpoch: 0,
    projectName: input.projectId === null ? { kind: "none" } : { kind: "resolving" },
    noteDraft: "",
    conversationDraft: "",
    form: "quick_note",
    intent: null,
    outcome: "editable",
    modalOwner: "capture",
  };
}

/** The draft the current form is showing. */
export function activeDraft(state: CaptureSessionState): string {
  return state.form === "quick_note" ? state.noteDraft : state.conversationDraft;
}

/** Whether the surface currently holds an intent nothing has resolved. */
export function hasUnresolvedIntent(state: CaptureSessionState): boolean {
  return state.intent !== null && (state.outcome === "submitting" || state.outcome === "ambiguous");
}

/** Whether the editing context may still change. */
export function isEditable(state: CaptureSessionState): boolean {
  return state.outcome !== "submitting" && state.outcome !== "ambiguous";
}

/**
 * Freeze the current form into a submittable intent.
 *
 * The text is normalized **once**, by the existing `trim()` at this boundary,
 * and never again downstream. The key is supplied by the caller because it is
 * minted under a synchronous mutex before any await.
 */
export function freezeCaptureIntent(
  state: CaptureSessionState,
  idempotencyKey: string,
): FrozenCaptureIntent {
  return {
    principalId: state.principalId,
    sessionEpoch: state.sessionEpoch,
    captureKind: state.form as CaptureKind,
    text: activeDraft(state).trim(),
    idempotencyKey,
    projectId: state.projectId,
  };
}

/** Exact tuple equality, Project and null included. Epoch is not identity. */
export function captureIntentEquals(
  left: FrozenCaptureIntent | null,
  right: FrozenCaptureIntent | null,
): boolean {
  if (left === null || right === null) return left === right;
  return (
    left.principalId === right.principalId &&
    left.captureKind === right.captureKind &&
    left.text === right.text &&
    left.idempotencyKey === right.idempotencyKey &&
    left.projectId === right.projectId
  );
}

function withProject(
  state: CaptureSessionState,
  projectId: CaptureProjectId,
): CaptureSessionState {
  if (projectId === state.projectId) return state;
  return {
    ...state,
    projectId,
    // Any name or options request already in flight described a different
    // selection and must not be allowed to label this one.
    nameEpoch: state.nameEpoch + 1,
    projectName: projectId === null ? { kind: "none" } : { kind: "resolving" },
  };
}

/**
 * The whole local lifecycle.
 *
 * Returns the same state object for an event that must not change anything, so
 * "this was ignored" is observable rather than merely believed.
 */
export function captureSessionReducer(
  state: CaptureSessionState,
  event: CaptureSessionEvent,
): CaptureSessionState {
  switch (event.type) {
    case "open":
      return beginCaptureExperience(event);

    case "reopen":
      return { ...state, modalOwner: "capture" };

    case "select_project": {
      // A frozen intent's Project is not editable. The selection that produced it
      // is what was submitted, and changing it here would misdescribe it.
      if (!isEditable(state)) return state;
      return withProject(state, event.projectId);
    }

    case "project_name": {
      // A response from a superseded request cannot label the current selection.
      if (event.nameEpoch !== state.nameEpoch) return state;
      if (state.projectId === null) return state;
      return { ...state, projectName: event.name };
    }

    case "select_form": {
      if (!isEditable(state)) return state;
      if (event.form === state.form) return state;
      // Same local Project, both drafts preserved, no request and no new key.
      return { ...state, form: event.form };
    }

    case "edit_draft": {
      if (!isEditable(state)) return state;
      return event.form === "quick_note"
        ? { ...state, noteDraft: event.text }
        : { ...state, conversationDraft: event.text };
    }

    case "to_task":
      // Suspend, do not end. The experience, the context and both drafts stay.
      return { ...state, modalOwner: "task" };

    case "task_back": {
      // Adopt what Task actually holds. An unrelated unresolved Task intent
      // against A stays visibly A; it never silently becomes the launcher's B.
      const resumed: CaptureSessionState = { ...state, modalOwner: "capture" };
      return isEditable(state) ? withProject(resumed, event.projectId) : resumed;
    }

    case "freeze":
      return { ...state, intent: event.intent, outcome: "submitting", modalOwner: "capture" };

    case "result": {
      // A reply to an experience or an authentication epoch that has moved on
      // cannot publish into this one.
      if (event.experienceId !== state.experienceId) return state;
      if (event.sessionEpoch !== state.sessionEpoch) return state;
      if (state.intent === null) return state;
      if (event.outcome === "persisted" || event.outcome === "enqueued") {
        // Retire the intent and clear only the draft that was submitted.
        const cleared =
          state.intent.captureKind === "quick_note"
            ? { ...state, noteDraft: "" }
            : { ...state, conversationDraft: "" };
        return { ...cleared, intent: null, outcome: event.outcome };
      }
      if (event.outcome === "refused") {
        // A definitive pre-write refusal returns to editable with the form and
        // the Project intact. A material edit mints a new key on the next save.
        return { ...state, intent: null, outcome: "refused" };
      }
      // Ambiguous: the frozen intent remains authoritative and retry resends it.
      return { ...state, outcome: "ambiguous" };
    }

    case "close": {
      if (hasUnresolvedIntent(state)) {
        // The surface closes; the submitted intent does not. It is retained in
        // the same authenticated shell runtime and an explicit reopen resumes it.
        return { ...state, modalOwner: "none" };
      }
      return { ...state, modalOwner: "none", outcome: "editable" };
    }

    case "discard_unsent": {
      if (!isEditable(state)) return state;
      // Only this experience's unsent drafts and local context. Never global
      // preference, and never anything the offline queue is holding.
      return { ...state, noteDraft: "", conversationDraft: "", modalOwner: "none" };
    }

    case "global_scope_changed":
      // Deliberately inert. The local Project was chosen for this note; a
      // navigation elsewhere in the app does not refile it.
      return state;

    case "principal_changed": {
      if (
        event.principalId === state.principalId &&
        event.sessionEpoch === state.sessionEpoch
      ) {
        return state;
      }
      // In-flight UI authority and any name/options result are invalidated. An
      // unresolved intent keeps its original Principal and is never rebound.
      return {
        ...state,
        principalId: event.principalId,
        sessionEpoch: event.sessionEpoch,
        nameEpoch: state.nameEpoch + 1,
        projectName: state.projectId === null ? { kind: "none" } : { kind: "resolving" },
        modalOwner: "none",
      };
    }
  }
}
