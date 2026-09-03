import type { Decoder } from "../types";
import { decodeTaskMutation, type TaskMutationResult } from "./_mutation-helpers";

export type TasksCreateResult = TaskMutationResult;

export const decodeTasksCreate: Decoder<TasksCreateResult> = decodeTaskMutation;
