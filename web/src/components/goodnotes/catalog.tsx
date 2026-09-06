/**
 * GoodNotes catalog rows. These components receive records the page already
 * classified; they do not decide empty vs unavailable, and they do not invent
 * a run or page version so a row can be opened.
 */
import type { GoodNotesNotebook } from "@/lib/api/decode/capabilities/goodnotes.notebooks.list";
import type { GoodNotesPage } from "@/lib/api/decode/capabilities/goodnotes.pages.list";
import type { GoodNotesRun } from "@/lib/api/decode/capabilities/goodnotes.runs.list";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardTitle } from "@/components/ui/card";

function moment(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : `${parsed.toISOString().replace("T", " ").slice(0, 16)} UTC`;
}

export function goodnotesCatalogHref(params: {
  notebookId?: string;
  logicalPageId?: string;
  pageVersionId?: string;
  runId?: string;
  contentSha256?: string;
}): string {
  const search = new URLSearchParams();
  if (params.notebookId) search.set("notebookId", params.notebookId);
  if (params.logicalPageId) search.set("logicalPageId", params.logicalPageId);
  if (params.pageVersionId) search.set("pageVersionId", params.pageVersionId);
  if (params.runId) search.set("runId", params.runId);
  if (params.contentSha256) search.set("contentSha256", params.contentSha256);
  const query = search.toString();
  return query ? `/knowledge/goodnotes?${query}` : "/knowledge/goodnotes";
}

export function NotebookList({
  notebooks,
  selectedNotebookId,
}: {
  notebooks: readonly GoodNotesNotebook[];
  selectedNotebookId: string;
}) {
  return (
    <ul className="flex flex-col gap-3" data-testid="goodnotes-notebooks">
      {notebooks.map((notebook) => {
        const selected = notebook.notebook_id === selectedNotebookId;
        return (
          <li key={notebook.notebook_id}>
            <Card data-testid="goodnotes-notebook" aria-current={selected ? "true" : undefined}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <CardTitle>{notebook.title}</CardTitle>
                <Badge tone="neutral">
                  {notebook.page_count === 1 ? "1 page" : `${notebook.page_count} pages`}
                </Badge>
              </div>
              <CardBody>
                <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
                  <dt className="text-muted">updated</dt>
                  <dd>{moment(notebook.updated_at)}</dd>
                  <dt className="text-muted">liveness</dt>
                  <dd data-testid="goodnotes-notebook-liveness">{notebook.liveness}</dd>
                </dl>
                <p className="mt-2 text-xs">
                  Liveness is reported as unknown. That is not a claim that a notebook store
                  is unavailable.
                </p>
                <a
                  href={goodnotesCatalogHref({ notebookId: notebook.notebook_id })}
                  className="mt-3 inline-flex min-h-11 items-center rounded-md border border-moss-green px-4 py-2 text-sm font-medium text-moss-green hover:bg-moss-sand"
                >
                  {selected ? "Selected notebook" : "List pages"}
                </a>
              </CardBody>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}

export function PageList({
  notebookId,
  pages,
  selectedLogicalPageId,
}: {
  notebookId: string;
  pages: readonly GoodNotesPage[];
  selectedLogicalPageId: string;
}) {
  return (
    <ul className="flex flex-col gap-3" data-testid="goodnotes-pages">
      {pages.map((page) => {
        const selected = page.logical_page_id === selectedLogicalPageId;
        const canOpen = Boolean(page.run_id);
        return (
          <li key={page.page_version_id}>
            <Card data-testid="goodnotes-page" aria-current={selected ? "true" : undefined}>
              <CardTitle>
                <span className="font-mono text-sm break-all">{page.logical_page_id}</span>
              </CardTitle>
              <CardBody>
                <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
                  <dt className="text-muted">page version</dt>
                  <dd className="font-mono text-xs break-all">{page.page_version_id}</dd>
                  <dt className="text-muted">updated</dt>
                  <dd>{moment(page.updated_at)}</dd>
                  <dt className="text-muted">latest</dt>
                  <dd>{page.is_latest ? "yes" : "no"}</dd>
                </dl>
                {canOpen && page.run_id ? (
                  <a
                    href={goodnotesCatalogHref({
                      notebookId,
                      logicalPageId: page.logical_page_id,
                      pageVersionId: page.page_version_id,
                      runId: page.run_id,
                      contentSha256: page.content_sha256,
                    })}
                    className="mt-3 inline-flex min-h-11 items-center rounded-md bg-moss-green px-4 py-2 text-sm font-medium text-on-interactive hover:bg-moss-everglade"
                  >
                    Open evidence
                  </a>
                ) : (
                  <p className="mt-3 text-xs" data-testid="goodnotes-page-no-run">
                    This page has no run id, so it cannot be opened as evidence.
                  </p>
                )}
              </CardBody>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}

export function RunList({
  notebookId,
  runs,
}: {
  notebookId: string;
  runs: readonly GoodNotesRun[];
}) {
  return (
    <ul className="flex flex-col gap-3" data-testid="goodnotes-runs">
      {runs.map((run) => {
        const canOpen = Boolean(run.page_version_id);
        return (
          <li key={run.run_id}>
            <Card data-testid="goodnotes-run">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <CardTitle>
                  <span className="font-mono text-sm break-all">{run.run_id}</span>
                </CardTitle>
                <Badge tone={run.failure_class ? "coral" : "neutral"}>{run.state}</Badge>
              </div>
              <CardBody>
                <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-1">
                  <dt className="text-muted">started</dt>
                  <dd>{moment(run.started_at)}</dd>
                  <dt className="text-muted">completed</dt>
                  <dd>{run.completed_at ? moment(run.completed_at) : "not completed"}</dd>
                </dl>
                {canOpen && run.page_version_id ? (
                  <a
                    href={goodnotesCatalogHref({
                      notebookId,
                      pageVersionId: run.page_version_id,
                      runId: run.run_id,
                    })}
                    className="mt-3 inline-flex min-h-11 items-center rounded-md border border-moss-green px-4 py-2 text-sm font-medium text-moss-green hover:bg-moss-sand"
                  >
                    Open evidence
                  </a>
                ) : (
                  <p className="mt-3 text-xs" data-testid="goodnotes-run-no-page">
                    This run has no page version id, so it cannot be opened as evidence.
                  </p>
                )}
              </CardBody>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}
