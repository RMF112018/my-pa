"use client";

/**
 * The Issue timeline (record lineage S3 contract sections 7.3 and 7.6).
 *
 * Entries are shown in server order, one `issues.timeline` page at a time; "Show
 * more" asks for the next page with the previous page's cursor and the same
 * page size only. A native entry never shows a field value: it says the values
 * were not recorded, except a Constraint event carrying its recorded
 * ball-in-court. Messages replace counts: nothing here states how much was
 * withheld or left out.
 */
import { useCallback, useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import type { IssuesTimelineResult, TimelineEntry } from "@/lib/api/decode/capabilities/issues.timeline";
import type { RecordRefView } from "@/lib/api/decode/capabilities/records.lineage";
import { fetchIssueTimeline, type ApiFailure } from "@/lib/api/work-client";
import {
  FAMILY_WORDS, ISSUE_MESSAGES, RecordName, completenessMessages, instantWords, words,
} from "./presentation";

export const TIMELINE_PAGE_SIZE = 25;
export const TIMELINE_UNAVAILABLE = "The timeline is unavailable.";
export const TIMELINE_EMPTY = "Nothing is recorded for this Issue yet.";

const LINK_ACTIONS: Readonly<Record<string, string>> = {
  assert: "recorded",
  end: "ended",
  correct_evidence: "evidence corrected",
  contest: "contested",
  reinstate: "reinstated",
};
const PROJECT_ACTIONS: Readonly<Record<string, string>> = {
  assert: "Linked to a Project",
  end: "Project link ended",
  reinstate: "Project link reinstated",
};
const NATIVE_FAMILY: Readonly<Record<string, string>> = {
  task: "Task", commitment: "Commitment", constraint: "Constraint", meeting: "Meeting", capture: "Capture",
};

function capitalized(value: string): string {
  return `${value.charAt(0).toUpperCase()}${value.slice(1)}`;
}

/** "A Task originated from a Meeting note version", "a Task is related to a Meeting", … */
export function relationSentence(relation: string, from: RecordRefView, to: RecordRefView): string {
  const left = FAMILY_WORDS[from.family];
  const right = FAMILY_WORDS[to.family];
  const verb: Readonly<Record<string, string>> = {
    issue_member: "has as a member",
    originated_from: "originated from",
    discusses: "discusses",
    delegated_from: "was delegated from",
    escalated_from: "was escalated from",
    blocks: "blocks",
    created_to_resolve: "was created to resolve",
    related_context: "is related to",
  };
  return capitalized(`${left} ${verb[relation] ?? words(relation)} ${right}`);
}

function holderWords(holder: TimelineEntry["from_holder"]): string {
  if (holder === null) return "someone";
  return holder.kind === "principal" ? "you" : `Entity ${holder.entity_id}`;
}

/** One entry's plain-language action. */
export function entryAction(entry: TimelineEntry): string {
  switch (entry.kind) {
    case "issue_revision":
      return `Issue ${words(entry.action)}`;
    case "project_link":
      return PROJECT_ACTIONS[entry.action] ?? `Project link ${words(entry.action)}`;
    case "membership":
      return `Member ${LINK_ACTIONS[entry.action] ?? words(entry.action)}: ${FAMILY_WORDS[entry.to!.family]}${entry.member_role ? ` as ${words(entry.member_role)}` : ""}`;
    case "association":
      return `${relationSentence(entry.relation_type!, entry.from!, entry.to!)}: ${LINK_ACTIONS[entry.action] ?? words(entry.action)}`;
    case "handoff":
      return `Responsibility handed from ${holderWords(entry.from_holder)} to ${holderWords(entry.to_holder)}${entry.voided ? " (voided)" : ""}`;
    case "handoff_correction":
      return entry.correction_action === "void"
        ? "Handoff voided"
        : `Handoff retimed to ${entry.corrected_effective_at ? instantWords(entry.corrected_effective_at) : "another time"}`;
    case "native_event": {
      const family = NATIVE_FAMILY[entry.native!.record_family] ?? "Record";
      return `${family} ${words(entry.native!.event_kind)}`;
    }
  }
}

function EntryDetail({ entry }: { readonly entry: TimelineEntry }) {
  if (entry.kind === "issue_revision") {
    return (
      <p className="text-muted break-words">
        Title: {entry.title} · State: {words(entry.state ?? "")}
        {entry.outcome ? <> · Outcome: {entry.outcome}</> : null}
      </p>
    );
  }
  if (entry.kind === "native_event") {
    const fields = entry.recorded_fields;
    if (fields === null) {
      return (
        <p className="text-muted">
          {ISSUE_MESSAGES.partialFields}
          {entry.native!.changed_fields.length > 0 ? ` (changed: ${entry.native!.changed_fields.map(words).join(", ")})` : null}
        </p>
      );
    }
    const parties = fields.ball_in_court.map((party) => party.display_label);
    return (
      <p className="text-muted break-words">
        Recorded state: {words(fields.lifecycle_state)} · Ball in court: {parties.length > 0 ? parties.join(", ") : "nobody recorded"}
      </p>
    );
  }
  return null;
}

type State =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly entries: readonly TimelineEntry[]; readonly last: IssuesTimelineResult; readonly more: "idle" | "loading" | "failed" }
  | { readonly kind: "unavailable" }
  | { readonly kind: "unsupported" };

