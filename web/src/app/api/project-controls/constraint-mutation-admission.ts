/**
 * Exact-Project admission for the existing-record Constraint and Category writes.
 * **Server-only**: imported by route handlers and nothing else.
 *
 * Every existing-record authoring command is keyed by record identity alone —
 * `UpdateConstraint` names a `constraint_id`, `UpdateConstraintCategory` a
 * `category_id` — and the backend resolves the Project from the record. The URL
 * these routes are served under names a Project too, and nothing in the command
 * would notice if the two disagreed: a caller could write to a record in one of
 * their Projects through another Project's path. These preflights close that.
 * Each is handed to the shared write helper as its `admit` hook, so it runs
 * after the Origin check, the session Principal, the clean body and the closed
 * field map, and immediately before the mutation is invoked — there is no
 * second copy of that pipeline here, only the one comparison it lacks.
 *
 * **The answers, and why each is what it is** (artifact 17 §6, plan §7):
 *
 * - The record is in the URL's Project → `null`, and the mutation proceeds.
 * - The record is readable but belongs to another Project → the same local
 *   `404` the detail read gives for that case, from the one shared helper, so a
 *   write cannot distinguish what a read may not. The mutation is never sent.
 * - The preflight read is itself refused (absent, denied, rate limited, the
 *   gateway unavailable, a malformed success) → that typed refusal, rendered by
 *   `refuse` exactly as the mutation's own refusal would be. Collapsing those to
 *   a `404` would tell a caller "not found" when the truth is "try later".
 *
 * **Same Principal, structurally.** The read is the context's `read`, which the
 * write helper binds to the Principal it resolved for this request. This module
 * never resolves, names or forwards an identity, so there is no way for the
 * preflight and the mutation to be asked as two different callers.
 *
 * **Stale-state window.** Each existing-record command requires an expected
 * version. A Project move landing between this read and the dispatch advances
 * that version, so the mutation conflicts (`409`) rather than silently applying
 * across Projects.
 */
import type { NextResponse } from "next/server";
import type { AdmissionContext } from "@/lib/api/work-route";
import {
  CATEGORY_STATES,
  categoryNotFound,
  constraintNotFound,
} from "@/app/api/project-controls/constraint-requests";

type Admission = (context: AdmissionContext) => Promise<NextResponse | null>;

/**
 * Admit a write to `constraintId` only when it is in `projectId`.
 *
 * `constraints.read` resolves the record from its identity alone, exactly as
 * the detail route does, and the decoded, backend-owned `projectId` is what is
 * compared — never anything the browser said.
 */
export function admitExistingConstraint(projectId: string, constraintId: string): Admission {
  return async ({ read, refuse }) => {
    const outcome = await read("constraints.read", { constraint_id: constraintId });
    if (!outcome.ok) return refuse(outcome.status, outcome.error);
    return outcome.result.constraint.projectId === projectId ? null : constraintNotFound();
  };
}

/**
 * Admit a write to `categoryId` only when it is in `projectId`.
 *
 * There is no single-Category read, so the Project's whole scheme is listed —
 * every state, because deactivating or renaming an inactive or archived
 * Category is still a write to *this* Project's Category — and the path id must
 * be a member of it. A Category's Project never changes, so membership now is
 * membership at dispatch.
 */
export function admitExistingCategory(projectId: string, categoryId: string): Admission {
  return async ({ read, refuse }) => {
    const outcome = await read("constraint_categories.list", {
      project_id: projectId,
      states: [...CATEGORY_STATES],
    });
    if (!outcome.ok) return refuse(outcome.status, outcome.error);
    const member = outcome.result.categories.some(
      (category) => category.categoryId === categoryId && category.projectId === projectId,
    );
    return member ? null : categoryNotFound();
  };
}
