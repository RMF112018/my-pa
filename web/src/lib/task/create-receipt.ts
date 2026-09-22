/**
 * What a Task create has to prove before anything announces it (C08).
 *
 * `CreateIntentSession.submit` confirms, reconciles and announces on whatever
 * its transport callback resolves with. So the verification has to happen
 * **inside** that callback, before it returns — by the time `submit` has
 * resolved, the surface has already said "Task created" and a mounted list has
 * already been told to re-read.
 *
 * The check reuses the canonical decoder rather than reading fields by hand, and
 * then asks three things the decoder cannot: that this result is the one the
 * request asked for (same Project, including No Project), that the history entry
 * describes *this* Task, and that it describes a create that was actually
 * applied.
 *
 * **A failure here is ambiguous, not a refusal.** The backend may well have
 * committed; what could not be established is that this response describes it.
 * So the error is the existing unavailable classification, the intent stays
 * unresolved under the same key, and the retry is the same create rather than a
 * second one.
 *
 * **A later current version is not a mismatch.** A canonical replay can return a
 * Task that has moved on since this create, so the current version is not
 * required to equal the history entry's after-version. A *Project* that has
 * moved on is different: it means this response cannot confirm the create
 * context that was requested, and that is held for inspection rather than
 * silently accepted or turned into a second Task.
 */
import { decodeTaskMutation } from "@/lib/api/decode/capabilities/_mutation-helpers";
import type { TaskMutationResult } from "@/lib/api/decode/capabilities/_mutation-helpers";
import type { ApiFailure } from "@/lib/api/work-client";
import type { TaskCreateRequest } from "@/lib/task/create-intent";

/**
 * The failure a Task create raises when its confirmation cannot be verified.
 *
 * `ApiFailure` is a type, not a constructor, so this is a factory over a plain
 * `Error` carrying the three fields the existing classifier reads. The message
 * is product language: it says what to do, and it does not claim nothing was
 * created, because that is exactly what is not known.
 */
export function unverifiedTaskCreateError(): ApiFailure {
  const error: ApiFailure = new Error(
    "Task confirmation could not be verified. Retry the same create.",
  );
  error.status = 503;
  error.code = "unavailable";
  error.errorClass = "unavailable";
  return error;
}

/**
 * Whether a thrown transport failure is an invalid-shape 503 rather than a
 * definitive canonical refusal.
 *
 * `workRequest` raises `upstream_contract_invalid` for a 2xx it could not read.
 * That is the same ambiguity as a failed verification and must reach the session
 * classified the same way, instead of as a distinct code the Task surface would
 * then have to interpret.
 */
export function isUnreadableCreateResponse(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const failure = error as ApiFailure;
  return failure.status === 503 && failure.code === "upstream_contract_invalid";
}

/**
 * The canonical Task this create produced, or a thrown ambiguity.
 *
 * Throws `unverifiedTaskCreateError()`; never returns a partially checked
 * result and never returns null, because a caller that received a value must be
 * able to confirm on it without a second test.
 */
export function verifyTaskCreateResult(
  input: unknown,
  request: TaskCreateRequest,
): TaskMutationResult {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    throw unverifiedTaskCreateError();
  }
  if ((input as { shape?: unknown }).shape !== "backend") throw unverifiedTaskCreateError();

  const decoded = decodeTaskMutation(input);
  if (!decoded.ok) throw unverifiedTaskCreateError();
  const { task, history } = decoded.value;

  // No Project is omission in the Task request contract and null in the
  // canonical row. These are the two ends of the same statement.
  const expectedProject = request.projectId ?? null;
  if (task.project_id !== expectedProject) throw unverifiedTaskCreateError();

  if (history.task_id !== task.task_id) throw unverifiedTaskCreateError();
  if (history.action !== "create") throw unverifiedTaskCreateError();
  if (history.outcome !== "applied") throw unverifiedTaskCreateError();

  return decoded.value;
}
