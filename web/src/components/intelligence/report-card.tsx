import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { EpistemicLabel } from "@/components/ui/epistemic-label";
import type { ReportListEntry } from "@/lib/api/decode/capabilities/reports.list";
import { intelligenceReport } from "@/lib/routes/intelligence";

const STATE_TONE: Record<string, "green" | "gold" | "coral" | "neutral"> = {
  final: "green",
  partial: "gold",
  superseded: "gold",
  rejected: "coral",
};

export function ReportCard({
  row,
  currentCycle,
}: {
  readonly row: ReportListEntry;
  readonly currentCycle?: string | null;
}) {
  const isBrief = row.artifact_kind === "morning_brief";
  const inCurrent = currentCycle != null && row.cycle_run_id === currentCycle;
  return (
    <Card
      data-testid="intelligence-report"
      data-report-id={row.report_id}
      data-brief-artifact={isBrief ? "true" : undefined}
      className={isBrief ? "border-moss-green/50" : undefined}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <CardTitle>
          <Link
            href={intelligenceReport(row.report_id)}
            className="inline-flex min-h-[var(--control-height)] items-center text-moss-green underline-offset-2 hover:underline"
          >
            {row.title}
          </Link>
        </CardTitle>
        <div className="flex flex-wrap items-center gap-1">
          {isBrief ? (
            <Badge tone="green">
              <span data-testid="intelligence-brief-artifact">Brief artifact</span>
            </Badge>
          ) : null}
          {inCurrent ? <Badge tone="neutral">Current cycle</Badge> : null}
          {row.artifact_state === "superseded" ? <EpistemicLabel role="superseded" /> : null}
          {row.artifact_state === "partial" ? <EpistemicLabel role="pipeline-incomplete" /> : null}
        </div>
      </div>
      <CardBody>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 break-words text-xs">
          <dt>Identifier</dt>
          <dd data-testid="intelligence-report-id">{row.report_id}</dd>
          <dt>Stage</dt>
          <dd data-testid="intelligence-stage">{row.stage}</dd>
          <dt>Kind</dt>
          <dd data-testid="intelligence-kind">{row.artifact_kind}</dd>
          <dt>State</dt>
          <dd data-testid="intelligence-artifact-state">
            <Badge tone={STATE_TONE[row.artifact_state] ?? "neutral"}>{row.artifact_state}</Badge>
          </dd>
          <dt>Cycle</dt>
          <dd className="break-all">{row.cycle_run_id}</dd>
        </dl>
      </CardBody>
    </Card>
  );
}

export function ReportListing({
  items,
  currentCycle,
}: {
  readonly items: readonly ReportListEntry[];
  readonly currentCycle?: string | null;
}) {
  return (
    <ul className="flex flex-col gap-3" data-testid="intelligence-listing">
      {items.map((row) => (
        <li key={row.report_id}>
          <ReportCard row={row} currentCycle={currentCycle} />
        </li>
      ))}
    </ul>
  );
}
