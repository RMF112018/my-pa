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
import { PageHeader } from "@/components/shell/page-header";
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
import {
  diagnosticError,
  diagnosticLimitations,
} from "@/lib/diagnostics/presentation";
import { serverDiagnosticsEnabled } from "@/lib/diagnostics/server";

export const metadata = { title: "Intelligence — my-pa" };
export const dynamic = "force-dynamic";

const SCOPE = "intelligence";
const BLURB = "Evidence-grounded reports and briefs.";
const SYNTHETIC_DETAIL =
  "The synthetic provider has no report fixture. Report reads are not available in this build.";

/**
 * WP07-DIAG-011 / R031. Specialist readiness is classified diagnostic, and
 * `reports.resolve_set` is read for nothing else on this page — its answer
 * reaches `ReadinessPanel` and no other consumer. AC-48 therefore requires the
 * gate to sit *before* the invocation: the caller must not reach this function
 * at all while diagnostics are off, which is why the decision is made there and
 * not here.
 */
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
  // WP07: resolved once per request (memoised) so the diagnostic-bearing
  // props below are never built, and therefore never serialized into the
  // RSC payload, while diagnostics are off.
  const diagnosticsEnabled = await serverDiagnosticsEnabled();
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const heading = (
    <PageHeader
      headingId="intelligence-heading"
      title="Intelligence"
      description={BLURB}
      actions={
        <Link
          href={intelligenceHistory()}
          className="inline-flex min-h-[var(--control-height)] items-center text-sm text-interactive underline"
        >
          History
        </Link>
      }
    />
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
        detail={SYNTHETIC_DETAIL}
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
        error={diagnosticError(diagnosticsEnabled, answer.error)}
        limitations={diagnosticLimitations(diagnosticsEnabled, answer.disclosure.limitations)}
        testId="intelligence-unavailable"
      />,
    );
  }

  if (answer.kind === "empty") {
    return frame(
      <SurfaceState
        kind="empty"
        title="No briefings yet"
        detail="None are stored for your account yet."
        testId="intelligence-empty"
      />,
    );
  }

  const items = answer.result.items;
  const cycleRunId = currentCycleRunId(items);
  // The readiness panel is diagnostic in full, so while diagnostics are off the
  // diagnostic-only read is skipped and no readiness surface is rendered — no
  // placeholder, no empty wrapper, no reserved spacing. Silence does not
  // mislead here: nothing on this page claims the report set is complete, and
  // `ReportListing` below still renders every report that exists regardless of
  // specialist coverage.
  const readiness =
    diagnosticsEnabled && cycleRunId !== null
      ? await loadReadiness(principal, cycleRunId)
      : null;
  const listing = <ReportListing items={items} currentCycle={cycleRunId} diagnosticsEnabled={diagnosticsEnabled} />;

  const body = (
    <>
      {readiness && cycleRunId ? (
        <ReadinessPanel diagnosticsEnabled={diagnosticsEnabled} answer={readiness} cycleRunId={cycleRunId} />
      ) : null}
      <h2 className="mb-2 text-base font-semibold text-text-primary">Reports</h2>
      <p className="mb-3 text-sm text-muted">
        Missing specialists do not hide available reports. A morning brief is a report, not a list
        of structured brief items.
      </p>
      {listing}
    </>
  );

  if (answer.kind === "degraded") {
    return frame(
      <>
        <DegradedBanner
          scope="these reports"
          limitations={diagnosticLimitations(diagnosticsEnabled, answer.disclosure.limitations)}
          truncated={answer.disclosure.truncated}
        />
        {answer.rowCount === 0 ? (
          <SurfaceState
            kind="degraded"
            title="Reports were read incompletely and returned nothing"
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
