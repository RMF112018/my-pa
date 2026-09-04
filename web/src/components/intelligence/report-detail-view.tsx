import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { EpistemicLabel, type EpistemicRole } from "@/components/ui/epistemic-label";
import { RichContent } from "@/components/ui/rich-content";
import { safeHref } from "@/lib/http/safe-href";
import { markdownToRich } from "@/lib/content/markdown-to-rich";
import type { ReportsReadResult, ReportProvenanceRef } from "@/lib/api/decode/capabilities/reports.read";
import { intelligenceHome, intelligenceReport } from "@/lib/routes/intelligence";

const STATE_TONE: Record<string, "green" | "gold" | "coral" | "neutral"> = {
  final: "green",
  partial: "gold",
  superseded: "gold",
  rejected: "coral",
};

function provenanceRole(ref: ReportProvenanceRef): EpistemicRole {
  if (ref.relation === "derived_from") return "ai-derived";
  return "source";
}

export function structuredContentKeys(
  content: Readonly<Record<string, unknown>> | undefined,
): readonly string[] {
  if (content === undefined) return [];
  return Object.keys(content);
}

export function ReportDetailView({ report }: { readonly report: ReportsReadResult }) {
  const bodyNodes =
    report.body_markdown !== undefined ? markdownToRich(report.body_markdown) : [];
  const structuredKeys = structuredContentKeys(report.structured_content);
  const hrefFor = (id: string) => intelligenceReport(id);

  return (
    <article className="mx-auto max-w-4xl" data-testid="intelligence-report-detail">
      <p className="mb-3">
        <Link
          href={intelligenceHome()}
          className="inline-flex min-h-[var(--control-height)] items-center text-sm text-moss-green underline"
        >
          ← Intelligence
        </Link>
      </p>
      <header className="mb-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h1 id="intelligence-report-heading" className="text-xl font-semibold text-moss-slate">
            {report.title}
          </h1>
          <div className="flex flex-wrap gap-1">
            <Badge tone={STATE_TONE[report.artifact_state] ?? "neutral"}>{report.artifact_state}</Badge>
            {report.artifact_state === "superseded" ? <EpistemicLabel role="superseded" /> : null}
            {report.artifact_kind === "morning_brief" ? (
              <Badge tone="green">Brief artifact</Badge>
            ) : null}
          </div>
        </div>
        <p className="mt-1 text-sm text-muted">
          Secondary markdown is visual body, not a Brief section/item schema.
        </p>
      </header>

      <Card>
        <CardTitle>Artifact</CardTitle>
        <CardBody>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 break-words text-xs">
            <dt>Kind</dt>
            <dd data-testid="intelligence-kind">{report.artifact_kind}</dd>
            <dt>Stage</dt>
            <dd data-testid="intelligence-stage">{report.stage}</dd>
            <dt>Focus</dt>
            <dd>{report.focus_area_id ?? "none"}</dd>
            <dt>Report date</dt>
            <dd data-testid="intelligence-report-date">{report.report_date}</dd>
            <dt>Version</dt>
            <dd>{report.version}</dd>
            <dt>State</dt>
            <dd data-testid="intelligence-artifact-state">{report.artifact_state}</dd>
            <dt>Source lane</dt>
            <dd>{report.source_lane ?? "none"}</dd>
            <dt>Cycle</dt>
            <dd className="break-all">{report.cycle_run_id}</dd>
            <dt>Run</dt>
            <dd className="break-all">{report.report_run_id}</dd>
            <dt>Committed</dt>
            <dd data-testid="intelligence-committed-at">{report.committed_at}</dd>
            <dt>Supersedes</dt>
            <dd data-testid="intelligence-supersedes">
              {report.supersedes_report_id ? (
                <Link href={hrefFor(report.supersedes_report_id)} className="text-moss-green underline">
                  {report.supersedes_report_id}
                </Link>
              ) : (
                "none"
              )}
            </dd>
            <dt>Dependencies</dt>
            <dd data-testid="intelligence-dependencies">
              {report.dependency_report_ids.length === 0
                ? "none"
                : report.dependency_report_ids.map((id) => (
                    <span key={id} className="mr-2 inline-block">
                      <Link href={hrefFor(id)} className="text-moss-green underline">
                        {id}
                      </Link>
                    </span>
                  ))}
            </dd>
          </dl>
        </CardBody>
      </Card>

      <section aria-labelledby="intelligence-body-heading" className="mt-4">
        <h2 id="intelligence-body-heading" className="mb-2 text-base font-semibold text-moss-slate">
          Secondary body
        </h2>
        {report.body_markdown === undefined ? (
          <p className="text-sm text-muted" data-testid="intelligence-body-absent">
            This artifact has no secondary markdown body.
          </p>
        ) : bodyNodes.length === 0 ? (
          <p className="text-sm text-muted" data-testid="intelligence-body-empty">
            Secondary body contained no allowlisted markdown.
          </p>
        ) : (
          <div
            className="max-w-full overflow-x-auto break-words"
            data-testid="intelligence-body-markdown"
          >
            <RichContent nodes={bodyNodes} />
          </div>
        )}
      </section>

      <details className="mt-4 rounded-lg border border-border bg-surface p-3" data-testid="intelligence-structured">
        <summary className="cursor-pointer text-sm font-medium text-moss-slate">
          Persisted structured content
        </summary>
        {structuredKeys.length === 0 ? (
          <p className="mt-2 text-sm text-muted" data-testid="intelligence-structured-absent">
            No persisted structured content is present. Opaque structured content is not inferred
            from markdown, and no Brief section/item schema is invented here.
          </p>
        ) : (
          <div className="mt-2 text-sm" data-testid="intelligence-structured-present">
            <p>
              Persisted structured content is present. Keys: {structuredKeys.join(", ")}. This is
              not a Brief section/item schema and is not rendered as items.
            </p>
            <ul className="mt-1 list-inside list-disc text-xs" data-testid="intelligence-structured-keys">
              {structuredKeys.map((key) => (
                <li key={key}>{key}</li>
              ))}
            </ul>
          </div>
        )}
      </details>

      <details className="mt-3 rounded-lg border border-border bg-surface p-3" data-testid="intelligence-provenance">
        <summary className="cursor-pointer text-sm font-medium text-moss-slate">
          Report-level provenance
        </summary>
        <p className="mt-2 text-xs text-muted">
          These refs belong to the artifact as a whole. They are not item-level evidence.
        </p>
        {report.provenance.length === 0 ? (
          <p className="mt-2 text-sm" data-testid="intelligence-provenance-none">
            No report-level provenance refs were provided. That is the list as returned, not a claim
            that matching evidence was searched and found empty.
          </p>
        ) : (
          <ul className="mt-2 flex flex-col gap-2" data-testid="intelligence-provenance-list">
            {report.provenance.map((ref, index) => {
              const href = ref.source_url ? safeHref(ref.source_url) : null;
              return (
                <li key={`${ref.source_ref}-${index}`} className="text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <EpistemicLabel role={provenanceRole(ref)} />
                    <span>
                      {ref.relation} · {ref.source_system} · {ref.source_ref}
                    </span>
                  </div>
                  {href ? (
                    <a href={href} className="text-moss-green underline" rel="noreferrer">
                      {href}
                    </a>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </details>
    </article>
  );
}
