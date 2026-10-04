import { serializeTaskQueryKey, type TaskQueryKey } from "@/lib/task/query-key";
import {
  ReadCoordinatorCore,
  type ResourceFreshnessStatus,
  type ResourceReadOutcome,
  type ResourceReadResult,
  type ResourceQuerySnapshot,
  type ResourceReadFetchContext,
  type ResourceReadOptions,
} from "@/lib/workspace/resource-coordinator";

export type TaskFreshnessStatus = ResourceFreshnessStatus;
export type TaskReadOutcome = ResourceReadOutcome;
export type TaskReadResult<T> = ResourceReadResult<T>;
export type TaskQuerySnapshot<T> = ResourceQuerySnapshot<T, TaskQueryKey>;
export type TaskReadFetchContext = ResourceReadFetchContext<TaskQueryKey>;
export type TaskReadFetcher<T> = (context: TaskReadFetchContext) => Promise<T>;
export type TaskReadOptions = ResourceReadOptions;
export interface TaskConfirmedWriteOptions {
  readonly entityId?: string;
  readonly at?: number;
}

/** Compatibility adapter: Task key bytes and exact-key entity revisions stay unchanged. */
export class TaskReadCoordinator<T = unknown> extends ReadCoordinatorCore<T, TaskQueryKey> {
  private readonly entityBarriers = new Map<string, number>();

  constructor() {
    super(serializeTaskQueryKey, () => ({ family: "tasks", identity: null }), "TaskReadCoordinator has been disposed");
  }

  override raiseMutationBarrier(key: TaskQueryKey, options: TaskConfirmedWriteOptions = {}): number {
    let minimum = 0;
    if (options.entityId) {
      minimum = Math.max((this.entityBarriers.get(options.entityId) ?? 0) + 1,
        (this.getSnapshot(key)?.mutationBarrier ?? 0) + 1);
    }
    const revision = this.raiseExactBarrier(key, minimum);
    if (options.entityId) this.entityBarriers.set(options.entityId, revision);
    return revision;
  }

  override applyConfirmed(key: TaskQueryKey, data: T, options: TaskConfirmedWriteOptions = {}): TaskQuerySnapshot<T> {
    this.raiseMutationBarrier(key, options);
    return this.confirm(key, data, options.at);
  }

  override dispose(): void {
    super.dispose();
    this.entityBarriers.clear();
  }
}

export function createTaskReadCoordinator<T = unknown>(): TaskReadCoordinator<T> {
  return new TaskReadCoordinator<T>();
}
