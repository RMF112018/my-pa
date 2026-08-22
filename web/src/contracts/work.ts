export type TaskLifecycle = "open" | "in_progress" | "waiting" | "blocked" | "completed" | "cancelled";
export type TaskPriority = "p1" | "p2" | "p3" | "p4";

export interface CounterpartyOption {
  person_id: string;
  display_name: string;
}

export interface TaskRow {
  task_id: string; title: string; lifecycle_state: TaskLifecycle; priority: TaskPriority | null;
  due_at: string | null; archived_at: string | null; created_at: string; updated_at: string;
}
export interface TaskDetail extends TaskRow {
  description: string | null; evidence_state: string; origin_evidence_ref: string;
  closure_evidence_ref: string | null; closure_history_id: string | null; version: number;
  scheduled_at: string | null; deferred_until: string | null; commitment_id: string | null;
  role: string | null; opened_at: string; closed_at: string | null;
}
export interface CommitmentRow {
  commitment_id: string; direction: "owed_by_principal" | "owed_to_principal"; state: "open" | "closed";
  counterparty_person_id: string | null; title: string; description: string | null; due_date: string | null;
  created_at: string; updated_at: string; version: number;
  counterparty: CounterpartyOption | null;
}
export interface CommitmentDetail extends CommitmentRow {
  evidence_state: string; origin_evidence_ref: string; closure_evidence_ref: string | null; closed_at: string | null;
}
export interface WaitingOnRow {
  commitment_id: string; title: string; counterparty_person_id: string | null;
  due_date: string | null; state: "open";
  follow_up_task_id: string | null; follow_up_task_title: string | null;
  follow_up_task_state: TaskLifecycle | null;
  counterparty: CounterpartyOption | null;
}
export interface WorkHistoryRow {
  history_id: string; action: string; actor: string; outcome: string; before_version: number;
  after_version: number; occurred_at: string; recorded_at: string;
}

export type TaskBulkMutation =
  | {
      readonly kind: "update";
      readonly task_id: string;
      readonly expected_version: number;
      readonly values: Readonly<Record<string, string | boolean>>;
      readonly clear_fields: readonly string[];
    }
  | {
      readonly kind: "transition";
      readonly task_id: string;
      readonly expected_version: number;
      readonly to_state: Exclude<TaskLifecycle, "completed" | "cancelled">;
    };

export interface TaskBulkPreviewReceipt {
  readonly bulk_operation_id: string;
  readonly expires_at: string;
  readonly affected: number;
  readonly no_op: number;
  readonly rejected: number;
  readonly replayed: boolean;
}

export interface TaskBulkConfirmReceipt {
  readonly bulk_operation_id: string;
  readonly affected: number;
  readonly no_op: number;
  readonly rejected: number;
  readonly history_ids: readonly string[];
  readonly replayed: boolean;
}
