/**
 * Relationship timeline route — WP-06 (R5): `/api/relationships/:personId/timeline`.
 *
 * A person's timeline is the accepted-only slice of their relationship events:
 * proposed (not-accepted) events never surface as fact, mirroring the Python
 * `list_accepted_events` filter (`accepted IS TRUE`). The principal is derived
 * from the session, never the path — a person id that does not resolve within
 * the caller's own partition returns `not_found` and reveals nothing, so a
 * foreign person and an unknown person are indistinguishable (MU-AC-05). Cross-
 * principal existence is never disclosed.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import {
  acceptedTimeline,
  syntheticPersonId,
} from "@/lib/fixtures/situation";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ personId: string }> },
) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const { personId } = await context.params;

  // The person must resolve within the caller's own partition. A foreign or
  // unknown id is indistinguishable — never confirm another principal's
  // person exists.
  if (personId !== syntheticPersonId(guard.principal)) {
    return NextResponse.json(
      { error: { code: "not_found", message: "no such person" } },
      { status: 404 },
    );
  }

  return NextResponse.json({
    personId,
    events: acceptedTimeline(guard.principal, personId),
    disclosure: syntheticDisclosure(`relationship:${personId}:timeline`),
  });
}
