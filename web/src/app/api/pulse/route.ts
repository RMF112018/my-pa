/**
 * Home Today / Pulse — **Home composition over canonical Today Tasks + Pulse attention.**
 *
 * WP-POSTUX-06 establishes one canonical Today Task membership predicate consumed
 * by both Work and Home. This route implements Home's composition: it answers
 * `todayRows` — one row for every canonical Today Task from
 * `tasks.list?work_view=today&work_date=&timezone=`, each carrying the derived
 * Pulse row for that Task where `continuity.pulse` produced one, followed by the
 * Pulse rows about things that are not Tasks.
 *
 * **One canonical Today selector.** The route requires explicit `work_date` (YYYY-MM-DD)
 * and valid IANA `timezone` query parameters and derives them from the authenticated
 * session only. It calls `tasks.list` with `work_view=today` — the same shared
 * predicate Work uses — to obtain canonical Today Task membership. Every Task in
 * that set becomes one row of the answer, whether or not the derivation flagged
 * it; nothing in this route can remove a Task from it.
 *
 * **Pulse annotates; it does not select.** The route separately invokes
 * `continuity.pulse`. A Pulse row whose `item_type` is `task` is attached to the
 * canonical Task row with the same id, under `attention`, and is otherwise
 * dropped: a Task the derivation flagged but which the canonical predicate did
 * not return is not Today, and a Pulse row cannot make it so. A Pulse row of any
 * other type is carried through as its own attention row, because the canonical
 * Task predicate says nothing about commitments, decisions, observations,
 * relationship events or situations.
 *
 * **Failure semantics.** If canonical Today (tasks.list) fails, the result is
 * `UNAVAILABLE` (not empty), and the response is 400+ with no fallback. If
 * canonical Today succeeds and Pulse fails, the canonical Task rows are answered
 * with no `attention` on any of them, no non-Task rows, and
 * `completeness: "partial"` — a Pulse failure costs annotation, never content.
 * Stale or cached responses must never be shown as current without a freshness
 * boundary.
 *
 * **Row order.** Task rows first, in the order `tasks.list` returned them (its
 * server-side deterministic order: calendar timestamp, then priority rank, then
 * task id), then the non-Task Pulse rows in the order `continuity.pulse`
 * returned them (its own attention rank). Both halves are server orders and the
 * composition is a concatenation: nothing here sorts, and no client does either.
 * `attentionRank` deliberately does not reorder a Task row — the Tasks are one
 * canonical set, and letting a flag move a row would make a Task's position
 * depend on whether the derivation happened to notice it.
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
import type { BackendPulseItem, TodayRow } from "@/contracts/views";

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

/**
 * Compose the answer's rows from the canonical Today Task set and whatever the
 * derivation raised.
 *
 * The canonical set is the content and is reproduced whole. A Task Pulse row is
 * looked up by `itemRef` and attached to its Task; the first such row wins, so a
 * duplicate cannot silently replace the annotation already attached. A Task
 * Pulse row with no canonical Task is dropped — it names something the shared
 * predicate did not put in Today.
 */
function composeTodayRows(
  tasks: readonly TaskListEntry[],
  pulseItems: readonly BackendPulseItem[],
): readonly TodayRow[] {
  const attentionByTaskId = new Map<string, BackendPulseItem>();
  for (const item of pulseItems) {
    if (item.itemType !== "task") continue;
    if (!attentionByTaskId.has(item.itemRef)) attentionByTaskId.set(item.itemRef, item);
  }

  const taskRows: TodayRow[] = tasks.map((task) => {
    const attention = attentionByTaskId.get(task.task_id);
    return {
      kind: "task",
      taskId: task.task_id,
      title: task.title,
      // Omitted rather than undefined: the field's absence is the statement.
      ...(attention !== undefined ? { attention } : {}),
    };
  });

  const attentionRows: TodayRow[] = pulseItems
    .filter((item) => item.itemType !== "task")
    .map((item) => ({ kind: "attention", item }));

  return [...taskRows, ...attentionRows];
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
    /*
      The synthetic answer carries the fixture `PulseItem` shape under
      `pulseItems`, which is neither `BackendPulseItem` nor a `TodayRow`, and it
      is labelled `shape: "synthetic"` so nothing can read it as the backend
      answer. The Today surface never sees it: `today/page.tsx` short-circuits a
      synthetic build to the fixture list without reading this route.
    */
    return noStore(
      NextResponse.json({
        shape: "synthetic",
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

  // The canonical Today Task set, and the whole of Home's Today content.
  // `tasks.list` is decoded by `decodeTasksList`, so `tasks` is already a
  // `TaskListEntry[]`: a shape guard here would only re-check what the decoder
  // refused to admit.
  const canonicalTasks: readonly TaskListEntry[] = tasksOutcome.result.tasks;

  // Separately invoke Pulse for annotation and for non-Task attention material.
  let pulseItems: readonly BackendPulseItem[] = [];
  let pulsePartial = false;

  const pulseOutcome = await invokeGateway(guard.principal, "continuity.pulse");
  if (!pulseOutcome.ok) {
    // A Pulse failure costs annotation, not content: the canonical Task rows are
    // still answered, unannotated, and the answer says it is partial.
    pulsePartial = true;
  } else {
    const result = pulseOutcome.result;
    if (result && result.pulse_items) {
      pulseItems = result.pulse_items.map(toBackendItem);
    }
  }

  return noStore(
    NextResponse.json({
      shape: "backend",
      todayRows: composeTodayRows(canonicalTasks, pulseItems),
      disclosure: backendDisclosure(SCOPE, tasksOutcome.disclosure, transportLimitations()),
      completeness: pulsePartial ? "partial" : "full",
    }),
  );
}
