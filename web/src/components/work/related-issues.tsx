"use client";

/**
 * The related-Issue panel of one Task, Commitment or Constraint view (record
 * lineage S1 contract section 7.4, plan WP-06A S1 card; the S2 relations and the
 * `closed` Issue state are worded per S2 contract section 7.4).
 *
 * Read-only and server-batched: everything it renders comes from one
 * `records.lineage` answer for this record (one hop, optionally under a chosen
 * Issue) and, only when the user opens an evidence anchor, one note-version
 * read. It never reads an Issue, an edge or a record on its own, never joins
 * records here, and never states a count of anything it was not given.
 *
 * With the lineage plane switched off the capability answers `unsupported`, and
 * the panel then renders nothing at all.
 */
import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import type {
  AssociationView,
  EvidenceAnchorView,
  RecordsLineageResult,
} from "@/lib/api/decode/capabilities/records.lineage";
import {
  fetchNoteVersion,
  fetchRelatedIssues,
  type ApiFailure,
  type RelatedIssuesFamily,
} from "@/lib/api/work-client";

export const RELATED_ISSUES_EMPTY = "No related Issue is recorded for this record.";
export const RELATED_ISSUES_PARTIAL = "Some related records could not be shown.";
export const RELATED_ISSUES_TRUNCATED = "Only part of this record's lineage is shown.";
export const RELATED_ISSUES_UNAVAILABLE = "Related Issues are unavailable.";

type RecordRef = AssociationView["from"];

type PanelState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly lineage: RecordsLineageResult; readonly forIssueId: string | undefined }
  | { readonly kind: "unavailable" }
  | { readonly kind: "unsupported" };

function words(value: string): string {
  return value.replaceAll("_", " ");
}

const FAMILY_WORDS: Readonly<Record<RecordRef["family"], string>> = {
  situation: "an Issue",
  meeting: "a Meeting",
  meeting_note_version: "a Meeting note version",
  task: "a Task",
  commitment: "a Commitment",
  constraint: "a Constraint",
  capture_version: "a Capture version",
};

function sameRef(left: RecordRef, right: RecordRef): boolean {
  return left.family === right.family && left.record_id === right.record_id;
}

/** The relation in words, read from this record's side of the edge. */
function relationWords(edge: AssociationView, root: RecordRef): string {
  if (edge.kind === "issue_membership") {
    return edge.member_role === null ? "Member of this Issue" : `Member of this Issue as ${words(edge.member_role)}`;
  }
  const outgoing = sameRef(edge.from, root);
  const other = outgoing ? edge.to : edge.from;
  const family = FAMILY_WORDS[other.family];
  switch (edge.relation_type) {
    case "originated_from":
      return outgoing ? `Originated from ${family}` : `Origin of ${family}`;
    // S2 (contract section 7.4): the direction is read from which endpoint this record is.
    case "delegated_from":
      return outgoing ? `Delegated from ${family}` : `Delegated to ${family}`;
    case "escalated_from":
      return outgoing ? `Escalated from ${family}` : `Escalated to ${family}`;
    case "blocks":
      return outgoing ? `Blocks ${family}` : `Blocked by ${family}`;
    case "created_to_resolve":
      return outgoing ? `Created to resolve ${family}` : `${family.charAt(0).toUpperCase()}${family.slice(1)} was created to resolve it`;
    default:
      return outgoing ? `Discusses ${family}` : `Discussed in ${family}`;
  }
}

/** "Meeting note version n, characters a–b", "Capture version n", or the legacy wording. */
export function anchorLabel(anchor: EvidenceAnchorView): string {
  const passage = anchor.passage_start_cp !== null && anchor.passage_end_cp !== null
    ? `, characters ${anchor.passage_start_cp}–${anchor.passage_end_cp}` : "";
  const label = anchor.family === "meeting_note_version"
    ? `Meeting note version ${anchor.source_version_no ?? "not recorded"}${passage}`
    : anchor.family === "capture_version"
      ? `Capture version ${anchor.source_version_no ?? "not recorded"}`
      : "Capture, version not recorded";
  return anchor.availability === "archived" ? `${label}, Capture archived` : label;
}

