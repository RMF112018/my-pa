"use client";

/**
 * Review workbench — WP-05 (R4).
 *
 * Presents each proposal as a case awaiting the user's disposition. The
 * workbench never asserts anything: a proposal only becomes a canonical
 * reviewed assertion when the user chooses accept / correct-and-accept, and
 * a disposition returns the immutable receipt the promotion issues. Every
 * case is principal-scoped by the server; a foreign case never reaches this
 * component. Correct-and-accept preserves the original proposal and records a
 * separate reviewed value — it does not rewrite the proposal text.
 */
import { useState } from "react";
import type { ReviewCase, ReviewDisposition } from "@/contracts/views";
import type { Receipt } from "@/contracts/envelope";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { RevealDialog } from "@/components/shell/reveal-dialog";
import { apiPost } from "@/lib/api/client";

interface DecideResponse {
  receipt: Receipt;
  status: string;
}

const DISPOSITION_LABEL: Record<ReviewDisposition, string> = {
  accept: "Accept",
  correct: "Correct & accept",
  reject: "Reject",
  defer: "Defer",
  unresolved: "Unresolved",
};

type CaseStatus =
  | { phase: "open" }
  | { phase: "correcting" }
  | { phase: "submitting" }
  | { phase: "decided"; disposition: ReviewDisposition; receipt: Receipt }
  | { phase: "error"; message: string };

export function ReviewWorkbench({ cases }: { cases: readonly ReviewCase[] }) {
  const [revealSubject, setRevealSubject] = useState<string | null>(null);
  const [statuses, setStatuses] = useState<Record<string, CaseStatus>>({});

  function statusFor(id: string): CaseStatus {
    return statuses[id] ?? { phase: "open" };
  }

  function setStatus(id: string, status: CaseStatus) {
    setStatuses((prev) => ({ ...prev, [id]: status }));
  }

  async function decide(
    reviewCaseId: string,
    disposition: ReviewDisposition,
    correctedValue?: string,
  ) {
    setStatus(reviewCaseId, { phase: "submitting" });
    // The payload carries only the disposition (and a correction when
    // correcting) — never an identity field. The session cookie is identity.
    const payload: Record<string, unknown> = { disposition };
    if (disposition === "correct") payload.correctedValue = correctedValue ?? "";
    try {
      const response = await apiPost<DecideResponse>(
        { hasSession: true },
        `/api/review/${encodeURIComponent(reviewCaseId)}/decide`,
        payload,
      );
      if (response.ok && response.data) {
        setStatus(reviewCaseId, {
          phase: "decided",
          disposition,
          receipt: response.data.receipt,
        });
      } else {
        setStatus(reviewCaseId, {
          phase: "error",
          message: response.error ?? "The disposition could not be recorded.",
        });
      }
    } catch {
      setStatus(reviewCaseId, {
        phase: "error",
        message: "The disposition could not be recorded.",
      });
    }
  }

  if (cases.length === 0) {
    return <p className="text-sm text-muted">No proposals are waiting for your review.</p>;
  }

  return (
    <ul className="flex flex-col gap-3">
      {cases.map((item) => {
        const status = statusFor(item.reviewCaseId);
        return (
          <li key={item.reviewCaseId}>
            <Card data-testid="review-case">
              <div className="flex items-start justify-between gap-2">
                <CardTitle>{item.proposalSummary}</CardTitle>
                <Badge tone="gold">Proposed</Badge>
              </div>
              <CardBody>
                <p className="text-xs uppercase tracking-wide text-muted">
                  Proposal — not asserted. Awaiting your disposition.
                </p>

                <div className="mt-3">
                  <p className="font-medium text-moss-slate">Evidence</p>
                  <ul className="mt-1 flex flex-col gap-1">
                    {item.evidence.map((span) => (
                      <li
                        key={`${span.sourceVersionId}:${span.startOffset}`}
                        className="border-l-2 border-moss-green/40 pl-2 italic"
                        data-testid="evidence-span"
                      >
                        “{span.surfaceText}”
                      </li>
                    ))}
                  </ul>
                </div>

                <p className="mt-3">
                  <span className="font-medium text-moss-slate">If accepted:</span>{" "}
                  {item.impactSummary}
                </p>

                {status.phase === "decided" ? (
                  <div
                    className="mt-3 rounded-md border border-moss-green/30 bg-moss-green/5 p-3"
                    role="status"
                    data-testid={`receipt-${item.reviewCaseId}`}
                  >
                    <p className="font-medium text-moss-everglade">
                      Recorded: {DISPOSITION_LABEL[status.disposition]}
                    </p>
                    <p className="mt-1 text-xs text-muted">
                      Receipt {status.receipt.receiptId} · transition{" "}
                      {status.receipt.transition} · policy {status.receipt.policyVersion}
                    </p>
                  </div>
                ) : status.phase === "correcting" ? (
                  <CorrectionForm
                    onCancel={() => setStatus(item.reviewCaseId, { phase: "open" })}
                    onSubmit={(value) => decide(item.reviewCaseId, "correct", value)}
                  />
                ) : (
                  <>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        onClick={() => decide(item.reviewCaseId, "accept")}
                        disabled={status.phase === "submitting"}
                        data-testid={`accept-${item.reviewCaseId}`}
                      >
                        Accept
                      </Button>
                      <Button
                        variant="secondary"
                        onClick={() => setStatus(item.reviewCaseId, { phase: "correcting" })}
                        disabled={status.phase === "submitting"}
                        data-testid={`correct-${item.reviewCaseId}`}
                      >
                        Correct &amp; accept
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => decide(item.reviewCaseId, "defer")}
                        disabled={status.phase === "submitting"}
                      >
                        Defer
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() => decide(item.reviewCaseId, "reject")}
                        disabled={status.phase === "submitting"}
                        data-testid={`reject-${item.reviewCaseId}`}
                      >
                        Reject
                      </Button>
                    </div>
                    {status.phase === "error" ? (
                      <p role="alert" className="mt-2 text-moss-coral">
                        {status.message}
                      </p>
                    ) : null}
                  </>
                )}

                <div className="mt-3">
                  <Button
                    variant="ghost"
                    onClick={() => setRevealSubject(item.proposalId)}
                    data-testid={`reveal-${item.reviewCaseId}`}
                  >
                    Why am I seeing this?
                  </Button>
                </div>
              </CardBody>
            </Card>
          </li>
        );
      })}
      <RevealDialog
        open={revealSubject !== null}
        onClose={() => setRevealSubject(null)}
        subjectId={revealSubject ?? ""}
      />
    </ul>
  );
}

function CorrectionForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");
  return (
    <div className="mt-3 flex flex-col gap-2">
      <TextField
        label="Corrected value"
        hint="Correct-and-accept records your value and preserves the original proposal."
        value={value}
        onChange={(event) => setValue(event.target.value)}
        data-testid="correction-field"
      />
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          onClick={() => onSubmit(value)}
          disabled={value.trim().length === 0}
          data-testid="correction-submit"
        >
          Record correction
        </Button>
      </div>
    </div>
  );
}
