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
 * So this component shows exactly what the listing carries — identifiers, types
 * and states, and no invented proposal text. Capture rows still offer Reveal
 * (`knowledge.reveal`), which is capture-oriented. GoodNotes rows link to the
 * notebook page by the identifiers the listing returned and do not call Reveal.
 *
 * **Knowledge Assertion cases (KLP R6 section 10.2).** They offer exactly
 * accept, reject, defer, mark-unresolved and invalidate: Correct is hidden
 * (S-7 — R6 has no typed correction-patch editor, and a free-text correction is
 * refused by the backend). They never call extraction Reveal. The listing row
 * carries the read-only candidate (KLP-WP-04 fix round 4, Manager ruling on
 * DEV-83): the proposed typed value, qualifier, effective bounds, the cited
 * evidence ids and the current single_current holder's value, rendered before
 * the decision controls so a reviewer sees what it decides. Nothing about it is
 * invented: a field the server sent null renders as absent, and a holder the
 * caller may not see arrives null like no holder at all.
 *
 * **Unknown cases (KLP-AC-135)** — a kind this build does not know — render
 * inert: the case id and the reported kind, and no control. A row the decoder
 * had to drop is counted in a limitation above the list instead of failing the
 * page.
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
import Link from "next/link";
import type {
  BackendReviewCase,
  BackendReviewDisposition,
  DecidableBackendReviewCase,
  KnowledgeAssertionBackendReviewCase,
} from "@/contracts/views";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { WhenDiagnostics } from "@/components/diagnostics/diagnostics-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { RevealDialog } from "@/components/shell/reveal-dialog";
import { apiPost } from "@/lib/api/client";
import { mapUserError } from "@/lib/ui/user-error";

type Disposition = BackendReviewDisposition;

interface DispositionOption {
  readonly value: Disposition;
  readonly label: string;
}

/** The five verbs this tier may submit on a capture-family case, and the words a person reads. */
const DISPOSITIONS: readonly DispositionOption[] = [
  { value: "accept", label: "Accept" },
  { value: "correct", label: "Correct & accept" },
  { value: "reject", label: "Reject" },
  { value: "defer", label: "Defer" },
  { value: "unresolved", label: "Mark unresolved" },
];

/**
 * KLP R6 section 10.2: a Knowledge Assertion case offers accept, reject, defer,
 * mark-unresolved and invalidate — never Correct (S-7).
 */
export const KNOWLEDGE_DISPOSITIONS: readonly DispositionOption[] = [
  { value: "accept", label: "Accept" },
  { value: "reject", label: "Reject" },
  { value: "defer", label: "Defer" },
  { value: "unresolved", label: "Mark unresolved" },
  { value: "invalidate", label: "Invalidate" },
];

function dispositionsFor(row: DecidableBackendReviewCase): readonly DispositionOption[] {
  return row.subjectKind === "knowledge_assertion" ? KNOWLEDGE_DISPOSITIONS : DISPOSITIONS;
}

/** Knowledge proposal states no further decision can move. */
const KNOWLEDGE_TERMINAL_STATES: ReadonlySet<string> = new Set([
  "accepted",
  "corrected_accepted",
  "rejected",
  "invalidated",
  "superseded",
]);

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

function isTerminalDisposition(value: string | null): boolean {
  return value === "accept" || value === "correct_and_accept";
}

function isTerminalCase(row: DecidableBackendReviewCase): boolean {
  if (row.subjectKind === "knowledge_assertion") {
    return KNOWLEDGE_TERMINAL_STATES.has(row.proposalState) || isTerminalDisposition(row.latestDisposition);
  }
  return isTerminalDisposition(row.latestDisposition);
}

function isGoodNotesCase(
  row: DecidableBackendReviewCase,
): row is Extract<BackendReviewCase, { subjectKind: "goodnotes_semantic" | "goodnotes_region" }> {
  return row.subjectKind === "goodnotes_semantic" || row.subjectKind === "goodnotes_region";
}

function goodnotesKnowledgeHref(
  row: Extract<BackendReviewCase, { subjectKind: "goodnotes_semantic" | "goodnotes_region" }>,
): string {
  const params = new URLSearchParams();
  if (row.subjectKind === "goodnotes_semantic") {
    params.set("runId", row.runId);
    params.set("pageVersionId", row.pageVersionId);
  } else {
    params.set("pageVersionId", row.pageVersionId);
  }
  return `/knowledge/goodnotes?${params.toString()}`;
}

