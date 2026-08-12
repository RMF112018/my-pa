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
 * **The four outcomes below are four different things, and this component keeps
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
 * * **unavailable** — the backend could not be reached. Also nothing stored, but
 *   a different instruction: retrying is worth doing, and the retry reuses the
 *   same attempt key so it cannot become a second capture.
 *
 * **Enrichment state is not among them**, and its absence is deliberate. The save
 * is durable before any processing runs and no capability this tier can call
 * reports how that processing went, so this screen says the note is safe and that
 * proposals appear in Review when they exist — it does not claim a degradation it
 * cannot observe.
 */
import { useEffect, useRef, useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { apiPost } from "@/lib/api/client";

/** The two source classes a person may author. Quick note unless they say otherwise. */
const CAPTURE_KINDS = [
  { value: "quick_note", label: "Quick note" },
  { value: "conversation_log", label: "Conversation log" },
] as const;

type CaptureKind = (typeof CAPTURE_KINDS)[number]["value"];

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
  | { readonly kind: "unavailable"; readonly reason: string };

/**
 * Which acknowledgement this is, read from the route's own answer.
 *
 * `status === "persisted"` is the single condition for calling a save durable,
 * and it is checked positively: a response whose shape this function does not
 * recognise falls to `acknowledged`, which understates rather than overstates.
 * The failure direction matters — an unrecognised answer treated as durable is a
 * person told their note is safe when nothing knows that it is.
 */
function acknowledgement(data: CaptureAck): Outcome {
  const receiptId = data.receipt?.receiptId ?? data.receiptId ?? null;
  if (data.status === "persisted") {
    return { kind: "durable", receiptId, created: data.created !== false };
  }
  return { kind: "acknowledged", receiptId };
}

export function CaptureDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState<CaptureKind>("quick_note");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  // One idempotency key per submission attempt: minted at first save, kept
  // across retries of the same text, discarded when the text changes.
  const attemptKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (open) {
      setOutcome({ kind: "idle" });
      // Move focus into the single capture field once the dialog is open.
      const t = setTimeout(() => fieldRef.current?.focus(), 0);
      return () => clearTimeout(t);
    }
  }, [open]);

  async function save() {
    if (!text.trim()) return;
    setOutcome({ kind: "saving" });
    if (!attemptKeyRef.current) {
      attemptKeyRef.current = `cap-${crypto.randomUUID()}`;
    }
    try {
      const result = await apiPost<CaptureAck>({ hasSession: true }, "/api/capture", {
        text: text.trim(),
        captureKind: kind,
        idempotencyKey: attemptKeyRef.current,
      });
      if (result.ok && result.data) {
        const settled = acknowledgement(result.data);
        setOutcome(settled);
        // The field is cleared only for a durable save. An acknowledgement that
        // is not a save leaves the note where the person can still copy it.
        if (settled.kind === "durable") {
          setText("");
          attemptKeyRef.current = null;
        }
        return;
      }
      const reason = result.error ?? "the request did not complete";
      setOutcome(
        result.errorClass === "unavailable"
          ? { kind: "unavailable", reason }
          : { kind: "refused", reason },
      );
    } catch {
      setOutcome({
        kind: "unavailable",
        reason: "the request did not reach the server",
      });
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="Capture">
      <div className="flex flex-col gap-3">
        <TextField
          ref={fieldRef}
          label="What happened?"
          hint="One field is enough. Captured items are held for review — nothing is asserted on your behalf."
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            // Edited text is a new submission attempt, not a retry.
            attemptKeyRef.current = null;
          }}
          data-testid="capture-field"
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
                onChange={() => setKind(option.value)}
                data-testid={`capture-kind-${option.value}`}
              />
              {option.label}
            </label>
          ))}
        </fieldset>
        {outcome.kind === "durable" ? (
          <p role="status" data-testid="capture-durable" className="text-sm text-moss-green">
            {outcome.created
              ? "Saved. Your note is stored and will appear in Review."
              : "Already saved — the original receipt was returned. Nothing was stored twice."}
            {outcome.receiptId ? (
              <span className="ml-1 font-mono text-xs">({outcome.receiptId})</span>
            ) : null}
          </p>
        ) : null}
        {outcome.kind === "acknowledged" ? (
          <p role="status" data-testid="capture-acknowledged" className="text-sm text-moss-coral">
            Acknowledged, but <strong>not stored</strong>. This build is serving the synthetic
            provider, which keeps nothing across a restart. Keep this note somewhere else.
            {outcome.receiptId ? (
              <span className="ml-1 font-mono text-xs">({outcome.receiptId})</span>
            ) : null}
          </p>
        ) : null}
        {outcome.kind === "refused" ? (
          <p role="alert" data-testid="capture-refused" className="text-sm text-moss-coral">
            Refused, and nothing was stored: {outcome.reason} Your note is still in the field.
          </p>
        ) : null}
        {outcome.kind === "unavailable" ? (
          <p role="alert" data-testid="capture-unavailable" className="text-sm text-moss-coral">
            Not saved — the service could not be reached: {outcome.reason} Your note is still in
            the field, and retrying resubmits the same attempt rather than capturing it twice.
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
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
