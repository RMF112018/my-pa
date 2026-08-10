/**
 * Library — the browsable record, served from the Python capture plane.
 *
 * **What this page said until now, and why it had to go.** It rendered a fixed
 * `NotConnected` card reading "No sources are connected yet" — a sentence that
 * was printed whether or not the backend was reachable, whether or not the
 * Principal held captures, and whether or not anything had been asked. It was a
 * claim about the reader's own record that nothing had established, sitting in
 * front of a real, already-wired capability (`app/api/library/route.ts` has
 * spoken to `capture.list`, `capture.search`, `knowledge.search` and
 * `knowledge.read` since WP-11). A person holding a hundred stored captures was
 * being told they had none.
 *
 * **The four answers this page can give are four different things**, decided by
 * `lib/api/surface-answer.ts` and never by counting rows first:
 *
 * * **records** — `capture.list` (or `capture.search`, when the reader searched)
 *   returned rows, and they are shown;
 * * **empty** — the read succeeded and carried nothing. The only state here that
 *   asserts anything about what the Principal holds;
 * * **unavailable** — the gateway refused, was unreachable, or answered with
 *   `coverage: "unavailable"`, meaning it did not search. Nothing is claimed;
 * * **degraded** — the backend said its own answer is partial or truncated. The
 *   rows are still shown, above a banner that says what is missing.
 *
 * **This page reaches the gateway directly rather than through its own API
 * route**, which is the pattern `app/(app)/today` established and the reason
 * `lib/fixtures/gate.ts` records: a server component calling its own route would
 * be a second copy of the same decision, and the two copies would drift.
 *
 * **There is no synthetic Library fixture and none is invented here.** With the
 * synthetic provider explicitly on, this page says there is nothing to serve —
 * the same answer `/api/library` gives — because a fixture written now would be
 * a second thing to keep true about a plane that is already real.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { callGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import { CaptureListing, CaptureMatches } from "@/components/library/library-records";
import type { BackendCaptureEntry, BackendCaptureMatch } from "@/contracts/views";

export const metadata = { title: "Library — my-pa" };

/** The listing this page renders is a read of the moment, never a cached one. */
export const dynamic = "force-dynamic";

const SCOPE = "library";

const BLURB =
  "Library is the browsable record of what you have captured. Every row below is a stored " +
  "capture of yours, read from the record itself — nothing here is a summary, a sample, or a " +
  "placeholder.";

interface PythonCaptureEntry {
  readonly capture_id: string;
  readonly owner_principal_id: string;
  readonly created_at: string;
  readonly version_count: number;
  readonly latest_version_id: string;
  readonly latest_version_number: number;
  readonly latest_recorded_at: string;
}

interface PythonCaptureMatch {
  readonly capture_id: string;
  readonly version_id: string;
  readonly version_number: number;
  readonly character_count: number;
  readonly recorded_at: string;
}

function toEntry(row: PythonCaptureEntry): BackendCaptureEntry {
  return {
    captureId: row.capture_id,
    ownerPrincipalId: row.owner_principal_id,
    createdAt: row.created_at,
    versionCount: row.version_count,
    latestVersionId: row.latest_version_id,
    latestVersionNumber: row.latest_version_number,
    latestRecordedAt: row.latest_recorded_at,
  };
}

function toMatch(row: PythonCaptureMatch): BackendCaptureMatch {
  return {
    captureId: row.capture_id,
    versionId: row.version_id,
    versionNumber: row.version_number,
    characterCount: row.character_count,
    recordedAt: row.recorded_at,
  };
}

/**
 * The search field.
 *
 * A plain `GET` form, so it works with JavaScript unavailable, is linkable, and
 * keeps the query in the URL where a reader can see what was asked. The label is
 * real rather than a placeholder, because a placeholder disappears on focus and
 * is not reliably announced.
 */
function SearchForm({ query }: { query: string }) {
  return (
    <form method="get" role="search" className="mb-4 flex flex-wrap items-end gap-2">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <label htmlFor="library-q" className="text-sm font-medium text-moss-slate">
          Search your captures
        </label>
        <input
          id="library-q"
          name="q"
          type="search"
          defaultValue={query}
          className="min-h-11 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
          aria-describedby="library-q-hint"
        />
        <p id="library-q-hint" className="text-xs text-muted">
          Exact word matching over your own captures. Words are not stemmed, so
          &ldquo;pour&rdquo; and &ldquo;pouring&rdquo; are different terms.
        </p>
      </div>
      <button
        type="submit"
        className="inline-flex min-h-11 items-center rounded-md bg-moss-green px-4 py-2 text-sm font-medium text-white hover:bg-moss-everglade"
      >
        Search
      </button>
    </form>
  );
}

