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
 * Since WP-TUX-07 this page classifies once and hands that answer to
 * `TodayPulseSurface`, which owns every read after it through `/api/pulse`. The
 * classification, the authentication and the synthetic short-circuit all stay
 * here, on the server, for the reason above: this page still does not call its
 * own API route.
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
import { TodayPulseSurface } from "@/components/pulse/today-pulse-surface";
import { PageHeader } from "@/components/shell/page-header";
import { IntelligencePulse } from "./intelligence-pulse";
import type {
  ContinuityPulseResult,
  PulseItem,
} from "@/lib/api/decode/capabilities/continuity.pulse";
import type { BackendPulseItem, TodayPulseAnswer } from "@/contracts/views";
import type { SurfaceAnswer } from "@/lib/api/surface-answer";

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
    // The derivation's ordering rank. Never Task priority — see `views.ts`.
    attentionRank: row.attention_rank,
    generatedAt: row.generated_at,
    ...(row.subject_title !== undefined ? { subjectTitle: row.subject_title } : {}),
  };
}

/**
 * Carry the server's one classification across the client boundary without
 * re-deciding it.
 *
 * Only what the surface renders crosses: the rows, the disclosed limitations,
 * and the failure. The `GatewayOutcome` itself does not — it carries transport
 * detail a browser has no use for and no business holding.
 */
function toClientAnswer(answer: SurfaceAnswer<ContinuityPulseResult>): TodayPulseAnswer {
  switch (answer.kind) {
    case "unavailable":
      return {
        kind: "unavailable",
        error: answer.error,
        limitations: answer.disclosure.limitations,
      };
    case "empty":
      return { kind: "empty" };
    case "degraded":
      return {
        kind: "degraded",
        items: answer.result.pulse_items.map(toItem),
        limitations: answer.disclosure.limitations,
        truncated: answer.disclosure.truncated,
      };
    default:
      return { kind: "records", items: answer.result.pulse_items.map(toItem) };
  }
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
      <TodayPulseSurface initialAnswer={toClientAnswer(answer)} />
      {intelligencePulse}
    </section>
  );
}
