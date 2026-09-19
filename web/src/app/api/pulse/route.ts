/**
 * Home Today / Pulse — **Home composition over canonical Today Tasks + Pulse attention.**
 *
 * WP-POSTUX-06 establishes one canonical Today Task membership predicate consumed
 * by both Work and Home. This route implements Home's composition: canonical
 * Today Tasks from `tasks.list?work_view=today&work_date=&timezone=` plus optional
 * auxiliary Pulse attention enrichment.
 *
 * **One canonical Today selector.** The route requires explicit `work_date` (YYYY-MM-DD)
 * and valid IANA `timezone` query parameters and derives them from the authenticated
 * session only. It calls `tasks.list` with `work_view=today` — the same shared
 * predicate Work uses — to obtain canonical Today Task membership. That Task set
 * is the authoritative Home Today content.
 *
 * **Pulse is auxiliary attention only.** The route separately invokes
 * `continuity.pulse` for enrichment/attention ranking. Pulse Task items are
 * ranked/decorated presentation; they do not add to, remove from, or redefine
 * the canonical Today Task set. Pulse is also optional: if Pulse fails, the
 * canonical Today Tasks are still valid, and the response must compose them as
 * a `PARTIAL` result with the canonical baseline preserved.
 *
 * **Failure semantics.** If canonical Today (tasks.list) fails, the result is
 * `UNAVAILABLE` (not empty), and the response is 400+ with no fallback. If
 * canonical Today succeeds and Pulse enrichment fails, the response includes
 * the canonical Tasks with `completeness: PARTIAL` and Pulse omitted. Stale or
 * cached responses must never be shown as current without a freshness boundary.
 *
 * **Cache control.** All responses, including 400+ errors, carry
 * `Cache-Control: no-store` to prevent silent stale service-worker replay.
 *
 * **Principal is session-derived only.** The route takes no browser-supplied
 * Principal ID. `requirePrincipal` derives it from the verified session.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { backendDisclosure, invokeGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { syntheticPulse, syntheticDisclosure } from "@/lib/fixtures/pulse";
import type { PulseItem } from "@/lib/api/decode/capabilities/continuity.pulse";
import type { TaskListEntry } from "@/lib/api/decode/capabilities/tasks.list";
import type { BackendPulseItem } from "@/contracts/views";

const SCOPE = "pulse";

function isValidIANATimezone(timezone: unknown): timezone is string {
  if (typeof timezone !== "string") return false;
  if (timezone.length === 0 || timezone.length > 64) return false;
  if (!/^[A-Za-z0-9_+\/-]+$/.test(timezone)) return false;
  try {
    new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date());
    return true;
  } catch {
    return false;
  }
}

function isValidWorkDate(date: unknown): date is string {
  if (typeof date !== "string") return false;
  return /^\d{4}-\d{2}-\d{2}$/.test(date);
}

function noStore(response: NextResponse) {
  response.headers.set("cache-control", "private, no-store");
  return response;
}

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
    attentionRank: row.attention_rank,
    generatedAt: row.generated_at,
    ...(row.subject_title !== undefined ? { subjectTitle: row.subject_title } : {}),
  };
}

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return noStore(guard.response);

  const serving = resolveServing();
  if (serving.kind === "refused") return noStore(serving.response);

  // Extract and validate work_date and timezone from query parameters.
  const workDate = request.nextUrl.searchParams.get("workDate");
  const timezone = request.nextUrl.searchParams.get("timezone");

  if (!isValidWorkDate(workDate)) {
    return noStore(
      NextResponse.json(
        {
          error: {
            errorClass: "validation",
            code: "invalid_request",
            message: "workDate is required and must be YYYY-MM-DD",
          },
        },
        { status: 400 },
      ),
    );
  }

  if (!isValidIANATimezone(timezone)) {
    return noStore(
      NextResponse.json(
        {
          error: {
            errorClass: "validation",
            code: "invalid_request",
            message: "timezone is required and must be a valid IANA timezone name",
          },
        },
        { status: 400 },
      ),
    );
  }

  if (serving.kind === "synthetic") {
    return noStore(
      NextResponse.json({
        shape: "synthetic",
        canonicalTasks: [],
        pulseItems: syntheticPulse(guard.principal),
        disclosure: syntheticDisclosure(SCOPE),
        completeness: "full",
      }),
    );
  }

  // Invoke the canonical Today Task selector: tasks.list with work_view=today.
  const tasksOutcome = await invokeGateway(guard.principal, "tasks.list", {
    work_view: "today",
    work_date: workDate,
    timezone: timezone,
  });

  if (!tasksOutcome.ok) {
    // Canonical Today failure means Home Today is unavailable, not empty.
    return noStore(gatewayRefusal(SCOPE, tasksOutcome.status, tasksOutcome.error));
  }

  // Extract canonical Today Task IDs for membership tracking. `tasks.list` is
  // decoded by `decodeTasksList`, so `tasks` is already a `TaskListEntry[]`:
  // a shape guard here would only re-check what the decoder refused to admit.
  const canonicalTasks: readonly TaskListEntry[] = tasksOutcome.result.tasks;
  const canonicalTaskIds = new Set(canonicalTasks.map((task) => task.task_id));

  // Separately invoke Pulse for auxiliary attention enrichment (optional).
  let pulseItems: BackendPulseItem[] = [];
  let pulsePartial = false;

  const pulseOutcome = await invokeGateway(guard.principal, "continuity.pulse");
  if (!pulseOutcome.ok) {
    // Pulse enrichment failure does not suppress canonical Tasks; mark as partial.
    pulsePartial = true;
  } else {
    const result = pulseOutcome.result;
    if (result && result.pulse_items) {
      // Map Pulse items; filter out Task items that are not in canonical Today.
      // Non-Task Pulse items are always included as separate attention material.
      pulseItems = result.pulse_items
        .map(toBackendItem)
        .filter((item) => item.itemType !== "task" || canonicalTaskIds.has(item.itemRef));
    }
  }

  return noStore(
    NextResponse.json({
      shape: "backend",
      canonicalTasks: canonicalTasks,
      pulseItems: pulseItems,
      disclosure: backendDisclosure(SCOPE, tasksOutcome.disclosure, transportLimitations()),
      completeness: pulsePartial ? "partial" : "full",
    }),
  );
}
