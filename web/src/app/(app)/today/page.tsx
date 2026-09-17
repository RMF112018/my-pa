/**
 * Today — client-first hydration over canonical Today Tasks + Pulse attention.
 *
 * WP-POSTUX-06 establishes one canonical Today Task membership predicate shared
 * by both Work and Home. This page is responsible only for authentication and
 * layout; the surface component (`TodayPulseSurface`) owns the derivation
 * starting from browser-computed work_date and timezone.
 *
 * **Why the surface owns the derivation.** The browser's current civil date and
 * IANA timezone are required to query canonical Today Tasks, and they change at
 * midnight and on timezone change. The server cannot observe either. Home must
 * compute them and recompute them on every revalidation. The server's role is
 * narrowly: authenticate, short-circuit the synthetic build, and hand off to
 * the surface.
 *
 * **Why the synthetic short-circuit stays.** A synthetic build renders the
 * fixture list directly on this page to avoid a network round-trip in that
 * special case. The surface component would need the same short-circuit to
 * avoid a useless `/api/pulse` call in synthetic mode, so the logic stays here
 * as a one-place guard: if synthetic, render the fixture; otherwise, pass to
 * the surface.
 *
 * **No server-side Pulse invocation.** This page does not call
 * `continuity.pulse` on the server. It did under WP-TUX-07 to classify one
 * authoritative answer and hand it across the client boundary. WP-POSTUX-06
 * changes that: the surface now queries `/api/pulse` with explicit work_date
 * and timezone, recomputing them on midnight and timezone change. The server
 * classification pattern is therefore no longer useful — the answer is stale
 * the moment the page renders if the browser's time is different from the
 * server's, and at midnight it becomes misleading.
 *
 * The three serving states stay separate and none of them is a fallback:
 * `synthetic` requires `MYPA_DATA_PROVIDER=synthetic` and renders the fixture
 * list; `backend` passes to the surface; a refused gateway is handled by the
 * surface as unavailable/degraded.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { syntheticPulse } from "@/lib/fixtures/pulse";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { PulseList } from "@/components/pulse/pulse-list";
import { TodayPulseSurface } from "@/components/pulse/today-pulse-surface";
import { PageHeader } from "@/components/shell/page-header";
import { IntelligencePulse } from "./intelligence-pulse";

export const metadata = { title: "Today — my-pa" };

/** Today is a statement about now, so it is read at request time. */
export const dynamic = "force-dynamic";

export default async function TodayPage() {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const heading = (
    <PageHeader headingId="today-heading" title="Today" description="What needs you today." />
  );

  if (syntheticDataEnabled()) {
    return (
      <section aria-labelledby="today-heading" className="mx-auto max-w-2xl">
        {heading}
        <PulseList items={syntheticPulse(principal)} />
      </section>
    );
  }

  const intelligencePulse = await IntelligencePulse({ principal });

  return (
    <section aria-labelledby="today-heading" className="mx-auto max-w-2xl">
      {heading}
      <TodayPulseSurface />
      {intelligencePulse}
    </section>
  );
}
