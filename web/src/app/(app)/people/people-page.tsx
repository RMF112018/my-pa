/**
 * People — contract-backed entity search, resolve, and profile reads.
 *
 * **Not a directory.** An empty URL does not list every entity. The reader
 * searches (`entities.search`) or resolves a reference (`entities.resolve`).
 * Ambiguity from resolve stays visible as `outcome`; this page offers no merge.
 *
 * Canonical profile addresses are `/people/{entityId}`. A leftover
 * `?entityId=` query is redirected there so old deep links keep working.
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
import { PeopleSearchForm, PeopleResolveForm } from "@/components/people/people-forms";
import { SearchHits } from "@/components/people/search-hits";
import { ResolvePanel } from "@/components/people/resolve-panel";
import { UnresolvedMentionsPanel } from "@/components/people/unresolved-mentions";
import { peopleEntity } from "@/lib/routes/people";
import type { EntitySearchResult } from "@/lib/api/decode/capabilities/entities.search";
import type { EntityResolveResult } from "@/lib/api/decode/capabilities/entities.resolve";
import type { EntitiesUnresolvedMentionsResult } from "@/lib/api/decode/capabilities/entities.unresolved_mentions";
import type { PrincipalSession } from "@/contracts/identity";

const SCOPE = "people";

const BLURB =
  "People is search, resolve, and a profile of one entity you already hold. " +
  "Search finds names; resolve says whether a reference names one person, several, or none. " +
  "It does not list everyone, and it does not merge anyone.";

function frame(children: React.ReactNode) {
  return (
    <section aria-labelledby="people-heading" className="mx-auto max-w-3xl">
      <h1 id="people-heading" className="mb-1 text-2xl font-semibold tracking-tight text-moss-slate">
        People
      </h1>
      <p className="mb-6 max-w-3xl text-sm text-muted">{BLURB}</p>
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

async function unresolvedPanel(principal: PrincipalSession, after: string) {
  const outcome = (await invokeGateway(principal, "entities.unresolved_mentions", {
    ...(after ? { after } : {}),
  })) as GatewayOutcome<EntitiesUnresolvedMentionsResult>;
  const answer = surfaceAnswer(`${SCOPE}:entities.unresolved_mentions`, outcome, (result) =>
    result.mentions.length,
  );
  if (answer.kind === "unavailable" || answer.kind === "empty") return null;
  return (
    <UnresolvedMentionsPanel mentions={answer.result.mentions} disclosure={answer.disclosure} />
  );
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
  const mentionsAfter = oneParam(params, "mentionsAfter");

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

  if (entityId) {
    redirect(peopleEntity(entityId));
  }

  const forms = (
    <>
      <PeopleSearchForm query={query} />
      <PeopleResolveForm reference={reference} />
    </>
  );

  if (reference) {
    const outcome = (await invokeGateway(principal, "entities.resolve", {
      reference,
    })) as GatewayOutcome<EntityResolveResult>;
    if (!outcome.ok && outcome.error.errorClass === "validation") {
      return frame(
        <>
          {forms}
          <SurfaceState
            kind="unavailable"
            title="That reference was not a valid resolve query"
            detail={outcome.error.message}
            testId="people-resolve-invalid"
          />
        </>,
      );
    }
    const answer = surfaceAnswer(`${SCOPE}:entities.resolve`, outcome, () => 1);
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
            <ResolvePanel resolution={answer.result.resolution} />
          </>
        )}
      </>,
    );
  }

  if (query) {
    const outcome = (await invokeGateway(principal, "entities.search", {
      query,
    })) as GatewayOutcome<EntitySearchResult>;
    if (!outcome.ok && outcome.error.errorClass === "validation") {
      return frame(
        <>
          {forms}
          <SurfaceState
            kind="unavailable"
            title="That search was not a valid query"
            detail={outcome.error.message}
            testId="people-search-invalid"
          />
        </>,
      );
    }
    const answer = surfaceAnswer(
      `${SCOPE}:entities.search`,
      outcome,
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

  const mentions = await unresolvedPanel(principal, mentionsAfter);

  return frame(
    <>
      {forms}
      <SurfaceState
        kind="empty"
        title="Ask by name or by reference"
        detail="This is not a directory of everyone. Search a name, or resolve a reference. Ambiguous answers stay visible; nothing here merges two people."
        testId="people-idle"
      />
      {mentions}
    </>,
  );
}
