"use client";

/**
 * The Reports list and search (WP07 contract U7), and the Trash.
 *
 * The plane is chosen (Standalone | All, default Standalone) and sent
 * explicitly on every request; on the `all` plane, pipeline (Intelligence)
 * items are labelled "Pipeline", link to their existing Intelligence page and
 * carry no action. The lifecycle filter is Active | Archived; trashed reports
 * have their own page (`mode="trash"`: standalone, lifecycleStates=[trashed],
 * Restore per item). A search box, a type filter and a tag filter refine the
 * read; "Load more" follows the page's cursor with the same filters.
 */
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { LoadingStatus, SurfaceState } from "@/components/ui/surface-state";
import type {
  IntelligenceCatalogItem,
  StandaloneCatalogItem,
} from "@/lib/api/decode/capabilities/reports.standalone";
import { intelligenceReport } from "@/lib/routes/intelligence";
import {
  CONFLICT_MESSAGE,
  STALE_MESSAGE,
  changeReportLifecycle,
  classifyConflict,
  fetchReportCatalog,
  reportIntent,
  type CatalogQuery,
  type ReportLifecycleFilter,
  type ReportPlane,
  type ReportRefusal,
} from "@/lib/reports/client";
import {
  HeldBadge,
  NEW_REPORT_HREF,
  TRASH_HREF,
  instantWords,
  lifecycleWords,
  refusalWords,
  reportHref,
  shortId,
} from "./presentation";

export const CATALOG_PAGE_SIZE = 25;

type Item = (StandaloneCatalogItem | IntelligenceCatalogItem) & { readonly snippet?: string };

type State =
  | { readonly kind: "loading" }
  | { readonly kind: "failed"; readonly refused: ReportRefusal }
  | { readonly kind: "ready"; readonly items: readonly Item[]; readonly next: string | null; readonly more: "idle" | "loading" | "failed" };
/** A state is the answer to one request; any other request's answer reads as loading. */
type Answered = { readonly key: string; readonly state: State };

interface Filters {
  readonly plane: ReportPlane;
  readonly lifecycle: Exclude<ReportLifecycleFilter, "trashed">;
  readonly query: string;
  readonly type: string;
  readonly tag: string;
}

const INITIAL: Filters = { plane: "standalone", lifecycle: "active", query: "", type: "", tag: "" };

function queryOf(mode: "catalog" | "trash", filters: Filters, cursor?: string): CatalogQuery {
  if (mode === "trash") {
    return { plane: "standalone", lifecycleStates: ["trashed"], pageSize: CATALOG_PAGE_SIZE, ...(cursor ? { cursor } : {}) };
  }
  const tag = filters.tag.trim();
  return {
    plane: filters.plane,
    lifecycleStates: [filters.lifecycle],
    pageSize: CATALOG_PAGE_SIZE,
    ...(filters.query.trim() ? { query: filters.query.trim() } : {}),
    ...(filters.type.trim() ? { type: filters.type.trim() } : {}),
    ...(tag ? { tags: [tag] } : {}),
    ...(cursor ? { cursor } : {}),
  };
}

function StandaloneRow({
  item,
  restore,
}: {
  readonly item: StandaloneCatalogItem & { readonly snippet?: string };
  readonly restore?: (item: StandaloneCatalogItem) => void;
}) {
  return (
    <li className="grid gap-1 rounded-lg border border-border p-3" data-plane="standalone">
      <div className="flex flex-wrap items-center gap-2">
        <Link href={reportHref(item.report_id)} className="break-words font-medium underline underline-offset-2">{item.title}</Link>
        <Badge>{lifecycleWords(item.lifecycle_state)}</Badge>
        <HeldBadge held={item.held} />
      </div>
      <p className="text-sm text-text-secondary">
        {[item.type ?? "No type", item.tags.length > 0 ? `Tags: ${item.tags.join(", ")}` : null, `Version ${item.head_version_number}`, `Updated ${instantWords(item.updated_at)}`]
          .filter(Boolean)
          .join(" · ")}
      </p>
      {item.snippet ? <p className="text-sm text-text-muted">{item.snippet}</p> : null}
      {restore ? (
        <div>
          <Button size="sm" variant="secondary" onClick={() => restore(item)}>Restore</Button>
        </div>
      ) : null}
    </li>
  );
}

