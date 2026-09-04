/**
 * People — contract-backed entity search, resolve, and profile reads.
 *
 * **Not a directory.** An empty URL does not list every entity. The reader
 * searches (`entities.search`) or resolves a reference (`entities.resolve`).
 * Ambiguity from resolve stays visible as `outcome`; this page offers no merge.
 *
 * **`entities.profile` is the record-family card**, not `entities.context`.
 * Context remains the frozen wire shape for callers that ask for it through
 * the BFF; this page does not widen it.
 *
 * The page reaches the gateway directly rather than through its own BFF route,
 * matching Knowledge: a server component calling its own API would be a second
 * copy of the same decision.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway, type GatewayOutcome } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import type { EntitySearchResult } from "@/lib/api/decode/capabilities/entities.search";
import type { EntityResolveResult } from "@/lib/api/decode/capabilities/entities.resolve";
import type { EntityProfileResult } from "@/lib/api/decode/capabilities/entities.profile";

const SCOPE = "people";

const BLURB =
  "People is a read of entities you already hold. Search finds names; resolve " +
  "says whether a reference names one person, several, or none. It does not " +
  "list everyone, and it does not merge anyone.";

function SearchForm({ query }: { query: string }) {
  return (
    <form method="get" role="search" className="mb-4 flex flex-wrap items-end gap-2">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <label htmlFor="people-q" className="text-sm font-medium text-moss-slate">
          Search people
        </label>
        <input
          id="people-q"
          name="q"
          type="search"
          defaultValue={query}
          className="min-h-11 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
          aria-describedby="people-q-hint"
        />
        <p id="people-q-hint" className="text-xs text-muted">
          A name match over your own entities. This is browse, not identity.
        </p>
      </div>
      <button
        type="submit"
        className="inline-flex min-h-11 items-center rounded-md bg-moss-green px-4 py-2 text-sm font-medium text-on-interactive hover:bg-moss-everglade"
      >
        Search
      </button>
    </form>
  );
}

function ResolveForm({ reference }: { reference: string }) {
  return (
    <form method="get" className="mb-6 flex flex-wrap items-end gap-2">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <label htmlFor="people-reference" className="text-sm font-medium text-moss-slate">
          Resolve a reference
        </label>
        <input
          id="people-reference"
          name="reference"
          type="text"
          defaultValue={reference}
          className="min-h-11 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
          aria-describedby="people-reference-hint"
        />
        <p id="people-reference-hint" className="text-xs text-muted">
          Asks who this names. An ambiguous answer stays ambiguous; nothing here merges.
        </p>
      </div>
      <button
        type="submit"
        className="inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-moss-slate"
      >
        Resolve
      </button>
    </form>
  );
}

function frame(children: React.ReactNode) {
  return (
    <section aria-labelledby="people-heading" className="mx-auto max-w-2xl">
      <h1 id="people-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        People
      </h1>
      <p className="mb-4 text-sm text-muted">{BLURB}</p>
      {children}
    </section>
  );
}

function oneParam(
  params: Record<string, string | string[] | undefined>,
  name: string,
): string {
  const raw = params[name];
  return (Array.isArray(raw) ? raw[0] : raw)?.trim() ?? "";
}

export async function PeoplePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const params = await searchParams;
  const query = oneParam(params, "q");
  const reference = oneParam(params, "reference");
  const entityId = oneParam(params, "entityId");

  if (syntheticDataEnabled()) {
    return frame(
      <SurfaceState
        kind="not_implemented"
        title="People has no synthetic fixture"
        detail="This build is serving the synthetic provider. People reads the Python entity plane, and no fixture stands in for it — run against the gateway to see real records."
        testId="people-synthetic"
      />,
    );
  }

  const forms = (
    <>
      <SearchForm query={query} />
      <ResolveForm reference={reference} />
    </>
  );

  if (entityId) {
    const answer = surfaceAnswer(
      `${SCOPE}:entities.profile`,
      (await invokeGateway(principal, "entities.profile", {
        entity_id: entityId,
      })) as GatewayOutcome<EntityProfileResult>,
      () => 1,
    );
    return frame(
      <>
        {forms}
        {answer.kind === "unavailable" ? (
          <SurfaceState
            kind="unavailable"
            title="That profile could not be read"
            detail={answer.error.message}
            limitations={answer.disclosure.limitations}
            testId="people-profile-unavailable"
          />
        ) : answer.kind === "empty" ? (
          <SurfaceState
            kind="unavailable"
            title="That profile could not be read"
            detail="The read succeeded without a profile, which is not a complete answer."
            testId="people-profile-unavailable"
          />
        ) : (
          <>
            {answer.kind === "degraded" ? (
              <DegradedBanner
                scope="this profile"
                limitations={answer.disclosure.limitations}
                truncated={answer.disclosure.truncated}
              />
            ) : null}
            <ProfileCard profile={answer.result.profile} />
          </>
        )}
      </>,
    );
  }

  if (reference) {
    const answer = surfaceAnswer(
      `${SCOPE}:entities.resolve`,
      (await invokeGateway(principal, "entities.resolve", {
        reference,
      })) as GatewayOutcome<EntityResolveResult>,
      () => 1,
    );
    return frame(
      <>
        {forms}
        {answer.kind === "unavailable" ? (
          <SurfaceState
            kind="unavailable"
            title="That reference could not be resolved"
            detail={answer.error.message}
            limitations={answer.disclosure.limitations}
            testId="people-resolve-unavailable"
          />
        ) : answer.kind === "empty" ? (
          <SurfaceState
            kind="unavailable"
            title="That reference could not be resolved"
            detail="The read succeeded without a resolution, which is not a complete answer."
            testId="people-resolve-unavailable"
          />
        ) : (
          <>
            {answer.kind === "degraded" ? (
              <DegradedBanner
                scope="this resolution"
                limitations={answer.disclosure.limitations}
                truncated={answer.disclosure.truncated}
              />
            ) : null}
            <ResolutionCard resolution={answer.result.resolution} />
          </>
        )}
      </>,
    );
  }

  if (query) {
    const answer = surfaceAnswer(
      `${SCOPE}:entities.search`,
      (await invokeGateway(principal, "entities.search", {
        query,
      })) as GatewayOutcome<EntitySearchResult>,
      (result) => result.entities.length,
    );
    return frame(
      <>
        {forms}
        {answer.kind === "unavailable" ? (
          <SurfaceState
            kind="unavailable"
            title="Your people could not be searched"
            detail={answer.error.message}
            limitations={answer.disclosure.limitations}
            testId="people-search-unavailable"
          />
        ) : answer.kind === "empty" ? (
          <SurfaceState
            kind="empty"
            title="No entity of yours matched those words"
            detail={`The search ran over your own entities and matched none of them for “${query}”.`}
            limitations={answer.disclosure.limitations}
            testId="people-search-empty"
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
                detail="Because the search did not cover everything, no match is not the same as nobody. Nothing is claimed about who you hold."
                testId="people-search-degraded-empty"
              />
            ) : (
              <SearchHits entities={answer.result.entities} />
            )}
          </>
        ) : (
          <SearchHits entities={answer.result.entities} />
        )}
      </>,
    );
  }

  return frame(
    <>
      {forms}
      <SurfaceState
        kind="empty"
        title="Ask by name or by reference"
        detail="This is not a directory of everyone. Search a name, or resolve a reference. Ambiguous answers stay visible; nothing here merges two people."
        testId="people-idle"
      />
    </>,
  );
}

function SearchHits({
  entities,
}: {
  entities: EntitySearchResult["entities"];
}) {
  return (
    <ul data-testid="people-search-hits" className="space-y-2">
      {entities.map((row) => (
        <li key={row.entity_id} className="rounded-md border border-border bg-surface p-3">
          <a
            href={`/people?entityId=${encodeURIComponent(row.entity_id)}`}
            className="font-medium text-moss-slate underline"
          >
            {row.display_name}
          </a>
          <p className="mt-1 text-xs text-muted">{row.entity_id}</p>
          {row.affiliated_organizations.length > 0 ? (
            <p className="mt-1 text-sm text-muted">
              {row.affiliated_organizations.join(", ")}
            </p>
          ) : null}
          {row.project_roles.length > 0 ? (
            <p className="text-sm text-muted">{row.project_roles.join(", ")}</p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function ResolutionCard({
  resolution,
}: {
  resolution: EntityResolveResult["resolution"];
}) {
  return (
    <div data-testid="people-resolve-result" className="rounded-md border border-border bg-surface p-4">
      <p data-testid="people-resolve-outcome" className="text-sm font-medium text-moss-slate">
        Outcome: {resolution.outcome}
      </p>
      {resolution.entity_id ? (
        <p className="mt-2">
          <a
            href={`/people?entityId=${encodeURIComponent(resolution.entity_id)}`}
            className="underline"
          >
            Open profile
          </a>
        </p>
      ) : null}
      {resolution.candidates.length > 0 ? (
        <ul data-testid="people-resolve-candidates" className="mt-3 space-y-2">
          {resolution.candidates.map((candidate) => (
            <li key={candidate.entity_id}>
              <a
                href={`/people?entityId=${encodeURIComponent(candidate.entity_id)}`}
                className="underline"
              >
                {candidate.display_name}
              </a>
              <span className="ml-2 text-xs text-muted">{candidate.entity_id}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function ProfileCard({
  profile,
}: {
  profile: EntityProfileResult["profile"];
}) {
  return (
    <article data-testid="people-profile" className="rounded-md border border-border bg-surface p-4">
      <h2 className="text-lg font-semibold text-moss-slate">{profile.entity.display_name}</h2>
      <p className="text-xs text-muted">{profile.entity.entity_id}</p>
      <section className="mt-4" aria-labelledby="people-profile-names">
        <h3 id="people-profile-names" className="text-sm font-medium text-moss-slate">
          Names
        </h3>
        {profile.names.length === 0 ? (
          <p className="text-sm text-muted">No typed names on file.</p>
        ) : (
          <ul>
            {profile.names.map((name) => (
              <li key={name.entity_name_id} className="text-sm">
                {name.display_value}
              </li>
            ))}
          </ul>
        )}
      </section>
    </article>
  );
}
