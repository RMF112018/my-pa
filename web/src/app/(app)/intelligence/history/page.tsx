/**
 * Intelligence history — artifacts grouped by backend report date / cycle.
 *
 * Business date comes from reports.resolve_set. List order is the fallback
 * when a cycle has no resolver date. The browser clock is never "current".
 */
import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway, type GatewayOutcome } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { FeatureRouteState } from "@/components/shell/feature-route-state";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardTitle } from "@/components/ui/card";
import { ReportListing } from "@/components/intelligence/report-card";
import {
  groupArtifactsByCycle,
  REPORT_IDENTIFIER,
  resolveSetPayload,
  type CycleDate,
} from "@/components/intelligence/cycle-selection";
import { intelligenceHome, intelligenceHistory } from "@/lib/routes/intelligence";
import type { ReportsListResult } from "@/lib/api/decode/capabilities/reports.list";
import type { ReportsResolveSetResult } from "@/lib/api/decode/capabilities/reports.resolve_set";
import type { PrincipalSession } from "@/contracts/identity";

export const metadata = { title: "Intelligence history — my-pa" };
export const dynamic = "force-dynamic";

const BLURB = "Prior Morning Intelligence runs, dated by the report plane.";

async function datesForCycles(
  principal: PrincipalSession,
  cycleRunIds: readonly string[],
): Promise<readonly CycleDate[]> {
  const unique = [...new Set(cycleRunIds)];
  const rows = await Promise.all(
    unique.map(async (cycle_run_id) => {
      const outcome = (await invokeGateway(
        principal,
        "reports.resolve_set",
        resolveSetPayload(cycle_run_id),
      )) as GatewayOutcome<ReportsResolveSetResult>;
      if (!outcome.ok) return null;
      return {
        cycle_run_id: outcome.result.cycle_run_id,
        business_date: outcome.result.business_date,
      };
    }),
  );
  return rows.filter((row): row is CycleDate => row !== null);
}

export default async function IntelligenceHistoryPage({
  searchParams,
}: {
  searchParams: Promise<{ cycleRunId?: string }>;
}) {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const { cycleRunId: requested } = await searchParams;
  const focus =
    typeof requested === "string" && REPORT_IDENTIFIER.test(requested) ? requested : undefined;

  const heading = (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 id="intelligence-history-heading" className="mb-1 text-xl font-semibold text-moss-slate">
          Intelligence history
        </h1>
        <p className="text-sm text-muted">{BLURB}</p>
      </div>
      <Link
        href={intelligenceHome()}
        className="inline-flex min-h-[var(--control-height)] items-center text-sm text-moss-green underline"
      >
        Current Intelligence
      </Link>
    </div>
  );

  const frame = (children: React.ReactNode) => (
    <section aria-labelledby="intelligence-history-heading" className="mx-auto max-w-4xl">
      {heading}
      {children}
    </section>
  );

  if (syntheticDataEnabled()) {
    return (
      <FeatureRouteState
        title="Intelligence history"
        description={BLURB}
        state="not_implemented"
        detail="The synthetic provider has no report fixture. Report reads require the executable Python Intelligence plane."
      />
    );
  }

  const answer = surfaceAnswer(
    "intelligence:history:reports.list",
    (await invokeGateway(principal, "reports.list", {
      include_superseded: true,
    })) as GatewayOutcome<ReportsListResult>,
    (result) => result.items.length,
  );

  if (answer.kind === "unavailable") {
    return frame(
      <SurfaceState
        kind="unavailable"
        title="Report history could not be read"
        detail={answer.error.message}
        limitations={answer.disclosure.limitations}
        testId="intelligence-history-unavailable"
      />,
    );
  }

  if (answer.kind === "empty") {
    return frame(
      <SurfaceState
        kind="empty"
        title="No report history is stored"
        detail="The report plane was read and it holds no artifact for this Principal."
        testId="intelligence-history-empty"
      />,
    );
  }

  const items = answer.result.items;
  const dates = await datesForCycles(
    principal,
    items.map((item) => item.cycle_run_id),
  );
  const groups = groupArtifactsByCycle(items, dates).filter((group) =>
    focus ? group.cycle_run_id === focus : true,
  );

  const listing = (
    <div className="flex flex-col gap-6" data-testid="intelligence-history">
      {groups.length === 0 ? (
        <SurfaceState
          kind="unavailable"
          title="That cycle is not in the listed history"
          detail="The requested cycle_run_id did not match a listed artifact. This is not an empty history."
          testId="intelligence-history-unknown-cycle"
        />
      ) : (
        groups.map((group) => (
          <section
            key={group.cycle_run_id}
            aria-labelledby={`cycle-${group.cycle_run_id}`}
            data-testid="intelligence-history-cycle"
            data-current={group.current ? "true" : "false"}
          >
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h2
                id={`cycle-${group.cycle_run_id}`}
                className="text-base font-semibold text-moss-slate"
              >
                {group.business_date ?? "Business date not resolved"}
              </h2>
              {group.current ? <Badge tone="green">Current cycle</Badge> : <Badge tone="neutral">Prior cycle</Badge>}
            </div>
            <Card className="mb-3">
              <CardTitle>Cycle</CardTitle>
              <CardBody>
                <p className="break-all font-mono text-xs">{group.cycle_run_id}</p>
                <Link
                  href={intelligenceHistory(group.cycle_run_id)}
                  className="mt-2 inline-flex min-h-[var(--control-height)] items-center text-sm text-moss-green underline"
                >
                  Open this run
                </Link>
              </CardBody>
            </Card>
            <ReportListing
              items={group.items}
              currentCycle={group.current ? group.cycle_run_id : null}
            />
          </section>
        ))
      )}
    </div>
  );

  if (answer.kind === "degraded") {
    return frame(
      <>
        <DegradedBanner
          scope="report history"
          limitations={answer.disclosure.limitations}
          truncated={answer.disclosure.truncated}
        />
        {answer.rowCount === 0 ? (
          <SurfaceState
            kind="degraded"
            title="History was read incompletely and returned nothing"
            detail="An empty history is not established by an incomplete read."
            testId="intelligence-history-degraded-empty"
          />
        ) : (
          listing
        )}
      </>,
    );
  }

  return frame(listing);
}
