"use client";

/**
 * The Review workbench for cases the backend actually holds.
 *
 * Separate from `ReviewWorkbench` for the reason `BackendReviewCase` is separate
 * from `ReviewCase`: **`review.list` carries no proposal text, no evidence span,
 * and no impact summary.** The fixture shape has all three. Rendering a real case
 * through the fixture component would mean inventing them, and a workbench that
 * invents the sentence a person is deciding about is the worst failure this
 * surface can have — worse than showing nothing, because the person would act on
 * it.
 *
 * So this component shows exactly what the listing carries — which case, which
 * proposal, which capture and version, the proposal type and state, the risk
 * class, when it opened, the review version, and any disposition already
 * recorded — and states plainly, once and prominently, that the listing carries
 * no content. Reveal is offered on every row so the evidence behind a case can be
 * opened before it is decided; that is a separate, audited read
 * (`knowledge.reveal`) rather than content smuggled into a listing.
 *
 * **`expectedReviewVersion` is sent from the row, never defaulted.**
 * `review.decide` runs under optimistic concurrency: a decision made against a
 * stale version is answered `conflict` rather than silently winning. The version
 * shown on the row is the version submitted, so what a person saw is what they
 * decided against — and a conflict is surfaced as a conflict, telling them to
 * reload rather than retrying into a race.
 *
 * **Nothing here renders a success that did not happen.** A decision is
 * `decided` only on `status: "persisted"` with a receipt; a synthetic
 * acknowledgement, an unrecognised answer, a refusal, and an unreachable server
 * are four different rendered states, in the direction that understates.
 */
import { useState } from "react";
import type { BackendReviewCase } from "@/contracts/views";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { RevealDialog } from "@/components/shell/reveal-dialog";
import { apiPost } from "@/lib/api/client";

/** The five verbs this tier may submit, and the words a person reads. */
const DISPOSITIONS = [
  { value: "accept", label: "Accept" },
  { value: "correct", label: "Correct & accept" },
  { value: "reject", label: "Reject" },
  { value: "defer", label: "Defer" },
  { value: "unresolved", label: "Mark unresolved" },
] as const;

type Disposition = (typeof DISPOSITIONS)[number]["value"];

interface DecideResponse {
  readonly shape?: string;
  readonly status?: string;
  readonly receipt?: {
    readonly decisionId?: string;
    readonly reviewVersion?: number;
    readonly proposalState?: string;
    readonly assertionId?: string | null;
    readonly receiptId?: string | null;
  } | null;
}

type RowState =
  | { readonly phase: "open" }
  | { readonly phase: "correcting" }
  | { readonly phase: "submitting" }
  | {
      readonly phase: "decided";
      readonly disposition: Disposition;
      readonly decisionId: string;
      readonly proposalState: string;
      readonly assertionId: string | null;
      readonly receiptId: string | null;
      readonly reviewVersion: number;
    }
  | { readonly phase: "not_persisted"; readonly detail: string }
  | { readonly phase: "conflict"; readonly message: string }
  | { readonly phase: "refused"; readonly message: string }
  | { readonly phase: "unavailable"; readonly message: string };

const RISK_TONE: Record<string, "coral" | "gold" | "neutral"> = {
  high: "coral",
  medium: "gold",
  low: "neutral",
};

function moment(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : `${parsed.toISOString().replace("T", " ").slice(0, 16)} UTC`;
}

