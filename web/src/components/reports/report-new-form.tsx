"use client";

/**
 * `/reports/new` (WP07 contract U6/U7): publish one standalone report.
 *
 * The inline request is built first; when its JSON UTF-8 length is above
 * 512 KiB the content goes through a transfer (begin -> append* -> finalize)
 * and the publish carries `{transfer: {sessionId, contentToken}}` instead. While
 * the publish answer is ambiguous the form's `transferBinding` keeps that
 * transfer in memory, so resubmitting the unchanged draft reuses it with the
 * same key (the server replays the receipt) instead of minting a second
 * session that would conflict; it is aborted on a definitive refusal, a changed
 * draft or leaving the page (best effort). One idempotency key per
 * intent (`reportIntent`): kept while answers are ambiguous, new after any
 * definitive answer or a changed draft. A second submit while one is in
 * flight is ignored. On success the shell's feedback says the version and
 * receipt, and the browser goes to the report.
 */
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { PageHeader } from "@/components/shell/page-header";
import { Button } from "@/components/ui/button";
import { useMutationFeedback } from "@/components/ui/mutation-feedback";
import { mutationKey } from "@/lib/api/work-client";
import { publishReport, reportIntent, type PublishRequest, type ReportOutcome } from "@/lib/reports/client";
import { needsTransfer, transferBinding } from "@/lib/reports/transfer-client";
import type { ReportsPublishResult } from "@/lib/api/decode/capabilities/reports.publish";
import { refusalWords, reportHref, shortId } from "./presentation";
import {
  EMPTY_DRAFT,
  FORM_MESSAGES,
  FormBreadcrumb,
  ReportFieldsEditor,
  contentOf,
  hasErrors,
  publishFields,
  stagedBytesOf,
  validateDraft,
  type DraftErrors,
  type ReportDraft,
} from "./report-form";

type Phase = "idle" | "sending" | "uploading" | "done";

export function ReportNewForm() {
  const router = useRouter();
  const feedback = useMutationFeedback();
  const intent = useRef(reportIntent("report-publish"));
  const transfer = useRef(transferBinding());
  const inFlight = useRef(false);
  const [draft, setDraft] = useState<ReportDraft>(EMPTY_DRAFT);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [phase, setPhase] = useState<Phase>("idle");
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const binding = transfer.current;
    return () => { void binding.release(); };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current) return;
    const found = validateDraft(draft, { content: true });
    setErrors(found);
    const content = contentOf(draft);
    if (hasErrors(found) || content === null) return;
    inFlight.current = true;
    setFailure(null);
    const payload = { ...publishFields(draft), content };
    const request: PublishRequest = { ...payload, idempotencyKey: intent.current.keyFor(payload) };
    let outcome: ReportOutcome<ReportsPublishResult>;
    if (needsTransfer(request)) {
      setPhase("uploading");
      outcome = await transfer.current.submit(
        JSON.stringify(payload),
        // Each fresh upload is its own session; the publish key is the intent's.
        { format: content.format, staged: stagedBytesOf(content), idempotencyKey: mutationKey("report-transfer") },
        (staged) => publishReport({ ...request, content: staged }),
      );
    } else {
      setPhase("sending");
      await transfer.current.release();
      outcome = await publishReport(request);
    }
    intent.current.settle(outcome);
    inFlight.current = false;
    if (outcome.ok) {
      const result = outcome.value;
      setPhase("done");
      feedback.publish({
        eventId: `report:publish:${result.receipt_id}`,
        kind: "success",
        message: `Report published: version ${result.version_number}. Receipt ${shortId(result.receipt_id)}${result.replayed ? " (replayed)" : ""}.`,
      });
      router.push(reportHref(result.report_id));
      return;
    }
    setPhase("idle");
    setFailure(refusalWords(outcome));
  }

  const busy = phase !== "idle";
  return (
    <div className="mx-auto w-full max-w-3xl p-4">
      <FormBreadcrumb trail={[{ label: "Reports", href: "/reports" }, { label: "New report" }]} />
      <PageHeader title="New report" eyebrow="Reports" />
      <form noValidate aria-label="New report" className="grid gap-4" onSubmit={(event) => void submit(event)}>
        <ReportFieldsEditor draft={draft} onChange={setDraft} errors={errors} contentEditable disabled={busy} />
        {phase === "uploading" || phase === "sending" ? (
          <p role="status" className="text-sm text-text-secondary">
            {phase === "uploading" ? FORM_MESSAGES.uploading : FORM_MESSAGES.sending}
          </p>
        ) : null}
        {failure ? <p role="alert" className="text-sm text-destructive">{failure}</p> : null}
        <div className="flex justify-end gap-2">
          <Button type="submit" pending={busy}>Publish</Button>
        </div>
      </form>
    </div>
  );
}
