import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { CommitmentDetailView, TaskDetailView } from "@/components/work/work-detail";
import { WorkPerspectives } from "@/components/work/work-perspectives";
import type {
  CommitmentDetail as CommitmentDetailContract,
  CommitmentRow,
  TaskDetail as TaskDetailContract,
  TaskRow,
} from "@/contracts/work";

const task: TaskDetailContract = {
  task_id: "tsk_story000000000001", title: "Prepare the permit review", description: "Synthetic Storybook fixture.",
  lifecycle_state: "in_progress", priority: "p1", due_at: "2026-08-22T17:00:00Z",
  scheduled_at: "2026-08-22T13:00:00Z", deferred_until: "2026-08-21T13:00:00Z",
  archived_at: null, created_at: "2026-08-20T12:00:00Z", updated_at: "2026-08-22T12:00:00Z",
  evidence_state: "accepted", origin_evidence_ref: "cap_story_origin_0001", closure_evidence_ref: null,
  accepted_by_review_decision_id: "rdec_story0000000001", acceptance_kind: "review",
  closure_history_id: null, version: 3, commitment_id: "cmt_story000000000001", role: "follow_up",
  project_id: "prj_story000000000001", situation_id: "sit_story000000000001",
  opened_at: "2026-08-20T12:00:00Z", closed_at: null,
};

const tasks: readonly TaskRow[] = [
  task,
  { ...task, task_id: "tsk_story000000000002", title: "Wait for revised drawings", lifecycle_state: "waiting", priority: "p2", due_at: null, scheduled_at: null, deferred_until: null, version: 1 },
  { ...task, task_id: "tsk_story000000000003", title: "Resolve access constraint", lifecycle_state: "blocked", priority: null, scheduled_at: null, deferred_until: null, version: 2 },
  { ...task, task_id: "tsk_story000000000004", title: "Archive signed checklist", lifecycle_state: "completed", priority: "p4", version: 4 },
];

const commitment: CommitmentDetailContract = {
  commitment_id: "cmt_story000000000001", title: "Revised drawings from Sam", description: "Synthetic Storybook fixture.",
  direction: "owed_to_principal", state: "open", counterparty_person_id: "per_story000000000001",
  counterparty: { person_id: "per_story000000000001", display_name: "Sam Rivera" },
  due_date: "2026-08-22T16:00:00Z", created_at: "2026-08-20T12:00:00Z", updated_at: "2026-08-22T11:00:00Z",
  version: 2, evidence_state: "accepted", origin_evidence_ref: "cap_story_origin_0002",
  closure_evidence_ref: null, accepted_by_review_decision_id: "rdec_story0000000002", closed_at: null,
};

const commitments: readonly CommitmentRow[] = [
  commitment,
  { ...commitment, commitment_id: "cmt_story000000000002", title: "Send Sam the approved log", direction: "owed_by_principal", state: "closed", version: 4 },
];

const noOp = () => undefined;
const common = { selectedTaskIds: [] as readonly string[], onSelectTask: noOp, onOpen: noOp, onMoveTask: noOp };

const meta = {
  title: "Work/Canonical states",
  parameters: { layout: "padded" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

export const TaskList: Story = { render: () => <WorkPerspectives {...common} perspective="list" rows={tasks} commitments={false} /> };
export const TaskBoard: Story = { render: () => <WorkPerspectives {...common} perspective="board" rows={tasks} commitments={false} /> };
export const TaskCalendar: Story = { render: () => <WorkPerspectives {...common} perspective="calendar" rows={tasks} commitments={false} /> };
export const CommitmentList: Story = { render: () => <WorkPerspectives {...common} perspective="list" rows={commitments} commitments /> };
export const CommitmentBoardDarkCompact: Story = { globals: { theme: "dark", density: "compact" }, render: () => <WorkPerspectives {...common} perspective="board" rows={commitments} commitments /> };

function mockDetailFetch() {
  const original = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = String(input);
    const body = url.includes("/history")
      ? { history: [{ history_id: "his_story000000000001", action: "updated", actor: "principal", outcome: "applied", before_version: 2, after_version: 3, occurred_at: "2026-08-22T12:00:00Z", recorded_at: "2026-08-22T12:00:00Z" }] }
      : url === "/api/commitments?pageSize=100"
        ? { commitments }
        : url.includes("/api/tasks/")
          ? { task }
          : { commitment, follow_up_task: task, counterparty_options: [commitment.counterparty], counterparty_options_truncated: false };
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  };
  return () => { globalThis.fetch = original; };
}

export const TaskDetail: Story = { beforeEach: mockDetailFetch, render: () => <TaskDetailView taskId={task.task_id} /> };
export const CommitmentDetail: Story = { beforeEach: mockDetailFetch, render: () => <CommitmentDetailView commitmentId={commitment.commitment_id} /> };
export const MobileCalendar: Story = { parameters: { viewport: { defaultViewport: "mobile" } }, render: () => <WorkPerspectives {...common} perspective="calendar" rows={tasks} commitments={false} /> };
