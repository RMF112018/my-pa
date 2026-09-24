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
import { PageHeader } from "@/components/shell/page-header";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import type { ContinuityWorkspace, SituationRow } from "@/lib/api/decode/capabilities/continuity.situations";
import type { ProjectRow } from "@/lib/api/decode/capabilities/continuity.projects";
import type {
  BackendProject,
  BackendSituation,
  ProjectState,
  SituationState,
} from "@/contracts/views";
import type { PrincipalSession } from "@/contracts/identity";
import {
  diagnosticError,
  diagnosticLimitations,
} from "@/lib/diagnostics/presentation";
import { serverDiagnosticsEnabled } from "@/lib/diagnostics/server";
import { PROJECT_SCOPE_COOKIE, parseProjectScopePreference } from "@/lib/project-scope/preference";
import { ALL_PROJECTS, type ProjectScope } from "@/lib/project-scope/scope";
import { constraintsRoute } from "@/app/(app)/work/projects/[projectId]/constraints/constraint-url-state";

/** The canonical portfolio-wide Constraint route (`work/constraints/page.tsx`). */
const PORTFOLIO_CONSTRAINTS_ROUTE = "/work/constraints";

const BLURB =
  "Situations gather what matters about a project, relationship, or topic into one purposeful " +
  "view. Each references records it does not own, and only accepted records appear.";

/**
 * The Constraints panel's data, read once, server-side, from a real backend
 * aggregate — never a client-side scan of a fetched list.
 *
 * A `PROJECT`-scope read is one Project's own `constraints.overview`
 * (`totalOpen`/`needsAttention`, both counted on that Project's own
 * calendar). An `ALL_PROJECTS`-scope read is `constraints.portfolio_overview`
 * — deliberately *not* summed into one cross-Project total (each entry is
 * counted on its own Project's calendar, and the portfolio capability itself
 * carries no roll-up member for exactly that reason); what this panel shows
 * instead is a count of Projects, which is safe to count regardless of which
 * calendar each one is on.
 */
type ConstraintsPanelData =
  | { readonly kind: "project"; readonly projectId: string; readonly totalOpen: number; readonly needsAttention: number }
  | { readonly kind: "portfolio"; readonly projectsWithOpen: number; readonly needsAttentionProjects: number }
  | { readonly kind: "unavailable" };

async function readConstraintsPanelData(
  principal: PrincipalSession,
  scope: ProjectScope,
): Promise<ConstraintsPanelData> {
  if (scope.kind === "PROJECT") {
    const outcome = await invokeGateway(principal, "constraints.overview", { project_id: scope.projectId });
    if (!outcome.ok) return { kind: "unavailable" };
    return {
      kind: "project",
      projectId: scope.projectId,
      totalOpen: outcome.result.overview.totalOpen,
      needsAttention: outcome.result.overview.needsAttention,
    };
  }
  const outcome = await invokeGateway(principal, "constraints.portfolio_overview", {});
  if (!outcome.ok) return { kind: "unavailable" };
  const projects = outcome.result.overview.projects;
  return {
    kind: "portfolio",
    projectsWithOpen: projects.filter((project) => project.totalOpen > 0).length,
    needsAttentionProjects: projects.filter((project) => project.needsAttention > 0).length,
  };
}

/**
 * The command center's one Constraints tile.
 *
 * `PC-CM-SCOPE-AC-021`: it routes to the exact-Project Constraints route when
 * the current scope names one Project, and to the portfolio Constraints route
 * otherwise — the same scope-aware destination `project-picker.tsx` already
 * lands a scope switch on. `PC-CM-SCOPE-AC-020`: this is the one panel on this
 * page carrying a backend-aggregated figure; Situations and Projects above
 * remain the plain, unaggregated lists they already were.
 */
function ConstraintsPanel({ data }: { data: ConstraintsPanelData }) {
  if (data.kind === "unavailable") {
    return (
      <SurfaceState
        kind="unavailable"
        title="Constraints could not be read"
        testId="work-constraints-unavailable"
      />
    );
  }
  const href = data.kind === "project" ? constraintsRoute(data.projectId) : PORTFOLIO_CONSTRAINTS_ROUTE;
  return (
    <Link
      href={href}
      data-testid="work-constraints-panel"
      className="block rounded-xl border border-moss-slate/10 bg-surface p-4 hover:border-moss-green"
    >
      <h2 className="font-semibold text-moss-slate">Constraints</h2>
      {data.kind === "project" ? (
        <p className="mt-2 text-sm text-moss-slate">
          {data.totalOpen} open
          {data.needsAttention > 0 ? `, ${data.needsAttention} needing attention` : ""}
        </p>
      ) : (
        <p className="mt-2 text-sm text-moss-slate">
          {data.projectsWithOpen} Project{data.projectsWithOpen === 1 ? "" : "s"} with open Constraints
          {data.needsAttentionProjects > 0 ? `, ${data.needsAttentionProjects} needing attention` : ""}
        </p>
      )}
    </Link>
  );
}

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
  // WP07: resolved once per request (memoised) so the diagnostic-bearing
  // props below are never built, and therefore never serialized into the
  // RSC payload, while diagnostics are off.
  const diagnosticsEnabled = await serverDiagnosticsEnabled();
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const heading = <PageHeader headingId="work-heading" title="Situations" description={BLURB} />;
  const projectScope: ProjectScope = parseProjectScopePreference(cookieStore.get(PROJECT_SCOPE_COOKIE)?.value) ?? ALL_PROJECTS;

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

  const [situationsOutcome, projectsOutcome, constraintsPanelData] = await Promise.all([
    invokeGateway(principal, "continuity.situations"),
    invokeGateway(principal, "continuity.projects"),
    readConstraintsPanelData(principal, projectScope),
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
        <ConstraintsPanel data={constraintsPanelData} />
        <SurfaceState
          kind="unavailable"
          title="Situations could not be read"
          error={diagnosticError(diagnosticsEnabled, failure.kind === "unavailable" ? failure.error : undefined)}
          limitations={diagnosticLimitations(diagnosticsEnabled, failure.disclosure.limitations)}
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
      <ConstraintsPanel data={constraintsPanelData} />
      {degraded ? (
        <DegradedBanner
          scope="this board"
          limitations={diagnosticLimitations(diagnosticsEnabled, [
            ...situationsAnswer.disclosure.limitations,
            ...projectsAnswer.disclosure.limitations,
          ])}
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
