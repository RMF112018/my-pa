/**
 * `/work/projects/[projectId]/constraints` — the canonical Constraint route.
 *
 * Frozen by `CM-FE-AC-002`, and reached under Work → Project Controls →
 * Constraints. The Project identifier is **route identity**: it is a path
 * segment, not a query parameter and not a UI-only filter, so two Projects can
 * never be two states of one address (`02` §2). No new top-level destination is
 * added for it; `components/shell/destinations.ts` already carries Work, and
 * the accepted information architecture places Constraints inside it.
 *
 * **This build has no Constraint backend, and the page says so rather than
 * inventing one.** There is no BFF route and no gateway capability for
 * Constraints at this head. What exists is the synthetic corpus, behind the
 * repository's own `MYPA_DATA_PROVIDER` switch — the same fail-closed gate
 * every other fixture passes. A deployment that has not set it gets an explicit
 * "not built here" state, never an empty Register: rendering zero Constraints
 * for a capability that does not exist would be the exact lie
 * `components/ui/surface-state.tsx` was written to prevent, and
 * `CM-FE-AC-029`/`02` §15 require the two to stay distinct.
 */
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import {
  syntheticConstraintProjects,
  syntheticConstraintWorkspace,
} from "@/lib/fixtures/constraints";
import { SurfaceState } from "@/components/ui/surface-state";
import { PageHeader } from "@/components/shell/page-header";
import { ConstraintsWorkspace } from "./constraints-workspace";
import { parseConstraintUrlState, type RawSearchParams } from "./constraint-url-state";

export const metadata = { title: "Constraints — my-pa" };

export default async function ConstraintsPage({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<RawSearchParams>;
}) {
  const { projectId } = await params;
  const initialState = parseConstraintUrlState(await searchParams);

  if (!syntheticDataEnabled()) {
    return (
      <section className="mx-auto max-w-4xl" data-testid="constraints-not-built">
        <PageHeader title="Constraints" description={`Project Controls · ${projectId}`} />
        <SurfaceState
          kind="not_implemented"
          title="Constraint Management is not served by this build"
          detail={
            "There is no Constraint read capability behind this route yet, so there is nothing to " +
            "ask and retrying cannot change that. No Constraints were invented to fill the space. " +
            "The fixture workspace is served only by a build that explicitly sets " +
            "MYPA_DATA_PROVIDER=synthetic."
          }
          testId="constraints-not-implemented"
        />
      </section>
    );
  }

  const workspace = syntheticConstraintWorkspace(projectId);
  if (workspace === null) {
    return (
      <section className="mx-auto max-w-4xl" data-testid="constraints-project-not-found">
        <PageHeader title="Constraints" description={`Project Controls · ${projectId}`} />
        <SurfaceState
          kind="unavailable"
          title="That Project could not be read"
          detail={`No Project with the identifier ${projectId} was returned. Nothing is claimed about what it holds.`}
          testId="constraints-project-unavailable"
        />
      </section>
    );
  }

  return (
    <ConstraintsWorkspace
      workspace={workspace}
      projects={syntheticConstraintProjects()}
      initialState={initialState}
    />
  );
}
