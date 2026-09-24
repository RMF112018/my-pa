/**
 * `/work/constraints` — the canonical portfolio-wide Constraint route.
 *
 * Frozen by `PC-CM-SCOPE-AC-014`. There is no Project segment: a portfolio
 * read derives its Project set from the Principal, server-side, exactly as
 * `constraints.portfolio_overview` itself does (`/api/project-controls/
 * portfolio/constraints/overview`) — this route never asks the browser which
 * Projects to include and never enumerates them client-side.
 *
 * **A real, row-level, cross-Project Constraint Register** — the controlling
 * plan's §6.1 ("one shared/adapted workspace rather than a parallel product")
 * and §6.2 ("Portfolio data"), corrected into this file after an earlier
 * per-Project-card version was ruled a material gap against that plan. The
 * interactive body is `PortfolioConstraintsRegister`, a thin client adaptation
 * of the exact-Project Register's own `ConstraintsRegister`/`RegisterTable`,
 * reading `constraints.portfolio_list`/`portfolio_search` — see that file's
 * own doc comment for the row-open/navigation contract and for why its view
 * state is not URL-synced (disclosed scope line, not an oversight).
 *
 * **Two distinct disclosures, never conflated.** This server component keeps
 * its own `constraints.portfolio_overview` read for the top-level
 * `omittedProjects` figure and the page's `unavailable` gate — a read of
 * *positions*, on each Project's own calendar. `PortfolioConstraintsRegister`
 * keeps its own, separate `omittedProjects` from its own `portfolio_list`/
 * `portfolio_search` read — a read of *rows*, for whichever query is currently
 * applied. The two can differ (a different read, a different instant, a
 * different query) and neither stands in for the other.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { PageHeader } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { SurfaceState } from "@/components/ui/surface-state";
import { PortfolioConstraintsRegister } from "./portfolio-constraints-register";

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

  const { omittedProjects } = outcome.result.overview;

  return (
    <section className="mx-auto max-w-4xl" data-testid="portfolio-constraints-page">
      {heading}
      <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="portfolio-context">
        <Badge tone="neutral">All Projects</Badge>
        <Badge tone="green">Live read plane</Badge>
      </div>
      {omittedProjects > 0 ? (
        <p className="mt-2 text-sm text-muted" data-testid="portfolio-omitted-projects">
          {omittedProjects} owned Project{omittedProjects === 1 ? "" : "s"} could not be counted for
          the Project position summary.
        </p>
      ) : null}
      <div className="mt-4">
        <PortfolioConstraintsRegister />
      </div>
    </section>
  );
}
