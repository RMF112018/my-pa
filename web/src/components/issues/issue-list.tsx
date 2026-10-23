"use client";

/**
 * The Issues index (record lineage S3 contract section 7.6): one `issues.list`
 * page at a time, newest first, an optional state filter, and "More" with the
 * previous page's last Issue. Each title opens the Issue view. With the lineage
 * plane switched off the read answers `unsupported` and the index says so.
 */
import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import type { IssueListEntry } from "@/lib/api/decode/capabilities/issues.list";
import { ISSUE_STATES } from "@/lib/api/decode/capabilities/records.lineage";
import { fetchIssues, type ApiFailure } from "@/lib/api/work-client";
import { ISSUE_MESSAGES, instantWords, words } from "./presentation";

export const ISSUES_EMPTY = "No Issue is recorded.";
export const ISSUES_UNAVAILABLE = "Issues are unavailable.";

type State =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly issues: readonly IssueListEntry[]; readonly next: string | null; readonly restricted: boolean; readonly more: "idle" | "loading" | "failed" }
  | { readonly kind: "unavailable" }
  | { readonly kind: "unsupported" };

export function IssueList() {
  const filterId = useId();
  const [stateFilter, setStateFilter] = useState<string>("");
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchIssues(stateFilter === "" ? {} : { state: stateFilter }).then(
      (page) => { if (!cancelled) setState({ kind: "ready", issues: page.issues, next: page.next_cursor, restricted: page.restricted, more: "idle" }); },
      (error: unknown) => {
        if (!cancelled) setState({ kind: (error as ApiFailure).code === "unsupported" ? "unsupported" : "unavailable" });
      },
    );
    return () => { cancelled = true; };
  }, [stateFilter]);

  async function more() {
    if (state.kind !== "ready" || state.next === null) return;
    const current = state;
    setState({ ...current, more: "loading" });
    try {
      const page = await fetchIssues({ ...(stateFilter === "" ? {} : { state: stateFilter }), after: current.next! });
      setState({ kind: "ready", issues: [...current.issues, ...page.issues], next: page.next_cursor, restricted: current.restricted || page.restricted, more: "idle" });
    } catch {
      setState({ ...current, more: "failed" });
    }
  }

  let body: React.ReactNode;
  if (state.kind === "loading") body = <p role="status" className="mt-3 text-muted">Reading Issues…</p>;
  else if (state.kind === "unsupported") body = <p className="mt-3 text-muted">{ISSUE_MESSAGES.notAvailable}</p>;
  else if (state.kind === "unavailable") body = <p className="mt-3 text-muted">{ISSUES_UNAVAILABLE}</p>;
  else {
    body = (
      <>
        {state.restricted ? <p className="mt-3 text-muted">{ISSUE_MESSAGES.restricted}</p> : null}
        {state.issues.length === 0 ? <p className="mt-3 text-muted">{ISSUES_EMPTY}</p> : (
          <ul className="mt-3 grid gap-2" aria-label="Issues">
            {state.issues.map((issue) => (
              <li key={issue.issue_id} className="rounded-lg border border-moss-slate/15 p-3">
                <Link href={`/work/issues/${encodeURIComponent(issue.issue_id)}`} className="break-words font-medium underline underline-offset-2">
                  {issue.title}
                </Link>
                <p className="text-sm text-muted">State: {words(issue.state)} · Updated {instantWords(issue.updated_at)}</p>
              </li>
            ))}
          </ul>
        )}
        {state.next !== null ? (
          <Button size="sm" variant="secondary" className="mt-3" disabled={state.more === "loading"} onClick={() => void more()}>More</Button>
        ) : null}
        {state.more === "failed" ? <p className="mt-2 text-muted">{ISSUES_UNAVAILABLE}</p> : null}
      </>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl p-4" data-testid="issue-list">
      <nav aria-label="Breadcrumb" className="text-sm">
        <ol className="flex flex-wrap items-center gap-1 text-muted">
          <li><Link href="/work" className="underline underline-offset-2">Work</Link></li>
          <li aria-hidden="true">›</li>
          <li aria-current="page" className="text-moss-slate">Issues</li>
        </ol>
      </nav>
      <h1 className="mt-2 text-xl font-semibold">Issues</h1>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <label htmlFor={filterId} className="text-sm">State</label>
        <Select id={filterId} value={stateFilter} onChange={(event) => { setState({ kind: "loading" }); setStateFilter(event.target.value); }}>
          <option value="">All states</option>
          {ISSUE_STATES.map((value) => <option key={value} value={value}>{words(value)}</option>)}
        </Select>
      </div>
      {body}
    </div>
  );
}
