/** Relationship timeline from the accepted, Principal-scoped continuity model. */
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { invokeGateway } from "@/lib/api/gateway";
import { acceptedTimeline, syntheticPersonId } from "@/lib/fixtures/situation";
import { RelationshipTimeline } from "@/components/relationship/relationship-timeline";
import { SurfaceState } from "@/components/ui/surface-state";
import type { ContinuitySituationsResult } from "@/lib/api/decode/capabilities/continuity.situations";

export const metadata = { title: "Relationship — my-pa" };

export default async function RelationshipPage({
  params,
}: {
  params: Promise<{ personId: string }>;
}) {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const { personId } = await params;

  const heading = (
    <>
      <h1 id="relationship-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        Relationship timeline
      </h1>
      <p className="mb-4 text-sm text-muted">
        A continuity view of accepted interactions, meetings, and commitments for one person.
      </p>
    </>
  );

  if (!syntheticDataEnabled()) {
    const outcome = await invokeGateway(principal, "continuity.situations");
    if (!outcome.ok) {
      return (
        <section aria-labelledby="relationship-heading" className="mx-auto max-w-2xl">
          {heading}
          <SurfaceState
            kind="unavailable"
            title="Relationship timeline could not be read"
            detail={outcome.error.message}
            testId="relationship-unavailable"
          />
        </section>
      );
    }
    const result = outcome.result as ContinuitySituationsResult;
    if (result.relationship_events === undefined) {
      return (
        <section aria-labelledby="relationship-heading" className="mx-auto max-w-2xl">
          {heading}
          <SurfaceState
            kind="unavailable"
            title="Relationship timeline could not be read"
            detail="the gateway result did not match the capability contract"
            testId="relationship-unavailable"
          />
        </section>
      );
    }
    const events = result.relationship_events
      .filter((event) => event.person_id === personId)
      .map((event) => ({
        eventId: event.event_id,
        principalId: principal.principalId,
        personId: event.person_id,
        eventType: event.event_type,
        occurredAt: event.occurred_at,
        context: event.context,
        accepted: true,
        sourceRef: event.source_ref,
      }));
    return (
      <section aria-labelledby="relationship-heading" className="mx-auto max-w-2xl">
        {heading}
        <RelationshipTimeline events={events} />
      </section>
    );
  }

  // A person that does not resolve within the caller's own partition is
  // not_found — a foreign person and an unknown person are indistinguishable.
  if (personId !== syntheticPersonId(principal)) notFound();

  return (
    <section aria-labelledby="relationship-heading" className="mx-auto max-w-2xl">
      {heading}
      <p className="mb-3 text-sm text-muted">
        This build is serving the synthetic provider. Everything below is a principal-scoped
        fixture; no live source is connected.
      </p>
      <RelationshipTimeline events={acceptedTimeline(principal, personId)} />
    </section>
  );
}