export function IssueTimeline({ issueId, pageSize = TIMELINE_PAGE_SIZE }: { readonly issueId: string; readonly pageSize?: number }) {
  const headingId = useId();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchIssueTimeline(issueId, { pageSize }).then(
      (page) => { if (!cancelled) setState({ kind: "ready", entries: page.entries, last: page, more: "idle" }); },
      (error: unknown) => {
        if (!cancelled) setState({ kind: (error as ApiFailure).code === "unsupported" ? "unsupported" : "unavailable" });
      },
    );
    return () => { cancelled = true; };
  }, [issueId, pageSize, generation]);

  const restart = useCallback(() => { setState({ kind: "loading" }); setGeneration((value) => value + 1); }, []);

  async function more() {
    if (state.kind !== "ready" || state.last.next_cursor === null) return;
    const { entries, last } = state;
    setState({ ...state, more: "loading" });
    try {
      const page = await fetchIssueTimeline(issueId, { pageSize, cursor: last.next_cursor! });
      setState({ kind: "ready", entries: [...entries, ...page.entries], last: page, more: "idle" });
    } catch {
      setState({ kind: "ready", entries, last, more: "failed" });
    }
  }

  if (state.kind === "unsupported") return null;
  let body: React.ReactNode;
  if (state.kind === "loading") {
    body = <p role="status" className="text-muted">Reading the timeline…</p>;
  } else if (state.kind === "unavailable") {
    body = <p className="text-muted">{TIMELINE_UNAVAILABLE}</p>;
  } else {
    const { entries, last } = state;
    const restartRequired = last.complete_state === "scope_changed_restart_required";
    const messages = completenessMessages(last.qualifiers, ISSUE_MESSAGES.partialTimeline);
    body = (
      <>
        {messages.map((message) => (
          <p key={message.code} className="mt-2 text-muted" data-testid={`timeline-message-${message.code}`}>{message.text}</p>
        ))}
        {restartRequired ? (
          <Button size="sm" variant="secondary" className="mt-2" onClick={restart}>Start again</Button>
        ) : null}
        {entries.length === 0 && !restartRequired ? <p className="mt-2 text-muted">{TIMELINE_EMPTY}</p> : null}
        {entries.length > 0 ? (
          <ol className="mt-2 grid gap-2" aria-label="Timeline entries">
            {entries.map((entry) => (
              <li key={entry.entry_id} className="rounded-lg border border-moss-slate/15 p-3" data-testid="timeline-entry">
                <p className="text-xs text-muted"><time dateTime={entry.at}>{instantWords(entry.at)}</time></p>
                <p className="font-medium text-moss-slate break-words">{entryAction(entry)}</p>
                {entry.subject !== null && entry.kind !== "issue_revision" ? (
                  <p className="text-sm">About: <RecordName value={entry.subject} /></p>
                ) : null}
                <EntryDetail entry={entry} />
              </li>
            ))}
          </ol>
        ) : null}
        {last.next_cursor !== null && !restartRequired ? (
          <Button size="sm" variant="secondary" className="mt-2" disabled={state.more === "loading"} onClick={() => void more()}>
            Show more
          </Button>
        ) : null}
        {state.more === "loading" ? <p role="status" className="mt-2 text-muted">Reading more of the timeline…</p> : null}
        {state.more === "failed" ? <p className="mt-2 text-muted">{TIMELINE_UNAVAILABLE}</p> : null}
      </>
    );
  }
  return (
    <section aria-labelledby={headingId} data-testid="issue-timeline" className="mt-6 rounded-xl border border-moss-slate/15 bg-surface p-4 text-sm">
      <h2 id={headingId} className="font-semibold">Timeline</h2>
      {body}
    </section>
  );
}
