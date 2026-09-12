import { TaskDetailViewConnected } from "@/components/work/work-detail";

export const metadata = { title: "Task — my-pa" };

/**
 * Standalone Task route.
 *
 * This page sits inside the signed-in `(app)` layout, which mounts `AppShell`
 * and therefore the session-scoped `TaskRuntimeProvider`. The connected detail
 * variant consumes that shell runtime, so there is no second route-local
 * mutation/read coordinator, no second feedback queue, and no second Task
 * operation engine: a Task opened here and the same Task opened in the
 * Work-hosted sheet share identical operation semantics, and shell-persistent
 * success and conflict feedback survives on this route.
 */
export default async function TaskPage({ params }: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await params;
  return <TaskDetailViewConnected taskId={taskId} />;
}
