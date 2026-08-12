import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME, verifySession } from "@/lib/auth/session";
import {
  syntheticProjects,
  syntheticSituations,
  syntheticPersonId,
} from "@/lib/fixtures/situation";
import { SituationBoard } from "@/components/situation/situation-board";

export const metadata = { title: "Situations — my-pa" };

export default async function SituationsPage() {
  const cookieStore = await cookies();
  const principal = await verifySession(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const situations = syntheticSituations(principal);
  const projects = syntheticProjects(principal);
  const personId = syntheticPersonId(principal);

  return (
    <section aria-labelledby="situations-heading" className="mx-auto max-w-2xl">
      <h1 id="situations-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        Situations
      </h1>
      <p className="mb-4 text-sm text-muted">
        Situations gather what matters about a project, relationship, or topic into one purposeful
        view. Each references records it does not own, and only accepted records appear. Everything
        below is a principal-scoped synthetic fixture; no live sources are connected yet.
      </p>
      <SituationBoard situations={situations} projects={projects} />
      <p className="mt-6 text-sm">
        <Link
          href={`/relationships/${encodeURIComponent(personId)}`}
          className="text-moss-green underline underline-offset-2"
          data-testid="relationship-link"
        >
          Open the relationship timeline for the owner&rsquo;s rep →
        </Link>
      </p>
    </section>
  );
}
