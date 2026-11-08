"use client";

/**
 * One standalone report (WP07 contract U7): the head version (or an exact
 * version chosen by number), its details, short digests, lifecycle state and
 * read-only hold badge; a History tab (versions and lifecycle events, paged);
 * and the lifecycle actions its state allows. Every read includes withdrawn
 * reports, so an archived or trashed report opens and can be restored.
 */
import Link from "next/link";
import { useCallback, useEffect, useId, useState } from "react";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import { LoadingStatus, SurfaceState } from "@/components/ui/surface-state";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { StandaloneReportReadResult } from "@/lib/api/decode/capabilities/reports.standalone";
import { fetchReport, type ReportRefusal } from "@/lib/reports/client";
import {
  HeldBadge,
  REPORT_MESSAGES,
  instantWords,
  lifecycleWords,
  refusalWords,
  shortDigest,
} from "./presentation";
import { ReportContent } from "./report-content";
import { ReportHistory } from "./report-history";
import { ReportLifecycleActions } from "./report-lifecycle-actions";

type State =
  | { readonly kind: "loading" }
  | { readonly kind: "failed"; readonly refused: ReportRefusal }
  | { readonly kind: "ready"; readonly report: StandaloneReportReadResult; readonly refreshing: boolean };

function Fact({ label, children }: { readonly label: string; readonly children: React.ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs font-medium uppercase tracking-wide text-text-muted">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

export function ReportView({ reportId }: { readonly reportId: string }) {
  const versionSelectId = useId();
  /** `undefined` is the head; a number is that exact version. */
  const [versionNumber, setVersionNumber] = useState<number | undefined>(undefined);
  const [refreshKey, setRefreshKey] = useState(0);
  const requestKey = `${reportId}:${versionNumber ?? "head"}:${refreshKey}`;
  const [answered, setAnswered] = useState<{ readonly key: string; readonly state: State }>({ key: "", state: { kind: "loading" } });
  // While a newer read is in flight the last report stays on screen, marked busy.
  const state: State = answered.key === requestKey
    ? answered.state
    : answered.state.kind === "ready" ? { ...answered.state, refreshing: true } : { kind: "loading" };

  useEffect(() => {
    let cancelled = false;
    void fetchReport(reportId, { includeWithdrawn: true, ...(versionNumber !== undefined ? { versionNumber } : {}) }).then((outcome) => {
      if (cancelled) return;
      setAnswered({
        key: requestKey,
        state: outcome.ok ? { kind: "ready", report: outcome.value, refreshing: false } : { kind: "failed", refused: outcome },
      });
    });
    return () => { cancelled = true; };
  }, [reportId, versionNumber, requestKey]);

  /** Reload server state at the head: after an action, or "Review latest". */
  const reloadLatest = useCallback(() => {
    setVersionNumber(undefined);
    setRefreshKey((key) => key + 1);
  }, []);

  const breadcrumb = (current: string) => (
    <nav aria-label="Breadcrumb" className="mb-2 text-sm">
      <ol className="flex flex-wrap items-center gap-1 text-text-muted">
        <li><Link href="/reports" className="underline underline-offset-2">Reports</Link></li>
        <li aria-hidden="true">›</li>
        <li aria-current="page" className="text-text-primary">{current}</li>
      </ol>
    </nav>
  );

  if (state.kind === "loading") {
    return <div className="mx-auto w-full max-w-5xl p-4">{breadcrumb("Report")}<LoadingStatus label="Reading the report…" /></div>;
  }
  if (state.kind === "failed") {
    const notFound = state.refused.status === 404;
    return (
      <div className="mx-auto w-full max-w-5xl p-4">
        {breadcrumb("Report")}
        <SurfaceState
          kind={notFound ? "not_found" : "unavailable"}
          title={notFound ? "Report not found" : "Report unavailable"}
          detail={notFound ? REPORT_MESSAGES.notFound : refusalWords(state.refused)}
          onRetry={notFound ? undefined : reloadLatest}
        />
      </div>
    );
  }

  const report = state.report;
  const isHead = report.version_number === report.head_version_number;
  const versions = Array.from({ length: report.head_version_number }, (_, index) => report.head_version_number - index);

  return (
    <div className="mx-auto w-full max-w-5xl p-4" data-testid="report-view" aria-busy={state.refreshing || undefined}>
      {breadcrumb(report.title)}
      <PageHeader
        title={report.title}
        eyebrow="Report"
        description={report.summary ?? undefined}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{lifecycleWords(report.lifecycle_state)}</Badge>
            <HeldBadge held={report.held} />
          </div>
        }
      />
      <ReportLifecycleActions report={report} onChanged={reloadLatest} />
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <label htmlFor={versionSelectId} className="text-sm">Version</label>
        <Select
          id={versionSelectId}
          value={String(report.version_number)}
          onChange={(event) => setVersionNumber(Number(event.target.value))}
        >
          {versions.map((number) => (
            <option key={number} value={number}>
              {number === report.head_version_number ? `Version ${number} (latest)` : `Version ${number}`}
            </option>
          ))}
        </Select>
        {!isHead ? <span className="text-sm text-text-muted">{`Showing an earlier version; the latest is version ${report.head_version_number}.`}</span> : null}
      </div>
      <Tabs defaultValue="content" className="mt-4">
        <TabsList aria-label="Report sections">
          <TabsTrigger value="content">Content</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>
        <TabsContent value="content" className="mt-4 grid gap-4">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Report details">
            <Fact label="Version">{`${report.version_number} of ${report.head_version_number}`}</Fact>
            <Fact label="State">{lifecycleWords(report.lifecycle_state)}</Fact>
            <Fact label="Type">{report.type ?? "None"}</Fact>
            <Fact label="Report date">{report.report_date ?? "None"}</Fact>
            <Fact label="Format">{report.content.format}</Fact>
            <Fact label="Recorded">{instantWords(report.recorded_at)}</Fact>
            <Fact label="Content digest"><code>{shortDigest(report.content.decoded_sha256)}</code></Fact>
            <Fact label="Manifest digest"><code>{shortDigest(report.manifest_sha256)}</code></Fact>
            <Fact label="Tags">{report.tags.length > 0 ? report.tags.join(", ") : "None"}</Fact>
            <Fact label="Topics">{report.topics.length > 0 ? report.topics.join(", ") : "None"}</Fact>
            {report.change_reason ? <Fact label="Change reason">{report.change_reason}</Fact> : null}
          </dl>
          <ReportContent key={report.version_id} report={report} />
        </TabsContent>
        <TabsContent value="history" className="mt-4">
          <ReportHistory
            reportId={report.report_id}
            refreshKey={refreshKey}
            selectedVersion={report.version_number}
            onSelectVersion={setVersionNumber}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