function isUnsupported(error: unknown): boolean {
  return (error as ApiFailure | undefined)?.code === "unsupported";
}

type NoteState =
  | { readonly kind: "closed" }
  | { readonly kind: "loading" }
  | { readonly kind: "open"; readonly body: string }
  | { readonly kind: "failed" };

function NoteAnchor({ anchor }: { readonly anchor: EvidenceAnchorView }) {
  const regionId = useId();
  const [note, setNote] = useState<NoteState>({ kind: "closed" });
  const [expanded, setExpanded] = useState(false);
  const versionId = anchor.version_id;

  async function toggle() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (note.kind === "open" || versionId === null) return;
    setNote({ kind: "loading" });
    try {
      const read = await fetchNoteVersion(anchor.root_id, versionId);
      const body = read.note.body_markdown;
      setNote(body === undefined ? { kind: "failed" } : { kind: "open", body });
    } catch {
      setNote({ kind: "failed" });
    }
  }

  const passage = note.kind === "open" && anchor.passage_start_cp !== null && anchor.passage_end_cp !== null
    // Offsets count Unicode code points, as the server does.
    ? Array.from(note.body).slice(anchor.passage_start_cp, anchor.passage_end_cp).join("")
    : null;

  return (
    <>
      <Button
        size="sm"
        variant="secondary"
        className="mt-1"
        aria-expanded={expanded}
        aria-controls={regionId}
        onClick={() => void toggle()}
      >
        {expanded ? "Hide note version" : "Open note version"}
      </Button>
      <div id={regionId} hidden={!expanded} className="mt-2">
        {!expanded ? null : note.kind === "loading" ? (
          <p role="status" className="text-muted">Reading the note version…</p>
        ) : note.kind === "failed" ? (
          <p className="text-muted">The note version could not be read.</p>
        ) : note.kind === "open" ? (
          <>
            {passage !== null ? (
              <figure className="mb-2">
                <figcaption className="text-xs text-muted">Cited passage</figcaption>
                <blockquote className="mt-1 whitespace-pre-wrap break-words border-l-2 border-moss-slate/30 pl-2">{passage}</blockquote>
              </figure>
            ) : null}
            <p className="text-xs text-muted">Note version text</p>
            <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md border border-moss-slate/15 p-2 font-sans text-sm">{note.body}</pre>
          </>
        ) : null}
      </div>
    </>
  );
}

