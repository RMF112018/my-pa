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
import { PageHeader } from "@/components/shell/page-header";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import { EntityProfilePanel } from "@/components/people/entity-profile";
import {
  AssignmentsPanel,
  IdentityHistoryPanel,
  RelationshipsPanel,
} from "@/components/people/related-records";
import { canvasMap } from "@/lib/routes/canvas";
import { peopleHome } from "@/lib/routes/people";
import type { EntityProfileResult } from "@/lib/api/decode/capabilities/entities.profile";
import type { EntitiesAssignmentsListResult } from "@/lib/api/decode/capabilities/entities.assignments.list";
import type { EntitiesRelationshipsResult } from "@/lib/api/decode/capabilities/entities.relationships";
import type { EntitiesIdentityHistoryResult } from "@/lib/api/decode/capabilities/entities.identity_history";
import type { DisclosureEnvelope } from "@/contracts/envelope";
import {
  diagnosticError,
  diagnosticLimitations,
  diagnosticText,
} from "@/lib/diagnostics/presentation";
import { serverDiagnosticsEnabled } from "@/lib/diagnostics/server";
import { WEB_LIMITATIONS } from "@/lib/diagnostics/safe-detail";
import type { ErrorEnvelope } from "@/contracts/envelope";

const SCOPE = "people";

function oneParam(
  params: Record<string, string | string[] | undefined>,
  name: string,
): string {
  const raw = params[name];
  return (Array.isArray(raw) ? raw[0] : raw)?.trim() ?? "";
}

/** Did the read fail? Product truth, needed in both modes. */
function readFailed(outcome: GatewayOutcome<unknown>): boolean {
  return !outcome.ok;
}

/**
 * The backend's own sentence for a failed read, or nothing.
 *
 * Returned raw, and wrapped in `diagnosticText` at each callsite rather than
 * inside here. This is a **server** component, so a raw gateway message handed
 * to a child is serialized into the RSC payload whatever the child then does
 * with it — and the static guard that enforces that reads the callsite, so
 * burying the helper call in here would have hidden these three from it.
 */
/**
 * The failure envelope of a read that did not succeed, or nothing.
 *
 * WP08-RT-F010: this used to return `outcome.error.message`, which handed the
 * gateway's own sentence down to the panels as display text. The envelope goes
 * down instead and `diagnosticText` reads it into the closed vocabulary, so the
 * message never becomes prose on a page.
 */
function failedError(outcome: GatewayOutcome<unknown>): ErrorEnvelope | null {
  if (outcome.ok) return null;
  return outcome.error;
}

export async function PeopleEntityPage({
  params,
  searchParams,
}: {
  params: Promise<{ entityId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  // WP07: resolved once per request (memoised) so the diagnostic-bearing
  // props below are never built, and therefore never serialized into the
  // RSC payload, while diagnostics are off.
  const diagnosticsEnabled = await serverDiagnosticsEnabled();
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const { entityId: rawId } = await params;
  const entityId = decodeURIComponent(rawId);
  const historyAfter = searchParams ? oneParam(await searchParams, "historyAfter") : "";

  if (syntheticDataEnabled()) {
    return (
      <section aria-labelledby="people-entity-heading" className="mx-auto max-w-4xl">
        <PageHeader headingId="people-entity-heading" title="Person" />
        <SurfaceState
          kind="not_implemented"
          title="People has no synthetic fixture"
          detail="This build is serving sample data. People is not included in that sample, so there is no one to look up here."
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
          <Link href={peopleHome()} className="text-interactive underline">
            ← People
          </Link>
        </p>
        <PageHeader headingId="people-entity-heading" title="Person" />
        <SurfaceState
          kind="unavailable"
          title={notFound ? "That entity was not found" : "That profile could not be read"}
          error={diagnosticError(diagnosticsEnabled, profileAnswer.kind === "unavailable" ? profileAnswer.error : undefined)}
          detail={
            profileAnswer.kind === "unavailable"
              ? undefined
              : "The read succeeded without a profile, which is not a complete answer."
          }
          limitations={diagnosticLimitations(diagnosticsEnabled, profileAnswer.disclosure.limitations)}
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
        <Link href={peopleHome()} className="text-interactive underline">
          ← People
        </Link>
        {" · "}
        <Link
          href={canvasMap({ focusEntityId: profile.entity.entity_id })}
          className="text-interactive underline"
          data-testid="people-view-map"
        >
          View map
        </Link>
      </p>
      {companionFailed ? (
        <DegradedBanner
          scope="this person"
          limitations={diagnosticLimitations(diagnosticsEnabled, [
            assignmentAnswer.kind === "unavailable" ? WEB_LIMITATIONS.assignmentsUnreadable : "",
            relationshipAnswer.kind === "unavailable" ? WEB_LIMITATIONS.relationshipsUnreadable : "",
            historyAnswer.kind === "unavailable" ? WEB_LIMITATIONS.identityHistoryUnreadable : "",
          ].filter(Boolean))}
        />
      ) : null}
      <EntityProfilePanel diagnosticsEnabled={diagnosticsEnabled}
        profile={profile}
        headingLevel={1}
        headingId="people-entity-heading"
      />
      <AssignmentsPanel diagnosticsEnabled={diagnosticsEnabled}
        assignments={assignments}
        disclosure={assignmentDisclosure}
        unavailable={readFailed(assignmentsOutcome)}
        unavailableDiagnostic={diagnosticText(diagnosticsEnabled, failedError(assignmentsOutcome))}
      />
      <RelationshipsPanel diagnosticsEnabled={diagnosticsEnabled}
        relationships={relationships}
        subjectId={profile.entity.entity_id}
        disclosure={relationshipDisclosure}
        unavailable={readFailed(relationshipsOutcome)}
        unavailableDiagnostic={diagnosticText(diagnosticsEnabled, failedError(relationshipsOutcome))}
      />
      <IdentityHistoryPanel diagnosticsEnabled={diagnosticsEnabled}
        entries={historyEntries}
        truncated={historyTruncated}
        nextCursor={historyCursor}
        entityId={profile.entity.entity_id}
        unavailable={readFailed(historyOutcome)}
        unavailableDiagnostic={diagnosticText(diagnosticsEnabled, failedError(historyOutcome))}
      />
    </section>
  );
}
