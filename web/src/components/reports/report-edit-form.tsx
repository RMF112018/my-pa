"use client";

/**
 * `/reports/[reportId]/edit` (WP07 contract U5-U7, Amendment A2).
 *
 * The head is read with its body (withdrawn reports included, so an archived or
 * trashed one says why it cannot be edited). Only an active report is edited.
 * A head whose body the read omitted is edited metadata-only until the user
 * loads its full content (verified by `readFullContent`); content is then
 * editable and sent only if it changed.
 *
 * Submit sends ONLY the changed fields in `patch`, emptied optional fields in
 * `clearFields`, a required change reason, and `expectedVersion` = the head
 * version the form was checked against. A submit that changes nothing is
 * stopped here ("Nothing changed"). Large content goes through a transfer; while
 * the update answer is ambiguous the form's `transferBinding` keeps it in memory
 * so the unchanged resubmit reuses it with the same key (see transfer-client).
 *
 * Conflict (U5/A2): never retried, never overwritten. A 409 whose `current`
 * head differs from the expected version says "This report changed since you
 * opened it (now version N)"; any other 409 says the request conflicted. The
 * draft is kept either way. "Review latest" reads the head again into a side
 * panel, and the next submit is checked against that version, with a new
 * idempotency key (the payload changed, and the key rotated after the 409).
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMutationFeedback } from "@/components/ui/mutation-feedback";
import { LoadingStatus, SurfaceState } from "@/components/ui/surface-state";
import { mutationKey } from "@/lib/api/work-client";
import type { StandaloneReportReadResult } from "@/lib/api/decode/capabilities/reports.standalone";
import type { ReportsUpdateResult } from "@/lib/api/decode/capabilities/reports.update";
import {
  CONFLICT_MESSAGE,
  STALE_MESSAGE,
  classifyConflict,
  fetchReport,
  reportIntent,
  updateReport,
  type ReportOutcome,
  type ReportRefusal,
  type UpdateRequest,
} from "@/lib/reports/client";
import {
  contentFromDecoded,
  needsTransfer,
  readFullContent,
  transferBinding,
} from "@/lib/reports/transfer-client";
import {
  HeldBadge,
  REPORT_MESSAGES,
  byteWords,
  lifecycleWords,
  refusalWords,
  reportHref,
  shortId,
} from "./presentation";
import { RenderedReportContent } from "./report-content";
import {
  FORM_MESSAGES,
  FormBreadcrumb,
  REASON_MAX_CHARACTERS,
  ReportFieldsEditor,
  buildPatch,
  codePoints,
  hasErrors,
  isNoChange,
  metadataDraft,
  stagedBytesOf,
  validateDraft,
  withContent,
  type DraftErrors,
  type ReportDraft,
} from "./report-form";

type Load =
  | { readonly kind: "loading" }
  | { readonly kind: "failed"; readonly refused: ReportRefusal }
  | { readonly kind: "ready"; readonly report: StandaloneReportReadResult };

type Phase = "idle" | "sending" | "uploading" | "done";

type Notice =
  | { readonly kind: "stale" | "conflict"; readonly text: string }
  | { readonly kind: "error"; readonly text: string };

type Latest =
  | { readonly kind: "loading" }
  | { readonly kind: "failed"; readonly text: string }
  | { readonly kind: "ready"; readonly report: StandaloneReportReadResult };

function hasInlineContent(report: StandaloneReportReadResult): boolean {
  return report.content.body !== undefined || report.content.data !== undefined;
}

export function ReportEditForm({ reportId }: { readonly reportId: string }) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    void fetchReport(reportId, { includeBody: true, includeWithdrawn: true }).then((outcome) => {
      if (cancelled) return;
      setLoad(outcome.ok ? { kind: "ready", report: outcome.value } : { kind: "failed", refused: outcome });
    });
    return () => { cancelled = true; };
  }, [reportId]);

  const trail = (label: string) => [{ label: "Reports", href: "/reports" }, { label, href: reportHref(reportId) }, { label: "Edit" }];

  if (load.kind === "loading") {
    return <div className="mx-auto w-full max-w-3xl p-4"><FormBreadcrumb trail={trail("Report")} /><LoadingStatus label="Reading the report…" /></div>;
  }
  if (load.kind === "failed") {
    const notFound = load.refused.status === 404;
    return (
      <div className="mx-auto w-full max-w-3xl p-4">
        <FormBreadcrumb trail={trail("Report")} />
        <SurfaceState
          kind={notFound ? "not_found" : "unavailable"}
          title={notFound ? "Report not found" : "Report unavailable"}
          detail={notFound ? REPORT_MESSAGES.notFound : refusalWords(load.refused)}
        />
      </div>
    );
  }
  const report = load.report;
  if (report.lifecycle_state !== "active") {
    return (
      <div className="mx-auto w-full max-w-3xl p-4">
        <FormBreadcrumb trail={trail(report.title)} />
        <PageHeader title={`Edit ${report.title}`} eyebrow="Reports" />
        <div role="status" className="grid gap-2 text-sm" data-testid="report-not-editable">
          <p>{`This report is ${lifecycleWords(report.lifecycle_state)}. Only active reports can be edited; restore it first.`}</p>
          <p><Link href={reportHref(report.report_id)} className="underline underline-offset-2">Back to the report</Link></p>
        </div>
      </div>
    );
  }
  return <EditForm key={report.version_id} report={report} trail={trail(report.title)} />;
}

function EditForm({
  report,
  trail,
}: {
  readonly report: StandaloneReportReadResult;
  readonly trail: readonly { readonly label: string; readonly href?: string }[];
}) {
  const router = useRouter();
  const feedback = useMutationFeedback();
  const reasonId = useId();
  const intent = useRef(reportIntent("report-update"));
  const transfer = useRef(transferBinding());
  const inFlight = useRef(false);
  const initialContent = hasInlineContent(report);
  const initial = initialContent
    ? withContent(metadataDraft(report), { body: report.content.body, data: report.content.data })
    : metadataDraft(report);
  /** What the user started from: the patch names what differs from it. */
  const [baseline, setBaseline] = useState<ReportDraft>(initial);
  const [draft, setDraft] = useState<ReportDraft>(initial);
  const [contentLoaded, setContentLoaded] = useState(initialContent);
  const [contentLoad, setContentLoad] = useState<{ readonly kind: "idle" | "loading" } | { readonly kind: "failed"; readonly text: string }>({ kind: "idle" });
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [expectedVersion, setExpectedVersion] = useState(report.head_version_number);
  const [phase, setPhase] = useState<Phase>("idle");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [latest, setLatest] = useState<Latest | null>(null);

  useEffect(() => {
    // One binding per mount: the cleanup disposes it, and a remount (StrictMode
    // runs mount -> cleanup -> mount) gets a live one rather than the disposed one.
    const binding = transferBinding();
    transfer.current = binding;
    return () => { void binding.dispose(); };
  }, []);

  const latestReport = latest?.kind === "ready" ? latest.report : null;
  const latestEditable = latestReport === null || latestReport.lifecycle_state === "active";

  async function loadContent() {
    const pointer = report.content.body_chunked_read;
    if (!pointer) return;
    setContentLoad({ kind: "loading" });
    const outcome = await readFullContent(report.report_id, report.version_number, pointer, { includeWithdrawn: true });
    const decoded = outcome.ok ? contentFromDecoded(report.content.format, outcome.value) : null;
    if (!outcome.ok || decoded === null) {
      setContentLoad({ kind: "failed", text: outcome.ok ? REPORT_MESSAGES.unverified : refusalWords(outcome) });
      return;
    }
    // Only the content fields are filled; metadata the user already typed stays.
    setBaseline((current) => withContent(current, decoded));
    setDraft((current) => withContent(current, decoded));
    setContentLoaded(true);
    setContentLoad({ kind: "idle" });
  }

  async function reviewLatest() {
    setNotice(null);
    setLatest({ kind: "loading" });
    const outcome = await fetchReport(report.report_id, { includeBody: true, includeWithdrawn: true });
    if (!outcome.ok) {
      setLatest({ kind: "failed", text: refusalWords(outcome) });
      return;
    }
    setLatest({ kind: "ready", report: outcome.value });
    setExpectedVersion(outcome.value.head_version_number);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current || !latestEditable) return;
    const found = validateDraft(draft, { content: contentLoaded });
    setErrors(found);
    const trimmedReason = reason.trim();
    const reasonProblem = trimmedReason === ""
      ? FORM_MESSAGES.reasonRequired
      : codePoints(trimmedReason) > REASON_MAX_CHARACTERS ? FORM_MESSAGES.reasonTooLong : null;
    setReasonError(reasonProblem);
    if (hasErrors(found) || reasonProblem) return;
    const change = buildPatch(baseline, draft, { content: contentLoaded });
    if (isNoChange(change)) {
      setNotice({ kind: "error", text: FORM_MESSAGES.nothingChanged });
      return;
    }
    inFlight.current = true;
    setNotice(null);
    const payload = {
      expectedVersion,
      patch: change.patch,
      ...(change.clearFields.length > 0 ? { clearFields: change.clearFields } : {}),
      changeReason: trimmedReason,
    };
    const signed = { reportId: report.report_id, ...payload };
    const request: UpdateRequest = { ...payload, idempotencyKey: intent.current.keyFor(signed) };
    const content = change.patch.content;
    let outcome: ReportOutcome<ReportsUpdateResult>;
    if (content !== undefined && !("transfer" in content) && needsTransfer(request)) {
      setPhase("uploading");
      outcome = await transfer.current.submit(
        JSON.stringify(signed),
        { format: content.format, staged: stagedBytesOf(content), idempotencyKey: mutationKey("report-transfer") },
        (staged) => updateReport(report.report_id, { ...request, patch: { ...request.patch, content: staged } }),
      );
    } else {
      setPhase("sending");
      await transfer.current.release();
      outcome = await updateReport(report.report_id, request);
    }
    intent.current.settle(outcome);
    inFlight.current = false;
    if (outcome.ok) {
      const result = outcome.value;
      setPhase("done");
      feedback.publish({
        eventId: `report:update:${result.receipt.receipt_id}`,
        kind: "success",
        message: result.outcome === "no_op"
          ? `No new version: the report already matched. Receipt ${shortId(result.receipt.receipt_id)}.`
          : `Report saved: version ${result.version_number}. Receipt ${shortId(result.receipt.receipt_id)}${result.replayed ? " (replayed)" : ""}.`,
      });
      router.push(reportHref(result.report_id));
      return;
    }
    setPhase("idle");
    const conflict = classifyConflict(outcome, { expectedVersion });
    if (conflict.kind === "stale") setNotice({ kind: "stale", text: STALE_MESSAGE(conflict.current.headVersionNumber) });
    else if (conflict.kind === "conflict") setNotice({ kind: "conflict", text: CONFLICT_MESSAGE });
    else setNotice({ kind: "error", text: refusalWords(outcome) });
  }

  const busy = phase !== "idle";
  const pointer = report.content.body_chunked_read;
  const contentNotice = (
    <div className="grid gap-2 rounded-lg border border-border p-3" data-testid="report-edit-content-omitted">
      <p className="text-sm text-text-secondary">
        This report&apos;s content is too large to show at once. You can change its details without it, or load it to edit it.
      </p>
      {pointer ? (
        <div>
          <Button
            size="sm"
            variant="secondary"
            pending={contentLoad.kind === "loading"}
            disabled={busy || contentLoad.kind === "loading"}
            onClick={() => void loadContent()}
          >
            {`Load full content (${byteWords(pointer.byte_count)})`}
          </Button>
        </div>
      ) : null}
      {contentLoad.kind === "failed" ? <p role="alert" className="text-sm text-destructive">{contentLoad.text}</p> : null}
    </div>
  );

  return (
    <div className="mx-auto w-full max-w-5xl p-4">
      <FormBreadcrumb trail={trail} />
      <PageHeader
        title={`Edit ${report.title}`}
        eyebrow="Reports"
        description={`Editing from version ${report.head_version_number}.`}
        actions={<HeldBadge held={report.held} />}
      />
      <div className={latest ? "grid gap-6 lg:grid-cols-2" : "grid gap-6"}>
        <form noValidate aria-label="Edit report" className="grid gap-4" onSubmit={(event) => void submit(event)}>
          <ReportFieldsEditor
            draft={draft}
            onChange={setDraft}
            errors={errors}
            contentEditable={contentLoaded}
            contentNotice={contentNotice}
            disabled={busy}
          />
          <div className="flex flex-col gap-1">
            <label htmlFor={reasonId} className="text-sm font-medium text-text-primary">
              Reason for the change<span className="ml-1 font-normal text-muted" aria-hidden="true">(required)</span>
            </label>
            <Input
              id={reasonId}
              value={reason}
              required
              aria-required
              disabled={busy}
              aria-invalid={reasonError ? true : undefined}
              aria-describedby={reasonError ? `${reasonId}-error` : undefined}
              onChange={(event) => setReason(event.target.value)}
            />
            {reasonError ? <p id={`${reasonId}-error`} role="alert" className="text-xs text-destructive">{reasonError}</p> : null}
          </div>
          {phase === "uploading" || phase === "sending" ? (
            <p role="status" className="text-sm text-text-secondary">
              {phase === "uploading" ? FORM_MESSAGES.uploading : FORM_MESSAGES.sending}
            </p>
          ) : null}
          {notice ? (
            <div role="alert" data-testid="report-edit-notice" data-kind={notice.kind} className="grid gap-2 text-sm">
              <p>{notice.text}</p>
              {notice.kind !== "error" ? (
                <>
                  <p className="text-text-secondary">Your changes are kept. Review the latest version, re-apply what you need, then save again.</p>
                  <div><Button size="sm" variant="secondary" onClick={() => void reviewLatest()}>Review latest</Button></div>
                </>
              ) : null}
            </div>
          ) : null}
          <div className="flex justify-end gap-2">
            <Link
              href={reportHref(report.report_id)}
              className="inline-flex min-h-[var(--control-height)] items-center rounded-[var(--radius-md)] px-3 text-sm font-medium"
            >
              Cancel
            </Link>
            <Button type="submit" pending={busy} disabled={!latestEditable}>Save</Button>
          </div>
        </form>
        {latest ? <LatestPanel latest={latest} expectedVersion={expectedVersion} /> : null}
      </div>
    </div>
  );
}