function Edge({ edge, root }: { readonly edge: AssociationView; readonly root: RecordRef }) {
  return (
    <li className="rounded-lg border border-moss-slate/15 p-3" data-testid={`related-issue-edge-${edge.link_id}`}>
      <p className="font-medium text-moss-slate">{relationWords(edge, root)}</p>
      <p className="mt-1 text-muted">
        State: {words(edge.lifecycle_state)} · Basis: {words(edge.acceptance_basis)} · Recorded by: {words(edge.authority_class)}
      </p>
      {edge.evidence.length > 0 ? (
        <ul className="mt-2 grid gap-2" aria-label="Evidence">
          {edge.evidence.map((anchor) => (
            <li key={anchor.anchor_id}>
              <span>{anchorLabel(anchor)}</span>
              <span className="text-muted"> ({words(anchor.role)})</span>
              {anchor.family === "meeting_note_version" && anchor.version_id !== null ? <NoteAnchor anchor={anchor} /> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export interface RelatedIssuesPanelProps {
  readonly family: RelatedIssuesFamily;
  readonly recordId: string;
  /** The heading level that fits the host view's outline. */
  readonly headingLevel?: 2 | 3;
}

export function RelatedIssuesPanel({ family, recordId, headingLevel = 2 }: RelatedIssuesPanelProps) {
  const headingId = useId();
  const choiceName = useId();
  const [chosenIssueId, setChosenIssueId] = useState<string | undefined>(undefined);
  const [state, setState] = useState<PanelState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchRelatedIssues(family, recordId, chosenIssueId).then(
      (lineage) => { if (!cancelled) setState({ kind: "ready", lineage, forIssueId: chosenIssueId }); },
      (error: unknown) => { if (!cancelled) setState({ kind: isUnsupported(error) ? "unsupported" : "unavailable" }); },
    );
    return () => { cancelled = true; };
  }, [family, recordId, chosenIssueId]);

  if (state.kind === "unsupported") return null;
  const Heading = headingLevel === 3 ? "h3" : "h2";

  // The answer on screen stays until the re-query lands, so the choice the user
  // just made keeps its focus and its checked state.
  function choose(issueId: string) {
    if (issueId !== chosenIssueId) setChosenIssueId(issueId);
  }

  let body: React.ReactNode;
  if (state.kind === "loading") {
    body = <p role="status" className="text-muted">Reading related Issues…</p>;
  } else if (state.kind === "unavailable") {
    body = <p className="text-muted">{RELATED_ISSUES_UNAVAILABLE}</p>;
  } else {
    const { lineage } = state;
    const pending = state.forIssueId !== chosenIssueId;
    const candidates = lineage.issues_matching_root;
    const selectedId = lineage.complete_state === "unresolved_ambiguity" ? null : lineage.selected_issue_id;
    const issueNode = selectedId === null
      ? undefined
      : lineage.nodes.find((node) => node.family === "situation" && node.record_id === selectedId);
    const match = selectedId === null ? undefined : candidates.find((candidate) => candidate.issue_id === selectedId);
    const issueTitle = issueNode?.title ?? match?.title;
    const issueState = issueNode?.state ?? match?.state;
    const edges = lineage.typed_edges.filter((edge) => sameRef(edge.from, lineage.root) || sameRef(edge.to, lineage.root));
    body = (
      <>
        {candidates.length > 1 ? (
          <fieldset className="mt-2">
            <legend className="text-sm">
              {selectedId === null
                ? "This record belongs to several Issues. Choose one to see its lineage."
                : "This record belongs to several Issues."}
            </legend>
            <div className="mt-1 grid gap-1">
              {candidates.map((candidate) => (
                <label key={candidate.issue_id} className="flex min-h-11 items-center gap-2">
                  <input
                    type="radio"
                    name={choiceName}
                    value={candidate.issue_id}
                    checked={candidate.issue_id === (chosenIssueId ?? selectedId)}
                    onChange={() => choose(candidate.issue_id)}
                  />
                  <span className="break-words">{candidate.title} <span className="text-muted">({words(candidate.state)})</span></span>
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}
        {pending ? <p role="status" className="mt-2 text-muted">Reading related Issues…</p> : null}
        {selectedId === null && candidates.length === 0 ? <p className="text-muted">{RELATED_ISSUES_EMPTY}</p> : null}
        {selectedId !== null && !pending ? (
          <div className="mt-2" data-testid="related-issue-selected">
            <p className="break-words font-medium text-moss-slate">
              Issue: {issueTitle ?? "Title not shown"}{issueState ? <span className="font-normal text-muted"> · State: {words(issueState)}</span> : null}
            </p>
            {edges.length > 0 ? (
              <ul className="mt-2 grid gap-2">
                {edges.map((edge) => <Edge key={edge.link_id} edge={edge} root={lineage.root} />)}
              </ul>
            ) : null}
          </div>
        ) : null}
        {lineage.complete_state === "partial_native_history" ? <p className="mt-2 text-muted">{RELATED_ISSUES_PARTIAL}</p> : null}
        {lineage.complete_state === "truncated_budget" ? <p className="mt-2 text-muted">{RELATED_ISSUES_TRUNCATED}</p> : null}
      </>
    );
  }

  return (
    <section aria-labelledby={headingId} data-testid="related-issues" className="mt-6 rounded-xl border border-moss-slate/15 bg-surface p-4 text-sm">
      <Heading id={headingId} className="font-semibold">Related Issues</Heading>
      {body}
    </section>
  );
}
