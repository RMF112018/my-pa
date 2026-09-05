/**
 * Work — served from the Python gateway by default (WP-11).
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
import { invokeGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { SituationBoard } from "@/components/situation/situation-board";
import { BackendSituationBoard } from "@/components/situation/backend-situation-board";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import type { ContinuityWorkspace, SituationRow } from "@/lib/api/decode/capabilities/continuity.situations";
import type { ProjectRow } from "@/lib/api/decode/capabilities/continuity.projects";
import type {
  BackendProject,
  BackendSituation,
  ProjectState,
  SituationState,
} from "@/contracts/views";

const BLURB =
  "Situations gather what matters about a project, relationship, or topic into one purposeful " +
  "view. Each references records it does not own, and only accepted records appear.";

function ContinuityWorkspacePanel({ data }: { data: ContinuityWorkspace }) {
  const groups = [
    ["Frames", data.frames, (item: { label: string }) => item.label],
    ["Trace", data.traces, (item: { object_type: string; object_id: string }) => `${item.object_type}: ${item.object_id}`],
    ["Commitments", data.commitments, (item: { summary: string }) => item.summary],
    ["Decisions", data.decisions, (item: { question: string }) => item.question],
    ["Tasks", data.tasks, (item: { title: string }) => item.title],
  ] as const;
  return (
    <section aria-label="Continuity workspace" className="mt-8 grid gap-4 sm:grid-cols-2">
      {groups.map(([label, items, describe]) => (
        <article key={label} className="rounded-xl border border-moss-slate/10 bg-surface p-4">
          <h2 className="font-semibold text-moss-slate">{label}</h2>
          {items.length === 0 ? (
            <p className="mt-2 text-sm text-muted">No accepted {label.toLowerCase()}.</p>
          ) : (
            <ul className="mt-2 space-y-2 text-sm">
              {items.map((item) => (
                <li key={Object.values(item)[0] as string}>{describe(item as never)}</li>
              ))}
            </ul>
          )}
        </article>
      ))}
    </section>
  );
}

function toSituation(row: SituationRow): BackendSituation {
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

function toProject(row: ProjectRow): BackendProject {
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

export async function WorkPage() {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const heading = (
    <>
      <h1 id="work-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        Situations
      </h1>
      <p className="mb-4 text-sm text-muted">{BLURB}</p>
    </>
  );

  if (syntheticDataEnabled()) {
    const personId = syntheticPersonId(principal);
    return (
      <section aria-labelledby="work-heading" className="mx-auto max-w-2xl">
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
    invokeGateway(principal, "continuity.situations"),
    invokeGateway(principal, "continuity.projects"),
  ]);

  const situationsAnswer = surfaceAnswer(
    "situations:continuity.situations",
    situationsOutcome,
    (result) => result.situations.length,
  );
  const projectsAnswer = surfaceAnswer(
    "situations:continuity.projects",
    projectsOutcome,
    (result) => result.projects.length,
  );

  // **Either read failing makes the whole board unavailable, and it is not
  // partially rendered.** The board is one claim about a Principal's live work;
  // showing the half that answered beside a silently missing half would present
  // an incomplete picture as a whole one, and the reader has no way to see the
  // difference. A partial *answer* is different — the backend says so, and that
  // is the `degraded` branch below.
  if (situationsAnswer.kind === "unavailable" || projectsAnswer.kind === "unavailable") {
    const failure =
      situationsAnswer.kind === "unavailable" ? situationsAnswer : projectsAnswer;
    return (
      <section aria-labelledby="work-heading" className="mx-auto max-w-2xl">
        {heading}
        <SurfaceState
          kind="unavailable"
          title="Situations could not be read"
          detail={failure.kind === "unavailable" ? failure.error.message : ""}
          limitations={failure.disclosure.limitations}
          testId="situations-unavailable"
        />
      </section>
    );
  }

  const situations =
    situationsAnswer.kind === "empty" ? [] : situationsAnswer.result.situations.map(toSituation);
  const projects =
    projectsAnswer.kind === "empty" ? [] : projectsAnswer.result.projects.map(toProject);
  const degraded = situationsAnswer.kind === "degraded" || projectsAnswer.kind === "degraded";

  return (
    <section aria-labelledby="work-heading" className="mx-auto max-w-2xl">
      {heading}
      {degraded ? (
        <DegradedBanner
          scope="this board"
          limitations={[
            ...situationsAnswer.disclosure.limitations,
            ...projectsAnswer.disclosure.limitations,
          ]}
          truncated={
            situationsAnswer.disclosure.truncated || projectsAnswer.disclosure.truncated
          }
        />
      ) : null}
      {situations.length === 0 && projects.length === 0 ? (
        // A partial answer that carried nothing is not an empty board, and the
        // distinction is made here for the same reason Today, Library and Review
        // make it: the rows may exist and simply not have been returned, so the
        // only truthful thing to say is that the read was incomplete.
        degraded ? (
          <SurfaceState
            kind="degraded"
            title="The board was read incompletely and returned nothing"
            detail={
              "An empty board is not established by a partial read. Situations or projects may " +
              "exist that this answer did not cover."
            }
            testId="situations-degraded-empty"
          />
        ) : (
          <SurfaceState
            kind="empty"
            title="You hold no situations or projects"
            detail={
              "Both were read successfully and both are empty. Nothing failed; there is simply " +
              "nothing recorded yet."
            }
            testId="situations-empty"
          />
        )
      ) : (
        // One half may be empty while the other carried rows. Whether *that*
        // half's emptiness was established is per-answer, not per-board, so each
        // answer's own partiality is carried down rather than the board-wide OR.
        <BackendSituationBoard
          situations={situations}
          projects={projects}
          situationsPartial={situationsAnswer.kind === "degraded"}
          projectsPartial={projectsAnswer.kind === "degraded"}
        />
      )}
      {situationsAnswer.kind === "empty" ||
      situationsAnswer.result.relationship_events === undefined ? null : (
        <ContinuityWorkspacePanel data={situationsAnswer.result as ContinuityWorkspace} />
      )}
    </section>
  );
}
