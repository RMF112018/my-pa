import { Badge } from "@/components/ui/badge";
import { Card, CardBody } from "@/components/ui/card";
import { EpistemicLabel, type EpistemicRole } from "@/components/ui/epistemic-label";
import { SurfaceState } from "@/components/ui/surface-state";
import type { ReportsResolveSetResult } from "@/lib/api/decode/capabilities/reports.resolve_set";
import { MORNING_BRIEF_SET_ID, nonReadyRequiredCount } from "@/components/intelligence/cycle-selection";

const AGGREGATE_TONE: Record<string, "green" | "gold" | "coral" | "neutral"> = {
  READY: "green",
  DEGRADED: "gold",
  BLOCKED: "coral",
};

const MEMBER_TONE: Record<string, "green" | "gold" | "coral" | "neutral"> = {
  READY: "green",
  MISSING: "coral",
  FAILED: "coral",
  PARTIAL: "gold",
  STALE: "gold",
  SUPERSEDED: "gold",
  NOT_EXPECTED: "neutral",
};

function memberEpistemic(readiness: string): EpistemicRole | null {
  switch (readiness) {
    case "MISSING":
    case "PARTIAL":
      return "pipeline-incomplete";
    case "FAILED":
      return "unavailable";
    case "STALE":
      return "stale";
    case "SUPERSEDED":
      return "superseded";
    default:
      return null;
  }
}

export type ReadinessAnswer =
  | { readonly kind: "resolved"; readonly result: ReportsResolveSetResult }
  | { readonly kind: "unavailable"; readonly detail: string }
  | { readonly kind: "degraded"; readonly result: ReportsResolveSetResult; readonly detail: string };

function freshnessCopy(result: ReportsResolveSetResult): string {
  const stale = result.members.filter((member) => member.readiness === "STALE");
  const committed = result.members
    .map((member) => member.committed_at)
    .filter((value): value is string => typeof value === "string" && value.length > 0);
  const latestCommitted = committed.length > 0 ? committed.reduce((a, b) => (a > b ? a : b)) : null;
  const parts: string[] = [];
  if (latestCommitted) parts.push(`Latest specialist commit ${latestCommitted}`);
  if (stale.length > 0) {
    parts.push(`${stale.length} STALE member${stale.length === 1 ? "" : "s"}`);
  }
  if (parts.length === 0) {
    return "Freshness is taken from specialist committed_at and STALE member state, not the browser clock.";
  }
  return `${parts.join(". ")}. Freshness is not the browser clock.`;
}

export function ReadinessPanel({
  answer,
  cycleRunId,
}: {
  readonly answer: ReadinessAnswer;
  readonly cycleRunId: string;
}) {
  if (answer.kind === "unavailable") {
    return (
      <SurfaceState
        kind="unavailable"
        title="Specialist readiness could not be read"
        detail={answer.detail}
        testId="intelligence-readiness-unavailable"
      />
    );
  }

  const result = answer.result;
  const missingRequired = nonReadyRequiredCount(result.members);
  const aggregateTone = AGGREGATE_TONE[result.aggregate] ?? "neutral";

  return (
    <Card data-testid="intelligence-readiness" className="mb-4">
      {answer.kind === "degraded" ? (
        <p className="mb-2 text-sm text-moss-gold-strong" role="status">
          Readiness was returned incompletely. {answer.detail}
        </p>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="text-base font-semibold text-moss-slate">Morning Intelligence readiness</h2>
        <Badge tone={aggregateTone}>
          <span data-testid="intelligence-readiness-aggregate">{result.aggregate}</span>
        </Badge>
      </div>
      <CardBody>
        <p data-testid="intelligence-readiness-not-health" className="text-sm">
          Aggregate {result.aggregate} is specialist coverage for{" "}
          <code>{MORNING_BRIEF_SET_ID}</code>, not a claim that the system is healthy or that all
          sources are good.
        </p>
        {result.aggregate !== "READY" || missingRequired > 0 ? (
          <p data-testid="intelligence-readiness-partial" className="mt-2 text-sm" role="status">
            Coverage is partial: {missingRequired} required member
            {missingRequired === 1 ? " is" : "s are"} not READY.
          </p>
        ) : (
          <p data-testid="intelligence-readiness-ready" className="mt-2 text-sm" role="status">
            Specialist coverage is READY. That is Brief-input coverage, not system health.
          </p>
        )}
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 break-words text-xs">
          <dt>Business date</dt>
          <dd data-testid="intelligence-business-date">{result.business_date}</dd>
          <dt>Cycle</dt>
          <dd data-testid="intelligence-cycle-run-id" className="break-all">
            {result.cycle_run_id || cycleRunId}
          </dd>
          <dt>Freshness</dt>
          <dd data-testid="intelligence-freshness">{freshnessCopy(result)}</dd>
        </dl>
        {result.members.length === 0 ? (
          <p className="mt-3 text-sm" data-testid="intelligence-readiness-members-none" role="status">
            The resolver returned no members. That is not an empty-success listing of specialists.
          </p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2" data-testid="intelligence-readiness-members">
            {result.members.map((member) => {
              const epistemic = memberEpistemic(member.readiness);
              return (
                <li
                  key={member.member_id}
                  data-testid="intelligence-readiness-member"
                  data-member-id={member.member_id}
                  data-readiness={member.readiness}
                  className="rounded-md border border-border p-2"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-moss-slate">{member.member_id}</span>
                    <Badge tone={MEMBER_TONE[member.readiness] ?? "neutral"}>
                      <span data-testid="intelligence-readiness-member-state">{member.readiness}</span>
                    </Badge>
                    {member.required ? (
                      <span className="text-xs">required</span>
                    ) : (
                      <span className="text-xs">optional</span>
                    )}
                    {epistemic ? <EpistemicLabel role={epistemic} /> : null}
                  </div>
                  <p className="mt-1 break-words text-xs">{member.readiness_reason}</p>
                </li>
              );
            })}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