export default async function LibraryPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const params = await searchParams;
  const rawQuery = params["q"];
  const query = (Array.isArray(rawQuery) ? rawQuery[0] : rawQuery)?.trim() ?? "";

  const heading = (
    <>
      <h1 id="library-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        Library
      </h1>
      <p className="mb-4 text-sm text-muted">{BLURB}</p>
    </>
  );

  const frame = (children: React.ReactNode) => (
    <section aria-labelledby="library-heading" className="mx-auto max-w-2xl">
      {heading}
      {children}
    </section>
  );

  if (syntheticDataEnabled()) {
    return frame(
      <SurfaceState
        kind="not_implemented"
        title="Library has no synthetic fixture"
        detail={
          "This build is serving the synthetic provider. Library reads the Python capture " +
          "plane, and no fixture stands in for it — run against the gateway to see real records."
        }
        testId="library-synthetic"
      />,
    );
  }

  if (query) {
    const answer = surfaceAnswer(
      `${SCOPE}:capture.search`,
      await callGateway<{ matches?: readonly PythonCaptureMatch[] }>(principal, "capture.search", {
        query,
      }),
      (result) => (result.matches ?? []).length,
    );

    return frame(
      <>
        <SearchForm query={query} />
        {answer.kind === "unavailable" ? (
          <SurfaceState
            kind="unavailable"
            title="Your captures could not be searched"
            detail={answer.error.message}
            limitations={answer.disclosure.limitations}
            testId="library-search-unavailable"
          />
        ) : answer.kind === "empty" ? (
          <SurfaceState
            kind="empty"
            title="No capture of yours matched those words"
            detail={`The search ran over your own captures and matched none of them for “${query}”.`}
            limitations={answer.disclosure.limitations}
            testId="library-search-empty"
          />
        ) : answer.kind === "degraded" ? (
          <>
            <DegradedBanner
              scope="this search"
              limitations={answer.disclosure.limitations}
              truncated={answer.disclosure.truncated}
            />
            {answer.rowCount === 0 ? (
              <SurfaceState
                kind="degraded"
                title="The search was incomplete and returned nothing"
                detail={
                  "Because the search did not cover everything, no match is not the same as no " +
                  "capture. Nothing is claimed about what you hold."
                }
                testId="library-search-degraded-empty"
              />
            ) : (
              <CaptureMatches matches={(answer.result.matches ?? []).map(toMatch)} />
            )}
          </>
        ) : (
          <CaptureMatches matches={(answer.result.matches ?? []).map(toMatch)} />
        )}
      </>,
    );
  }

  const answer = surfaceAnswer(
    `${SCOPE}:capture.list`,
    await callGateway<{ captures?: readonly PythonCaptureEntry[] }>(principal, "capture.list"),
    (result) => (result.captures ?? []).length,
  );

  return frame(
    <>
      <SearchForm query="" />
      {answer.kind === "unavailable" ? (
        <SurfaceState
          kind="unavailable"
          title="Your library could not be read"
          detail={answer.error.message}
          limitations={answer.disclosure.limitations}
          testId="library-unavailable"
        />
      ) : answer.kind === "empty" ? (
        <SurfaceState
          kind="empty"
          title="You have not captured anything yet"
          detail={
            "The capture record was read and it holds nothing. Use Capture to store your first " +
            "note; it will appear here."
          }
          limitations={answer.disclosure.limitations}
          testId="library-empty"
        />
      ) : answer.kind === "degraded" ? (
        <>
          <DegradedBanner
            scope="this listing"
            limitations={answer.disclosure.limitations}
            truncated={answer.disclosure.truncated}
          />
          {answer.rowCount === 0 ? (
            <SurfaceState
              kind="degraded"
              title="The listing was incomplete and returned nothing"
              detail={
                "Because the listing did not cover everything, an empty page is not evidence " +
                "that you hold nothing."
              }
              testId="library-degraded-empty"
            />
          ) : (
            <CaptureListing entries={(answer.result.captures ?? []).map(toEntry)} />
          )}
        </>
      ) : (
        <CaptureListing entries={(answer.result.captures ?? []).map(toEntry)} />
      )}
    </>,
  );
}
