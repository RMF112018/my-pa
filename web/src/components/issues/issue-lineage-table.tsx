"use client";

/**
 * The Issue's lineage as accessible tables (record lineage S3 contract sections
 * 7.2 and 7.6): the records reached from the Issue, each with the path that
 * reached it ("reached from X via relation"), and the links between them with
 * their relation, direction, state, basis, actor class and evidence. One
 * `records.lineage` read per page, the Issue as origin; "Show more" sends only
 * the cursor and the page size. Below 640 px each row stacks.
 *
 * Messages, never a count: hidden data, a changed access scope (with a restart),
 * a budget cut and a record that could not be shown are each said in words.
 */
import { useCallback, useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { anchorLabel } from "@/components/work/related-issues";
import type {
  AssociationView, EvidenceAnchorView, LineageNode, RecordsLineageResult,
} from "@/lib/api/decode/capabilities/records.lineage";
import { fetchIssueLineage, type ApiFailure } from "@/lib/api/work-client";
import { NoteVersionDrilldown } from "./note-version-drilldown";
import {
  FAMILY_WORDS, ISSUE_MESSAGES, RecordName, basisWords, completenessMessages, familyName, words,
} from "./presentation";

export const LINEAGE_PAGE_SIZE = 25;
export const LINEAGE_UNAVAILABLE = "The lineage is unavailable.";

/** S1/S2 relation words plus S3's "related to" (section 7.6). */
const RELATION_WORDS: Readonly<Record<AssociationView["relation_type"], string>> = {
  issue_member: "member of",
  originated_from: "originated from",
  discusses: "discusses",
  delegated_from: "delegated from",
  escalated_from: "escalated from",
  blocks: "blocks",
  created_to_resolve: "created to resolve",
  related_context: "related to",
};

/** `anchorLabel` already words an archived Capture; these are the other availabilities. */
const AVAILABILITY_WORDS: Readonly<Record<EvidenceAnchorView["availability"], string | null>> = {
  available: null,
  archived: null,
  legacy_unversioned: "version not recorded",
  restricted: "restricted by your access",
};

function nodeLabel(node: LineageNode): string {
  return node.family === "situation" && node.title !== undefined ? `Issue: ${node.title}` : `${familyName(node.family)} ${node.record_id}`;
}

/** "Reached from a Task via originated from", or the root's own words. */
export function pathWords(node: LineageNode, edges: ReadonlyMap<string, AssociationView>): string {
  if (node.reached_from === null || node.reached_via === null) return "The Issue itself";
  const from = FAMILY_WORDS[node.reached_from.family];
  if (node.reached_via.edge === "virtual") return `Reached from ${from} via note version of`;
  const edge = edges.get(node.reached_via.link_id);
  return `Reached from ${from} via ${edge === undefined ? "a link" : RELATION_WORDS[edge.relation_type]}`;
}

function anchorWords(anchor: EvidenceAnchorView): string {
  const availability = AVAILABILITY_WORDS[anchor.availability];
  return `${anchorLabel(anchor)} (${words(anchor.role)})${availability === null ? "" : `, ${availability}`}`;
}

type Accumulated = { readonly nodes: readonly LineageNode[]; readonly edges: readonly AssociationView[] };
type State =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly seen: Accumulated; readonly last: RecordsLineageResult; readonly more: "idle" | "loading" | "failed" }
  | { readonly kind: "unavailable" }
  | { readonly kind: "unsupported" };

function merge(seen: Accumulated, page: RecordsLineageResult): Accumulated {
  return { nodes: [...seen.nodes, ...page.nodes], edges: [...seen.edges, ...page.typed_edges] };
}

const CELL = "align-top py-2 pr-3 max-sm:block max-sm:py-1";
const ROW = "border-t border-moss-slate/15 max-sm:block max-sm:py-2";

function Stacked({ label, children }: { readonly label: string; readonly children: React.ReactNode }) {
  return <td className={CELL}><span className="font-medium sm:hidden">{label}: </span>{children}</td>;
}

