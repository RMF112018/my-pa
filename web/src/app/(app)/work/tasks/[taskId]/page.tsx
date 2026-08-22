import { TaskDetailView } from "@/components/work/work-detail";
export const metadata = { title: "Task — my-pa" };
export default async function TaskPage({ params }: { params: Promise<{ taskId: string }> }) { const { taskId } = await params; return <TaskDetailView taskId={taskId} />; }
