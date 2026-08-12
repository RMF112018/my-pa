/**
 * Situations and Projects as the backend returns them.
 *
 * Separate from `SituationBoard` for the reason `BackendSituation` is separate
 * from `Situation`: the fixture rows carry a `kind` and a per-row disclosure
 * that a real row does not, and rendering the two through one component would
 * mean inventing both. What a real Situation carries instead — the objects it
 * *references without owning*, and, once closed, the outcome it recorded — is
 * shown here, and a closed Situation says when it closed.
 *
 * **A section with no rows is only called empty when the answer that produced it
 * was whole.** The two halves come from two capabilities and either may come
 * back partial on its own, so each is told whether its own answer was partial;
 * a partial half with no rows says the read was incomplete instead of asserting
 * that the Principal holds none.
 */
import type { BackendProject, BackendSituation } from "@/contracts/views";
import { Card, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const SITUATION_STATE_TONE = {
  open: "neutral",
  active: "green",
  suspended: "gold",
  closed: "neutral",
} as const;

const PROJECT_STATE_TONE = {
  active: "green",
  on_hold: "gold",
  closed: "neutral",
} as const;

export function BackendSituationBoard({
  situations,
  projects,
  situationsPartial = false,
  projectsPartial = false,
}: {
  situations: readonly BackendSituation[];
  projects: readonly BackendProject[];
  /** Whether the answer these situations came from said it was partial. */
  situationsPartial?: boolean;
  /** Whether the answer these projects came from said it was partial. */
  projectsPartial?: boolean;
}) {
  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="board-situations">
        <h2 id="board-situations" className="mb-2 text-sm font-semibold text-moss-slate">
          Situations
        </h2>
        {situations.length === 0 && situationsPartial ? (
          <p className="text-sm text-muted" data-testid="situations-partial-empty">
            This answer was partial and returned no situation, so whether you hold any is not
            established here. What is shown may be incomplete.
          </p>
        ) : situations.length === 0 ? (
          <p className="text-sm text-muted" data-testid="situations-empty">
            You hold no situations yet.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {situations.map((s) => (
              <li key={s.situationId}>
                <Card data-testid="situation-card">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle>{s.title}</CardTitle>
                    <Badge tone={SITUATION_STATE_TONE[s.state]}>{s.state}</Badge>
                  </div>
                  <CardBody>
                    {s.description ? <p>{s.description}</p> : null}
                    <p className="mt-2 text-xs text-muted">
                      References {s.objectRefs.length} object(s), and owns none of them.
                    </p>
                    {s.outcome ? (
                      <p className="mt-1 text-xs text-muted">Outcome: {s.outcome}</p>
                    ) : null}
                  </CardBody>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="board-projects">
        <h2 id="board-projects" className="mb-2 text-sm font-semibold text-moss-slate">
          Projects
        </h2>
        {projects.length === 0 && projectsPartial ? (
          <p className="text-sm text-muted" data-testid="projects-partial-empty">
            This answer was partial and returned no project, so whether you hold any is not
            established here. What is shown may be incomplete.
          </p>
        ) : projects.length === 0 ? (
          <p className="text-sm text-muted" data-testid="projects-empty">
            You hold no projects yet.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {projects.map((p) => (
              <li key={p.projectId}>
                <Card data-testid="project-card">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle>{p.name}</CardTitle>
                    <Badge tone={PROJECT_STATE_TONE[p.state]}>{p.state}</Badge>
                  </div>
                  <CardBody>
                    {p.description ? <p>{p.description}</p> : null}
                    <p className="mt-2 text-xs text-muted">
                      {p.participants.length} participant(s).
                    </p>
                  </CardBody>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
