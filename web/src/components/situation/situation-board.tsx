"use client";

/**
 * Situation board — WP-06 (R5).
 *
 * Gathers the principal's Situations and Projects into one purposeful view.
 * A Situation references objects it does not own (product package
 * `09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`), so the board shows what each
 * Situation points at without claiming authority over it. Every record here
 * is principal-scoped by the server; a foreign Situation or Project never
 * reaches this component. Nothing is asserted — a Situation is a lens, not a
 * promotion.
 */
import type { Project, Situation } from "@/contracts/views";
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

export function SituationBoard({
  situations,
  projects,
}: {
  situations: readonly Situation[];
  projects: readonly Project[];
}) {
  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="board-situations">
        <h2 id="board-situations" className="mb-2 text-sm font-semibold text-moss-slate">
          Situations
        </h2>
        {situations.length === 0 ? (
          <p className="text-sm text-muted">No situations are open right now.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {situations.map((s) => (
              <li key={s.situationId}>
                <Card data-testid="situation-card">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle>{s.title}</CardTitle>
                    <div className="flex shrink-0 gap-1">
                      <Badge tone="neutral">{s.kind}</Badge>
                      <Badge tone={SITUATION_STATE_TONE[s.state]}>{s.state}</Badge>
                    </div>
                  </div>
                  <CardBody>
                    {s.description ? <p>{s.description}</p> : null}
                    <p className="mt-2 text-xs text-muted">
                      References {s.referencedObjectIds.length} object
                      {s.referencedObjectIds.length === 1 ? "" : "s"} it does not own.
                    </p>
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
        {projects.length === 0 ? (
          <p className="text-sm text-muted">No projects yet.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {projects.map((p) => (
              <li key={p.projectId}>
                <Card data-testid="project-card">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle>{p.name}</CardTitle>
                    <Badge tone={PROJECT_STATE_TONE[p.state]}>{p.state.replace("_", " ")}</Badge>
                  </div>
                  <CardBody>
                    {p.description ? <p>{p.description}</p> : null}
                    {p.participants.length > 0 ? (
                      <p className="mt-2 text-xs text-muted">
                        Participants: {p.participants.join(", ")}
                      </p>
                    ) : null}
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
