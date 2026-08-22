"use client";

/**
 * Reveal — "why am I seeing this?", rendered so the three answers stay three.
 *
 * WP-02 posted to a stub route and showed a synthetic disclosure. WP-09 wires it
 * to `knowledge.reveal`, and the whole of this component's honesty contract is
 * that it renders **from `state`, never from the length of an array**:
 *
 * * `evidence` — the spans, the versions their offsets are counted in, and the
 *   derivation trace, with proposed and accepted in two separate regions.
 * * `no_evidence` — "we looked and there is nothing here". A finished search.
 * * `unavailable` — "we could not look here", with the gap that says why. It
 *   carries exactly the same empty arrays as `no_evidence`, so a renderer that
 *   branched on `spans.length` would show the two identically. This one branches
 *   on `state`, and `reveal.test.tsx` asserts the two render differently.
 *
 * **Proposed and accepted are two regions, not one list with a badge.** A
 * proposal is what a method suggested; an assertion is what a reviewer promoted.
 * They are labelled, separated, and given different styling, because a reader who
 * has to notice a badge is a reader who can fail to.
 *
 * **No span text is shown, because none is sent.** A span is a locator — the
 * version, the code-point range, the line and column, the role, and the digest of
 * the slice. Rendering an offset is not rendering content.
 */
import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { apiPost } from "@/lib/api/client";
import type { DisclosureEnvelope } from "@/contracts/envelope";

/** One exact citation, in the shape the Python `RevealSpanView` publishes. */
interface RevealSpan {
  readonly span_id: string;
  readonly version_id: string;
  readonly start_offset: number;
  readonly end_offset: number;
  readonly character_count: number;
  readonly offset_basis: string;
  readonly line_start: number;
  readonly column_start: number;
  readonly span_role: string;
  readonly quoted_text_sha256: string;
}

interface RevealVersion {
  readonly version_id: string;
  readonly version_number: number;
  readonly is_current: boolean;
  readonly derivation_state: string | null;
  readonly derivation_is_complete: boolean;
}

interface RevealProposal {
  readonly proposal_id: string;
  readonly proposal_type: string;
  readonly state: string;
  readonly method: string;
  readonly method_version: string;
  readonly review_case_id: string | null;
  readonly latest_disposition: string | null;
  readonly span_ids: readonly string[];
}

interface RevealAssertion {
  readonly assertion_id: string;
  readonly assertion_type: string;
  readonly state: string;
  readonly proposal_id: string;
  readonly decision_id: string;
  readonly disposition: string | null;
  readonly receipt_id: string | null;
  readonly policy_version: string | null;
  readonly span_ids: readonly string[];
}

interface RevealResult {
  readonly state: "evidence" | "no_evidence" | "unavailable";
  readonly gap: string | null;
  readonly subject_kind: string | null;
  readonly capture_id: string | null;
  readonly versions: readonly RevealVersion[];
  readonly spans: readonly RevealSpan[];
  readonly proposed: readonly RevealProposal[];
  readonly accepted: readonly RevealAssertion[];
  readonly versions_with_completed_derivation: number;
}

interface RevealResponse {
  readonly shape?: string;
  readonly state?: "evidence" | "no_evidence" | "unavailable";
  readonly result?: RevealResult;
  readonly reason?: string;
  readonly disclosure: DisclosureEnvelope;
}

/** What each gap means, in the caller's terms. Closed, like the token itself. */
const GAP_TEXT: Record<string, string> = {
  subject_kind_is_outside_the_evidence_model:
    "This kind of subject is outside the evidence model this build can traverse. Nothing was " +
    "searched, so nothing here says whether evidence exists.",
  derivation_has_not_completed_for_every_version:
    "At least one version of this item has not finished deriving. Nothing was searched to " +
    "completion, so nothing here says whether evidence exists.",
};

function Spans({ spans }: { spans: readonly RevealSpan[] }) {
  return (
    <ul data-testid="reveal-spans" className="flex flex-col gap-1 text-xs text-muted">
      {spans.map((span) => (
        <li key={span.span_id}>
          <span className="font-mono">{span.version_id}</span> [{span.start_offset}–
          {span.end_offset}) · line {span.line_start}, column {span.column_start} · {span.span_role}{" "}
          · {span.offset_basis} · sha256 {span.quoted_text_sha256.slice(0, 12)}…
        </li>
      ))}
    </ul>
  );
}

