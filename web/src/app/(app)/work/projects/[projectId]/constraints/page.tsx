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
 * The normal path is the WP08 same-origin read BFF. An explicit synthetic-data
 * switch retains the accepted fixture workspace for development and unit
 * evidence only. The two paths are selected here and never fall through into
 * one another, so a failed live read cannot be rendered as fixture truth.
 */
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import {
  syntheticConstraintProjects,
  syntheticConstraintWorkspace,
} from "@/lib/fixtures/constraints";
import { SurfaceState } from "@/components/ui/surface-state";
import { PageHeader } from "@/components/shell/page-header";
import { ConstraintsWorkspace } from "./constraints-workspace";
import { LiveConstraintsWorkspace } from "./live-constraints-workspace";
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
    return <LiveConstraintsWorkspace projectId={projectId} initialState={initialState} />;
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
