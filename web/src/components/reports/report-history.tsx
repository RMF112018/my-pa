"use client";

/**
 * The history of one standalone report (WP07 contract U7): its versions and
 * its lifecycle events, each a paginated `reports.history` read (`after` the
 * page's cursor). A version can be opened exactly by its number.
 */
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import type {
  ReportHistoryLifecycleItem,
  ReportHistoryVersionItem,
} from "@/lib/api/decode/capabilities/reports.history";
import { fetchReportHistory } from "@/lib/reports/client";
import { REPORT_MESSAGES, instantWords, lifecycleWords, refusalWords, shortDigest } from "./presentation";
import { ACTION_LABELS } from "./report-lifecycle-actions";

export const HISTORY_PAGE_SIZE = 20;

type Page<T> =
  | { readonly kind: "loading" }
  | { readonly kind: "failed"; readonly message: string }
  | { readonly kind: "ready"; readonly items: readonly T[]; readonly next: string | null; readonly more: "idle" | "loading" | "failed" };

function useHistoryPages<T>(reportId: string, entries: "versions" | "lifecycle", refreshKey: number) {
  const requestKey = `${reportId}:${entries}:${refreshKey}`;
  const [answered, setAnswered] = useState<{ readonly key: string; readonly page: Page<T> }>({ key: "", page: { kind: "loading" } });
  const page: Page<T> = answered.key === requestKey ? answered.page : { kind: "loading" };
  const setPage = useCallback((next: Page<T>) => setAnswered({ key: requestKey, page: next }), [requestKey]);
  useEffect(() => {
    let cancelled = false;
    void fetchReportHistory(reportId, { entries, pageSize: HISTORY_PAGE_SIZE, includeWithdrawn: true }).then((outcome) => {
      if (cancelled) return;
      if (!outcome.ok || outcome.value.entries !== entries) {
        setPage({ kind: "failed", message: outcome.ok ? REPORT_MESSAGES.unavailable : refusalWords(outcome) });
        return;
      }
      setPage({ kind: "ready", items: outcome.value.items as readonly T[], next: outcome.value.next_cursor, more: "idle" });
    });
    return () => { cancelled = true; };
  }, [reportId, entries, setPage]);

  async function more() {
    if (page.kind !== "ready" || page.next === null) return;
    const current = page;
    setPage({ ...current, more: "loading" });
    const outcome = await fetchReportHistory(reportId, { entries, pageSize: HISTORY_PAGE_SIZE, after: current.next!, includeWithdrawn: true });
    if (!outcome.ok || outcome.value.entries !== entries) {
      setPage({ ...current, more: "failed" });
      return;
    }
    setPage({ kind: "ready", items: [...current.items, ...(outcome.value.items as readonly T[])], next: outcome.value.next_cursor, more: "idle" });
  }

  return { page, more };
}

function PageFooter<T>({ page, more, label }: { readonly page: Page<T>; readonly more: () => void; readonly label: string }) {
  if (page.kind !== "ready") return null;
  return (
    <>
      {page.next !== null ? (
        <div>
          <Button size="sm" variant="secondary" pending={page.more === "loading"} onClick={more}>{`More ${label}`}</Button>
        </div>
      ) : null}
      {page.more === "failed" ? <p role="alert" className="text-sm text-text-muted">The next page could not be read.</p> : null}
    </>
  );
}

const CHANGE_WORDS: Record<string, string> = { initial: "First version", content: "Content changed", metadata: "Details changed" };

export function ReportHistory({
  reportId,
  refreshKey,
  selectedVersion,
  onSelectVersion,
}: {
  readonly reportId: string;
  readonly refreshKey: number;
  readonly selectedVersion: number;
  readonly onSelectVersion: (versionNumber: number) => void;
}) {
  const versions = useHistoryPages<ReportHistoryVersionItem>(reportId, "versions", refreshKey);
  const lifecycle = useHistoryPages<ReportHistoryLifecycleItem>(reportId, "lifecycle", refreshKey);

  return (
    <div className="grid gap-6">
      <section aria-label="Versions" className="grid gap-2">
        <h2 className="text-base font-semibold">Versions</h2>
        {versions.page.kind === "loading" ? <p role="status" className="text-sm text-text-muted">Reading versions…</p> : null}
        {versions.page.kind === "failed" ? <p role="alert" className="text-sm text-text-muted">{versions.page.message}</p> : null}
        {versions.page.kind === "ready" ? (
          <ol className="grid gap-2" aria-label="Version list">
            {versions.page.items.map((item) => (
              <li key={item.version_id} className="rounded-lg border border-border p-3 text-sm">
                <p className="font-medium">
                  {`Version ${item.version_number}`} · {CHANGE_WORDS[item.change_kind] ?? item.change_kind}
                </p>
                <p className="text-text-secondary">
                  {item.title} · {instantWords(item.recorded_at)} · {item.content.format} · digest {shortDigest(item.content.decoded_sha256)}
                </p>
                {item.change_reason ? <p className="text-text-secondary">Reason: {item.change_reason}</p> : null}
                {item.version_number === selectedVersion ? (
                  <p className="text-text-muted">Currently shown</p>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => onSelectVersion(item.version_number)}>
                    {`Show version ${item.version_number}`}
                  </Button>
                )}
              </li>
            ))}
          </ol>
        ) : null}
        <PageFooter page={versions.page} more={() => void versions.more()} label="versions" />
      </section>
      <section aria-label="Lifecycle events" className="grid gap-2">
        <h2 className="text-base font-semibold">Lifecycle events</h2>
        {lifecycle.page.kind === "loading" ? <p role="status" className="text-sm text-text-muted">Reading lifecycle events…</p> : null}
        {lifecycle.page.kind === "failed" ? <p role="alert" className="text-sm text-text-muted">{lifecycle.page.message}</p> : null}
        {lifecycle.page.kind === "ready" ? (
          lifecycle.page.items.length === 0 ? <p className="text-sm text-text-muted">No lifecycle change is recorded.</p> : (
            <ol className="grid gap-2" aria-label="Lifecycle event list">
              {lifecycle.page.items.map((item) => (
                <li key={item.event_id} className="rounded-lg border border-border p-3 text-sm">
                  <p className="font-medium">
                    {ACTION_LABELS[item.operation]}: {lifecycleWords(item.prior_state)} → {lifecycleWords(item.resulting_state)}
                  </p>
                  <p className="text-text-secondary">
                    {instantWords(item.transitioned_at)} · lifecycle revision {item.lifecycle_revision}
                    {item.reason ? ` · Reason: ${item.reason}` : ""}
                  </p>
                </li>
              ))}
            </ol>
          )
        ) : null}
        <PageFooter page={lifecycle.page} more={() => void lifecycle.more()} label="lifecycle events" />
      </section>
    </div>
  );
}
