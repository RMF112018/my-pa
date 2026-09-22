/**
 * A canonical Task create answer, for tests only.
 *
 * The Task create surface now verifies the whole canonical mutation before it
 * announces anything, so a stub with three fields on it is no longer a stub of
 * a canonical answer — it is a stub of a response the product would correctly
 * refuse. This builder produces the real shape once, so each test can say which
 * field it cares about instead of restating twenty-six it does not.
 *
 * Not part of the shipped bundle: nothing under `src/lib` or `src/components`
 * imports it, and it is not a `.test.ts` file, so Vitest does not collect it as
 * a suite.
 */

export interface TaskMutationFixtureOverrides {
  readonly taskId?: string;
  readonly title?: string;
  readonly description?: string | null;
  readonly priority?: string | null;
  readonly dueAt?: string | null;
  readonly projectId?: string | null;
  readonly situationId?: string | null;
  readonly version?: number;
  readonly replayed?: boolean;
  readonly action?: string;
  readonly outcome?: string;
  readonly historyTaskId?: string;
}

/** One complete `{shape, task, history, replayed}` body, as `/api/tasks` returns it. */
export function taskCreateResponse(overrides: TaskMutationFixtureOverrides = {}) {
  const taskId = overrides.taskId ?? "tsk_bbbbbbbb22222222";
  const version = overrides.version ?? 1;
  return {
    shape: "backend",
    task: {
      task_id: taskId,
      title: overrides.title ?? "Coordinate the review",
      description: overrides.description ?? null,
      lifecycle_state: "open",
      evidence_state: "accepted",
      origin_kind: "direct_principal",
      origin_evidence_ref: null,
      closure_evidence_ref: null,
      accepted_by_review_decision_id: null,
      acceptance_kind: null,
      closure_history_id: null,
      version,
      priority: overrides.priority ?? null,
      due_at: overrides.dueAt ?? null,
      scheduled_at: null,
      deferred_until: null,
      archived_at: null,
      project_id: overrides.projectId ?? null,
      situation_id: overrides.situationId ?? null,
      recurrence_id: null,
      opened_at: "2026-09-22T12:00:00Z",
      closed_at: null,
      created_at: "2026-09-22T12:00:00Z",
      updated_at: "2026-09-22T12:00:00Z",
      commitment_id: null,
      role: null,
    },
    history: {
      history_id: "tsh_aaaaaaaa11111111",
      task_id: overrides.historyTaskId ?? taskId,
      action: overrides.action ?? "create",
      actor: "principal",
      outcome: overrides.outcome ?? "applied",
      before_version: 0,
      after_version: version,
      occurred_at: "2026-09-22T12:00:00Z",
      recorded_at: "2026-09-22T12:00:00Z",
    },
    replayed: overrides.replayed ?? false,
  };
}
