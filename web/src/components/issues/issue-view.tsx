"use client";

/**
 * The Issue view (record lineage S3 contract section 7.6): a breadcrumb, the
 * header from one `issues.read` (title, state, native Project links and, when
 * closed, the closure outcome), the timeline and the lineage table. Each part
 * makes its own one read; nothing is joined in the browser. With the lineage
 * plane switched off every read answers `unsupported`, and the view says the
 * Issues are not available.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import type { IssuesReadResult } from "@/lib/api/decode/capabilities/issues.read";
import { fetchIssue, type ApiFailure } from "@/lib/api/work-client";
import { IssueLineageTable } from "./issue-lineage-table";
import { IssueTimeline } from "./issue-timeline";
import { ISSUE_MESSAGES, instantWords, words } from "./presentation";

type State =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly read: IssuesReadResult }
  | { readonly kind: "unavailable" }
  | { readonly kind: "unsupported" };

function Breadcrumb({ title }: { readonly title: string }) {
  return (
    <nav aria-label="Breadcrumb" className="text-sm">
      <ol className="flex flex-wrap items-center gap-1 text-muted">
        <li><Link href="/work" className="underline underline-offset-2">Work</Link></li>
        <li aria-hidden="true">›</li>
        <li><Link href="/work/issues" className="underline underline-offset-2">Issues</Link></li>
        <li aria-hidden="true">›</li>
        <li aria-current="page" className="break-words text-moss-slate">{title}</li>
      </ol>
    </nav>
  );
}

export function IssueView({ issueId }: { readonly issueId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchIssue(issueId).then(
      (read) => { if (!cancelled) setState({ kind: "ready", read }); },
      (error: unknown) => {
        if (!cancelled) setState({ kind: (error as ApiFailure).code === "unsupported" ? "unsupported" : "unavailable" });
      },
    );
    return () => { cancelled = true; };
  }, [issueId]);

  if (state.kind === "loading") {
    return <div className="mx-auto w-full max-w-5xl p-4"><p role="status" className="text-muted">Reading the Issue…</p></div>;
  }
  if (state.kind !== "ready") {
    return (
      <div className="mx-auto w-full max-w-5xl p-4">
        <Breadcrumb title="Issue" />
        <h1 className="mt-2 text-xl font-semibold">Issue</h1>
        <p className="mt-2 text-muted">{state.kind === "unsupported" ? ISSUE_MESSAGES.notAvailable : ISSUE_MESSAGES.unavailable}</p>
      </div>
    );
  }
  const { issue, restricted } = state.read;
  return (
    <div className="mx-auto w-full max-w-5xl p-4" data-testid="issue-view">
      <Breadcrumb title={issue.title} />
      <header className="mt-2">
        <h1 className="break-words text-xl font-semibold">{issue.title}</h1>
        <p className="mt-1 text-sm text-muted">State: {words(issue.state)} · Opened {instantWords(issue.opened_at)}</p>
        {issue.description ? <p className="mt-2 whitespace-pre-wrap break-words text-sm">{issue.description}</p> : null}
        {issue.closure !== null ? (
          <p className="mt-2 break-words text-sm" data-testid="issue-closure">
            Closed {instantWords(issue.closure.closed_at)}. Outcome: {issue.closure.outcome}
          </p>
        ) : null}
        {issue.project_links.length > 0 ? (
          <div className="mt-2 text-sm">
            <h2 className="font-medium">Projects</h2>
            <ul className="mt-1 grid gap-1">
              {issue.project_links.map((link) => (
                <li key={link.project_situation_id} className="break-all">
                  Project {link.project_id} <span className="text-muted">({words(link.state)})</span>
                </li>
              ))}
            </ul>
            {issue.project_links_truncated ? <p className="text-muted">Only some Project links are shown.</p> : null}
          </div>
        ) : null}
        {restricted ? <p className="mt-2 text-sm text-muted">{ISSUE_MESSAGES.restricted}</p> : null}
      </header>
      <IssueTimeline issueId={issue.issue_id} />
      <IssueLineageTable issueId={issue.issue_id} />
    </div>
  );
}
