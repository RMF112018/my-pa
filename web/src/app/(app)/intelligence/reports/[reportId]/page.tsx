/**
 * One Intelligence artifact. Loaded via reports.read through the server
 * gateway, not the page's own BFF. Malformed reads are unavailable.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { invokeGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { FeatureRouteState } from "@/components/shell/feature-route-state";
import { SurfaceState } from "@/components/ui/surface-state";
import { ReportDetailView } from "@/components/intelligence/report-detail-view";
import { REPORT_IDENTIFIER } from "@/components/intelligence/cycle-selection";

export const metadata = { title: "Intelligence report — my-pa" };
export const dynamic = "force-dynamic";

const BLURB = "Evidence-grounded reports and briefs.";

export default async function IntelligenceReportPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const { reportId } = await params;

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

  if (!REPORT_IDENTIFIER.test(reportId)) {
    return (
      <section className="mx-auto max-w-4xl">
        <h1 id="intelligence-report-heading" className="mb-4 text-xl font-semibold text-moss-slate">
          Intelligence report
        </h1>
        <SurfaceState
          kind="unavailable"
          title="This report could not be read"
          detail="The identifier is not an opaque report id, so nothing was retrieved."
          testId="intelligence-report-unavailable"
        />
      </section>
    );
  }

  const outcome = await invokeGateway(principal, "reports.read", {
    report_id: reportId,
    include_body: true,
  });

  if (!outcome.ok) {
    return (
      <section className="mx-auto max-w-4xl">
        <h1 id="intelligence-report-heading" className="mb-4 text-xl font-semibold text-moss-slate">
          Intelligence report
        </h1>
        <SurfaceState
          kind="unavailable"
          title="This report could not be read"
          detail={outcome.error.message}
          testId="intelligence-report-unavailable"
        />
      </section>
    );
  }

  return <ReportDetailView report={outcome.result} />;
}
