"use client";

import { useState } from "react";
import { apiPost } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { WhenDiagnostics } from "@/components/diagnostics/diagnostics-provider";
import { TextField } from "@/components/ui/field";

interface CorrectResponse {
  readonly disposition?: string;
  readonly occurrence_id?: string;
  readonly revision_id?: string;
}

type Outcome =
  | { readonly kind: "idle" }
  | { readonly kind: "submitting" }
  | { readonly kind: "appended"; readonly revisionId: string }
  | { readonly kind: "understated"; readonly detail: string }
  // `message` is always product language. `detail` is the backend's own string
  // and is governed by the global policy (WP07 §8.4) — a raw backend string is
  // unbounded and must never be the user-facing sentence.
  | { readonly kind: "refused"; readonly message: string; readonly detail?: string }
  | { readonly kind: "unavailable"; readonly message: string; readonly detail?: string };

/**
 * Governed correction. The session cookie is the only identity carrier; the
 * body is occurrenceId and transcription only.
 */
export function CorrectionForm({
  occurrenceId,
  initialTranscription = "",
}: {
  occurrenceId: string;
  initialTranscription?: string;
}) {
  const [transcription, setTranscription] = useState(initialTranscription);
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  async function submit() {
    if (transcription.length === 0) {
      setOutcome({
        kind: "refused",
        message: "A correction has to carry the transcription you are recording.",
      });
      return;
    }
    setOutcome({ kind: "submitting" });
    try {
      const answer = await apiPost<CorrectResponse>(
        { hasSession: true },
        "/api/goodnotes/correct",
        { occurrenceId, transcription },
      );
      if (answer.ok && answer.data?.disposition === "canonical_revision_appended") {
        setOutcome({
          kind: "appended",
          revisionId: answer.data.revision_id ?? "",
        });
        return;
      }
      if (answer.ok) {
        setOutcome({
          kind: "understated",
          detail: answer.data?.disposition ?? "the server did not report a stored canonical revision",
        });
        return;
      }
      setOutcome(
        answer.errorClass === "unavailable"
          ? {
              kind: "unavailable",
              message:
                "The correction was not recorded — the service could not be reached. Nothing was stored.",
              detail: answer.error ?? undefined,
            }
          : {
              kind: "refused",
              message: "The correction was refused and nothing was stored.",
              detail: answer.error ?? undefined,
            },
      );
    } catch {
      setOutcome({
        kind: "unavailable",
        message: "The request never reached the server, so nothing was stored.",
      });
    }
  }

  return (
    <form
      className="mt-3 flex flex-col gap-3"
      data-testid="goodnotes-correction-form"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <TextField
        label="Corrected transcription"
        hint="This is recorded as a governed correction against the occurrence, not as a new interpretation invented here."
        required
        value={transcription}
        onChange={(event) => setTranscription(event.target.value)}
        disabled={outcome.kind === "submitting" || outcome.kind === "appended"}
      />
      <Button type="submit" className="min-h-11 self-start" pending={outcome.kind === "submitting"}>
        Record correction
      </Button>
      {outcome.kind === "appended" ? (
        <p role="status" data-testid="goodnotes-correction-appended">
          A canonical revision was appended.
          <WhenDiagnostics>
            {outcome.revisionId ? <span className="ml-1">({outcome.revisionId})</span> : null}
          </WhenDiagnostics>
        </p>
      ) : null}
      {outcome.kind === "understated" ? (
        <p role="status" data-testid="goodnotes-correction-understated">
          The correction was not recorded as a stored canonical revision.
          <WhenDiagnostics>
            <span className="ml-1">{outcome.detail}</span>
          </WhenDiagnostics>
        </p>
      ) : null}
      {outcome.kind === "refused" ? (
        <p role="alert" data-testid="goodnotes-correction-refused">
          {outcome.message}
          <WhenDiagnostics>
            {outcome.detail ? <span className="ml-1">{outcome.detail}</span> : null}
          </WhenDiagnostics>
        </p>
      ) : null}
      {outcome.kind === "unavailable" ? (
        <p role="alert" data-testid="goodnotes-correction-unavailable">
          {outcome.message}
          <WhenDiagnostics>
            {outcome.detail ? <span className="ml-1">{outcome.detail}</span> : null}
          </WhenDiagnostics>
        </p>
      ) : null}
    </form>
  );
}