function LatestPanel({ latest, expectedVersion }: { readonly latest: Latest; readonly expectedVersion: number }) {
  if (latest.kind === "loading") return <LoadingStatus label="Reading the latest version…" />;
  if (latest.kind === "failed") return <p role="alert" className="text-sm text-destructive">{latest.text}</p>;
  const report = latest.report;
  return (
    <section aria-label="Latest version" data-testid="report-latest" className="grid content-start gap-3 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">{`Latest: version ${report.head_version_number}`}</h2>
        <Badge>{lifecycleWords(report.lifecycle_state)}</Badge>
        <HeldBadge held={report.held} />
      </div>
      {report.lifecycle_state === "active" ? (
        <p className="text-sm text-text-secondary">{`Your next save is checked against version ${expectedVersion}.`}</p>
      ) : (
        <p role="status" className="text-sm">{`This report is now ${lifecycleWords(report.lifecycle_state)} and cannot be edited.`}</p>
      )}
      <dl className="grid gap-2 text-sm">
        <div><dt className="font-medium">Title</dt><dd>{report.title}</dd></div>
        <div><dt className="font-medium">Type</dt><dd>{report.type ?? "None"}</dd></div>
        <div><dt className="font-medium">Topics</dt><dd>{report.topics.length > 0 ? report.topics.join(", ") : "None"}</dd></div>
        <div><dt className="font-medium">Tags</dt><dd>{report.tags.length > 0 ? report.tags.join(", ") : "None"}</dd></div>
        <div><dt className="font-medium">Summary</dt><dd>{report.summary ?? "None"}</dd></div>
        <div><dt className="font-medium">Report date</dt><dd>{report.report_date ?? "None"}</dd></div>
        {report.change_reason ? <div><dt className="font-medium">Change reason</dt><dd>{report.change_reason}</dd></div> : null}
      </dl>
      {hasInlineContent(report) ? (
        <RenderedReportContent format={report.content.format} body={report.content.body} data={report.content.data} />
      ) : (
        <p className="text-sm text-text-muted">The latest content is too large to show here; open the report to read it.</p>
      )}
    </section>
  );
}
