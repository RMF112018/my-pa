/**
 * Canonical entity profile. Reads the record-family card plus assignments,
 * relationships, and identity history. Missing companion reads are degraded,
 * not an empty success, and never hide a profile that did arrive.
 */
import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway, type GatewayOutcome } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import { EntityProfilePanel } from "@/components/people/entity-profile";
import {
  AssignmentsPanel,
  IdentityHistoryPanel,
  RelationshipsPanel,
} from "@/components/people/related-records";
import { peopleHome } from "@/lib/routes/people";
import type { EntityProfileResult } from "@/lib/api/decode/capabilities/entities.profile";
import type { EntitiesAssignmentsListResult } from "@/lib/api/decode/capabilities/entities.assignments.list";
import type { EntitiesRelationshipsResult } from "@/lib/api/decode/capabilities/entities.relationships";
import type { EntitiesIdentityHistoryResult } from "@/lib/api/decode/capabilities/entities.identity_history";
import type { DisclosureEnvelope } from "@/contracts/envelope";

const SCOPE = "people";

function oneParam(
  params: Record<string, string | string[] | undefined>,
  name: string,
): string {
  const raw = params[name];
  return (Array.isArray(raw) ? raw[0] : raw)?.trim() ?? "";
}

function failedMessage(outcome: GatewayOutcome<unknown>): string | null {
  if (outcome.ok) return null;
  return outcome.error.message;
}

export async function PeopleEntityPage({
  params,
  searchParams,
}: {
  params: Promise<{ entityId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const { entityId: rawId } = await params;
  const entityId = decodeURIComponent(rawId);
  const historyAfter = searchParams ? oneParam(await searchParams, "historyAfter") : "";

  if (syntheticDataEnabled()) {
    return (
      <section aria-labelledby="people-entity-heading" className="mx-auto max-w-4xl">
        <h1 id="people-entity-heading" className="mb-4 text-xl font-semibold text-moss-slate">
          Person
        </h1>
        <SurfaceState
          kind="not_implemented"
          title="People has no synthetic fixture"
          detail="This build is serving the synthetic provider. People reads the Python entity plane, and no fixture stands in for it — run against the gateway to see real records."
          testId="people-synthetic"
        />
      </section>
    );
  }

  const [profileOutcome, assignmentsOutcome, relationshipsOutcome, historyOutcome] = await Promise.all([
    invokeGateway(principal, "entities.profile", { entity_id: entityId }),
    invokeGateway(principal, "entities.assignments.list", { entity_id: entityId }),
    invokeGateway(principal, "entities.relationships", { entity_id: entityId }),
    invokeGateway(principal, "entities.identity_history", {
      entity_id: entityId,
      ...(historyAfter ? { after: historyAfter } : {}),
    }),
  ]);

  const profileAnswer = surfaceAnswer(`${SCOPE}:entities.profile`, profileOutcome, () => 1);

  if (profileAnswer.kind === "unavailable" || profileAnswer.kind === "empty") {
    const notFound = !profileOutcome.ok && profileOutcome.error.errorClass === "not_found";
    return (
      <section aria-labelledby="people-entity-heading" className="mx-auto max-w-4xl">
        <p className="mb-4 text-sm">
          <Link href={peopleHome()} className="text-moss-green underline">
            ← People
          </Link>
        </p>
        <h1 id="people-entity-heading" className="mb-4 text-xl font-semibold text-moss-slate">
          Person
        </h1>
        <SurfaceState
          kind="unavailable"
          title={notFound ? "That entity was not found" : "That profile could not be read"}
          detail={
            profileAnswer.kind === "unavailable"
              ? profileAnswer.error.message
              : "The read succeeded without a profile, which is not a complete answer."
          }
          limitations={profileAnswer.disclosure.limitations}
          testId="people-profile-unavailable"
        />
      </section>
    );
  }

  const profile = profileAnswer.result.profile;
  const assignmentAnswer = surfaceAnswer(
    `${SCOPE}:entities.assignments.list`,
    assignmentsOutcome,
    (result) => result.assignments.length,
  );
  const relationshipAnswer = surfaceAnswer(
    `${SCOPE}:entities.relationships`,
    relationshipsOutcome,
    (result) => result.relationships.length,
  );
  const historyAnswer = surfaceAnswer(
    `${SCOPE}:entities.identity_history`,
    historyOutcome,
    (result) => result.entries.length,
  );

  const companionFailed =
    assignmentAnswer.kind === "unavailable" ||
    relationshipAnswer.kind === "unavailable" ||
    historyAnswer.kind === "unavailable";

  let assignments: EntitiesAssignmentsListResult["assignments"] | null = null;
  let assignmentDisclosure: DisclosureEnvelope | null = null;
  if (assignmentAnswer.kind === "records" || assignmentAnswer.kind === "degraded") {
    assignments = assignmentAnswer.result.assignments;
    assignmentDisclosure = assignmentAnswer.disclosure;
  } else if (assignmentAnswer.kind === "empty") {
    assignments = [];
    assignmentDisclosure = assignmentAnswer.disclosure;
  }

  let relationships: EntitiesRelationshipsResult["relationships"] | null = null;
  let relationshipDisclosure: DisclosureEnvelope | null = null;
  if (relationshipAnswer.kind === "records" || relationshipAnswer.kind === "degraded") {
    relationships = relationshipAnswer.result.relationships;
    relationshipDisclosure = relationshipAnswer.disclosure;
  } else if (relationshipAnswer.kind === "empty") {
    relationships = [];
    relationshipDisclosure = relationshipAnswer.disclosure;
  }

  let historyEntries: EntitiesIdentityHistoryResult["entries"] | null = null;
  let historyTruncated = false;
  let historyCursor: string | null = null;
  if (historyAnswer.kind === "records" || historyAnswer.kind === "degraded") {
    historyEntries = historyAnswer.result.entries;
    historyTruncated = historyAnswer.result.is_truncated;
    historyCursor = historyAnswer.result.next_cursor;
  } else if (historyAnswer.kind === "empty") {
    historyEntries = [];
  }

  return (
    <section aria-labelledby="people-entity-heading" className="mx-auto max-w-4xl">
      <p className="mb-4 text-sm">
        <Link href={peopleHome()} className="text-moss-green underline">
          ← People
        </Link>
      </p>
      {companionFailed ? (
        <DegradedBanner
          scope="this person"
          limitations={[
            assignmentAnswer.kind === "unavailable" ? "Assignments could not be read." : "",
            relationshipAnswer.kind === "unavailable" ? "Relationships could not be read." : "",
            historyAnswer.kind === "unavailable" ? "Identity history could not be read." : "",
          ].filter(Boolean)}
        />
      ) : null}
      <EntityProfilePanel
        profile={profile}
        headingLevel={1}
        headingId="people-entity-heading"
      />
      <AssignmentsPanel
        assignments={assignments}
        disclosure={assignmentDisclosure}
        unavailable={failedMessage(assignmentsOutcome)}
      />
      <RelationshipsPanel
        relationships={relationships}
        subjectId={profile.entity.entity_id}
        disclosure={relationshipDisclosure}
        unavailable={failedMessage(relationshipsOutcome)}
      />
      <IdentityHistoryPanel
        entries={historyEntries}
        truncated={historyTruncated}
        nextCursor={historyCursor}
        entityId={profile.entity.entity_id}
        unavailable={failedMessage(historyOutcome)}
      />
    </section>
  );
}
