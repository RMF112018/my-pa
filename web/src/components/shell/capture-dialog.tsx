"use client";

/**
 * Capture — the one-field, always-available entry point.
 *
 * **One non-empty field is the whole precondition.** No title, no tags, and no
 * required type: the mode selector below defaults to Quick note and selecting
 * Conversation log is an option rather than a step. Save is disabled only while
 * the field is empty or a save is in flight.
 *
 * **Every submission attempt carries a stable idempotency key**, minted when the
 * attempt starts and kept across retries of the same text, so a network-level
 * replay returns the original receipt instead of admitting a duplicate. Editing
 * the text starts a new attempt with a new key. The route scopes the key to the
 * authenticated principal (`ADR-005`, `PKL-MYPA-D-WP03-001`).
 *
 * **The six outcomes below are six different things, and this component keeps
 * them apart.** Conflating them is the specific failure this screen can commit,
 * because the person reading it decides whether to keep their note somewhere else
 * on the strength of one line of text:
 *
 * * **durable** — `status: "persisted"`, a receipt the Python transaction issued.
 *   This is the only state that says "saved", and it says so because a row
 *   exists.
 * * **acknowledged, not persisted** — the explicitly-enabled synthetic provider.
 *   The literal is still exactly true there, and it is *not* rendered as a save:
 *   a person told "captured" for a receipt an in-process map minted has been told
 *   to stop worrying about a note that will not survive a restart.
 * * **refused** — validation, conflict, authorization, policy. Nothing was
 *   stored, the note stays in the field, and the reason is shown rather than a
 *   generic failure.
 * * **unavailable** — the server answered that it could not serve. Also nothing
 *   stored, but a different instruction: retrying is worth doing, and the retry
 *   reuses the same attempt key so it cannot become a second capture. This is
 *   the *reachable* backend saying no; a request that never arrived is the next
 *   state, not this one.
 * * **queued offline** — the request never reached the server and the note is
 *   held, encrypted, in this browser's own storage. It is **not** a save and is
 *   never rendered as one: nothing on the server knows the note exists, and the
 *   copy on this device is the only copy. It replays when the connection comes
 *   back, and the local copy is deleted only once the server's own receipt has
 *   been checked (`lib/offline/replay.ts`).
 * * **not held** — the note could not even be queued: no offline storage, no
 *   storable non-extractable key, or the device queue is at its bound. The note
 *   stays in the field and the reason is named, because the one thing this
 *   screen must never do is imply a hold it did not perform.
 *
 * **The chooser in front of all of this is a router, not a capture.** Capture
 * opens on three choices — Create Task, Quick note, Conversation log. The two
 * note kinds enter the data-entry branch below with that kind already selected,
 * and every downstream behavior — the single field, the attempt key, the six
 * outcomes above, the offline hold — is exactly what it was before the chooser
 * existed. Create Task is the one choice that is *not* a capture: it mints no
 * attempt key, issues no `/api/capture` request and never touches the offline
 * queue. It reports the choice to the shell through `onCreateTask`, and the
 * shell closes this dialog before opening the canonical Task sheet, so a Task
 * started from here can never be replayed as a note on reconnect.
 *
 * **Enrichment state is not among them**, and its absence is deliberate. The save
 * is durable before any processing runs and no capability this tier can call
 * reports how that processing went, so this screen says the note is safe and that
 * proposals appear in Review when they exist — it does not claim a degradation it
 * cannot observe.
 */
import { useEffect, useId, useRef, useState, type Dispatch } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { WhenDiagnostics } from "@/components/diagnostics/diagnostics-provider";
import { TextField } from "@/components/ui/field";
import { CaptureProjectSelector } from "@/components/capture/capture-project-selector";
import { apiPost } from "@/lib/api/client";
import { verifyCaptureReceipt } from "@/lib/capture/receipt";
import { freezeCaptureIntent, type CaptureSessionEvent, type CaptureSessionState } from "@/lib/capture/session";
import { CaptureQueueProtocolError } from "@/lib/offline/capture-intent-codec";
import { CaptureQueueUnavailableError } from "@/lib/offline/coordinator";
import { OfflineKeyUnavailableError } from "@/lib/offline/key";
import { OfflineQueueFullError } from "@/lib/offline/queue";
import { queueCaptureOffline } from "@/lib/offline/capture-queue";

