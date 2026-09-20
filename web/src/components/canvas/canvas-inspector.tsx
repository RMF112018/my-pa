"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { LoadingStatus } from "@/components/ui/surface-state";
import { useInspectorSelection } from "@/components/shell/inspector-selection";
import {
  WhenDiagnostics,
  useDiagnosticsEnabled,
} from "@/components/diagnostics/diagnostics-provider";
import { apiGet } from "@/lib/api/client";
import { decodeEntitiesIdentityHistory } from "@/lib/api/decode/capabilities/entities.identity_history";
import { decodeEntitiesRelationships } from "@/lib/api/decode/capabilities/entities.relationships";
import type { GraphEdge, GraphNode } from "@/lib/api/decode/capabilities/entities.graph";
import type { IdentityHistoryEntry } from "@/lib/api/decode/capabilities/_entity-read-helpers";
import { peopleEntity } from "@/lib/routes/people";

const SESSION = { hasSession: true } as const;

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-0.5" data-testid={`inspector-field-${label}`}>
      <dt className="text-xs text-text-muted">{label}</dt>
      <dd className="break-all text-sm text-text-primary">{value}</dd>
    </div>
  );
}

function absent(value: string | null | undefined): string {
  return value && value.length > 0 ? value : "none";
}

function currentnessLabel(isCurrent: boolean | null): string {
  if (isCurrent === true) return "current";
  if (isCurrent === false) return "not current";
  return "unspecified";
}

function identityHistoryPath(entityId: string, after?: string): string {
  const params = new URLSearchParams();
  if (after) params.set("after", after);
  const encoded = params.toString();
  const base = `/api/people/${encodeURIComponent(entityId)}/identity-history`;
  return encoded.length === 0 ? base : `${base}?${encoded}`;
}

type HistoryState =
  | { readonly status: "loading" }
  | { readonly status: "unavailable" }
  | {
      readonly status: "ready";
      readonly entries: readonly IdentityHistoryEntry[];
      readonly is_truncated: boolean;
      readonly next_cursor: string | null;
    };

