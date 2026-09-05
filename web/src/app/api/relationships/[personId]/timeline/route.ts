/** Accepted relationship events from the Principal-scoped continuity read model. */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { backendDisclosure, invokeGateway, transportLimitations } from "@/lib/api/gateway";
import { acceptedTimeline, syntheticPersonId } from "@/lib/fixtures/situation";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

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
  if (serving.kind === "backend") {
    const outcome = await invokeGateway(guard.principal, "continuity.situations");
    if (!outcome.ok) return gatewayRefusal(scope, outcome.status, outcome.error);
    const result = outcome.result;
    if (result.relationship_events === undefined) {
      return gatewayRefusal(scope, 503, {
        errorClass: "unavailable",
        code: "upstream_contract_invalid",
        message: "the gateway result did not match the capability contract",
      });
    }
    const events = result.relationship_events
      .filter((event) => event.person_id === personId)
      .map((event) => ({
        eventId: event.event_id,
        principalId: guard.principal.principalId,
        personId: event.person_id,
        eventType: event.event_type,
        occurredAt: event.occurred_at,
        context: event.context,
        accepted: true,
        sourceRef: event.source_ref,
      }));
    return NextResponse.json({
      shape: "backend",
      personId,
      events,
      disclosure: backendDisclosure(scope, outcome.disclosure, transportLimitations()),
    });
  }

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
