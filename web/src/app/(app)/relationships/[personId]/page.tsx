/**
 * Relationship timeline — **not backend-backed at this head, and the page says
 * so rather than failing.**
 *
 * This page called `acceptedTimeline` unconditionally. In a default build that
 * is not a page showing fixtures — `lib/fixtures/gate.ts` throws — it is a page
 * that raises an unhandled error, which is fail-loud but is not an answer. The
 * honest answer already exists and is written down in
 * `app/api/relationships/[personId]/timeline/route.ts`: a principal-scoped,
 * accepted-only read model exists in PostgreSQL, no member of the v1 capability
 * set exposes it over the gateway, and wiring one needs a migration *and* the
 * partitioning of a table-wide unique constraint first (NOTE 3 out of WP-04).
 *
 * **No capability is added here and none may be.** This change is the page
 * stating what the route already states; it deliberately does not reach for the
 * relationship plane, because the constraint that makes reaching for it a
 * cross-Principal existence disclosure has not been fixed.
 *
 * The synthetic branch is unchanged, still explicit, and still refuses a foreign
 * or unknown person identically — a person that does not resolve inside the
 * caller's own partition is `not_found`, so a foreign person and an absent one
 * are one answer.
 */
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { acceptedTimeline, syntheticPersonId } from "@/lib/fixtures/situation";
import { RelationshipTimeline } from "@/components/relationship/relationship-timeline";
import { SurfaceState } from "@/components/ui/surface-state";

export const metadata = { title: "Relationship — my-pa" };

const NO_CAPABILITY =
  "A principal-scoped, accepted-only relationship read model exists in the database, but no " +
  "member of the v1 capability set exposes it over the gateway. Adding one requires a schema " +
  "migration, and the relationship plane additionally carries a table-wide unique constraint " +
  "that has to be partitioned before it can be read across Principals safely.";

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
    return (
      <section aria-labelledby="relationship-heading" className="mx-auto max-w-2xl">
        {heading}
        <SurfaceState
          kind="not_implemented"
          title="Relationship timelines are not readable in this build"
          detail={NO_CAPABILITY}
          testId="relationship-not-implemented"
        />
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