export function RevealDialog({
  open,
  onClose,
  subjectId,
}: {
  open: boolean;
  onClose: () => void;
  subjectId: string;
}) {
  const [response, setResponse] = useState<RevealResponse | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [failure, setFailure] = useState<string | null>(null);

  async function reveal() {
    setStatus("loading");
    setResponse(null);
    setFailure(null);
    try {
      const answer = await apiPost<RevealResponse>({ hasSession: true }, "/api/reveal", {
        subjectId,
      });
      if (answer.ok && answer.data) {
        setResponse(answer.data);
        setStatus("idle");
      } else {
        if (answer.status === 401 || answer.errorClass === "authentication") {
          setFailure("Your session expired before evidence could be read.");
        } else if (answer.status === 403 || answer.errorClass === "authorization" || answer.errorClass === "policy_denied") {
          setFailure("Evidence was not authorized. Nothing was disclosed.");
        } else if (answer.status === 404 || answer.errorClass === "not_found") {
          setFailure("Evidence was not found, or it is outside your authority.");
        } else {
          setFailure("Evidence is unavailable right now. Nothing was disclosed.");
        }
        setStatus("error");
      }
    } catch {
      setFailure("Evidence is unavailable right now. Nothing was disclosed.");
      setStatus("error");
    }
  }

  const result = response?.result;
  // Read off `state`, never off the arrays. See the module docstring.
  const state = response?.state ?? result?.state ?? null;

  return (
    <Dialog open={open} onClose={onClose} title="Why am I seeing this?">
      <div className="flex flex-col gap-3 text-sm text-moss-slate">
        {response === null ? (
          <p className="text-muted">
            Reveal shows the evidence and reasoning behind an item. Nothing is hidden from you.
          </p>
        ) : null}

        {state === "unavailable" ? (
          <div data-testid="reveal-unavailable" className="flex flex-col gap-1">
            <p className="font-semibold text-moss-coral-strong">This was not searched.</p>
            <p>
              {(result?.gap ? GAP_TEXT[result.gap] : undefined) ??
                response?.reason ??
                "The evidence behind this item could not be searched, so nothing here says " +
                  "whether evidence exists."}
            </p>
          </div>
        ) : null}

        {state === "no_evidence" ? (
          <div data-testid="reveal-no-evidence" className="flex flex-col gap-1">
            <p className="font-semibold">Searched. No evidence is recorded.</p>
            <p className="text-muted">
              Every version of this item finished deriving and produced nothing, across{" "}
              {result?.versions.length ?? 0} version(s).
            </p>
          </div>
        ) : null}

        {state === "evidence" && result ? (
          <div data-testid="reveal-evidence" className="flex flex-col gap-3">
            <section className="flex flex-col gap-1">
              <h3 className="text-xs font-semibold uppercase tracking-wide">Source spans</h3>
              <Spans spans={result.spans} />
            </section>

            {result.accepted.length > 0 ? (
              <section data-testid="reveal-accepted" className="flex flex-col gap-1">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-moss-slate">
                  Accepted — promoted by your review
                </h3>
                <ul className="flex flex-col gap-1 text-xs">
                  {result.accepted.map((record) => (
                    <li key={record.assertion_id}>
                      <span className="font-mono">{record.assertion_id}</span> · {record.assertion_type}{" "}
                      · {record.state} · decision {record.decision_id}
                      {record.disposition ? ` (${record.disposition})` : ""}
                      {record.receipt_id ? ` · receipt ${record.receipt_id}` : " · no receipt"}
                      {record.policy_version ? ` · policy ${record.policy_version}` : ""}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {result.proposed.length > 0 ? (
              <section data-testid="reveal-proposed" className="flex flex-col gap-1">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
                  Proposed — not asserted, awaiting your disposition
                </h3>
                <ul className="flex flex-col gap-1 text-xs text-muted">
                  {result.proposed.map((proposal) => (
                    <li key={proposal.proposal_id}>
                      <span className="font-mono">{proposal.proposal_id}</span> ·{" "}
                      {proposal.proposal_type} · {proposal.state} · {proposal.method}@
                      {proposal.method_version}
                      {proposal.review_case_id ? ` · review ${proposal.review_case_id}` : ""}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        ) : null}

        {response ? (
          <div className="text-xs text-muted">
            <p>Coverage: {response.disclosure.coverage}. {response.disclosure.limitations.join(" ")}</p>
            {response.disclosure.truncated || response.disclosure.limitations.length > 0 ? (
              <p data-testid="reveal-limited" className="mt-1">
                {response.disclosure.limitations.some((item) => item.toLowerCase().includes("redact"))
                  ? "Evidence disclosure is redacted or limited by the server."
                  : "Evidence disclosure is limited by the server."}
              </p>
            ) : null}
          </div>
        ) : null}

        {status === "error" ? (
          <p role="alert" className="text-moss-coral-strong">
            {failure ?? "Evidence is unavailable right now. Nothing was disclosed."}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button onClick={reveal} disabled={status === "loading"}>
            {status === "loading" ? "Loading…" : "Reveal"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
