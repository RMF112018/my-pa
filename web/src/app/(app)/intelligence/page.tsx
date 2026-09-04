/**
 * Intelligence — Principal-scoped report artifacts from the Python plane.
 *
 * This page does not scrape markdown into items and does not invent a Morning
 * Brief section schema. It lists handler fields the BFF already decoded:
 * identifier, title, stage, kind, and artifact state. Empty, unavailable, and
 * results stay distinct.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway, type GatewayOutcome } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { FeatureRouteState } from "@/components/shell/feature-route-state";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import { Card, CardBody, CardTitle } from "@/components/ui/card";
import type { ReportsListResult } from "@/lib/api/decode/capabilities/reports.list";

export const metadata = { title: "Intelligence — my-pa" };
export const dynamic = "force-dynamic";

const SCOPE = "intelligence";

const BLURB = "Evidence-grounded reports and briefs.";

export default async function IntelligencePage() {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const heading = (
    <>
      <h1 id="intelligence-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        Intelligence
      </h1>
      <p className="mb-4 text-sm text-muted">{BLURB}</p>
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
    (await invokeGateway(principal, "reports.list")) as GatewayOutcome<ReportsListResult>,
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
  const listing = (
    <ul className="flex flex-col gap-3" data-testid="intelligence-listing">
      {items.map((row) => (
        <li key={row.report_id}>
          <Card data-testid="intelligence-report" data-report-id={row.report_id}>
            <CardTitle>{row.title}</CardTitle>
            <CardBody>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                <dt>Identifier</dt>
                <dd data-testid="intelligence-report-id">{row.report_id}</dd>
                <dt>Stage</dt>
                <dd data-testid="intelligence-stage">{row.stage}</dd>
                <dt>Kind</dt>
                <dd data-testid="intelligence-kind">{row.artifact_kind}</dd>
                <dt>State</dt>
                <dd data-testid="intelligence-artifact-state">{row.artifact_state}</dd>
              </dl>
            </CardBody>
          </Card>
        </li>
      ))}
    </ul>
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
          listing
        )}
      </>,
    );
  }

  return frame(listing);
}
