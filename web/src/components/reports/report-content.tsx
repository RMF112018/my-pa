"use client";

/**
 * One version's content (WP07 contract U6/U7).
 *
 * Markdown is rendered with the SAME safe renderer the Intelligence report
 * detail uses (`markdownToRich` -> `RichContent`, both shared modules; nothing
 * under components/intelligence is imported or changed). Text is preformatted,
 * JSON pretty-printed text; a mixed version shows its body (markdown renderer)
 * and then its data. Nothing here uses dangerouslySetInnerHTML.
 *
 * A body the read omitted (`body_omitted` + `body_chunked_read`) is offered as
 * "Load full content (size)", read through `readFullContent`, which verifies
 * every chunk and the whole against the pointer's sha256 before anything is
 * rendered; a mismatch renders nothing but the refusal.
 */
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { RichContent } from "@/components/ui/rich-content";
import { markdownToRich } from "@/lib/content/markdown-to-rich";
import type { StandaloneReportReadResult } from "@/lib/api/decode/capabilities/reports.standalone";
import { contentFromDecoded, readFullContent, type ReportFormat } from "@/lib/reports/transfer-client";
import { REPORT_MESSAGES, byteWords, refusalWords } from "./presentation";

export function RenderedReportContent({
  format,
  body,
  data,
}: {
  readonly format: ReportFormat;
  readonly body?: string;
  readonly data?: unknown;
}) {
  const pre = "whitespace-pre-wrap break-words rounded-[var(--radius-md)] bg-surface-subtle p-3 font-mono text-sm";
  return (
    <div data-testid="report-content" data-format={format} className="grid gap-3">
      {format === "markdown" || format === "mixed" ? (
        body !== undefined ? <RichContent nodes={markdownToRich(body)} /> : null
      ) : null}
      {format === "text" && body !== undefined ? <pre className={pre}>{body}</pre> : null}
      {(format === "json" || format === "mixed") && data !== undefined ? (
        <pre className={pre} aria-label="Report data">{JSON.stringify(data, null, 2)}</pre>
      ) : null}
    </div>
  );
}

type FullState =
  | { readonly kind: "idle" }
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly body?: string; readonly data?: unknown }
  | { readonly kind: "failed"; readonly message: string };

/** The content block of one read version. Keyed by version by its parent. */
export function ReportContent({ report }: { readonly report: StandaloneReportReadResult }) {
  const content = report.content;
  const [full, setFull] = useState<FullState>({ kind: "idle" });

  if (content.body !== undefined || content.data !== undefined) {
    return <RenderedReportContent format={content.format} body={content.body} data={content.data} />;
  }
  const pointer = content.body_chunked_read;
  if (content.body_omitted === undefined || pointer === undefined) {
    return <p className="text-sm text-text-muted">The content of this version was not read.</p>;
  }

  async function load() {
    setFull({ kind: "loading" });
    const outcome = await readFullContent(report.report_id, report.version_number, pointer!, { includeWithdrawn: true });
    if (!outcome.ok) {
      setFull({ kind: "failed", message: refusalWords(outcome) });
      return;
    }
    const decoded = contentFromDecoded(content.format, outcome.value);
    setFull(decoded === null ? { kind: "failed", message: REPORT_MESSAGES.unverified } : { kind: "ready", ...decoded });
  }

  if (full.kind === "ready") return <RenderedReportContent format={content.format} body={full.body} data={full.data} />;
  return (
    <div className="grid gap-2" data-testid="report-content-omitted">
      <p className="text-sm text-text-secondary">This version is too large to show at once.</p>
      <div>
        <Button size="sm" variant="secondary" pending={full.kind === "loading"} disabled={full.kind === "loading"} onClick={() => void load()}>
          {`Load full content (${byteWords(pointer.byte_count)})`}
        </Button>
      </div>
      {full.kind === "failed" ? <p role="alert" className="text-sm text-destructive">{full.message}</p> : null}
    </div>
  );
}