export function IssueLineageTable({ issueId, pageSize = LINEAGE_PAGE_SIZE }: { readonly issueId: string; readonly pageSize?: number }) {
  const headingId = useId();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchIssueLineage(issueId, { pageSize }).then(
      (page) => { if (!cancelled) setState({ kind: "ready", seen: merge({ nodes: [], edges: [] }, page), last: page, more: "idle" }); },
      (error: unknown) => {
        if (!cancelled) setState({ kind: (error as ApiFailure).code === "unsupported" ? "unsupported" : "unavailable" });
      },
    );
    return () => { cancelled = true; };
  }, [issueId, pageSize, generation]);

  const restart = useCallback(() => { setState({ kind: "loading" }); setGeneration((value) => value + 1); }, []);

  async function more() {
    if (state.kind !== "ready" || state.last.next_cursor === null) return;
    const { seen, last } = state;
    setState({ ...state, more: "loading" });
    try {
      const page = await fetchIssueLineage(issueId, { pageSize, cursor: last.next_cursor! });
      // A restart answer discloses nothing and replaces what is on screen.
      const next = page.complete_state === "scope_changed_restart_required" ? { nodes: [], edges: [] } : merge(seen, page);
      setState({ kind: "ready", seen: next, last: page, more: "idle" });
    } catch {
      setState({ kind: "ready", seen, last, more: "failed" });
    }
  }

  if (state.kind === "unsupported") return null;
  let body: React.ReactNode;
  if (state.kind === "loading") {
    body = <p role="status" className="text-muted">Reading the lineage…</p>;
  } else if (state.kind === "unavailable") {
    body = <p className="text-muted">{LINEAGE_UNAVAILABLE}</p>;
  } else {
    const { seen, last } = state;
    const restartRequired = last.complete_state === "scope_changed_restart_required";
    const edgesById = new Map(seen.edges.map((edge) => [edge.link_id, edge]));
    const messages = completenessMessages(last.qualifiers, ISSUE_MESSAGES.partialLineage);
    body = (
      <>
        {messages.map((message) => (
          <p key={message.code} className="mt-2 text-muted" data-testid={`lineage-message-${message.code}`}>{message.text}</p>
        ))}
        {restartRequired ? <Button size="sm" variant="secondary" className="mt-2" onClick={restart}>Start again</Button> : null}
        {!restartRequired && seen.nodes.length > 0 ? (
          <table className="mt-3 w-full border-collapse text-left max-sm:block" data-testid="lineage-nodes">
            <caption className="text-left font-medium">Records</caption>
            <thead className="max-sm:sr-only">
              <tr><th scope="col" className={CELL}>Record</th><th scope="col" className={CELL}>Depth</th><th scope="col" className={CELL}>How it was reached</th></tr>
            </thead>
            <tbody className="max-sm:block">
              {seen.nodes.map((node) => (
                <tr key={`${node.family}:${node.record_id}`} className={ROW}>
                  <Stacked label="Record"><RecordName value={{ family: node.family, record_id: node.record_id }} label={nodeLabel(node)} /></Stacked>
                  <Stacked label="Depth">{node.depth}</Stacked>
                  <Stacked label="How it was reached">{pathWords(node, edgesById)}</Stacked>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {!restartRequired && seen.edges.length > 0 ? (
          <table className="mt-4 w-full border-collapse text-left max-sm:block" data-testid="lineage-links">
            <caption className="text-left font-medium">Links</caption>
            <thead className="max-sm:sr-only">
              <tr>
                <th scope="col" className={CELL}>From</th><th scope="col" className={CELL}>Relation</th><th scope="col" className={CELL}>To</th>
                <th scope="col" className={CELL}>State</th><th scope="col" className={CELL}>Basis</th><th scope="col" className={CELL}>Recorded by</th>
                <th scope="col" className={CELL}>Evidence</th>
              </tr>
            </thead>
            <tbody className="max-sm:block">
              {seen.edges.map((edge) => (
                <tr key={edge.link_id} className={ROW} data-testid={`lineage-link-${edge.link_id}`}>
                  <Stacked label="From"><RecordName value={edge.from} /></Stacked>
                  <Stacked label="Relation">{RELATION_WORDS[edge.relation_type]}{edge.member_role ? ` (${words(edge.member_role)})` : ""}</Stacked>
                  <Stacked label="To"><RecordName value={edge.to} /></Stacked>
                  <Stacked label="State">{words(edge.lifecycle_state)}</Stacked>
                  <Stacked label="Basis">{basisWords(edge)}</Stacked>
                  <Stacked label="Recorded by">{words(edge.authority_class)}</Stacked>
                  <Stacked label="Evidence">
                    {edge.evidence.length === 0 ? "None" : (
                      <ul className="grid gap-1">
                        {edge.evidence.map((anchor) => (
                          <li key={anchor.anchor_id}>
                            <span>{anchorWords(anchor)}</span>
                            <NoteVersionDrilldown anchor={anchor} />
                          </li>
                        ))}
                      </ul>
                    )}
                  </Stacked>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {last.next_cursor !== null && !restartRequired ? (
          <Button size="sm" variant="secondary" className="mt-3" disabled={state.more === "loading"} onClick={() => void more()}>
            Show more
          </Button>
        ) : null}
        {state.more === "loading" ? <p role="status" className="mt-2 text-muted">Reading more of the lineage…</p> : null}
        {state.more === "failed" ? <p className="mt-2 text-muted">{LINEAGE_UNAVAILABLE}</p> : null}
      </>
    );
  }
  return (
    <section aria-labelledby={headingId} data-testid="issue-lineage" className="mt-6 rounded-xl border border-moss-slate/15 bg-surface p-4 text-sm">
      <h2 id={headingId} className="font-semibold">Lineage</h2>
      {body}
    </section>
  );
}