function NodeInspector({ node }: { node: GraphNode }) {
  /*
   * WP07. This inspector's labels *are* backend field names and its values are
   * raw identifiers, so the whole `<dl>` below is diagnostics. What a person
   * needs without diagnostics — which record this is, and a link to it — is
   * kept, in human words.
   *
   * The identity-history read is also diagnostics-only, so it is not issued at
   * all while diagnostics are off rather than issued and discarded.
   */
  const diagnosticsEnabled = useDiagnosticsEnabled();
  const [history, setHistory] = useState<HistoryState>({ status: "loading" });
  const [continuing, setContinuing] = useState(false);

  useEffect(() => {
    if (!diagnosticsEnabled) return;
    let cancelled = false;
    void (async () => {
      const response = await apiGet(SESSION, identityHistoryPath(node.entity_id));
      if (cancelled) return;
      if (!response.ok || response.data === null) {
        setHistory({ status: "unavailable" });
        return;
      }
      const decoded = decodeEntitiesIdentityHistory(response.data);
      if (!decoded.ok) {
        setHistory({ status: "unavailable" });
        return;
      }
      setHistory({
        status: "ready",
        entries: decoded.value.entries,
        is_truncated: decoded.value.is_truncated,
        next_cursor: decoded.value.next_cursor,
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [node.entity_id, diagnosticsEnabled]);

  async function onContinue() {
    if (history.status !== "ready" || !history.next_cursor || continuing) return;
    setContinuing(true);
    try {
      const response = await apiGet(
        SESSION,
        identityHistoryPath(node.entity_id, history.next_cursor),
      );
      if (!response.ok || response.data === null) {
        return;
      }
      const decoded = decodeEntitiesIdentityHistory(response.data);
      if (!decoded.ok) return;
      setHistory({
        status: "ready",
        entries: [...history.entries, ...decoded.value.entries],
        is_truncated: decoded.value.is_truncated,
        next_cursor: decoded.value.next_cursor,
      });
    } finally {
      setContinuing(false);
    }
  }

  return (
    <div data-testid="inspector-node" className="mt-3 grid gap-3">
      <WhenDiagnostics>
        <dl className="grid gap-2">
          <Field label="display_label" value={node.display_label} />
          <Field label="entity_type" value={node.entity_type} />
          <Field label="status" value={node.status} />
          <Field label="superseded_by_entity_id" value={absent(node.superseded_by_entity_id)} />
          <Field label="entity_id" value={node.entity_id} />
        </dl>
      </WhenDiagnostics>
      <p className="text-sm">
        <Link
          href={peopleEntity(node.entity_id)}
          className="text-interactive underline decoration-interactive/40 underline-offset-2"
        >
          {node.display_label}
        </Link>
      </p>
      {/*
        WP07 §6.2/AC-43. The identity-history read is diagnostics-only and is not
        issued while diagnostics are off, so `status` stays "loading" forever and
        this `role="status"` live region announced a read that would never
        complete — on every node inspection, to every screen reader. The owner is
        gated, not the rows inside it, so while off there is no live region, no
        heading and no reserved gap.
      */}
      <WhenDiagnostics>
      {history.status === "loading" ? (
        <LoadingStatus label="Reading identity history…" />
      ) : (
        <div data-testid="inspector-changes" className="grid gap-2">
          <h3 className="text-sm font-medium text-text-primary">Identity history</h3>
          {history.status === "unavailable" ? (
            <p className="text-sm text-text-secondary">Identity history could not be read.</p>
          ) : (
            <>
              {history.is_truncated ? (
                <p className="text-sm text-text-secondary">This page of identity history is truncated.</p>
              ) : null}
              {history.entries.length === 0 ? (
                <p className="text-sm text-text-muted">No identity-history entries were returned.</p>
              ) : (
                <ol className="grid gap-2">
                  {history.entries.map((entry) => (
                    <li key={entry.history_id} className="grid gap-1 rounded border border-border p-2">
                      <p className="font-mono text-xs text-text-primary">{entry.history_id}</p>
                      <p className="text-sm text-text-primary">{entry.operation}</p>
                      <p className="text-xs text-text-muted">{entry.occurred_at}</p>
                    </li>
                  ))}
                </ol>
              )}
              {history.next_cursor ? (
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  data-testid="inspector-changes-continue"
                  pending={continuing}
                  onClick={() => {
                    void onContinue();
                  }}
                >
                  Continue identity history
                </Button>
              ) : null}
            </>
          )}
        </div>
      )}
      </WhenDiagnostics>
    </div>
  );
}

function EdgeInspector({
  edge,
  from,
  to,
}: {
  edge: GraphEdge;
  from?: GraphNode;
  to?: GraphNode;
}) {
  // The only consumers of this read are the `effective_from`/`effective_to`
  // fields in the gated `<dl>` below, so it is diagnostics-only work and is
  // not performed at all while diagnostics are off.
  const diagnosticsEnabled = useDiagnosticsEnabled();
  const [windowFields, setWindowFields] = useState<{
    readonly effective_from: string | null;
    readonly effective_to: string | null;
  } | null>(null);

  useEffect(() => {
    if (!diagnosticsEnabled) return;
    if (edge.edge_kind !== "relationship") return;
    let cancelled = false;
    void (async () => {
      const response = await apiGet(
        SESSION,
        `/api/people/${encodeURIComponent(edge.from_entity_id)}/relationships`,
      );
      if (cancelled) return;
      if (!response.ok || response.data === null) return;
      const decoded = decodeEntitiesRelationships(response.data);
      if (!decoded.ok) return;
      const row = decoded.value.relationships.find(
        (item) => item.relationship_id === edge.edge_id,
      );
      if (!row) return;
      setWindowFields({
        effective_from: row.effective_from,
        effective_to: row.effective_to,
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [edge.edge_id, edge.edge_kind, edge.from_entity_id, diagnosticsEnabled]);

  const stateOrStatus = edge.state ?? edge.status;

  return (
    <div data-testid="inspector-edge" className="mt-3 grid gap-3">
      <WhenDiagnostics>
      <dl className="grid gap-2">
        <Field label="type" value={edge.type} />
        <Field label="edge_kind" value={edge.edge_kind} />
        {stateOrStatus ? <Field label={edge.state ? "state" : "status"} value={stateOrStatus} /> : null}
        <Field label="is_current" value={currentnessLabel(edge.is_current)} />
        <Field label="version" value={String(edge.version)} />
        <Field label="from_entity_id" value={edge.from_entity_id} />
        <Field label="to_entity_id" value={absent(edge.to_entity_id)} />
        <Field label="scope_entity_id" value={absent(edge.scope_entity_id)} />
        {windowFields ? (
          <>
            <Field label="effective_from" value={absent(windowFields.effective_from)} />
            <Field label="effective_to" value={absent(windowFields.effective_to)} />
          </>
        ) : null}
      </dl>
      </WhenDiagnostics>
      {from || to ? (
        <p className="text-xs text-text-muted">
          {/* The relationship in human terms. An endpoint the graph did not
              name is described, never printed as its key. */}
          {from ? from.display_label : "an unnamed record"}
          {to ? ` → ${to.display_label}` : edge.to_entity_id ? " → an unnamed record" : ""}
        </p>
      ) : null}
    </div>
  );
}

export function CanvasInspector() {
  const { selection } = useInspectorSelection();
  if (selection === null) {
    return (
      <p data-testid="inspector-empty" className="mt-3 text-sm text-text-secondary">
        Select supported evidence to inspect source, freshness, provenance, and limitations.
        Nothing sensitive is persisted here.
      </p>
    );
  }
  if (selection.kind === "node") {
    return <NodeInspector key={selection.node.entity_id} node={selection.node} />;
  }
  return (
    <EdgeInspector
      key={selection.edge.edge_id}
      edge={selection.edge}
      from={selection.from}
      to={selection.to}
    />
  );
}
