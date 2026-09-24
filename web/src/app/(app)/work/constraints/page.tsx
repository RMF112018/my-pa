/**
 * `/work/constraints` — the canonical portfolio-wide Constraint route.
 *
 * Frozen by `PC-CM-SCOPE-AC-014`. There is no Project segment: a portfolio
 * read derives its Project set from the Principal, server-side, exactly as
 * `constraints.portfolio_overview` itself does (`/api/project-controls/
 * portfolio/constraints/overview`) — this route never asks the browser which
 * Projects to include and never enumerates them client-side.
 *
 * **One backend aggregate, not a client roll-up.** Each row here is one owned
 * Project's own `ConstraintOverview`, counted on that Project's own calendar;
 * there is deliberately no summed portfolio-wide total, for the same reason
 * `constraints.portfolio_overview`'s own decoder carries none (`03` — a sum
 * across different Project calendars is not a figure any backend answer could
 * be checked against).
 *
 * **This is the portfolio's landing surface, not a cross-Project row-level
 * Register.** `constraints.portfolio_list`/`portfolio_search` (the BFF's
 * `GET /api/project-controls/portfolio/constraints`) exist and are exercised
 * by this feature's contract tests, but no row-level cross-Project browsing
 * UI is built against them here — each Project's own full Register remains
 * the canonical place to browse, filter, search and (per
 * `PC-CM-SCOPE-AC-029`) author its Constraints; this page's Project cards link
 * straight into it. See the Phase 5-6 handoff for why that scope line was
 * drawn here.
 */
import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { SurfaceState } from "@/components/ui/surface-state";
import { constraintsRoute } from "@/app/(app)/work/projects/[projectId]/constraints/constraint-url-state";

export const metadata = { title: "Constraints — my-pa" };

export default async function PortfolioConstraintsPage() {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const heading = <PageHeader title="Constraints" description="Project Controls · every Project you own" />;

  if (syntheticDataEnabled()) {
    return (
      <section className="mx-auto max-w-4xl" data-testid="portfolio-constraints-synthetic">
        {heading}
        <SurfaceState
          kind="not_implemented"
          title="The portfolio Constraint view is not part of the fixture build"
          detail="Open a Project's own Constraints tab to see its fixture Register."
          testId="portfolio-constraints-not-implemented"
        />
      </section>
    );
  }

  const outcome = await invokeGateway(principal, "constraints.portfolio_overview", {});
  if (!outcome.ok) {
    return (
      <section className="mx-auto max-w-4xl" data-testid="portfolio-constraints-page">
        {heading}
        <SurfaceState kind="unavailable" title="The portfolio Constraint position could not be read" testId="portfolio-constraints-unavailable" />
      </section>
    );
  }

  const { projects, omittedProjects } = outcome.result.overview;

  return (
    <section className="mx-auto max-w-4xl" data-testid="portfolio-constraints-page">
      {heading}
      <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="portfolio-context">
        <Badge tone="neutral">All Projects</Badge>
        <Badge tone="green">Live read plane</Badge>
      </div>
      {omittedProjects > 0 ? (
        <p className="mt-2 text-sm text-muted" data-testid="portfolio-omitted-projects">
          {omittedProjects} owned Project{omittedProjects === 1 ? "" : "s"} could not be counted and{" "}
          {omittedProjects === 1 ? "is" : "are"} not shown below.
        </p>
      ) : null}
      {projects.length === 0 ? (
        <SurfaceState
          kind="empty"
          title="No Project has a countable Constraint position"
          detail="The read succeeded and returned nothing to show."
          testId="portfolio-constraints-empty"
        />
      ) : (
        <ul className="mt-4 grid gap-3 sm:grid-cols-2" data-testid="portfolio-project-list">
          {projects.map((project) => (
            <li key={project.projectId}>
              <Link
                href={constraintsRoute(project.projectId)}
                data-testid={`portfolio-project-${project.projectId}`}
                className="block rounded-xl border border-moss-slate/10 bg-surface p-4 hover:border-moss-green"
              >
                <h2 className="font-semibold text-moss-slate">{project.projectName ?? project.projectId}</h2>
                <p className="mt-2 text-sm text-moss-slate">
                  {project.totalOpen} open
                  {project.overdue > 0 ? `, ${project.overdue} overdue` : ""}
                  {project.needsAttention > 0 ? `, ${project.needsAttention} needing attention` : ""}
                </p>
                {project.draft > 0 ? (
                  <p className="mt-1 text-xs text-muted">{project.draft} Draft{project.draft === 1 ? "" : "s"}</p>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
