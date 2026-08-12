/**
 * Situations — served from the Python gateway by default (WP-11).
 *
 * Two capabilities, because the page shows two things and they are two grants:
 * `continuity.situations` and `continuity.projects`. Both are principal-scoped
 * at the persistence boundary, and neither echoes a Principal back — the session
 * cookie is the only identity carrier this tier has.
 *
 * The synthetic branch is unchanged and still requires `MYPA_DATA_PROVIDER`;
 * there is no fallback between the two, so a failed gateway is stated rather
 * than replaced with fixtures or with an empty board.
 */
import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import {
  syntheticProjects,
  syntheticSituations,
  syntheticPersonId,
} from "@/lib/fixtures/situation";
import { callGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { SituationBoard } from "@/components/situation/situation-board";
import { BackendSituationBoard } from "@/components/situation/backend-situation-board";
import { NotConnected } from "@/components/ui/not-connected";
import type {
  BackendProject,
  BackendSituation,
  ProjectState,
  SituationState,
} from "@/contracts/views";

export const metadata = { title: "Situations — my-pa" };

const BLURB =
  "Situations gather what matters about a project, relationship, or topic into one purposeful " +
  "view. Each references records it does not own, and only accepted records appear.";

interface PythonSituation {
  readonly situation_id: string;
  readonly title: string;
  readonly state: string;
  readonly description: string | null;
  readonly object_refs: readonly string[];
  readonly opened_at: string;
  readonly closed_at: string | null;
  readonly outcome: string | null;
}

interface PythonProject {
  readonly project_id: string;
  readonly name: string;
  readonly state: string;
  readonly description: string | null;
  readonly participants: readonly string[];
  readonly opened_at: string;
  readonly closed_at: string | null;
}

function toSituation(row: PythonSituation): BackendSituation {
  return {
    situationId: row.situation_id,
    title: row.title,
    state: row.state as SituationState,
    description: row.description,
    objectRefs: row.object_refs,
    openedAt: row.opened_at,
    closedAt: row.closed_at,
    outcome: row.outcome,
  };
}

function toProject(row: PythonProject): BackendProject {
  return {
    projectId: row.project_id,
    name: row.name,
    state: row.state as ProjectState,
    description: row.description,
    participants: row.participants,
    openedAt: row.opened_at,
    closedAt: row.closed_at,
  };
}

export default async function SituationsPage() {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const heading = (
    <>
      <h1 id="situations-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        Situations
      </h1>
      <p className="mb-4 text-sm text-muted">{BLURB}</p>
    </>
  );

  if (syntheticDataEnabled()) {
    const personId = syntheticPersonId(principal);
    return (
      <section aria-labelledby="situations-heading" className="mx-auto max-w-2xl">
        {heading}
        <SituationBoard
          situations={syntheticSituations(principal)}
          projects={syntheticProjects(principal)}
        />
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

  const [situationsOutcome, projectsOutcome] = await Promise.all([
    callGateway<{ situations?: readonly PythonSituation[] }>(principal, "continuity.situations"),
    callGateway<{ projects?: readonly PythonProject[] }>(principal, "continuity.projects"),
  ]);

  if (!situationsOutcome.ok || !projectsOutcome.ok) {
    const failure = situationsOutcome.ok ? projectsOutcome : situationsOutcome;
    return (
      <section aria-labelledby="situations-heading" className="mx-auto max-w-2xl">
        {heading}
        <NotConnected
          title="Situations could not be read"
          description={failure.ok ? "" : failure.error.message}
          arrivesWith="This is a stated failure, not an empty board. Nothing was read and nothing is claimed."
        />
      </section>
    );
  }

  return (
    <section aria-labelledby="situations-heading" className="mx-auto max-w-2xl">
      {heading}
      <BackendSituationBoard
        situations={(situationsOutcome.result.situations ?? []).map(toSituation)}
        projects={(projectsOutcome.result.projects ?? []).map(toProject)}
      />
    </section>
  );
}
