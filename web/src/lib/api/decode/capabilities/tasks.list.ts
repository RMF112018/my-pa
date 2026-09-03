import type { Decoder } from "../types";
import { decodeTaskListPage, type TaskListEntry } from "./_read-helpers";

export type { TaskListEntry };

export type TasksListResult = { readonly tasks: readonly TaskListEntry[] };

export const decodeTasksList: Decoder<TasksListResult> = decodeTaskListPage;