function IdentityFields({ row }: { row: DecidableBackendReviewCase }) {
  if (row.subjectKind === "knowledge_assertion") {
    return (
      <>
        <dt className="text-muted">subject</dt>
        <dd data-testid="review-subject-kind">{row.subjectKind}</dd>
        <dt className="text-muted">fact about</dt>
        <dd className="font-mono text-xs break-all" data-testid="review-fact-subject">
          {row.subjectKindOfFact} {row.subjectId}
        </dd>
      </>
    );
  }
  if (row.subjectKind === "goodnotes_semantic") {
    return (
      <>
        <dt className="text-muted">subject</dt>
        <dd data-testid="review-subject-kind">{row.subjectKind}</dd>
        <dt className="text-muted">run</dt>
        <dd className="font-mono text-xs break-all" data-testid="review-run-id">
          {row.runId}
        </dd>
        <dt className="text-muted">page version</dt>
        <dd className="font-mono text-xs break-all" data-testid="review-page-version-id">
          {row.pageVersionId}
        </dd>
      </>
    );
  }
  if (row.subjectKind === "goodnotes_region") {
    return (
      <>
        <dt className="text-muted">subject</dt>
        <dd data-testid="review-subject-kind">{row.subjectKind}</dd>
        <dt className="text-muted">region</dt>
        <dd className="font-mono text-xs break-all" data-testid="review-region-id">
          {row.regionId}
        </dd>
        <dt className="text-muted">page version</dt>
        <dd className="font-mono text-xs break-all" data-testid="review-page-version-id">
          {row.pageVersionId}
        </dd>
        <dt className="text-muted">confidence</dt>
        <dd data-testid="review-confidence">{String(row.confidence)}</dd>
      </>
    );
  }
  return (
    <>
      <dt className="text-muted">capture</dt>
      <dd className="font-mono text-xs break-all" data-testid="review-capture-id">
        {row.captureId}
      </dd>
      <dt className="text-muted">version</dt>
      <dd className="font-mono text-xs break-all" data-testid="review-version-id">
        {row.versionId}
      </dd>
    </>
  );
}

function UnknownCaseCard({ row }: { row: Extract<BackendReviewCase, { subjectKind: "unknown" }> }) {
  return (
    <Card
      data-testid="backend-review-case"
      data-review-case-id={row.reviewCaseId}
      data-subject-kind="unknown"
    >
      <CardTitle>
        <span className="text-sm">A case this workbench cannot show</span>
      </CardTitle>
      <CardBody>
        <p className="text-sm text-muted" data-testid="review-unknown-case">
          This kind of review case is not supported here, so it cannot be decided from this page.
        </p>
        <WhenDiagnostics>
          <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
            <dt className="text-muted">case</dt>
            <dd className="font-mono text-xs break-all">{row.reviewCaseId}</dd>
            <dt className="text-muted">reported kind</dt>
            <dd className="font-mono text-xs break-all">{row.reportedSubjectKind}</dd>
          </dl>
        </WhenDiagnostics>
      </CardBody>
    </Card>
  );
}

function shownValue(value: string | null, valueType: string): string {
  if (value === null) return "(no value)";
  return valueType === "datetime" ? moment(value) : value;
}

/**
 * The read-only candidate of one Knowledge case, exactly as the row carries it.
 * The cited evidence and holder identifiers are technical receipts and stay
 * behind the diagnostics gate; their count and the holder's value are review
 * truth.
 */
function CandidatePanel({ row }: { row: KnowledgeAssertionBackendReviewCase }) {
  return (
    <dl
      className="mt-3 grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1 rounded-md border border-border p-3 text-sm"
      data-testid="review-candidate"
    >
      <dt className="text-muted">predicate</dt>
      <dd className="font-mono text-xs break-all">{row.predicateCode}</dd>
      <dt className="text-muted">proposed value</dt>
      <dd data-testid="review-candidate-value">{shownValue(row.value, row.valueType)}</dd>
      {row.qualifier !== null ? (
        <>
          <dt className="text-muted">qualifier</dt>
          <dd className="font-mono text-xs break-all" data-testid="review-candidate-qualifier">
            {JSON.stringify(row.qualifier)}
          </dd>
        </>
      ) : null}
      <dt className="text-muted">effective</dt>
      <dd data-testid="review-candidate-effective">
        {row.effectiveFrom ? moment(row.effectiveFrom) : "unknown start"}
        {" – "}
        {row.effectiveTo ? moment(row.effectiveTo) : "open"}
      </dd>
      <dt className="text-muted">current value</dt>
      <dd data-testid="review-candidate-current">
        {row.currentAssertionId === null
          ? "none shown"
          : shownValue(row.currentValue, row.valueType)}
      </dd>
      <dt className="text-muted">cited evidence</dt>
      <dd data-testid="review-candidate-evidence-count">
        {row.evidenceRefIds.length === 1 ? "1 item" : `${row.evidenceRefIds.length} items`}
      </dd>
      <WhenDiagnostics>
        <dt className="text-muted">evidence ids</dt>
        <dd className="font-mono text-xs break-all" data-testid="review-candidate-evidence-ids">
          {row.evidenceRefIds.join(" ")}
        </dd>
        {row.currentAssertionId !== null ? (
          <>
            <dt className="text-muted">current assertion</dt>
            <dd className="font-mono text-xs break-all" data-testid="review-candidate-current-id">
              {row.currentAssertionId}
            </dd>
          </>
        ) : null}
      </WhenDiagnostics>
    </dl>
  );
}

