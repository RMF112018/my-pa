"use client";

/**
 * The minimal Meeting view (record lineage S3 contract section 7.6, D-18): its
 * header from the existing `meetings.read` route and the S1 related-Issue panel
 * for the Meeting. A Meeting in several Issues asks which one before it shows
 * any lineage (the panel's radio group). Read-only.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { RelatedIssuesPanel } from "@/components/work/related-issues";
import { instantWords, words } from "@/components/issues/presentation";
import type { MeetingsReadResult } from "@/lib/api/decode/capabilities/meetings.read";
import { fetchMeeting } from "@/lib/api/work-client";

export const MEETING_UNAVAILABLE = "This Meeting is unavailable.";

type State =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly meeting: MeetingsReadResult["meeting"] }
  | { readonly kind: "unavailable" };

export function MeetingView({ meetingId }: { readonly meetingId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchMeeting(meetingId).then(
      ({ meeting }) => { if (!cancelled) setState({ kind: "ready", meeting }); },
      () => { if (!cancelled) setState({ kind: "unavailable" }); },
    );
    return () => { cancelled = true; };
  }, [meetingId]);

  const title = state.kind === "ready" ? state.meeting.title : "Meeting";
  return (
    <div className="mx-auto w-full max-w-5xl p-4" data-testid="meeting-view">
      <nav aria-label="Breadcrumb" className="text-sm">
        <ol className="flex flex-wrap items-center gap-1 text-muted">
          <li><Link href="/work" className="underline underline-offset-2">Work</Link></li>
          <li aria-hidden="true">›</li>
          <li aria-current="page" className="break-words text-moss-slate">{title}</li>
        </ol>
      </nav>
      <h1 className="mt-2 break-words text-xl font-semibold">{title}</h1>
      {state.kind === "loading" ? <p role="status" className="mt-2 text-muted">Reading the Meeting…</p> : null}
      {state.kind === "unavailable" ? <p className="mt-2 text-muted">{MEETING_UNAVAILABLE}</p> : null}
      {state.kind === "ready" ? (
        <p className="mt-1 text-sm text-muted">
          {words(state.meeting.status)} · Starts {instantWords(state.meeting.start_at)}
        </p>
      ) : null}
      <RelatedIssuesPanel family="meeting" recordId={meetingId} />
    </div>
  );
}
