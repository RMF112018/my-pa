/**
 * Intelligence — Morning Intelligence working surface on the WP11 reports plane.
 *
 * Current cycle is the first listed artifact's cycle_run_id unless
 * reports.resolve_set later supplies business_date for grouping on History.
 * reports.list entries do not carry committed_at or report_date. The browser
 * clock is never a business date. structured_content is opaque; markdown is
 * not scraped into Brief items.
 */
import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { FeatureRouteState } from "@/components/shell/feature-route-state";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import { ReportListing } from "@/components/intelligence/report-card";
import { ReadinessPanel, type ReadinessAnswer } from "@/components/intelligence/readiness-panel";
import { readinessAnswerFromOutcome } from "@/lib/api/intelligence-readiness";
import {
  currentCycleRunId,
  resolveSetPayload,
} from "@/components/intelligence/cycle-selection";
import { intelligenceHistory } from "@/lib/routes/intelligence";
import type { PrincipalSession } from "@/contracts/identity";

export const metadata = { title: "Intelligence — my-pa" };
export const dynamic = "force-dynamic";

const SCOPE = "intelligence";
const BLURB = "Evidence-grounded reports and briefs.";

async function loadReadiness(
  principal: PrincipalSession,
  cycleRunId: string,
): Promise<ReadinessAnswer> {
  return readinessAnswerFromOutcome(
    `${SCOPE}:reports.resolve_set`,
    await invokeGateway(principal, "reports.resolve_set", resolveSetPayload(cycleRunId)),
  );
}

export default async function IntelligencePage() {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const heading = (
    <>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 id="intelligence-heading" className="mb-1 text-xl font-semibold text-moss-slate">
            Intelligence
          </h1>
          <p className="text-sm text-muted">{BLURB}</p>
        </div>
        <Link
          href={intelligenceHistory()}
          className="inline-flex min-h-[var(--control-height)] items-center text-sm text-moss-green underline"
        >
          History
        </Link>
      </div>
    </>
  );

  const frame = (children: React.ReactNode) => (
    <section aria-labelledby="intelligence-heading" className="mx-auto max-w-4xl">
      {heading}
      {children}
    </section>
  );

  if (syntheticDataEnabled()) {
    return (
      <FeatureRouteState
        title="Intelligence"
        description={BLURB}
        state="not_implemented"
        detail="The synthetic provider has no report fixture. Report reads require the executable Python Intelligence plane."
      />
    );
  }

  const answer = surfaceAnswer(
    `${SCOPE}:reports.list`,
    await invokeGateway(principal, "reports.list"),
    (result) => result.items.length,
  );

  if (answer.kind === "unavailable") {
    return frame(
      <SurfaceState
        kind="unavailable"
        title="Reports could not be read"
        detail={answer.error.message}
        limitations={answer.disclosure.limitations}
        testId="intelligence-unavailable"
      />,
    );
  }

  if (answer.kind === "empty") {
    return frame(
      <SurfaceState
        kind="empty"
        title="No reports are stored"
        detail="The report plane was read and it holds no artifact for this Principal."
        testId="intelligence-empty"
      />,
    );
  }

  const items = answer.result.items;
  const cycleRunId = currentCycleRunId(items);
  const readiness =
    cycleRunId === null ? null : await loadReadiness(principal, cycleRunId);
  const listing = <ReportListing items={items} currentCycle={cycleRunId} />;

  const body = (
    <>
      {readiness && cycleRunId ? (
        <ReadinessPanel answer={readiness} cycleRunId={cycleRunId} />
      ) : null}
      <h2 className="mb-2 text-base font-semibold text-moss-slate">Report artifacts</h2>
      <p className="mb-3 text-sm text-muted">
        Missing specialists do not hide available reports. A morning_brief row is a Brief artifact,
        not structured Brief items.
      </p>
      {listing}
    </>
  );

  if (answer.kind === "degraded") {
    return frame(
      <>
        <DegradedBanner
          scope="these reports"
          limitations={answer.disclosure.limitations}
          truncated={answer.disclosure.truncated}
        />
        {answer.rowCount === 0 ? (
          <SurfaceState
            kind="degraded"
            title="The report plane was read incompletely and returned nothing"
            detail="An empty listing is not established by an incomplete read."
            testId="intelligence-degraded-empty"
          />
        ) : (
          body
        )}
      </>,
    );
  }

  return frame(body);
}