/**
 * The fixed confirmation for discarding unsent drafts.
 *
 * Deliberately says what is *not* discarded. Someone closing a dialog with a
 * half-typed note has to be able to tell this apart from deleting the notes this
 * device is already holding for them.
 */
export const CAPTURE_DISCARD_PROMPT =
  "Discard the unsent drafts in this capture? Held offline notes are not deleted.";

/**
 * Why a note could not be held, in fixed product language.
 *
 * Every one of these means the same thing about the person's work — it is still
 * in the field and nothing was lost — and they differ only in what to do next.
 * The exception object is never rendered and never logged.
 */
function notHeldReason(error: unknown): string {
  if (error instanceof OfflineQueueFullError) {
    return "This device is already holding as many unsent notes as it can.";
  }
  if (error instanceof CaptureQueueUnavailableError) {
    return error.reason === "busy"
      ? "Another tab is using the offline queue. Try again in a moment."
      : "This browser cannot hold notes offline.";
  }
  if (error instanceof CaptureQueueProtocolError) {
    return "A different note is already held under this submission. Both were kept.";
  }
  if (error instanceof OfflineKeyUnavailableError) {
    return "This device has no usable key for offline notes.";
  }
  return "This device could not hold the note.";
}

/** The two source classes a person may author. Quick note unless they say otherwise. */
const CAPTURE_KINDS = [
  { value: "quick_note", label: "Quick note" },
  { value: "conversation_log", label: "Conversation log" },
] as const;

type CaptureKind = (typeof CAPTURE_KINDS)[number]["value"];

/**
 * Which half of the dialog is showing.
 *
 * `choose` is the router — no field, no attempt key, no request, nothing to
 * queue. `entry` is the unchanged capture surface, reached only by picking one
 * of the two note kinds.
 */
type Stage = "choose" | "entry";

interface CaptureAck {
  /** `"backend"` (durable) or `"synthetic"` (acknowledged only). */
  readonly shape?: string;
  readonly status?: string;
  readonly created?: boolean;
  /** The durable receipt, on the backend path. */
  readonly receipt?: { readonly receiptId?: string };
  /** The synthetic path's flat acknowledgement identifier. */
  readonly receiptId?: string;
}

type Outcome =
  | { readonly kind: "idle" }
  | { readonly kind: "saving" }
  | { readonly kind: "durable"; readonly receiptId: string | null; readonly created: boolean }
  | { readonly kind: "acknowledged"; readonly receiptId: string | null }
  | { readonly kind: "refused"; readonly reason: string }
  | { readonly kind: "unavailable"; readonly reason: string }
  | { readonly kind: "queued"; readonly entryId: string }
  | { readonly kind: "not_held"; readonly reason: string };


