/**
 * `/work/projects/[projectId]` — the canonical, scoped single-Project Work
 * route (`PC-CM-SCOPE-AC-013`).
 *
 * `work/projects/[projectId]/layout.tsx` (Impl-2, already landed) already
 * resolves and binds this segment's Project scope for every route beneath
 * it — including this one — and already re-verifies the session, so this
 * page adds neither.
 *
 * **What this route is, today.** Constraints is the only Project Controls
 * surface with a live Register at this head; Situations has no Project
 * filter in its own read contract, and the Tasks/Commitments Workbench is
 * portfolio-wide. Building a new per-Project aggregation across surfaces that
 * do not yet support one would be inventing product scope this dispatch does
 * not name (`AGENTS.md` §2's "smallest correct implementation" and the stop
 * condition against guessing at unspecified product behavior). So the
 * canonical single-Project Work destination *is*, for now, that Project's
 * canonical Constraints route — the one genuinely Project-scoped, live
 * surface that exists — and this route forwards to it rather than composing
 * a placeholder dashboard around nothing. `PC-CM-SCOPE-AC-015` (the
 * Constraints route's own identity stays unchanged) is a route it forwards
 * to, not a route it becomes.
 *
 * A later phase that adds a second Project-scoped surface is the point at
 * which this route earns its own composition, exactly as `work-page.tsx` (the
 * portfolio command center) composes Situations, Projects and now
 * Constraints today.
 */
import { redirect } from "next/navigation";
import { constraintsRoute } from "./constraints/constraint-url-state";

export const metadata = { title: "Work — my-pa" };

export default async function ProjectWorkPage({
  params,
}: {
  readonly params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  redirect(constraintsRoute(projectId));
}
