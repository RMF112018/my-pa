/**
 * Relationship timeline — **not backend-backed at this head, and it says so.**
 *
 * `SqlRelationshipEventRepository.list_accepted_events` is real, principal-scoped,
 * and already filters `accepted IS TRUE` so a proposed event never surfaces as
 * fact. It is unreachable over the transport for the reason `/api/pulse` sets out
 * in full: no `Capability` member exposes it, and a new one needs a migration.
 *
 * There is a second reason this one must not be wired casually, recorded as
 * NOTE 3 out of WP-04 and repeated here because this route is where it would
 * land: `relationship_identity_observations` carries a **table-wide** unique
 * constraint, so two Principals recording the same source version collide with an
 * `IntegrityError` where an absent row would have succeeded — an existence
 * disclosure across the partition. It is unreachable today because nothing wires
 * the relationship plane to a transport. Whoever wires it owns that constraint
 * first.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { notImplemented, resolveServing } from "@/lib/api/serving";
import { acceptedTimeline, syntheticPersonId } from "@/lib/fixtures/situation";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

const NO_CAPABILITY =
  "Relationship timelines have no backend capability. A principal-scoped, accepted-only " +
  "read model exists in PostgreSQL, but no member of the v1 capability set exposes it over " +
  "the gateway; adding one requires a migration, and the relationship plane additionally " +
  "carries a table-wide unique constraint that must be partitioned before it is wired.";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ personId: string }> },
) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const { personId } = await context.params;
  const scope = `relationship:${personId}:timeline`;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;
  if (serving.kind === "backend") return notImplemented(scope, NO_CAPABILITY);

  // The person must resolve within the caller's own partition. A foreign or
  // unknown id is indistinguishable — never confirm another principal's
  // person exists.
  if (personId !== syntheticPersonId(guard.principal)) {
    return NextResponse.json(
      { error: { errorClass: "not_found", code: "not_found", message: "no such person" } },
      { status: 404 },
    );
  }

  return NextResponse.json({
    shape: "synthetic",
    personId,
    events: acceptedTimeline(guard.principal, personId),
    disclosure: syntheticDisclosure(scope),
  });
}
