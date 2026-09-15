/**
 * `/api/project-controls/projects/[projectId]/settings` — the Project's calendar.
 *
 * The minimal supported administration transport for one Project's Constraint
 * settings, and the first write this route family has ever carried. `GET` asks
 * `project_controls.status` whether the Project's calendar is stated; `POST`
 * states it through `project_controls.configure`.
 *
 * **Why there is no logic here.** Both handlers are a path guard and a call.
 * Session resolution, the Principal derived from the opaque session SID rather
 * than from anything the browser said, same-origin mutation admission,
 * `cache-control: private, no-store`, the closed request allowlist, the
 * fail-closed decode of the gateway's success and the nondisclosing translation
 * of its refusals all live in `workGet`/`workPost`. A branch added here would
 * be a second policy for one of those, which is exactly what the shared helpers
 * exist to prevent. In particular this route never derives, reads, accepts or
 * forwards a Principal — `workPost` rejects a caller-supplied one, and there is
 * no code path in this file that could smuggle one past it.
 *
 * **The status mapping, and where each part of it is decided.**
 *
 * - A `projectId` that is not the Project identifier shape is `400` here,
 *   before a capability invocation is spent learning what the shape already
 *   says. Nothing about the rejected value is echoed.
 * - An authorized Project with no settings row is a `200` carrying the typed
 *   `not_configured` state. It is an answer, not an absence: the capability
 *   returns that state explicitly, and the browser may see it only *after*
 *   same-Principal Project authorization has succeeded.
 * - A foreign, unknown or deleted Project is a nondisclosing `503`, translated
 *   from the gateway's `unavailable` by `gatewayRefusal`. The landed capability
 *   maps all three to the one `unavailable` code, which `adapters/http/app.py`
 *   serves as 503, so the three are one external answer on purpose:
 *   distinguishing them would be an oracle for whether another Principal's
 *   Project exists.
 * - A transient upstream failure is the *same* `503`, deliberately, and so is a
 *   success whose shape the decoder refuses (`upstream_contract_invalid`). A
 *   malformed success is an unavailable backend, not a half-trusted answer.
 *   Telling "foreign" apart from "transient" here would mean rebuilding inside
 *   the BFF exactly the oracle §14 forbids, so this route does not try — which
 *   is why two cases it elsewhere calls indistinguishable share one status.
 * - Open question, escalated to the operator: plan §15 asks for `404` on the
 *   foreign/unknown/deleted case. The BFF cannot produce one without making
 *   that distinction, so the landed behavior is `503` and the divergence from
 *   the plan is recorded here rather than resolved here.
 *   `settings-route.test.ts` pins all of this, and states the same reasoning.
 *
 * The `POST` body vocabulary is `SETTINGS_FIELDS`, which admits three names and
 * refuses every other — including a `projectId`, because the Project is fixed
 * from the route segment and the two can therefore never disagree.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workGet, workPost } from "@/lib/api/work-route";
import {
  invalidPathIdentifier,
  isProjectId,
  NO_FIELDS,
  SETTINGS_FIELDS,
} from "@/app/api/project-controls/constraint-requests";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ projectId: string }> },
): Promise<NextResponse> {
  const { projectId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  return workGet(request, "project-controls-settings", "project_controls.status", NO_FIELDS, {
    project_id: projectId,
  });
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ projectId: string }> },
): Promise<NextResponse> {
  const { projectId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  return workPost(
    request,
    "project-controls-settings",
    "project_controls.configure",
    SETTINGS_FIELDS,
    { project_id: projectId },
  );
}