function PipelineRow({ item }: { readonly item: IntelligenceCatalogItem & { readonly snippet?: string } }) {
  return (
    <li className="grid gap-1 rounded-lg border border-border p-3" data-plane="intelligence">
      <div className="flex flex-wrap items-center gap-2">
        <Link href={intelligenceReport(item.report_id)} className="break-words font-medium underline underline-offset-2">{item.title}</Link>
        <Badge tone="synthetic">Pipeline</Badge>
      </div>
      <p className="text-sm text-text-secondary">
        {`${item.artifact_kind.replaceAll("_", " ")} · ${item.stage} · report date ${item.report_date}`}
      </p>
      {item.snippet ? <p className="text-sm text-text-muted">{item.snippet}</p> : null}
    </li>
  );
}

type Notice = { readonly kind: "receipt" | "conflict" | "error"; readonly text: string };

export function ReportCatalog({ mode = "catalog" }: { readonly mode?: "catalog" | "trash" }) {
  const ids = { plane: useId(), lifecycle: useId(), query: useId(), type: useId(), tag: useId() };
  const [filters, setFilters] = useState<Filters>(INITIAL);
  const [draft, setDraft] = useState({ query: "", type: "", tag: "" });
  const [reload, setReload] = useState(0);
  const requestKey = JSON.stringify([mode, filters, reload]);
  const [answered, setAnswered] = useState<Answered>({ key: "", state: { kind: "loading" } });
  const state: State = answered.key === requestKey ? answered.state : { kind: "loading" };
  const setState = (next: State) => setAnswered({ key: requestKey, state: next });
  const [notice, setNotice] = useState<Notice | null>(null);
  const restoreIntent = useRef(reportIntent("report-restore"));

  useEffect(() => {
    let cancelled = false;
    void fetchReportCatalog(queryOf(mode, filters)).then((outcome) => {
      if (cancelled) return;
      setAnswered({
        key: requestKey,
        state: outcome.ok
          ? { kind: "ready", items: outcome.value.items as readonly Item[], next: outcome.value.next_cursor, more: "idle" }
          : { kind: "failed", refused: outcome },
      });
    });
    return () => { cancelled = true; };
  }, [mode, filters, requestKey]);

  async function more() {
    if (state.kind !== "ready" || state.next === null) return;
    const current = state;
    setState({ ...current, more: "loading" });
    const outcome = await fetchReportCatalog(queryOf(mode, filters, current.next!));
    setState(outcome.ok
      ? { kind: "ready", items: [...current.items, ...(outcome.value.items as readonly Item[])], next: outcome.value.next_cursor, more: "idle" }
      : { ...current, more: "failed" });
  }

  const restore = useCallback(async (item: StandaloneCatalogItem) => {
    const expectedLifecycleRevision = item.lifecycle_revision;
    const intent = restoreIntent.current;
    const idempotencyKey = intent.keyFor({ reportId: item.report_id, expectedLifecycleRevision });
    setNotice(null);
    const outcome = await changeReportLifecycle(item.report_id, "restore", { expectedLifecycleRevision, idempotencyKey });
    intent.settle(outcome);
    if (outcome.ok) {
      setNotice({ kind: "receipt", text: `Restored "${item.title}". Receipt ${shortId(outcome.value.receipt.receipt_id)}.` });
      setReload((value) => value + 1);
      return;
    }
    const conflict = classifyConflict(outcome, { expectedLifecycleRevision });
    if (conflict.kind === "stale") setNotice({ kind: "conflict", text: STALE_MESSAGE(conflict.current.headVersionNumber) });
    else if (conflict.kind === "conflict") setNotice({ kind: "conflict", text: CONFLICT_MESSAGE });
    else setNotice({ kind: "error", text: refusalWords(outcome) });
  }, []);

  function search(event: FormEvent) {
    event.preventDefault();
    setFilters((current) => ({ ...current, ...draft }));
  }

  const trash = mode === "trash";
  let body: React.ReactNode;
  if (state.kind === "loading") body = <LoadingStatus label={trash ? "Reading Trash…" : "Reading reports…"} />;
  else if (state.kind === "failed") {
    body = (
      <SurfaceState
        kind="unavailable"
        title={trash ? "Trash unavailable" : "Reports unavailable"}
        detail={refusalWords(state.refused)}
        onRetry={() => setReload((value) => value + 1)}
      />
    );
  } else if (state.items.length === 0) {
    body = (
      <SurfaceState
        kind="empty"
        title={trash ? "Trash is empty" : "No reports match"}
        detail={trash ? "No report is in Trash." : "No report matches these filters."}
      />
    );
  } else {
    body = (
      <>
        <ul className="grid gap-2" aria-label={trash ? "Reports in Trash" : "Reports"}>
          {state.items.map((item) =>
            item.plane === "standalone" ? (
              <StandaloneRow key={item.report_id} item={item} restore={trash ? (row) => void restore(row) : undefined} />
            ) : (
              <PipelineRow key={item.report_id} item={item} />
            ),
          )}
        </ul>
        {state.next !== null ? (
          <div className="mt-3">
            <Button size="sm" variant="secondary" pending={state.more === "loading"} onClick={() => void more()}>Load more</Button>
          </div>
        ) : null}
        {state.more === "failed" ? <p role="alert" className="mt-2 text-sm text-text-muted">The next page could not be read.</p> : null}
      </>
    );
  }

  const links = (
    <div className="flex flex-wrap gap-2">
      {trash ? (
        <Link href="/reports" className="inline-flex min-h-[var(--control-height)] items-center rounded-[var(--radius-md)] border border-interactive px-3 text-sm font-medium text-interactive">All reports</Link>
      ) : (
        <Link href={TRASH_HREF} className="inline-flex min-h-[var(--control-height)] items-center rounded-[var(--radius-md)] border border-interactive px-3 text-sm font-medium text-interactive">Trash</Link>
      )}
      <Link href={NEW_REPORT_HREF} className="inline-flex min-h-[var(--control-height)] items-center rounded-[var(--radius-md)] bg-interactive px-3 text-sm font-medium text-on-interactive">New report</Link>
    </div>
  );

  return (
    <div className="mx-auto w-full max-w-5xl p-4" data-testid={trash ? "report-trash" : "report-catalog"}>
      <PageHeader
        title={trash ? "Trash" : "Reports"}
        description={trash
          ? "Reports moved to Trash. Restore one to return it to your reports."
          : "Your standalone reports. Choose All to include pipeline reports from Intelligence."}
        actions={links}
      />
      {trash ? null : (
        <form className="mb-4 grid gap-3" onSubmit={search} aria-label="Find reports">
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid gap-1">
              <label htmlFor={ids.plane} className="text-sm">Show</label>
              <Select id={ids.plane} value={filters.plane} onChange={(event) => setFilters((current) => ({ ...current, plane: event.target.value as ReportPlane }))}>
                <option value="standalone">Standalone</option>
                <option value="all">All</option>
              </Select>
            </div>
            <div className="grid gap-1">
              <label htmlFor={ids.lifecycle} className="text-sm">State</label>
              <Select id={ids.lifecycle} value={filters.lifecycle} onChange={(event) => setFilters((current) => ({ ...current, lifecycle: event.target.value as Filters["lifecycle"] }))}>
                <option value="active">Active</option>
                <option value="archived">Archived</option>
              </Select>
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid min-w-48 flex-1 gap-1">
              <label htmlFor={ids.query} className="text-sm">Search</label>
              <Input id={ids.query} type="search" value={draft.query} onChange={(event) => setDraft((current) => ({ ...current, query: event.target.value }))} />
            </div>
            <div className="grid gap-1">
              <label htmlFor={ids.type} className="text-sm">Type</label>
              <Input id={ids.type} value={draft.type} onChange={(event) => setDraft((current) => ({ ...current, type: event.target.value }))} />
            </div>
            <div className="grid gap-1">
              <label htmlFor={ids.tag} className="text-sm">Tag</label>
              <Input id={ids.tag} value={draft.tag} onChange={(event) => setDraft((current) => ({ ...current, tag: event.target.value }))} />
            </div>
            <Button type="submit" size="sm">Apply</Button>
          </div>
        </form>
      )}
      {notice ? (
        <div role={notice.kind === "receipt" ? "status" : "alert"} data-testid="report-action-feedback" className="mb-3 grid gap-2 text-sm">
          <p>{notice.text}</p>
          {notice.kind === "conflict" ? (
            <div>
              <Button size="sm" variant="secondary" onClick={() => { setNotice(null); setReload((value) => value + 1); }}>Review latest</Button>
            </div>
          ) : null}
        </div>
      ) : null}
      {body}
    </div>
  );
}
