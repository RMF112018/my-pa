/**
 * Today / Pulse — **real-backed as of WP-11.**
 *
 * This route answered `501 not_implemented` until now, and the reason it gave
 * was exact: a principal-scoped Pulse read model existed in Python and no member
 * of the capability set reached it. `continuity.pulse` is that member, and
 * revision `8f2b6c4d1a37` carries the forward `ALTER` that admits it to the
 * audited vocabulary.
 *
 * **What comes back is a derivation, not a list.** The backend selects the
 * Principal's *accepted*, open commitments, tasks and decisions and the
 * obligations standing on the current frames of running Situations, and returns
 * only those for which a named why-now condition holds — each with a closed
 * `reason_code`, the `basis_refs` a reader can open to check it, a consequence,
 * a next step, and an evidentiary urgency rank. An accepted object that is
 * merely recent, and carries no due moment, no named authority point and no
 * unmet obligation, is not in the answer at all.
 *
 * The order the gateway returns is the ranked order, and this route **must not
 * re-sort it**. `generatedAt` is identical on every item — it is the moment of
 * the read — so a sort by it would be arbitrary rather than chronological, and a
 * sort by anything else would discard the ranking that is the answer.
 *
 * **No browser Principal.** The envelope's `principal_id` is derived by
 * `callGateway` from the verified session cookie and from nothing else; this
 * route sends no payload at all, so there is nothing a caller could name.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { backendDisclosure, invokeGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { syntheticPulse, syntheticDisclosure } from "@/lib/fixtures/pulse";
import type { PulseItem } from "@/lib/api/decode/capabilities/continuity.pulse";
import type { BackendPulseItem } from "@/contracts/views";

const SCOPE = "pulse";

function toBackendItem(row: PulseItem): BackendPulseItem {
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
  };
}

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;

  if (serving.kind === "synthetic") {
    return NextResponse.json({
      shape: "synthetic",
      items: syntheticPulse(guard.principal),
      disclosure: syntheticDisclosure(SCOPE),
    });
  }

  const outcome = await invokeGateway(guard.principal, "continuity.pulse");
  if (!outcome.ok) return gatewayRefusal(SCOPE, outcome.status, outcome.error);
  const result = outcome.result;

  return NextResponse.json({
    shape: "backend",
    items: result.pulse_items.map(toBackendItem),
    disclosure: backendDisclosure(SCOPE, outcome.disclosure, transportLimitations()),
  });
}
