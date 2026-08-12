import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { SESSION_COOKIE_NAME, verifySession } from "@/lib/auth/session";
import { acceptedTimeline, syntheticPersonId } from "@/lib/fixtures/situation";
import { RelationshipTimeline } from "@/components/relationship/relationship-timeline";

export const metadata = { title: "Relationship — my-pa" };

export default async function RelationshipPage({
  params,
}: {
  params: Promise<{ personId: string }>;
}) {
  const cookieStore = await cookies();
  const principal = await verifySession(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const { personId } = await params;

  // A person that does not resolve within the caller's own partition is
  // not_found — a foreign person and an unknown person are indistinguishable.
  if (personId !== syntheticPersonId(principal)) notFound();

  const events = acceptedTimeline(principal, personId);

  return (
    <section aria-labelledby="relationship-heading" className="mx-auto max-w-2xl">
      <h1 id="relationship-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        Relationship timeline
      </h1>
      <p className="mb-4 text-sm text-muted">
        A continuity view of accepted interactions, meetings, and commitments for this person.
        Everything below is a principal-scoped synthetic fixture; no live sources are connected
        yet.
      </p>
      <RelationshipTimeline events={events} />
    </section>
  );
}
