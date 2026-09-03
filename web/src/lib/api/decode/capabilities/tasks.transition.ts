import type { Decoder } from "../types";
import { decodeTaskMutation, type TaskMutationResult } from "./_mutation-helpers";

export type TasksTransitionResult = TaskMutationResult;

export const decodeTasksTransition: Decoder<TasksTransitionResult> = decodeTaskMutation;
