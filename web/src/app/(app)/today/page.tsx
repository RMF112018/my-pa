/**
 * Today — the derived Pulse, served from the Python gateway by default.
 *
 * This page imported `syntheticPulse` directly until WP-11, which in a default
 * build meant it threw at the fixture gate: there was no backend capability to
 * fall back to. `continuity.pulse` is that capability, and this page reaches it
 * through the same server-only transport `/api/pulse` uses, for the reason
 * `lib/fixtures/gate.ts` records — a server component that called its own API
 * route would be a second copy of the same decision.
 *
 * The three serving states stay separate and none of them is a fallback:
 * `synthetic` requires `MYPA_DATA_PROVIDER=synthetic` and renders the fixture
 * list; `backend` renders the derivation; a refused or unreachable gateway
 * renders a stated failure and never an empty list, because an empty list here
 * would read as "nothing needs your attention today".
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { resolveSessionPrincipal } from "@/lib/auth/principal";
import { syntheticPulse } from "@/lib/fixtures/pulse";
import { invokeGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { surfaceAnswer } from "@/lib/api/surface-answer";
import { PulseList } from "@/components/pulse/pulse-list";
import { BackendPulseList } from "@/components/pulse/backend-pulse-list";
import { PageHeader } from "@/components/shell/page-header";
import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import { IntelligencePulse } from "./intelligence-pulse";
import type { PulseItem } from "@/lib/api/decode/capabilities/continuity.pulse";
import type { BackendPulseItem } from "@/contracts/views";

export const metadata = { title: "Today — my-pa" };

/** Today is a statement about now, so it is read at request time. */
export const dynamic = "force-dynamic";

function toItem(row: PulseItem): BackendPulseItem {
  return {
    pulseId: row.pulse_id,
    itemType: row.item_type,
    itemRef: row.item_ref,
    reasonCode: row.reason_code,
    reason: row.reason,
    basisRefs: row.basis_refs,
    consequence: row.consequence,
    nextStep: row.next_step,
    priority: row.attention_rank,
    generatedAt: row.generated_at,
    ...(row.subject_title !== undefined ? { subjectTitle: row.subject_title } : {}),
  };
}

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

  const answer = surfaceAnswer(
    "today:continuity.pulse",
    await invokeGateway(principal, "continuity.pulse"),
    (result) => result.pulse_items.length,
  );
  const intelligencePulse = await IntelligencePulse({ principal });

  return (
    <section aria-labelledby="today-heading" className="mx-auto max-w-2xl">
      {heading}
      {answer.kind === "unavailable" ? (
        <SurfaceState
          kind="unavailable"
          title="Today could not be derived"
          error={answer.error}
          limitations={answer.disclosure.limitations}
          testId="today-unavailable"
        />
      ) : answer.kind === "empty" ? (
        <SurfaceState
          kind="empty"
          title="Nothing needs attention right now"
          detail="This is about today, not everything you hold."
          diagnostic={
            "The derivation ran and found no accepted commitment, decision, task or situation that " +
            "a named condition holds about right now."
          }
          testId="today-empty"
        />
      ) : answer.kind === "degraded" ? (
        <>
          <DegradedBanner
            scope="today's derivation"
            limitations={answer.disclosure.limitations}
            truncated={answer.disclosure.truncated}
          />
          {answer.rowCount === 0 ? (
            <SurfaceState
              kind="degraded"
              title="Today is incomplete"
              detail="A quiet day is not established. Something may still need you."
              diagnostic={
                "The derivation was incomplete and surfaced nothing. A partial read does not " +
                "establish that nothing needs attention."
              }
              testId="today-degraded-empty"
            />
          ) : (
            // The gateway's order, untouched. See `BackendPulseList`.
            <BackendPulseList items={answer.result.pulse_items.map(toItem)} />
          )}
        </>
      ) : (
        <BackendPulseList items={answer.result.pulse_items.map(toItem)} />
      )}
      {intelligencePulse}
    </section>
  );
}