export function BackendReviewWorkbench({
  cases,
  droppedRows = 0,
}: {
  cases: readonly BackendReviewCase[];
  /** Listed rows the decoder had to drop (KLP-AC-135); stated, never hidden. */
  droppedRows?: number;
}) {
  const [states, setStates] = useState<Record<string, RowState>>({});
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [revealSubject, setRevealSubject] = useState<string | null>(null);

  const stateFor = (id: string): RowState => states[id] ?? { phase: "open" };
  const setState = (id: string, next: RowState) =>
    setStates((prior) => ({ ...prior, [id]: next }));

  async function decide(row: DecidableBackendReviewCase, disposition: Disposition) {
    if (!dispositionsFor(row).some((option) => option.value === disposition)) {
      // Not offered for this case kind (a Knowledge case never sends `correct`).
      setState(row.reviewCaseId, {
        phase: "refused",
        message: "That decision is not available for this case.",
      });
      return;
    }
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
      const presented = mapUserError({
        status: answer.status,
        errorClass: answer.errorClass,
        code: answer.code,
        message: answer.error,
      });
      setState(
        row.reviewCaseId,
        answer.errorClass === "conflict"
          ? { phase: "conflict", message: presented.message }
          : answer.errorClass === "unavailable"
            ? { phase: "unavailable", message: presented.message }
            : { phase: "refused", message: presented.message },
      );
    } catch (error) {
      setState(row.reviewCaseId, {
        phase: "unavailable",
        message: mapUserError(error).message,
      });
    }
  }

  return (
    <>
      <p
        className="mb-3 rounded-md border border-warning/40 border-l-4 border-l-warning bg-warning/10 p-3 text-sm"
        data-testid="review-listing-limitation"
      >
        <strong>This listing carries no proposal text.</strong> Open <em>Reveal</em> on a capture
        case, or the GoodNotes page, before you decide. A knowledge case shows its proposed value,
        bounds, cited evidence count and the current value it would replace.
      </p>
      {droppedRows > 0 ? (
        <p
          role="status"
          className="mb-3 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm"
          data-testid="review-dropped-rows"
        >
          {droppedRows === 1
            ? "1 listed case could not be read and is not shown."
            : `${droppedRows} listed cases could not be read and are not shown.`}
        </p>
      ) : null}
      <ul className="flex flex-col gap-3" data-testid="backend-review-list">
        {cases.map((row) => {
          if (row.subjectKind === "unknown") {
            return (
              <li key={row.reviewCaseId}>
                <UnknownCaseCard row={row} />
              </li>
            );
          }
          const state = stateFor(row.reviewCaseId);
          const terminal = state.phase === "decided" || isTerminalCase(row);
          const knowledge = row.subjectKind === "knowledge_assertion";
          return (
            <li key={row.reviewCaseId}>
              <Card
                data-testid="backend-review-case"
                data-review-case-id={row.reviewCaseId}
                data-subject-kind={row.subjectKind}
              >
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
                  {/*
                    WP07 §8.7: these are technical receipts — case, run and
                    page-version identifiers, raw state codes and a review
                    version counter. The risk class, proposal type, the decision
                    controls and the outcome copy are review truth and are
                    rendered outside this gate in both modes.
                  */}
                  <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
                    <dt className="text-muted">opened</dt>
                    <dd>{moment(row.openedAt)}</dd>
                    {row.latestDisposition ? (
                      <>
                        <dt className="text-muted">last disposition</dt>
                        <dd>{row.latestDisposition}</dd>
                      </>
                    ) : null}
                    {row.subjectKind === "knowledge_assertion" ? (
                      <>
                        <dt className="text-muted">fact about</dt>
                        <dd data-testid="review-fact-subject-kind">{row.subjectKindOfFact}</dd>
                        {row.reviewRequirement === "requires_operator" ? (
                          <>
                            <dt className="text-muted">review</dt>
                            <dd data-testid="review-requires-operator">operator review required</dd>
                          </>
                        ) : null}
                      </>
                    ) : null}
                  </dl>
                  <WhenDiagnostics>
                    <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
                      <dt className="text-muted">case</dt>
                      <dd className="font-mono text-xs break-all">{row.reviewCaseId}</dd>
                      <IdentityFields row={row} />
                      <dt className="text-muted">proposal state</dt>
                      <dd>{row.proposalState}</dd>
                      <dt className="text-muted">review version</dt>
                      <dd data-testid="review-version">{row.reviewVersion}</dd>
                    </dl>
                  </WhenDiagnostics>

                  {row.subjectKind === "knowledge_assertion" ? <CandidatePanel row={row} /> : null}

                  {state.phase === "decided" ? (
                    <p
                      role="status"
                      data-testid="review-decided"
                      className="mt-3 text-sm text-success"
                    >
                      Decided and stored. The proposal is now <strong>{state.proposalState}</strong>
                      .
                      {/*
                        WP07 §6.2. The decision outcome above is review truth. The
                        review version and the decision/assertion identifiers are
                        the receipts for it, and are the same receipts gated out of
                        the identity block above — rendering them here while
                        diagnostics are off would walk straight around that gate.
                      */}
                      <WhenDiagnostics>
                        <span className="ml-1">at review version {state.reviewVersion}.</span>
                        <span className="ml-1 font-mono text-xs">({state.decisionId})</span>
                        {state.assertionId ? (
                          <span className="ml-1 font-mono text-xs">
                            assertion {state.assertionId}
                          </span>
                        ) : null}
                      </WhenDiagnostics>
                    </p>
                  ) : state.phase === "not_persisted" ? (
                    <p
                      role="alert"
                      data-testid="review-not-persisted"
                      className="mt-3 text-sm text-destructive"
                    >
                      {/*
                        WP07 §6.4/§8.4. That nothing was stored and the case is
                        unchanged is the mutation outcome and is stated in product
                        language in both modes. The server's own answer is a raw
                        backend string and is governed.
                      */}
                      <strong>No decision was stored.</strong> This case is unchanged.
                      <WhenDiagnostics>
                        <span className="ml-1">
                          The server answered &ldquo;{state.detail}&rdquo; rather than a stored
                          decision.
                        </span>
                      </WhenDiagnostics>
                    </p>
                  ) : state.phase === "conflict" ? (
                    <p
                      role="alert"
                      data-testid="review-conflict"
                      className="mt-3 text-sm text-destructive"
                    >
                      <strong>Not decided — this case moved.</strong> {state.message} Reload the
                      list so you decide against what the case says now.
                    </p>
                  ) : state.phase === "unavailable" ? (
                    <p
                      role="alert"
                      data-testid="review-unavailable"
                      className="mt-3 text-sm text-destructive"
                    >
                      <strong>Not decided — the service could not be reached.</strong>{" "}
                      {state.message}
                    </p>
                  ) : state.phase === "refused" ? (
                    <p
                      role="alert"
                      data-testid="review-refused"
                      className="mt-3 text-sm text-destructive"
                    >
                      <strong>Refused, and nothing was stored.</strong> {state.message}
                    </p>
                  ) : isTerminalCase(row) ? (
                    <p
                      role="status"
                      data-testid="review-already-decided"
                      className="mt-3 text-sm text-success"
                    >
                      This case already has a stored {row.latestDisposition ?? row.proposalState}{" "}
                      disposition.
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

                  <div className="mt-3 flex flex-wrap gap-2">
                    {terminal
                      ? null
                      : dispositionsFor(row).map((option) => (
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
                    {knowledge ? null : isGoodNotesCase(row) ? (
                      <Link
                        href={goodnotesKnowledgeHref(row)}
                        className="inline-flex min-h-[var(--control-height)] items-center text-sm font-medium text-interactive underline decoration-interactive/40 underline-offset-2"
                        data-testid="review-goodnotes-link"
                      >
                        Open GoodNotes page
                      </Link>
                    ) : (
                      <Button
                        variant="ghost"
                        aria-haspopup="dialog"
                        onClick={() => setRevealSubject(row.captureId)}
                        data-testid="review-reveal"
                      >
                        Reveal
                      </Button>
                    )}
                  </div>
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
