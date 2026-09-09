/**
 * GoodNotes — notebooks, pages, and page evidence from the Python GoodNotes plane.
 *
 * Search deep-links here with identifiers only (`goodnotesSearchHref`). A read
 * requires both `runId` and `pageVersionId`; a missing half is not guessed from
 * the catalog. Catalog liveness is `unknown` and is not treated as a NAS outage.
 *
 * This page reaches the gateway directly rather than through `/api/goodnotes`,
 * for the same reason Knowledge does: a server component calling its own BFF
 * would be a second copy of the same decision.
 *
 * There is no synthetic GoodNotes fixture. With the synthetic provider on, this
 * page says there is nothing to serve — the same answer the BFF gives.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { PageHeader } from "@/components/shell/page-header";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import { NotebookList, PageList, RunList } from "@/components/goodnotes/catalog";
import { EvidenceSplit } from "@/components/goodnotes/evidence-split";
import { InterpretationPanel } from "@/components/goodnotes/interpretation-panel";
import { MissingRaster, SourceRaster } from "@/components/goodnotes/source-raster";
import type { GoodNotesPage } from "@/lib/api/decode/capabilities/goodnotes.pages.list";
import type { GoodNotesRun } from "@/lib/api/decode/capabilities/goodnotes.runs.list";

const SCOPE = "goodnotes";

const BLURB =
  "Handwritten notebooks. Catalog rows are identifiers that were returned. A page opens as " +
  "evidence only when both a run id and a page version id are known.";

const SYNTHETIC_DETAIL =
  "The synthetic provider has no GoodNotes fixture. Knowledge does not invent notebooks to fill the space.";

function firstParam(
  params: Record<string, string | string[] | undefined>,
  key: string,
): string {
  const raw = params[key];
  return (Array.isArray(raw) ? raw[0] : raw)?.trim() ?? "";
}

function CatalogSection({
  title,
  headingId,
  children,
}: {
  title: string;
  headingId: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={headingId} className="mt-6">
      <h2 id={headingId} className="mb-3 text-base font-semibold text-moss-slate">
        {title}
      </h2>
      {children}
    </section>
  );
}

export async function GoodNotesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const params = await searchParams;
  const notebookId = firstParam(params, "notebookId");
  const logicalPageId = firstParam(params, "logicalPageId");
  const pageVersionId = firstParam(params, "pageVersionId");
  const runId = firstParam(params, "runId");
  const contentSha256 = firstParam(params, "contentSha256");

  const heading = (
    <PageHeader
      headingId="goodnotes-heading"
      title="GoodNotes"
      description={BLURB}
      actions={
        <a
          href="/knowledge"
          className="inline-flex min-h-11 items-center text-sm font-medium text-interactive underline"
        >
          Back to Knowledge
        </a>
      }
    />
  );

  const frame = (children: React.ReactNode) => (
    <section aria-labelledby="goodnotes-heading" className="mx-auto max-w-6xl">
      {heading}
      {children}
    </section>
  );

  if (syntheticDataEnabled()) {
    return frame(
      <SurfaceState
        kind="not_implemented"
        title="GoodNotes has no synthetic fixture"
        detail={SYNTHETIC_DETAIL}
        testId="goodnotes-synthetic"
      />,
    );
  }

  const hasRun = runId.length > 0;
  const hasPageVersion = pageVersionId.length > 0;
  if (hasRun !== hasPageVersion) {
    return frame(
      <SurfaceState
        kind="unavailable"
        title="This GoodNotes page could not be read"
        detail={
          "Reading evidence requires both runId and pageVersionId. The missing identifier " +
          "was not guessed from the catalog or from any other field."
        }
        testId="goodnotes-read-missing-ids"
      />,
    );
  }

  if (hasRun && hasPageVersion) {
    const payload: Record<string, unknown> = {
      run_id: runId,
      page_version_id: pageVersionId,
    };
    if (contentSha256) payload.content_sha256 = contentSha256;
    const answer = surfaceAnswer(
      `${SCOPE}:goodnotes.read`,
      await invokeGateway(principal, "goodnotes.read", payload),
      () => 1,
    );

    if (answer.kind === "unavailable") {
      return frame(
        <SurfaceState
          kind="unavailable"
          title="This GoodNotes page could not be read"
          error={answer.error}
          limitations={answer.disclosure.limitations}
          testId="goodnotes-item-unavailable"
        />,
      );
    }
    if (answer.kind === "empty") {
      return frame(
        <SurfaceState
          kind="unavailable"
          title="This GoodNotes page could not be read"
          detail="The read succeeded but carried no record, so nothing is claimed."
          testId="goodnotes-item-unavailable"
        />,
      );
    }

    const record = answer.result;
    const digest = contentSha256 || record.content_sha256;
    const evidence = (
      <EvidenceSplit
        source={
          digest ? (
            <SourceRaster record={record} contentSha256={digest} />
          ) : (
            <MissingRaster />
          )
        }
        interpretation={<InterpretationPanel interpretation={record.interpretation} />}
      />
    );

    return frame(
      answer.kind === "degraded" ? (
        <>
          <DegradedBanner
            scope="this GoodNotes page"
            limitations={answer.disclosure.limitations}
            truncated={answer.disclosure.truncated}
          />
          {evidence}
        </>
      ) : (
        evidence
      ),
    );
  }

  const notebooksOutcome = await invokeGateway(principal, "goodnotes.notebooks.list");
  const notebooksAnswer = surfaceAnswer(
    `${SCOPE}:goodnotes.notebooks.list`,
    notebooksOutcome,
    (result) => result.notebooks.length,
  );

  let pagesAnswer: ReturnType<typeof surfaceAnswer<{ pages: readonly GoodNotesPage[] }>> | null =
    null;
  let runsAnswer: ReturnType<typeof surfaceAnswer<{ runs: readonly GoodNotesRun[] }>> | null = null;
  if (notebookId) {
    const [pagesOutcome, runsOutcome] = await Promise.all([
      invokeGateway(principal, "goodnotes.pages.list", { notebook_id: notebookId }),
      invokeGateway(principal, "goodnotes.runs.list", { notebook_id: notebookId }),
    ]);
    pagesAnswer = surfaceAnswer(
      `${SCOPE}:goodnotes.pages.list`,
      pagesOutcome,
      (result) => result.pages.length,
    );
    runsAnswer = surfaceAnswer(
      `${SCOPE}:goodnotes.runs.list`,
      runsOutcome,
      (result) => result.runs.length,
    );
  }

  return frame(
    <>
      {notebooksAnswer.kind === "unavailable" ? (
        <SurfaceState
          kind="unavailable"
          title="GoodNotes notebooks could not be read"
          error={notebooksAnswer.error}
          limitations={notebooksAnswer.disclosure.limitations}
          testId="goodnotes-notebooks-unavailable"
        />
      ) : notebooksAnswer.kind === "empty" ? (
        <SurfaceState
          kind="empty"
          title="No GoodNotes notebooks were returned"
          detail={
            "The notebook catalog was read and it holds nothing. That is not a claim that a " +
            "notebook store is unavailable."
          }
          limitations={notebooksAnswer.disclosure.limitations}
          testId="goodnotes-notebooks-empty"
        />
      ) : notebooksAnswer.kind === "degraded" ? (
        <>
          <DegradedBanner
            scope="this notebook listing"
            limitations={notebooksAnswer.disclosure.limitations}
            truncated={notebooksAnswer.disclosure.truncated}
          />
          {notebooksAnswer.rowCount === 0 ? (
            <SurfaceState
              kind="degraded"
              title="The notebook listing was incomplete and returned nothing"
              detail={
                "Because the listing did not cover everything, an empty page is not evidence " +
                "that you hold no notebooks."
              }
              testId="goodnotes-notebooks-degraded-empty"
            />
          ) : (
            <NotebookList
              notebooks={notebooksAnswer.result.notebooks}
              selectedNotebookId={notebookId}
            />
          )}
        </>
      ) : (
        <NotebookList
          notebooks={notebooksAnswer.result.notebooks}
          selectedNotebookId={notebookId}
        />
      )}

      {pagesAnswer ? (
        <CatalogSection title="Pages" headingId="goodnotes-pages-heading">
          {pagesAnswer.kind === "unavailable" ? (
            <SurfaceState
              kind="unavailable"
              title="Pages for this notebook could not be read"
              error={pagesAnswer.error}
              limitations={pagesAnswer.disclosure.limitations}
              testId="goodnotes-pages-unavailable"
            />
          ) : pagesAnswer.kind === "empty" ? (
            <SurfaceState
              kind="empty"
              title="This notebook has no pages"
              detail="The page listing was read and it holds nothing."
              limitations={pagesAnswer.disclosure.limitations}
              testId="goodnotes-pages-empty"
            />
          ) : pagesAnswer.kind === "degraded" ? (
            <>
              <DegradedBanner
                scope="this page listing"
                limitations={pagesAnswer.disclosure.limitations}
                truncated={pagesAnswer.disclosure.truncated}
              />
              {pagesAnswer.rowCount === 0 ? (
                <SurfaceState
                  kind="degraded"
                  title="The page listing was incomplete and returned nothing"
                  detail="An empty listing here is not evidence that the notebook has no pages."
                  testId="goodnotes-pages-degraded-empty"
                />
              ) : (
                <PageList
                  notebookId={notebookId}
                  pages={pagesAnswer.result.pages}
                  selectedLogicalPageId={logicalPageId}
                />
              )}
            </>
          ) : (
            <PageList
              notebookId={notebookId}
              pages={pagesAnswer.result.pages}
              selectedLogicalPageId={logicalPageId}
            />
          )}
        </CatalogSection>
      ) : null}

      {runsAnswer ? (
        <CatalogSection title="Runs" headingId="goodnotes-runs-heading">
          {runsAnswer.kind === "unavailable" ? (
            <SurfaceState
              kind="unavailable"
              title="Runs for this notebook could not be read"
              error={runsAnswer.error}
              limitations={runsAnswer.disclosure.limitations}
              testId="goodnotes-runs-unavailable"
            />
          ) : runsAnswer.kind === "empty" ? (
            <SurfaceState
              kind="empty"
              title="This notebook has no runs"
              detail="The run listing was read and it holds nothing."
              limitations={runsAnswer.disclosure.limitations}
              testId="goodnotes-runs-empty"
            />
          ) : runsAnswer.kind === "degraded" ? (
            <>
              <DegradedBanner
                scope="this run listing"
                limitations={runsAnswer.disclosure.limitations}
                truncated={runsAnswer.disclosure.truncated}
              />
              {runsAnswer.rowCount === 0 ? (
                <SurfaceState
                  kind="degraded"
                  title="The run listing was incomplete and returned nothing"
                  detail="An empty listing here is not evidence that the notebook has no runs."
                  testId="goodnotes-runs-degraded-empty"
                />
              ) : (
                <RunList notebookId={notebookId} runs={runsAnswer.result.runs} />
              )}
            </>
          ) : (
            <RunList notebookId={notebookId} runs={runsAnswer.result.runs} />
          )}
        </CatalogSection>
      ) : null}
    </>,
  );
}
