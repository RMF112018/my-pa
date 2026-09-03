import type { Decoder } from "../types";
import { decodeTaskMutation, type TaskMutationResult } from "./_mutation-helpers";

export type TasksUpdateResult = TaskMutationResult;

export const decodeTasksUpdate: Decoder<TasksUpdateResult> = decodeTaskMutation;