export function BackendReviewWorkbench({ cases }: { cases: readonly BackendReviewCase[] }) {
  const [states, setStates] = useState<Record<string, RowState>>({});
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [revealSubject, setRevealSubject] = useState<string | null>(null);

  const stateFor = (id: string): RowState => states[id] ?? { phase: "open" };
  const setState = (id: string, next: RowState) =>
    setStates((prior) => ({ ...prior, [id]: next }));

  async function decide(row: BackendReviewCase, disposition: Disposition) {
    const correctedValue = corrections[row.reviewCaseId]?.trim() ?? "";
    if (disposition === "correct" && correctedValue.length === 0) {
      setState(row.reviewCaseId, {
        phase: "refused",
        message: "A correction has to carry the value you are accepting instead.",
      });
      return;
    }
    setState(row.reviewCaseId, { phase: "submitting" });
    // Identity is never in this payload. The session cookie is the only carrier.
    const payload: Record<string, unknown> = {
      disposition,
      expectedReviewVersion: row.reviewVersion,
    };
    if (disposition === "correct") payload.correctedValue = correctedValue;

    try {
      const answer = await apiPost<DecideResponse>(
        { hasSession: true },
        `/api/review/${encodeURIComponent(row.reviewCaseId)}/decide`,
        payload,
      );
      if (answer.ok && answer.data?.status === "persisted" && answer.data.receipt?.decisionId) {
        const receipt = answer.data.receipt;
        setState(row.reviewCaseId, {
          phase: "decided",
          disposition,
          decisionId: receipt.decisionId as string,
          proposalState: receipt.proposalState ?? "unknown",
          assertionId: receipt.assertionId ?? null,
          receiptId: receipt.receiptId ?? null,
          reviewVersion: receipt.reviewVersion ?? row.reviewVersion + 1,
        });
        return;
      }
      if (answer.ok) {
        // The call succeeded and the answer was not a persisted decision. It is
        // reported as what it is rather than rounded up to a decision.
        setState(row.reviewCaseId, {
          phase: "not_persisted",
          detail: answer.data?.status ?? "the server did not report a stored decision",
        });
        return;
      }
      const message = answer.error ?? "the request did not complete";
      setState(
        row.reviewCaseId,
        answer.errorClass === "conflict"
          ? { phase: "conflict", message }
          : answer.errorClass === "unavailable"
            ? { phase: "unavailable", message }
            : { phase: "refused", message },
      );
    } catch {
      setState(row.reviewCaseId, {
        phase: "unavailable",
        message: "the request never reached the server, so nothing was decided",
      });
    }
  }

  return (
    <>
      <p
        className="mb-3 rounded-md border border-moss-gold/40 border-l-4 border-l-moss-gold bg-moss-gold/10 p-3 text-sm"
        data-testid="review-listing-limitation"
      >
        <strong>This listing carries no proposal text.</strong> The backend&rsquo;s review listing
        returns identifiers, types and states and no content, so nothing below summarises what a
        proposal says — that would have to be invented. Open <em>Reveal</em> on a case to read the
        evidence behind it before you decide.
      </p>
      <ul className="flex flex-col gap-3" data-testid="backend-review-list">
        {cases.map((row) => {
          const state = stateFor(row.reviewCaseId);
          return (
            <li key={row.reviewCaseId}>
              <Card data-testid="backend-review-case">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <CardTitle>
                    <span className="font-mono text-sm break-all">{row.proposalId}</span>
                  </CardTitle>
                  <span className="flex flex-wrap gap-1">
                    <Badge tone="neutral">{row.proposalType}</Badge>
                    <Badge tone={RISK_TONE[row.riskClass] ?? "neutral"}>
                      {row.riskClass} risk
                    </Badge>
                  </span>
                </div>
                <CardBody>
                  <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
                    <dt className="text-muted">case</dt>
                    <dd className="font-mono text-xs break-all">{row.reviewCaseId}</dd>
                    <dt className="text-muted">capture</dt>
                    <dd className="font-mono text-xs break-all">{row.captureId}</dd>
                    <dt className="text-muted">version</dt>
                    <dd className="font-mono text-xs break-all">{row.versionId}</dd>
                    <dt className="text-muted">proposal state</dt>
                    <dd>{row.proposalState}</dd>
                    <dt className="text-muted">opened</dt>
                    <dd>{moment(row.openedAt)}</dd>
                    <dt className="text-muted">review version</dt>
                    <dd data-testid="review-version">{row.reviewVersion}</dd>
                    {row.latestDisposition ? (
                      <>
                        <dt className="text-muted">last disposition</dt>
                        <dd>{row.latestDisposition}</dd>
                      </>
                    ) : null}
                  </dl>

                  {state.phase === "decided" ? (
                    <p
                      role="status"
                      data-testid="review-decided"
                      className="mt-3 text-sm text-moss-green"
                    >
                      Decided and stored. The proposal is now <strong>{state.proposalState}</strong>
                      , at review version {state.reviewVersion}.
                      <span className="ml-1 font-mono text-xs">({state.decisionId})</span>
                      {state.assertionId ? (
                        <span className="ml-1 font-mono text-xs">
                          assertion {state.assertionId}
                        </span>
                      ) : null}
                    </p>
                  ) : state.phase === "not_persisted" ? (
                    <p
                      role="alert"
                      data-testid="review-not-persisted"
                      className="mt-3 text-sm text-moss-coral-strong"
                    >
                      <strong>No decision was stored.</strong> The server answered &ldquo;
                      {state.detail}&rdquo; rather than a stored decision, so this case is
                      unchanged.
                    </p>
                  ) : state.phase === "conflict" ? (
                    <p
                      role="alert"
                      data-testid="review-conflict"
                      className="mt-3 text-sm text-moss-coral-strong"
                    >
                      <strong>Not decided — this case moved.</strong> {state.message} Reload the
                      list so you decide against what the case says now.
                    </p>
                  ) : state.phase === "unavailable" ? (
                    <p
                      role="alert"
                      data-testid="review-unavailable"
                      className="mt-3 text-sm text-moss-coral-strong"
                    >
                      <strong>Not decided — the service could not be reached.</strong>{" "}
                      {state.message}
                    </p>
                  ) : state.phase === "refused" ? (
                    <p
                      role="alert"
                      data-testid="review-refused"
                      className="mt-3 text-sm text-moss-coral-strong"
                    >
                      <strong>Refused, and nothing was stored.</strong> {state.message}
                    </p>
                  ) : null}

                  {state.phase === "correcting" ? (
                    <div className="mt-3">
                      <TextField
                        label="The value you are accepting instead"
                        hint="The original proposal is preserved; your correction is recorded beside it."
                        value={corrections[row.reviewCaseId] ?? ""}
                        onChange={(event) =>
                          setCorrections((prior) => ({
                            ...prior,
                            [row.reviewCaseId]: event.target.value,
                          }))
                        }
                        data-testid="review-correction-field"
                      />
                    </div>
                  ) : null}

                  {state.phase === "decided" ? null : (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {DISPOSITIONS.map((option) => (
                        <Button
                          key={option.value}
                          variant={option.value === "accept" ? "primary" : "secondary"}
                          disabled={state.phase === "submitting"}
                          onClick={() => {
                            if (option.value === "correct" && state.phase !== "correcting") {
                              setState(row.reviewCaseId, { phase: "correcting" });
                              return;
                            }
                            void decide(row, option.value);
                          }}
                          data-testid={`review-${option.value}`}
                        >
                          {option.label}
                        </Button>
                      ))}
                      <Button
                        variant="ghost"
                        aria-haspopup="dialog"
                        onClick={() => setRevealSubject(row.captureId)}
                        data-testid="review-reveal"
                      >
                        Reveal
                      </Button>
                    </div>
                  )}
                </CardBody>
              </Card>
            </li>
          );
        })}
      </ul>
      <RevealDialog
        open={revealSubject !== null}
        onClose={() => setRevealSubject(null)}
        subjectId={revealSubject ?? ""}
      />
    </>
  );
}
