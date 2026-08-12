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
import { callGateway } from "@/lib/api/gateway";
import { syntheticDataEnabled } from "@/lib/api/gateway-config";
import { PulseList } from "@/components/pulse/pulse-list";
import { BackendPulseList } from "@/components/pulse/backend-pulse-list";
import { NotConnected } from "@/components/ui/not-connected";
import type { BackendPulseItem } from "@/contracts/views";

export const metadata = { title: "Today — my-pa" };

interface PythonPulseItem {
  readonly pulse_id: string;
  readonly item_type: string;
  readonly item_ref: string;
  readonly reason_code: string;
  readonly reason: string;
  readonly basis_refs: readonly string[];
  readonly consequence: string | null;
  readonly next_step: string | null;
  readonly priority: number;
  readonly generated_at: string;
}

function toItem(row: PythonPulseItem): BackendPulseItem {
  return {
    pulseId: row.pulse_id,
    itemType: row.item_type,
    itemRef: row.item_ref,
    reasonCode: row.reason_code,
    reason: row.reason,
    basisRefs: row.basis_refs,
    consequence: row.consequence,
    nextStep: row.next_step,
    priority: row.priority,
    generatedAt: row.generated_at,
  };
}

export default async function TodayPage() {
  const cookieStore = await cookies();
  const principal = await resolveSessionPrincipal(cookieStore.get(SESSION_COOKIE_NAME)?.value);
  if (!principal) redirect("/sign-in");

  const heading = (
    <>
      <h1 id="today-heading" className="mb-1 text-xl font-semibold text-moss-slate">
        Today
      </h1>
      <p className="mb-4 text-sm text-muted">
        Pulse is not a list of what happened. Every item below is here because a named condition
        holds about it right now — a moment passed, a moment approaching, a decision waiting on
        someone — and each one shows that reason, the records it was computed from, and the next
        step.
      </p>
    </>
  );

  if (syntheticDataEnabled()) {
    return (
      <section aria-labelledby="today-heading" className="mx-auto max-w-2xl">
        {heading}
        <PulseList items={syntheticPulse(principal)} />
      </section>
    );
  }

  const outcome = await callGateway<{ pulse_items?: readonly PythonPulseItem[] }>(
    principal,
    "continuity.pulse",
  );

  return (
    <section aria-labelledby="today-heading" className="mx-auto max-w-2xl">
      {heading}
      {outcome.ok ? (
        // The gateway's order, untouched. See `BackendPulseList`.
        <BackendPulseList items={(outcome.result.pulse_items ?? []).map(toItem)} />
      ) : (
        <NotConnected
          title="Today could not be derived"
          description={outcome.error.message}
          arrivesWith="This is a stated failure, not an empty day. Nothing was read and nothing is claimed."
        />
      )}
    </section>
  );
}
