import Link from "next/link";
import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EpistemicLabel } from "@/components/ui/epistemic-label";
import { peopleEntity } from "@/lib/routes/people";
import type {
  EntityResolutionView,
  ResolutionOutcome,
} from "@/lib/api/decode/capabilities/entities.resolve";
import type { ResolutionCandidate } from "@/lib/api/decode/capabilities/_entity-read-helpers";
import { codeLabel } from "./format";

const OUTCOME_ROLE: Record<
  ResolutionOutcome,
  { readonly epistemic: "canonical" | "ambiguous" | "conflicted" | "superseded" | "unavailable"; readonly exact: boolean }
> = {
  resolved_exact: { epistemic: "canonical", exact: true },
  resolved_contextual: { epistemic: "canonical", exact: true },
  ambiguous: { epistemic: "ambiguous", exact: false },
  not_found: { epistemic: "unavailable", exact: false },
  conflicted_identifier: { epistemic: "conflicted", exact: false },
  historical_match: { epistemic: "superseded", exact: false },
};

function outcomeCopy(outcome: ResolutionOutcome): { title: string; detail: string } {
  switch (outcome) {
    case "resolved_exact":
      return {
        title: "Resolved to one entity",
        detail: "The reference named one current entity. That is an identity answer, not a search hit.",
      };
    case "resolved_contextual":
      return {
        title: "Resolved in context",
        detail: "The reference named one entity after the supplied context distinguished it from others.",
      };
    case "ambiguous":
      return {
        title: "More than one entity matches",
        detail:
          "Nothing here chooses among them. Every candidate is listed; the first is not opened for you, and nothing merges.",
      };
    case "not_found":
      return {
        title: "No entity matched that reference",
        detail: "The resolver ran and named nobody. That is not a directory, and it is not a failed read.",
      };
    case "conflicted_identifier":
      return {
        title: "That identifier is conflicted",
        detail:
          "Several entities claim the same identifier. This is not an exact resolve, and nothing here merges the conflict.",
      };
    case "historical_match":
      return {
        title: "Matched a historical identity",
        detail:
          "The reference matched, but not as a current identity. This is not styled as an exact resolve.",
      };
  }
}

function CandidateList({ candidates }: { candidates: readonly ResolutionCandidate[] }) {
  return (
    <ul data-testid="people-resolve-candidates" className="mt-3 space-y-2">
      {candidates.map((candidate) => (
        <li key={candidate.entity_id} className="rounded-md border border-border bg-surface p-3">
          <Link
            href={peopleEntity(candidate.entity_id)}
            className="font-medium text-moss-slate underline decoration-moss-green/40 underline-offset-2"
          >
            {candidate.display_name}
          </Link>
          <p className="mt-1 font-mono text-xs break-all text-muted">{candidate.entity_id}</p>
          <p className="mt-1 text-xs text-muted">
            {codeLabel(candidate.entity_type)} · {codeLabel(candidate.status)}
            {candidate.matched_on.length > 0 ? ` · matched on ${candidate.matched_on.map(codeLabel).join(", ")}` : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function ResolvePanel({ resolution }: { resolution: EntityResolutionView }) {
  const meta = OUTCOME_ROLE[resolution.outcome];
  const copy = outcomeCopy(resolution.outcome);
  const alert = resolution.outcome === "ambiguous" || resolution.outcome === "conflicted_identifier";
  const showPrimary =
    meta.exact && resolution.entity_id !== null && resolution.outcome !== "ambiguous";

  return (
    <Card
      data-testid="people-resolve-result"
      data-outcome={resolution.outcome}
      role={alert ? "alert" : "status"}
      className={alert ? "border-l-4 border-l-moss-gold" : undefined}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle>{copy.title}</CardTitle>
        <EpistemicLabel role={meta.epistemic} />
      </div>
      <CardBody>
        <p data-testid="people-resolve-outcome" className="font-medium text-moss-slate">
          Outcome: {resolution.outcome}
        </p>
        <p className="mt-2">{copy.detail}</p>
        {resolution.warnings.length > 0 ? (
          <ul className="mt-2 list-inside list-disc" data-testid="people-resolve-warnings">
            {resolution.warnings.map((warning) => (
              <li key={warning}>{codeLabel(warning)}</li>
            ))}
          </ul>
        ) : null}
        {showPrimary ? (
          <p className="mt-3">
            <Link
              href={peopleEntity(resolution.entity_id as string)}
              className="font-medium text-moss-green underline"
            >
              Open profile
            </Link>
          </p>
        ) : null}
        {resolution.candidates.length > 0 ? <CandidateList candidates={resolution.candidates} /> : null}
        {resolution.candidates_were_truncated ? (
          <p className="mt-2 text-xs text-muted">
            More candidates exist than this answer carries. Nothing here picked the rest for you.
          </p>
        ) : null}
        {resolution.outcome === "not_found" ? (
          <Badge tone="neutral">No match</Badge>
        ) : null}
      </CardBody>
    </Card>
  );
}