export function CaptureDialog({
  open,
  onClose,
  principalId,
  session,
  dispatch,
  onCreateTask,
}: {
  open: boolean;
  onClose: () => void;
  /**
   * The signed-in principal, supplied by the shell from the verified session.
   *
   * A queued entry is bound to this value at enqueue and the binding is never
   * rewritten, so the offline path cannot queue a note under an identity the
   * server never authenticated.
   */
  principalId: string;
  /** The shell's local Capture experience. This component owns none of it. */
  session: CaptureSessionState;
  dispatch: Dispatch<CaptureSessionEvent>;
  /**
   * The person chose Create Task rather than a note.
   *
   * Nothing about a capture has happened when this fires — no attempt key, no
   * request, no queue write — and this component opens nothing itself. The shell
   * owns the handoff so that exactly one overlay is mounted at a time, and the
   * nullable Project travels as an explicit argument rather than being re-read.
   */
  onCreateTask?: (projectId: string | null) => void;
}) {
  const [stage, setStage] = useState<Stage>("choose");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const firstChoiceRef = useRef<HTMLButtonElement>(null);
  const projectFieldId = useId();
  // One idempotency key per submission attempt: minted at first save, kept
  // across retries of the same text, discarded when the text changes.
  const attemptKeyRef = useRef<string | null>(null);
  /**
   * The synchronous duplicate-submit mutex.
   *
   * Claimed before any await and before any React state update, because a second
   * activation can arrive before the pending render lands. Without it a
   * double-tap mints a second key and issues a second request, which is two
   * captures for one intent.
   */
  const savingRef = useRef(false);

  // The draft, the kind and the Project all live in the shell's experience.
  // This component reads them and dispatches; it stores none of them, so a close
  // and reopen resumes what the shell still holds rather than a stale local copy.
  const kind: CaptureKind = session.form;
  const text = kind === "quick_note" ? session.noteDraft : session.conversationDraft;
  const projectId = session.projectId;

  // A newly opened dialog starts at the chooser, with no prior outcome showing.
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => {
      setStage("choose");
      setOutcome({ kind: "idle" });
    }, 0);
    return () => clearTimeout(t);
  }, [open]);

  /*
    Move focus into the dialog on open, at whichever stage is showing.

    The native `<dialog>` restores focus to the invoker on close by itself, so a
    missing focus move here would not be visible in a close-and-restore test — it
    would only be visible to someone actually using the keyboard, who would open
    Capture and find focus still outside it. Both stages therefore take focus
    explicitly: the chooser's first action, and the note field behind it.
  */
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => {
      if (stage === "entry") fieldRef.current?.focus();
      else firstChoiceRef.current?.focus();
    }, 0);
    return () => clearTimeout(t);
  }, [open, stage]);

  /** Enter the unchanged capture branch with the chosen kind already selected. */
  function chooseKind(chosen: CaptureKind) {
    dispatch({ type: "select_form", form: chosen });
    setStage("entry");
  }

  /**
   * Confirm discarding unsent drafts, through the browser's own prompt.
   *
   * A platform modal, not a second application focus trap. Cancelling keeps the
   * modal, the drafts and the Project exactly as they were.
   */
  function confirmDiscardUnsent(): boolean {
    return window.confirm(CAPTURE_DISCARD_PROMPT);
  }

  /** Close, confirming first when there is unsent work to lose. */
  function requestClose() {
    const dirty = session.noteDraft.trim() !== "" || session.conversationDraft.trim() !== "";
    // An in-flight or ambiguous submission is not a draft to discard: closing
    // does not cancel a request the server may already have committed.
    const unresolved = outcome.kind === "saving" || outcome.kind === "unavailable";
    if (dirty && !unresolved && !confirmDiscardUnsent()) return;
    if (dirty && !unresolved) dispatch({ type: "discard_unsent" });
    onClose();
  }

  async function save() {
    if (!text.trim()) return;
    // Synchronous, before any await and before any state update.
    if (savingRef.current) return;
    savingRef.current = true;
    if (!attemptKeyRef.current) {
      attemptKeyRef.current = `cap-${crypto.randomUUID()}`;
    }
    // Principal, epoch, kind, text, Project and key are frozen together here.
    const intent = freezeCaptureIntent(session, attemptKeyRef.current);
    const experienceId = session.experienceId;
    const epoch = session.sessionEpoch;
    setOutcome({ kind: "saving" });
    dispatch({ type: "freeze", intent });
    try {
      const result = await apiPost<CaptureAck>({ hasSession: true }, "/api/capture", {
        text: intent.text,
        captureKind: intent.captureKind,
        idempotencyKey: intent.idempotencyKey,
        // Omission and explicit null both mean No Project; this sends the
        // explicit form so the receipt's Project can be compared against it.
        projectId: intent.projectId,
      });
      if (result.ok && result.data) {
        // The browser repeats the whole check independently. A nominal success
        // this tier cannot verify is ambiguous, never a save.
        const verdict = await verifyCaptureReceipt(result.data, intent);
        if (!verdict.ok) {
          if (verdict.reason === "not_persisted") {
            setOutcome({ kind: "acknowledged", receiptId: result.data.receiptId ?? null });
            dispatch({ type: "result", experienceId, sessionEpoch: epoch, outcome: "refused" });
            return;
          }
          setOutcome({ kind: "unavailable", reason: verdict.reason });
          dispatch({ type: "result", experienceId, sessionEpoch: epoch, outcome: "ambiguous" });
          return;
        }
        setOutcome({
          kind: "durable",
          receiptId: verdict.ack.receipt.receiptId,
          created: verdict.ack.created,
        });
        dispatch({ type: "result", experienceId, sessionEpoch: epoch, outcome: "persisted" });
        attemptKeyRef.current = null;
        return;
      }
      const reason = result.error ?? "the request did not complete";
      if (result.errorClass === "unavailable") {
        // Includes the BFF's own 503 `upstream_contract_invalid`. The backend may
        // have committed; the frozen intent and its key are kept for the retry.
        setOutcome({ kind: "unavailable", reason });
        dispatch({ type: "result", experienceId, sessionEpoch: epoch, outcome: "ambiguous" });
        return;
      }
      setOutcome({ kind: "refused", reason });
      dispatch({ type: "result", experienceId, sessionEpoch: epoch, outcome: "refused" });
    } catch {
      // The request never reached the server, so nothing on the far side knows
      // this note exists. Hold it on this device rather than telling someone to
      // retry a note they may close the tab on.
      await hold(intent, experienceId, epoch);
    } finally {
      savingRef.current = false;
    }
  }

  /**
   * Queue the note locally, or say plainly that it was not held.
   *
   * The attempt key is deliberately *kept* on the queued path: it is minted once
   * and replayed verbatim, so a note that is queued and later replayed is one
   * capture rather than two. It is cleared only when the entry is safely held,
   * so a subsequent save in the same dialog starts its own attempt.
   */
  async function hold(
    intent: ReturnType<typeof freezeCaptureIntent>,
    experienceId: string,
    epoch: number,
  ) {
    try {
      // Exactly the frozen tuple, including the Project and the same key.
      const entry = await queueCaptureOffline({
        principalId,
        text: intent.text,
        captureKind: intent.captureKind,
        idempotencyKey: intent.idempotencyKey,
        projectId: intent.projectId,
      });
      setOutcome({ kind: "queued", entryId: entry.entryId });
      // Ownership transfers only after the queue has committed.
      dispatch({ type: "result", experienceId, sessionEpoch: epoch, outcome: "enqueued" });
      attemptKeyRef.current = null;
    } catch (error) {
      // Every refusal keeps the draft. The key is kept too, so a retry is the
      // same attempt rather than a second capture.
      setOutcome({ kind: "not_held", reason: notHeldReason(error) });
      dispatch({ type: "result", experienceId, sessionEpoch: epoch, outcome: "ambiguous" });
    }
  }

  // The chooser is its own render: the capture branch below is untouched.
  if (stage === "choose") {
    return (
      <Dialog open={open} onClose={onClose} title="Capture">
        <div
          role="group"
          aria-label="What are you capturing?"
          data-testid="capture-chooser"
          className="flex flex-col gap-2"
        >
          <Button
            ref={firstChoiceRef}
            variant="ghost"
            data-testid="capture-choice-create_task"
            onClick={() => onCreateTask?.(projectId)}
          >
            Create Task
          </Button>
          {CAPTURE_KINDS.map((option) => (
            <Button
              key={option.value}
              variant="ghost"
              data-testid={`capture-choice-${option.value}`}
              onClick={() => chooseKind(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onClose={onClose} title="Capture">
      <div className="flex flex-col gap-3">
        <TextField
          ref={fieldRef}
          label="What happened?"
          hint="One field is enough. Captured items are held for review — nothing is asserted on your behalf."
          value={text}
          disabled={outcome.kind === "saving"}
          onChange={(e) => {
            dispatch({ type: "edit_draft", form: kind, text: e.target.value });
            // Edited text is a new submission attempt, not a retry.
            attemptKeyRef.current = null;
          }}
          data-testid="capture-field"
        />
        <CaptureProjectSelector
          id={projectFieldId}
          value={projectId}
          /* Frozen while a submission is in flight: the Project that was sent is
             what the receipt will be compared against. */
          disabled={outcome.kind === "saving"}
          onChange={(next) => dispatch({ type: "select_project", projectId: next })}
          principalId={principalId}
          sessionEpoch={session.sessionEpoch}
        />
        <fieldset className="flex flex-wrap items-center gap-3">
          <legend className="sr-only">Capture kind</legend>
          {CAPTURE_KINDS.map((option) => (
            <label key={option.value} className="flex items-center gap-1.5 text-sm">
              <input
                type="radio"
                name="capture-kind"
                value={option.value}
                checked={kind === option.value}
                disabled={outcome.kind === "saving"}
                onChange={() => dispatch({ type: "select_form", form: option.value })}
                data-testid={`capture-kind-${option.value}`}
              />
              {option.label}
            </label>
          ))}
        </fieldset>
        {outcome.kind === "durable" ? (
          <p role="status" data-testid="capture-durable" className="text-sm text-success">
            {outcome.created
              ? "Saved. Your note is stored and will appear in Review."
              : "Already saved — the original receipt was returned. Nothing was stored twice."}
            {/* WP07: the storage outcome above is product truth. The receipt
                identifier is the technical receipt for it. */}
            <WhenDiagnostics>
              {outcome.receiptId ? (
                <span className="ml-1 font-mono text-xs">({outcome.receiptId})</span>
              ) : null}
            </WhenDiagnostics>
          </p>
        ) : null}
        {outcome.kind === "acknowledged" ? (
          <p role="status" data-testid="capture-acknowledged" className="text-sm text-destructive">
            Acknowledged, but <strong>not stored</strong>. This build is serving the synthetic
            provider, which keeps nothing across a restart. Keep this note somewhere else.
            <WhenDiagnostics>
              {outcome.receiptId ? (
                <span className="ml-1 font-mono text-xs">({outcome.receiptId})</span>
              ) : null}
            </WhenDiagnostics>
          </p>
        ) : null}
        {outcome.kind === "refused" ? (
          <p role="alert" data-testid="capture-refused" className="text-sm text-destructive">
            {/* §6.3/§8.4: `reason` is the backend's own string, and a raw backend
                string is unbounded. The refusal and the fact the note survives are
                the product truth and are stated without it. */}
            Refused, and nothing was stored. Your note is still in the field.
            <WhenDiagnostics>
              <span className="ml-1">{outcome.reason}</span>
            </WhenDiagnostics>
          </p>
        ) : null}
        {outcome.kind === "queued" ? (
          <p role="status" data-testid="capture-queued" className="text-sm text-destructive">
            <strong>Held on this device only</strong> — not saved on the server. The connection
            could not be reached, so the note is encrypted and kept here, and it will be sent when
            you are back online. Until then this device holds the only copy.
            <WhenDiagnostics>
              <span className="ml-1 font-mono text-xs">({outcome.entryId})</span>
            </WhenDiagnostics>
          </p>
        ) : null}
        {outcome.kind === "not_held" ? (
          <p role="alert" data-testid="capture-not-held" className="text-sm text-destructive">
            <strong>Not saved and not held.</strong> Your note is still in the field — copy it
            somewhere else before closing this dialog.
            <WhenDiagnostics>
              <span className="ml-1">{outcome.reason}</span>
            </WhenDiagnostics>
          </p>
        ) : null}
        {outcome.kind === "unavailable" ? (
          <p role="alert" data-testid="capture-unavailable" className="text-sm text-destructive">
            Not saved — the service could not be reached. Your note is still in the field, and
            retrying resubmits the same attempt rather than capturing it twice.
            <WhenDiagnostics>
              <span className="ml-1">{outcome.reason}</span>
            </WhenDiagnostics>
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            data-testid="capture-entry-back"
            onClick={() => setStage("choose")}
          >
            Back
          </Button>
          <Button variant="ghost" data-testid="capture-close" onClick={requestClose}>
            Close
          </Button>
          <Button onClick={save} disabled={outcome.kind === "saving" || !text.trim()}>
            {outcome.kind === "saving" ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
